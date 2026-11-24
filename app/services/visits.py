"""访问统计：卡片被打开的次数、时间、来源网络、访客指纹。

几条设计约束，写在这儿免得以后改坏：

1. **IP 不落库**，只存 sha256 前 16 位，配合同一个 secret 做盐——用来数「独立访客」，
   反查不出是谁。家庭面板的访客本来也就那几个 IP，但没必要留明文。
2. **day 存本地日期**（UTC + config.TZ_OFFSET_HOURS）。按天聚合直接 GROUP BY day，
   不在 SQL 里算时区，也不依赖容器的 tzdata。
3. **卡片名/分组名冗余存一份**。卡片删掉之后 visit.item_id 指向的空气，
   但明细里还能看到「当时打开的是啥」。排行则以当前卡片清单为准（含 0 次的）。
4. 3 秒内的同一 (IP, 卡片) 视为同一次打开，不重复计数——双击、刷新回退都会触发 click。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .. import config, db, security

# 去抖用的内存表：{(ip_hash, item_id): 上次记录时间戳}
_recent: dict[tuple[str, int], float] = {}
_salt: str | None = None


def local_day(now: datetime | None = None) -> str:
    """把 UTC 时刻折算成配置时区下的日期字符串。"""
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=config.TZ_OFFSET_HOURS)).strftime("%Y-%m-%d")


def _shift(days: int) -> str:
    now = datetime.now(timezone.utc) + timedelta(hours=config.TZ_OFFSET_HOURS)
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")


def _ip_hash(ip: str) -> str:
    # salt 缓存一份：load_secret() 在没有环境变量时会去读 data/secret.key，
    # 每点一次卡片读一次文件没必要
    global _salt
    if _salt is None:
        _salt = config.load_secret()
    return hashlib.sha256(f"{_salt}|{ip}".encode("utf-8")).hexdigest()[:16]


def record(item_id: int, ip: str, ua: str) -> bool:
    """记一次打开。返回 True 表示确实写库了。"""
    row = db.one(
        "SELECT i.id, i.name, g.name AS group_name"
        " FROM item i LEFT JOIN grp g ON g.id = i.group_id WHERE i.id=?",
        (item_id,),
    )
    if not row:  # 卡片不存在（刚被删掉 / 乱传 id），静默丢弃
        return False

    ip_hash = _ip_hash(ip)
    now = datetime.now(timezone.utc).timestamp()
    key = (ip_hash, item_id)
    last = _recent.get(key)
    if last is not None and now - last < config.VISIT_DEBOUNCE_SEC:
        return False
    _recent[key] = now
    if len(_recent) > 2000:  # 简易防水：超了就清掉过期的
        cutoff = now - config.VISIT_DEBOUNCE_SEC
        for k, ts in list(_recent.items()):
            if ts < cutoff:
                _recent.pop(k, None)

    db.run(
        "INSERT INTO visit(item_id, item_name, group_name, ip_hash, net, ua, day, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            item_id,
            row["name"][:120],
            (row["group_name"] or "")[:120],
            ip_hash,
            "lan" if security.is_lan(ip) else "wan",
            (ua or "")[:200],
            local_day(),
            db.utcnow(),
        ),
    )
    return True


def prune() -> int:
    """删掉超过保留期的记录。启动时跑一次，返回删除条数。"""
    cutoff = _shift(config.VISIT_KEEP_DAYS)
    n = db.scalar("SELECT COUNT(*) FROM visit WHERE day < ?", (cutoff,)) or 0
    if n:
        db.run("DELETE FROM visit WHERE day < ?", (cutoff,))
    return int(n)


def _ua_brief(ua: str) -> str:
    """把 UA 压成「系统 · 浏览器」两段，明细表里一列放得下。"""
    if not ua:
        return "未知"
    low = ua.lower()
    if "iphone" in low or "ipad" in low:
        os_name = "iOS"
    elif "android" in low:
        os_name = "Android"
    elif "windows" in low:
        os_name = "Windows"
    elif "mac os" in low or "macintosh" in low:
        os_name = "macOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = "其他"

    for key, label in (
        ("edg/", "Edge"),
        ("opr/", "Opera"),
        ("firefox/", "Firefox"),
        ("chrome/", "Chrome"),
        ("safari/", "Safari"),
        ("curl/", "curl"),
        ("python", "Python"),
    ):
        if key in low:
            return f"{os_name} · {label}"
    return os_name


def overview(days: int = 14) -> dict:
    """统计页要的全部数据，一次查完前端只渲染。"""
    today = local_day()
    week_ago = _shift(6)          # 含今天共 7 天
    span_start = _shift(days - 1)  # 趋势图窗口

    total = db.scalar("SELECT COUNT(*) FROM visit") or 0
    today_n = db.scalar("SELECT COUNT(*) FROM visit WHERE day=?", (today,)) or 0
    week_n = db.scalar("SELECT COUNT(*) FROM visit WHERE day>=?", (week_ago,)) or 0
    # 独立访客：总 / 近 7 天各一个
    uniq_total = db.scalar("SELECT COUNT(DISTINCT ip_hash) FROM visit") or 0
    uniq_week = (
        db.scalar("SELECT COUNT(DISTINCT ip_hash) FROM visit WHERE day>=?", (week_ago,)) or 0
    )

    # 趋势：先按天聚合，再补齐空缺的日期（没有访问的日子也要占一根空柱）
    rows = db.all_rows(
        "SELECT day, COUNT(*) AS n FROM visit WHERE day>=? GROUP BY day", (span_start,)
    )
    by_day = {r["day"]: r["n"] for r in rows}
    today_dt = datetime.now(timezone.utc) + timedelta(hours=config.TZ_OFFSET_HOURS)
    trend = []
    for i in range(days - 1, -1, -1):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"day": d, "n": by_day.get(d, 0)})

    # 卡片排行：以当前卡片清单为准，0 次的也在（用来看哪些连接没人点）
    rank = [
        {
            "id": r["id"],
            "name": r["name"],
            "group": r["group_name"] or "",
            "n": r["n"],
            "last": r["last"],
        }
        for r in db.all_rows(
            "SELECT i.id, i.name, g.name AS group_name,"
            " (SELECT COUNT(*) FROM visit v WHERE v.item_id = i.id) AS n,"
            " (SELECT MAX(v.created_at) FROM visit v WHERE v.item_id = i.id) AS last"
            " FROM item i LEFT JOIN grp g ON g.id = i.group_id"
            " ORDER BY n DESC, i.name"
        )
    ]

    net_rows = {
        r["net"]: r["n"]
        for r in db.all_rows(
            "SELECT net, COUNT(*) AS n FROM visit WHERE day>=? GROUP BY net", (week_ago,)
        )
    }

    recent = [
        {
            "at": r["created_at"],
            "name": r["name"] or r["item_name"],
            "group": r["group_name"],
            "net": r["net"],
            "ip": r["ip_hash"],
            "ua": _ua_brief(r["ua"]),
            "ua_raw": r["ua"],
        }
        for r in db.all_rows(
            "SELECT v.id, v.created_at, v.item_name, v.group_name, v.net, v.ip_hash, v.ua,"
            " COALESCE(i.name, '') AS name"
            " FROM visit v LEFT JOIN item i ON i.id = v.item_id"
            " ORDER BY v.id DESC LIMIT 50"
        )
    ]

    return {
        "kpi": {
            "total": total,
            "today": today_n,
            "week": week_n,
            "uniq_total": uniq_total,
            "uniq_week": uniq_week,
            "items": len(rank),
            "never": sum(1 for x in rank if x["n"] == 0),
        },
        "trend": trend,
        "rank": rank,
        "net": {"lan": net_rows.get("lan", 0), "wan": net_rows.get("wan", 0)},
        "recent": recent,
        "keep_days": config.VISIT_KEEP_DAYS,
        "range": {"start": span_start, "end": today, "days": days},
    }
