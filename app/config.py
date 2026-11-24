"""HomDeck 配置：全部来自环境变量，无隐式默认之外的魔法。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HOMEDECK_DATA", BASE_DIR / "data")).resolve()
ICON_DIR = DATA_DIR / "icons"
DB_PATH = DATA_DIR / "app.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

VERSION = "0.8.3"

# 会话签名密钥：优先环境变量，其次持久化到 data/secret.key
SECRET_KEY = os.environ.get("HOMEDECK_SECRET", "")
SESSION_COOKIE = "hd_session"
CSRF_COOKIE = "hd_csrf"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

# 首次启动创建的管理员
ADMIN_USER = os.environ.get("HOMEDECK_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("HOMEDECK_ADMIN_PASSWORD", "")

# 反向代理场景下才信任 X-Forwarded-For
TRUST_PROXY = os.environ.get("HOMEDECK_TRUST_PROXY", "0") == "1"

DEFAULT_LAN_CIDRS = "127.0.0.1/32,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"

# 上传限制
MAX_ICON_BYTES = 512 * 1024
ICON_MAX_SIDE = 512
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "ICO"}

# 限流
LOGIN_LIMIT_PER_MIN = 5
WRITE_LIMIT_PER_MIN = 60


def load_secret() -> str:
    """密钥只生成一次，落盘在 data/secret.key，随数据一起备份。"""
    if SECRET_KEY:
        return SECRET_KEY
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    from secrets import token_urlsafe

    key = token_urlsafe(48)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key
