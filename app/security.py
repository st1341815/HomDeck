"""认证、会话、CSRF、限流、内网判定。"""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config, db

_ph = PasswordHasher()
_serializer: URLSafeTimedSerializer | None = None


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(hashed: str, raw: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _ser() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(config.load_secret(), salt="homedeck")
    return _serializer


# ---------- 会话 ----------

def issue_session(resp: Response, user_id: int, csrf: str) -> None:
    token = _ser().dumps({"uid": user_id})
    resp.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    resp.set_cookie(
        config.CSRF_COOKIE,
        csrf,
        max_age=config.SESSION_MAX_AGE,
        httponly=False,
        samesite="lax",
        path="/",
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(config.SESSION_COOKIE, path="/")
    resp.delete_cookie(config.CSRF_COOKIE, path="/")


def session_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _ser().loads(token, max_age=config.SESSION_MAX_AGE)
    except BadSignature:
        return None
    row = db.one(
        "SELECT id, username, display_name, role, is_active FROM user WHERE id=?",
        (data.get("uid"),),
    )
    if not row or not row["is_active"]:
        return None
    return dict(row)


def require_admin(request: Request) -> dict:
    user = session_user(request)
    if not user:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="请先登录")
    if user["role"] != "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def check_csrf(request: Request) -> None:
    from fastapi import HTTPException

    cookie = request.cookies.get(config.CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=403, detail="CSRF 校验失败，请刷新页面重试")


# ---------- 限流（内存滑窗） ----------

_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window: float = 60.0) -> None:
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
    bucket.append(now)


# ---------- 内网判定 ----------

def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "0.0.0.0"


def _cidrs(raw: str) -> list:
    out = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            continue
    return out


def is_lan(ip: str, cidrs_raw: Optional[str] = None) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    raw = cidrs_raw if cidrs_raw is not None else db.get_setting(
        "lan_cidrs", config.DEFAULT_LAN_CIDRS
    )
    return any(addr in net for net in _cidrs(raw))
