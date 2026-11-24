-- HomDeck schema v1
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL DEFAULT '',
  role          TEXT NOT NULL DEFAULT 'admin',
  is_active     INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grp (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  icon       TEXT NOT NULL DEFAULT '',
  sort       INTEGER NOT NULL DEFAULT 0,
  visible    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id    INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  url_lan     TEXT NOT NULL DEFAULT '',
  url_wan     TEXT NOT NULL DEFAULT '',
  icon        TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  target      TEXT NOT NULL DEFAULT '_blank',
  sort        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_item_group_sort ON item(group_id, sort);

CREATE TABLE IF NOT EXISTS icon (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  path       TEXT NOT NULL UNIQUE,
  sha        TEXT,                 -- 转码后 webp 的 sha256，用于内容去重
  mime       TEXT NOT NULL,
  bytes      INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setting (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER,
  action     TEXT NOT NULL,
  target     TEXT,
  ip         TEXT,
  ua         TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit(created_at DESC);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 访问统计：谁在什么时候打开了哪张卡片。
-- 卡片名与分组名冗余存一份：卡片被删掉之后，历史记录还能看懂是什么。
-- day 是「本地日期」（UTC + HOMEDECK_TZ_OFFSET），按天聚合直接 GROUP BY，
-- 不依赖容器时区，也不用在 SQL 里做时区运算。
CREATE TABLE IF NOT EXISTS visit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id    INTEGER,
  item_name  TEXT NOT NULL DEFAULT '',
  group_name TEXT NOT NULL DEFAULT '',
  ip_hash    TEXT NOT NULL DEFAULT '',
  net        TEXT NOT NULL DEFAULT '',
  ua         TEXT NOT NULL DEFAULT '',
  day        TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_visit_created ON visit(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_visit_day ON visit(day);
CREATE INDEX IF NOT EXISTS ix_visit_item ON visit(item_id);
