"""模板渲染：统一注入站点信息、当前用户、CSRF。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import db, security
from .config import VERSION

_TPL_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TPL_DIR))

# 只接受 #rrggbb，避免把任意字符串拼进 style
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def safe_accent(value: str = "") -> str:
    return value if _HEX.match(value or "") else ""


def render(name: str, request: Request, ctx: Optional[dict[str, Any]] = None):
    data: dict[str, Any] = {
        "request": request,
        "site_name": db.get_setting("site_name", "HomDeck"),
        "site_icon": db.get_setting("site_icon", "🧭"),
        "site_theme": db.get_setting("theme", "auto"),
        "site_accent": safe_accent(db.get_setting("accent", "")),
        "user": security.session_user(request),
        "csrf": request.cookies.get("hd_csrf", ""),
        "version": VERSION,
    }
    if ctx:
        data.update(ctx)
    return templates.TemplateResponse(request=request, name=name, context=data)
