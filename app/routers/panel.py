"""公开面板：内网免登录可看，可选要求登录。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, security
from ..rendering import render

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
