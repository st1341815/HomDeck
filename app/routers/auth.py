"""登录、登出、当前用户。"""
from __future__ import annotations

from secrets import token_urlsafe

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .. import db, security
from ..rendering import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if security.session_user(request):
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/admin", status_code=303)
    return render("login.html", request, {"site_name": db.get_setting("site_name", "HomDeck")})


@router.post("/api/auth/login")
async def login(request: Request, response: Response):
    ip = security.client_ip(request)
    security.rate_limit(f"login:{ip}", 5)
    body = await request.json()
    username = (body.get("username") or "").strip()[:64]
    password = body.get("password") or ""

    row = db.one("SELECT * FROM user WHERE username=?", (username,))
    ok = bool(row) and row["is_active"] and security.verify_password(
        row["password_hash"], password
    )
    if not ok:
        db.audit(None, "login.fail", username, ip, request.headers.get("user-agent", ""))
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)

    csrf = token_urlsafe(24)
    security.issue_session(response, row["id"], csrf)
    db.run("UPDATE user SET last_login_at=? WHERE id=?", (db.utcnow(), row["id"]))
    db.audit(row["id"], "login.ok", username, ip, request.headers.get("user-agent", ""))
    return {"ok": True, "redirect": "/admin", "csrf": csrf}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    user = security.session_user(request)
    if user:
        security.check_csrf(request)
        db.audit(user["id"], "logout", user["username"], security.client_ip(request), "")
    security.clear_session(response)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    user = security.session_user(request)
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    return {"authenticated": True, "user": user}
