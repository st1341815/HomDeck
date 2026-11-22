"""图标与静态资源输出（只读、带缓存头、防目录穿越）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from .. import config

router = APIRouter()


@router.get("/i/{filename}")
def icon_file(filename: str):
    if "/" in filename or ".." in filename:
        return JSONResponse({"error": "非法路径"}, status_code=400)
    target = config.ICON_DIR / filename
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(
        target,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=2592000, immutable"},
    )


@router.get("/favicon.ico")
def favicon():
    f = Path(config.BASE_DIR) / "app" / "static" / "favicon.svg"
    if f.is_file():
        return FileResponse(f, media_type="image/svg+xml")
    return JSONResponse({"error": "not found"}, status_code=404)
