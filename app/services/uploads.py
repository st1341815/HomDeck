"""图标上传：白名单校验 + Pillow 解码 + 统一转 webp。"""
from __future__ import annotations

import io
from secrets import token_hex

from PIL import Image, UnidentifiedImageError

from .. import config, db


class UploadError(Exception):
    pass


def save_icon(raw: bytes, original_name: str) -> dict:
    if not raw:
        raise UploadError("文件为空")
    if len(raw) > config.MAX_ICON_BYTES:
        raise UploadError(f"文件超过 {config.MAX_ICON_BYTES // 1024} KB")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UploadError("无法识别的图片格式")

    if img.format not in config.ALLOWED_IMAGE_FORMATS:
        raise UploadError(f"不支持的图片格式：{img.format}")

    img = img.convert("RGBA")
    side = config.ICON_MAX_SIDE
    if max(img.size) > side:
        img.thumbnail((side, side), Image.LANCZOS)

    stem = token_hex(8)
    filename = f"{stem}.webp"
    target = config.ICON_DIR / filename
    img.save(target, "WEBP", quality=88, method=6)

    name = (original_name or "icon").rsplit("/", 1)[-1][:80]
    db.run(
        "INSERT INTO icon(name, path, mime, bytes, created_at) VALUES (?,?,?,?,?)",
        (name, filename, "image/webp", target.stat().st_size, db.utcnow()),
    )
    row = db.one("SELECT * FROM icon WHERE path=?", (filename,))
    return dict(row)


def delete_icon(icon_id: int) -> None:
    row = db.one("SELECT * FROM icon WHERE id=?", (icon_id,))
    if not row:
        raise UploadError("图标不存在")
    used = db.scalar(
        "SELECT COUNT(*) FROM item WHERE icon = ?", (f"/i/{row['path']}",)
    )
    if used:
        raise UploadError("该图标仍被卡片引用，不能删除")
    db.run("DELETE FROM icon WHERE id=?", (icon_id,))
    try:
        (config.ICON_DIR / row["path"]).unlink()
    except FileNotFoundError:
        pass


def list_icons() -> list[dict]:
    rows = db.all_rows("SELECT * FROM icon ORDER BY id DESC")
    return [
        {"id": r["id"], "name": r["name"], "url": f"/i/{r['path']}", "bytes": r["bytes"]}
        for r in rows
    ]
