"""SQLite 访问层：标准库 sqlite3，无 ORM，SQL 全部可审计。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from . import config

_conn: sqlite3.Connection | None = None


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.ICON_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(
            config.DB_PATH,
            check_same_thread=False,
            isolation_level=None,  # 自己管事务
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def close() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        finally:
            _conn = None


def init_db() -> None:
    conn = connect()
    conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '2')"
    )
    _seed_admin(conn)
    _seed_settings(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """给老库补列。新库走 schema.sql 就有，这里只处理已经存在的旧表。

    写成幂等的（先查 PRAGMA 再 ALTER），重启多少次都安全。
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(icon)")}
    if "sha" not in cols:
        conn.execute("ALTER TABLE icon ADD COLUMN sha TEXT")
        conn.commit()
        print("[HomDeck] 迁移：icon 表新增 sha 列（图标内容去重）", flush=True)
    # 索引必须在 sha 列存在之后建：老库的表是 IF NOT EXISTS 跳过去的，
    # 把这个语句放进 schema.sql 会在 ALTER 之前执行而报 no such column
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_icon_sha ON icon(sha) WHERE sha IS NOT NULL"
    )
    conn.commit()


def _seed_admin(conn: sqlite3.Connection) -> None:
    from .security import hash_password

    row = conn.execute("SELECT COUNT(*) AS n FROM user").fetchone()
    if row["n"]:
        return
    password = config.ADMIN_PASSWORD
    generated = False
    if not password:
        from secrets import token_urlsafe

        password = token_urlsafe(9)
        generated = True
    conn.execute(
        "INSERT INTO user(username, password_hash, display_name, role, created_at)"
        " VALUES (?,?,?,?,?)",
        (config.ADMIN_USER, hash_password(password), "管理员", "admin", utcnow()),
    )
    if generated:
        print("=" * 60, flush=True)
        print(f"[HomDeck] 初始管理员账号：{config.ADMIN_USER}", flush=True)
        print(f"[HomDeck] 初始密码（只显示这一次，请立刻修改）：{password}", flush=True)
        print("=" * 60, flush=True)


def _seed_settings(conn: sqlite3.Connection) -> None:
    defaults = {
        "site_name": "HomDeck",
        "site_icon": "🧭",
        "theme": "auto",
        "lan_cidrs": config.DEFAULT_LAN_CIDRS,
        "footer": "",
        "require_login": "0",
    }
    conn.executemany(
        "INSERT OR IGNORE INTO setting(key, value) VALUES (?,?)", list(defaults.items())
    )


def all_rows(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, params).fetchall()


def one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return connect().execute(sql, params).fetchone()


def scalar(sql: str, params: Sequence[Any] = ()) -> Any:
    row = one(sql, params)
    return row[0] if row else None


def run(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return connect().execute(sql, params)


def run_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    conn = connect()
    conn.execute("BEGIN")
    try:
        conn.executemany(sql, seq)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_setting(key: str, default: str = "") -> str:
    row = one("SELECT value FROM setting WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    run(
        "INSERT INTO setting(key, value) VALUES (?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def audit(user_id: int | None, action: str, target: str, ip: str, ua: str) -> None:
    run(
        "INSERT INTO audit(user_id, action, target, ip, ua, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (user_id, action, target[:200], ip[:64], ua[:200], utcnow()),
    )
