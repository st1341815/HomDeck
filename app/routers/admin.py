"""管理端 API：分组、卡片、图标、设置、备份、审计。全部需登录 + CSRF。"""
from __future__ import annotations

import io
import re
import urllib.parse
from typing import Optional

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from .. import db, security
from ..rendering import render
from ..services import backup as backup_svc
from ..services import favicon as favicon_svc
from ..services import uploads as upload_svc

router = APIRouter()


def _guard(request: Request, action: Optional[str] = None) -> dict:
    user = security.require_admin(request)
    security.check_csrf(request)
    if action:
        security.rate_limit(f"write:{user['id']}", 60)
    return user


# ---------- 页面 ----------

@router.get("/admin")
def admin_page(request: Request):
    from fastapi.responses import RedirectResponse

    user = security.session_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render("admin.html", request, {"user": user})


# ---------- 总览 ----------

@router.get("/api/admin/overview")
def overview(request: Request):
    security.require_admin(request)
    groups = [dict(r) for r in db.all_rows("SELECT * FROM grp ORDER BY sort, id")]
    items = [dict(r) for r in db.all_rows("SELECT * FROM item ORDER BY sort, id")]
    return {
        "groups": groups,
        "items": items,
        "icons": upload_svc.list_icons(),
        "settings": {r["key"]: r["value"] for r in db.all_rows("SELECT * FROM setting")},
        "audit": [dict(r) for r in db.all_rows("SELECT * FROM audit ORDER BY id DESC LIMIT 50")],
    }


# ---------- 分组 ----------

@router.post("/api/admin/groups")
async def create_group(request: Request):
    user = _guard(request, "write")
    body = await request.json()
    name = (body.get("name") or "").strip()[:40]
    if not name:
        return JSONResponse({"error": "分组名不能为空"}, status_code=400)
    nxt = (db.scalar("SELECT COALESCE(MAX(sort), 0) FROM grp") or 0) + 10
    cur = db.run(
        "INSERT INTO grp(name, icon, sort, created_at) VALUES (?,?,?,?)",
        (name, (body.get("icon") or "")[:40], nxt, db.utcnow()),
    )
    db.audit(user["id"], "group.create", name, security.client_ip(request), "")
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/admin/groups/{group_id}")
async def update_group(group_id: int, request: Request):
    user = _guard(request, "write")
    body = await request.json()
    row = db.one("SELECT * FROM grp WHERE id=?", (group_id,))
    if not row:
        return JSONResponse({"error": "分组不存在"}, status_code=404)
    name = (body.get("name") or row["name"]).strip()[:40]
    icon = body.get("icon", row["icon"])[:40]
    visible = int(bool(body.get("visible", row["visible"])))
    db.run(
        "UPDATE grp SET name=?, icon=?, visible=? WHERE id=?",
        (name, icon, visible, group_id),
    )
    db.audit(user["id"], "group.update", name, security.client_ip(request), "")
    return {"ok": True}


@router.delete("/api/admin/groups/{group_id}")
def delete_group(group_id: int, request: Request):
    user = _guard(request, "write")
    row = db.one("SELECT name FROM grp WHERE id=?", (group_id,))
    if not row:
        return JSONResponse({"error": "分组不存在"}, status_code=404)
    db.run("DELETE FROM item WHERE group_id=?", (group_id,))
    db.run("DELETE FROM grp WHERE id=?", (group_id,))
    db.audit(user["id"], "group.delete", row["name"], security.client_ip(request), "")
    return {"ok": True}


@router.post("/api/admin/groups/reorder")
async def reorder_groups(request: Request):
    _guard(request, "write")
    body = await request.json()
    for i, gid in enumerate(body.get("ids") or []):
        db.run("UPDATE grp SET sort=? WHERE id=?", ((i + 1) * 10, gid))
    return {"ok": True}


# ---------- 卡片 ----------

@router.post("/api/admin/items")
async def create_item(request: Request):
    user = _guard(request, "write")
    b = await request.json()
    name = (b.get("name") or "").strip()[:60]
    group_id = int(b.get("group_id") or 0)
    if not name or not group_id:
        return JSONResponse({"error": "卡片名和分组必填"}, status_code=400)
    nxt = (db.scalar(
        "SELECT COALESCE(MAX(sort), 0) FROM item WHERE group_id=?", (group_id,)
    ) or 0) + 10
    now = db.utcnow()
    cur = db.run(
        "INSERT INTO item(group_id, name, url_lan, url_wan, icon, description, target,"
        " sort, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            group_id,
            name,
            (b.get("url_lan") or "").strip()[:500],
            (b.get("url_wan") or "").strip()[:500],
            (b.get("icon") or "").strip()[:200],
            (b.get("description") or "").strip()[:200],
            b.get("target") if b.get("target") in ("_blank", "_self") else "_blank",
            nxt,
            now,
            now,
        ),
    )
    db.audit(user["id"], "item.create", name, security.client_ip(request), "")
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/admin/items/{item_id}")
async def update_item(item_id: int, request: Request):
    user = _guard(request, "write")
    row = db.one("SELECT * FROM item WHERE id=?", (item_id,))
    if not row:
        return JSONResponse({"error": "卡片不存在"}, status_code=404)
    b = await request.json()
    db.run(
        "UPDATE item SET name=?, url_lan=?, url_wan=?, icon=?, description=?,"
        " target=?, updated_at=? WHERE id=?",
        (
            (b.get("name") or row["name"]).strip()[:60],
            str(b.get("url_lan", row["url_lan"]))[:500],
            str(b.get("url_wan", row["url_wan"]))[:500],
            str(b.get("icon", row["icon"]))[:200],
            str(b.get("description", row["description"]))[:200],
            b.get("target") if b.get("target") in ("_blank", "_self") else row["target"],
            db.utcnow(),
            item_id,
        ),
    )
    db.audit(user["id"], "item.update", row["name"], security.client_ip(request), "")
    return {"ok": True}


@router.delete("/api/admin/items/{item_id}")
def delete_item(item_id: int, request: Request):
    user = _guard(request, "write")
    row = db.one("SELECT name FROM item WHERE id=?", (item_id,))
    if not row:
        return JSONResponse({"error": "卡片不存在"}, status_code=404)
    db.run("DELETE FROM item WHERE id=?", (item_id,))
    db.audit(user["id"], "item.delete", row["name"], security.client_ip(request), "")
    return {"ok": True}


@router.post("/api/admin/items/reorder")
async def reorder_items(request: Request):
    _guard(request, "write")
    body = await request.json()
    rows = []
    for gid, ids in (body.get("layout") or {}).items():
        for i, iid in enumerate(ids):
            rows.append(((i + 1) * 10, int(gid), iid))
    db.run_many("UPDATE item SET sort=?, group_id=? WHERE id=?", rows)
    return {"ok": True}


# ---------- 图标：从网址自动抓 ----------

@router.post("/api/admin/icon-from-url")
async def icon_from_url(request: Request):
    """给一个网址，自动找出它的图标，转 webp 存进图标库，返回 /i/xxx.webp。

    抓取是本机发出去的请求（内网地址也放行，这正是主场景），
    所以单独限流：一次最多 20 次/分钟，够点错重试，不够刷。
    """
    user = _guard(request, "write")
    security.rate_limit(f"favicon:{user['id']}", 20)
    body = await request.json()
    url = (body.get("url") or "").strip()
    try:
        raw, source = favicon_svc.fetch_icon(url)
        row = upload_svc.save_icon(raw, f"auto-{urllib.parse.urlparse(source).netloc or 'icon'}")
    except favicon_svc.FetchError as exc:
        return JSONResponse({"error": f"抓不到图标：{exc}"}, status_code=400)
    except upload_svc.UploadError as exc:
        return JSONResponse({"error": f"抓到了但用不了：{exc}"}, status_code=400)
    db.audit(user["id"], "icon.fetch", source, security.client_ip(request), "")
    return {"ok": True, "icon": f"/i/{row['path']}", "source": source, "bytes": row["bytes"]}


# ---------- 图标 ----------

@router.post("/api/admin/icons")
async def upload_icon(request: Request, file: UploadFile = File(...)):
    user = _guard(request, "write")
    raw = await file.read()
    try:
        meta = upload_svc.save_icon(raw, file.filename or "icon")
    except upload_svc.UploadError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    db.audit(user["id"], "icon.upload", meta["path"], security.client_ip(request), "")
    return {"ok": True, "id": meta["id"], "url": f"/i/{meta['path']}"}


@router.delete("/api/admin/icons/{icon_id}")
def delete_icon(icon_id: int, request: Request):
    _guard(request, "write")
    try:
        upload_svc.delete_icon(icon_id)
    except upload_svc.UploadError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True}


# ---------- 设置 / 密码 ----------

@router.put("/api/admin/settings")
async def update_settings(request: Request):
    user = _guard(request, "write")
    body = await request.json()
    allow = {"site_name", "site_icon", "theme", "accent", "lan_cidrs", "footer", "require_login"}
    for k, v in body.items():
        if k in allow:
            val = str(v)[:500]
            if k == "accent" and val and not re.match(r"^#[0-9a-fA-F]{6}$", val):
                return JSONResponse({"error": "主题色需为 #rrggbb 格式"}, status_code=400)
            db.set_setting(k, val)
    db.audit(user["id"], "settings.update", ",".join(body.keys()), security.client_ip(request), "")
    return {"ok": True}


@router.post("/api/admin/password")
async def change_password(request: Request):
    user = _guard(request, "write")
    body = await request.json()
    old = body.get("old") or ""
    new = body.get("new") or ""
    if len(new) < 8:
        return JSONResponse({"error": "新密码至少 8 位"}, status_code=400)
    row = db.one("SELECT password_hash FROM user WHERE id=?", (user["id"],))
    if not row or not security.verify_password(row["password_hash"], old):
        return JSONResponse({"error": "原密码错误"}, status_code=400)
    db.run(
        "UPDATE user SET password_hash=? WHERE id=?",
        (security.hash_password(new), user["id"]),
    )
    db.audit(user["id"], "password.change", user["username"], security.client_ip(request), "")
    return {"ok": True}


# ---------- 备份 / 恢复 ----------

@router.get("/api/admin/backup")
def export_backup(request: Request):
    user = security.require_admin(request)
    raw = backup_svc.export_zip()
    db.audit(user["id"], "backup.export", "", security.client_ip(request), "")
    stamp = db.utcnow().replace(":", "").replace("-", "")[:13]
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="homedeck-{stamp}.zip"'},
    )


@router.post("/api/admin/restore")
async def restore_backup(request: Request, file: UploadFile = File(...)):
    user = _guard(request, "write")
    raw = await file.read()
    try:
        backup_svc.restore_zip(raw)
    except backup_svc.BackupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    db.audit(user["id"], "backup.restore", "", security.client_ip(request), "")
    return {"ok": True}
