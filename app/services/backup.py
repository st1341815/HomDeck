"""全站备份与恢复：zip 只含 app.db + icons/，不含密钥以外的任何东西。"""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from .. import config, db

REQUIRED = {"app.db"}


class BackupError(Exception):
    pass


def export_zip() -> bytes:
    buf = io.BytesIO()
    conn = db.connect()
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(config.DB_PATH, "app.db")
        if config.ICON_DIR.exists():
            for f in sorted(config.ICON_DIR.iterdir()):
                if f.is_file():
                    zf.write(f, f"icons/{f.name}")
    buf.seek(0)
    return buf.read()


def restore_zip(raw: bytes) -> int:
    """校验 → 备份旧库 → 原子替换。失败抛异常，旧数据不动。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise BackupError("不是有效的 zip 文件")

    names = set(zf.namelist())
    if not REQUIRED.issubset(names):
        raise BackupError("备份包缺少 app.db")
    for n in names:
        if n.startswith("/") or ".." in Path(n).parts:
            raise BackupError("备份包路径非法")

    stamp = db.utcnow().replace(":", "").replace("-", "")[:15]
    backup_path = config.DATA_DIR / f"app.db.bak.{stamp}"
    if config.DB_PATH.exists():
        shutil.copy2(config.DB_PATH, backup_path)

    tmp_db = config.DATA_DIR / "app.db.restoring"
    with zf.open("app.db") as src, open(tmp_db, "wb") as dst:
        shutil.copyfileobj(src, dst)

    # 校验是合法 SQLite 且含 user 表
    import sqlite3

    try:
        probe = sqlite3.connect(tmp_db)
        probe.execute("SELECT COUNT(*) FROM user").fetchone()
        probe.close()
    except sqlite3.DatabaseError:
        tmp_db.unlink(missing_ok=True)
        raise BackupError("备份包里的数据库已损坏")

    from .. import db as dbmod

    dbmod.close()
    shutil.move(str(tmp_db), str(config.DB_PATH))

    if config.ICON_DIR.exists():
        shutil.rmtree(config.ICON_DIR)
    config.ICON_DIR.mkdir(parents=True, exist_ok=True)
    for n in names:
        if n.startswith("icons/") and not n.endswith("/"):
            target = config.ICON_DIR / Path(n).name
            with zf.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

    dbmod.init_db()
    return 1
