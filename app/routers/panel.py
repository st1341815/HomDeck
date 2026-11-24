"""公开面板：内网免登录可看，可选要求登录。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, security
from ..rendering import render
from ..services import visits

router = APIRouter()


def _pick_url(item: dict, lan: bool) -> str:
    if lan:
        return item.get("url_lan") or item.get("url_wan") or ""
    return item.get("url_wan") or item.get("url_lan") or ""


def build_panel(ip: str) -> dict:
    lan = security.is_lan(ip)
    groups = [dict(r) for r in db.all_rows("SELECT * FROM grp WHERE visible=1 ORDER BY sort, id")]
    items = [dict(r) for r in db.all_rows("SELECT * FROM item ORDER BY sort, id")]
    by_group: dict[int, list] = {}
    for it in items:
        url = _pick_url(it, lan)
        if not url:
            continue
        name = it["name"]
        by_group.setdefault(it["group_id"], []).append(
            {
                "id": it["id"],
                "name": name,
                "url": url,
                # 双地址都下发，前端可手动切换内网/外网而不必刷新页面
                "url_lan": it.get("url_lan") or "",
                "url_wan": it.get("url_wan") or "",
                "icon": it["icon"],
                "initial": (name.strip()[:1] or "?").upper(),
                "description": it["description"],
                "target": it["target"],
            }
        )
    out = []
    for g in groups:
        cards = by_group.get(g["id"], [])
        out.append({"id": g["id"], "name": g["name"], "icon": g["icon"], "items": cards})
    return {
        "site": {
            "name": db.get_setting("site_name", "HomDeck"),
            "icon": db.get_setting("site_icon", "🧭"),
            "footer": db.get_setting("footer", ""),
            "theme": db.get_setting("theme", "auto"),
            "accent": db.get_setting("accent", ""),
        },
        "is_lan": lan,
        "groups": out,
    }


@router.get("/")
def index(request: Request):
    user = security.session_user(request)
    if not user and db.get_setting("require_login", "0") == "1":
        return RedirectResponse("/login", status_code=303)
    data = build_panel(security.client_ip(request))
    return render("panel.html", request, {"data": data, "user": user})


@router.get("/api/panel")
def panel_api(request: Request):
    user = security.session_user(request)
    if not user and db.get_setting("require_login", "0") == "1":
        return JSONResponse({"error": "请先登录"}, status_code=401)
    return build_panel(security.client_ip(request))


@router.post("/api/visit")
async def record_visit(request: Request):
    """卡片被打开时前端 sendBeacon 过来的一条记录。

    公开端点（面板本身可以免登录），所以不校验 CSRF、不要求登录。
    代价是别人可以伪造点击刷统计——只影响自己看的数字，不做过度防御；
    但价格必须低：不存在的 id 静默丢弃，限流宽松到不会咬到正常用户。
    """
    ip = security.client_ip(request)
    security.rate_limit(f"visit:{ip}", 240)
    try:
        body = await request.json()
        item_id = int(body.get("id") or 0)
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"ok": False}, status_code=204)
    if item_id > 0:
        visits.record(item_id, ip, request.headers.get("user-agent", ""))
    # 204：sendBeacon 不读响应体，少传字节
    return Response(status_code=204)
