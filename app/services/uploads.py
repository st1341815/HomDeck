"""图标上传：白名单校验 + Pillow 解码 + 统一转 webp + 内容去重。

去重的关键在顺序：先解码转码成 webp，再对**转码后的字节**算 sha256。
这样同一个图标不管来自 上传 .ico / 抓取 .png / 换了文件名 / 不同服务抓同一张，
最终都落在同一个 sha 上，图标库里只会有一条。
"""
from __future__ import annotations

import hashlib
import io
from secrets import token_hex

from PIL import Image, UnidentifiedImageError

from .. import config, db


class UploadError(Exception):
    pass


def _to_webp(raw: bytes) -> bytes:
    """校验并转成 webp 字节。同一份输入必然产出同一份输出，去重才有意义。"""
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

    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_icon(raw: bytes, original_name: str) -> dict:
    """存图标。内容已存在则直接复用那条记录，不新建文件、不新增记录。"""
    data = _to_webp(raw)
    sha = _sha(data)

    dup = db.one("SELECT * FROM icon WHERE sha=?", (sha,))
    if dup:
        return {**dict(dup), "reused": True}

    filename = f"{token_hex(8)}.webp"
    target = config.ICON_DIR / filename
    target.write_bytes(data)

    name = (original_name or "icon").rsplit("/", 1)[-1][:80]
    db.run(
        "INSERT INTO icon(name, path, sha, mime, bytes, created_at) VALUES (?,?,?,?,?,?)",
        (name, filename, sha, "image/webp", len(data), db.utcnow()),
    )
    row = db.one("SELECT * FROM icon WHERE path=?", (filename,))
    return {**dict(row), "reused": False}


def delete_icon(icon_id: int) -> None:
    row = db.one("SELECT * FROM icon WHERE id=?", (icon_id,))
    if not row:
        raise UploadError("图标不存在")
    used = db.scalar(
        "SELECT COUNT(*) FROM item WHERE icon = ?", (f"/i/{row['path']}",)
    )
    if used:
        raise UploadError(f"仍被 {used} 张卡片使用，先把它们的图标换掉再删")
    db.run("DELETE FROM icon WHERE id=?", (icon_id,))
    try:
        (config.ICON_DIR / row["path"]).unlink()
    except FileNotFoundError:
        pass


def rename_icon(icon_id: int, name: str) -> dict:
    """给图标起个人名。空白折叠成单空格，最长 80 字。"""
    clean = " ".join((name or "").split())[:80]
    if not clean:
        raise UploadError("名字不能为空")
    row = db.one("SELECT * FROM icon WHERE id=?", (icon_id,))
    if not row:
        raise UploadError("图标不存在")
    db.run("UPDATE icon SET name=? WHERE id=?", (clean, icon_id))
    return {"id": icon_id, "name": clean, "old": row["name"]}


def _merge_into(keep: dict, dup: dict) -> None:
    """把 dup 合并进 keep：卡片引用改过去，多余的记录和文件删掉。"""
    db.run(
        "UPDATE item SET icon=? WHERE icon=?",
        (f"/i/{keep['path']}", f"/i/{dup['path']}"),
    )
    # auto- 前缀是抓取时自动起的名字，有机会就换成用户自己起的
    if keep["name"].startswith("auto-") and not dup["name"].startswith("auto-"):
        db.run("UPDATE icon SET name=? WHERE id=?", (dup["name"], keep["id"]))
    db.run("DELETE FROM icon WHERE id=?", (dup["id"],))
    try:
        (config.ICON_DIR / dup["path"]).unlink()
    except FileNotFoundError:
        pass


def dedupe_icons() -> dict:
    """把历史上重复存下的同一张图合并成一条（启动时跑一次，幂等）。

    早期 save_icon 只按文件名随机命名，不看内容——于是 4 台用同一套默认图标的
    NAS 会存成 4 份，同一个服务抓两次会存成 2 份。这里按转码后字节的 sha256
    归并，顺便把早期记录缺的 sha 回填上。
    """
    rows = db.all_rows("SELECT * FROM icon ORDER BY id")
    merged = 0
    backfilled = 0
    for r in rows:
        path = config.ICON_DIR / r["path"]
        if not path.exists():
            continue
        try:
            sha = _sha(path.read_bytes())
        except OSError:
            continue

        cur_sha = r["sha"] if "sha" in r.keys() else None
        holder = db.one("SELECT * FROM icon WHERE sha=?", (sha,))
        if holder and holder["id"] != r["id"]:
            _merge_into(dict(holder), dict(r))
            merged += 1
            continue

        if cur_sha != sha:
            db.run("UPDATE icon SET sha=? WHERE id=?", (sha, r["id"]))
            backfilled += 1

    return {"merged": merged, "backfilled": backfilled}


def list_icons() -> list[dict]:
    """用得多的排前面——清理时一眼看出哪些是没人用的孤儿图标。"""
    rows = db.all_rows(
        "SELECT i.*, (SELECT COUNT(*) FROM item WHERE item.icon = '/i/' || i.path) AS used"
        " FROM icon i ORDER BY used DESC, i.id DESC"
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "url": f"/i/{r['path']}",
            "bytes": r["bytes"],
            "used": r["used"],
        }
        for r in rows
    ]
