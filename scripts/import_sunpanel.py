#!/usr/bin/env python3
"""把 Sun-Panel 的卡片数据导入 HomDeck（用于两边对比效果）。

用法：
  python3 scripts/import_sunpanel.py \
      --sp-db /tmp/spdb/database.db \
      --sp-base http://192.168.1.6:13002 \
      --hd-base http://192.168.1.10:3302 \
      --hd-user admin --hd-pass '***' \
      [--wipe]

说明：
- 只导 deleted_at IS NULL 的记录；
- 分组按 sort 顺序；空分组跳过；
- 卡片图标从 Sun-Panel 的 /uploads/... 下载后上传到 HomDeck，转 webp 存储；
- 内网地址写 HomDeck 的 url_lan（Sun-Panel 的 url 字段本质是"直接用这个地址"），
  url_wan 留空，外网访问时 HomDeck 会自动回退到 url_lan，行为与 Sun-Panel 一致。
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys

import requests


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sp-db", required=True)
    p.add_argument("--sp-base", default="http://192.168.1.6:13002")
    p.add_argument("--hd-base", required=True)
    p.add_argument("--hd-user", default="admin")
    p.add_argument("--hd-pass", required=True)
    p.add_argument("--wipe", action="store_true", help="先清空 HomDeck 现有分组")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def sp_load(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    groups = [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, sort FROM item_icon_group"
            " WHERE deleted_at IS NULL ORDER BY sort, id"
        )
    ]
    cards = [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, url, lan_url, description, icon_json, item_icon_group_id,"
            " sort FROM item_icon WHERE deleted_at IS NULL ORDER BY sort, id"
        )
    ]
    return groups, cards


def icon_src(raw: str) -> str:
    try:
        d = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return ""
    return (d.get("src") or "").strip()


class HomDeck:
    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        r = self.s.post(
            f"{self.base}/api/auth/login",
            json={"username": user, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        self.csrf = r.json().get("csrf") or self.s.cookies.get("hd_csrf")
        if not self.csrf:
            sys.exit("登录成功但拿不到 CSRF token")

    def _h(self, extra=None):
        h = {"X-CSRF-Token": self.csrf}
        if extra:
            h.update(extra)
        return h

    def overview(self):
        r = self.s.get(f"{self.base}/api/admin/overview", timeout=10)
        r.raise_for_status()
        return r.json()

    def delete_group(self, gid: int):
        self.s.delete(
            f"{self.base}/api/admin/groups/{gid}", headers=self._h(), timeout=10
        )

    def add_group(self, name: str, icon: str) -> int:
        r = self.s.post(
            f"{self.base}/api/admin/groups",
            json={"name": name, "icon": icon},
            headers=self._h(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["id"]

    def upload_icon(self, filename: str, raw: bytes) -> str:
        r = self.s.post(
            f"{self.base}/api/admin/icons",
            headers=self._h(),
            files={"file": (filename, raw)},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["url"]

    def add_item(self, **kw) -> int:
        r = self.s.post(
            f"{self.base}/api/admin/items", json=kw, headers=self._h(), timeout=10
        )
        r.raise_for_status()
        return r.json()["id"]


GROUP_EMOJI = ["📚", "🏠", "📱", "🛠️", "🧪", "📦"]


def main():
    a = parse_args()
    groups, cards = sp_load(a.sp_db)
    hd = HomDeck(a.hd_base, a.hd_user, a.hd_pass)

    alive = {g["id"]: g for g in groups}
    cards_by_group: dict[int, list] = {}
    for c in cards:
        if c["item_icon_group_id"] in alive:
            cards_by_group.setdefault(c["item_icon_group_id"], []).append(c)

    print(f"Sun-Panel：{len(alive)} 个分组，{len(cards)} 张卡片")
    if a.dry_run:
        for g in groups:
            print(" ", g["title"], len(cards_by_group.get(g["id"], [])))
        return

    if a.wipe:
        for g in hd.overview()["groups"]:
            hd.delete_group(g["id"])
            print(f"  清空旧分组 {g['name']}")

    idx = 0
    for g in groups:
        items = cards_by_group.get(g["id"], [])
        if not items:
            print(f"  跳过空分组：{g['title']}")
            continue
        emoji = GROUP_EMOJI[idx % len(GROUP_EMOJI)]
        idx += 1
        gid = hd.add_group(g["title"], emoji)
        print(f"分组 [{g['title']}] → id={gid}，{len(items)} 张卡片")
        for c in items:
            icon = ""
            src = icon_src(c["icon_json"])
            if src:
                try:
                    ir = requests.get(f"{a.sp_base}{src}", timeout=20)
                    ir.raise_for_status()
                    icon = hd.upload_icon(src.rsplit("/", 1)[-1], ir.content)
                except Exception as exc:  # 图标失败不阻塞卡片导入
                    print(f"    ! 图标失败 {c['title']}: {exc}")
            hd.add_item(
                group_id=gid,
                name=c["title"][:60],
                url_lan=(c["lan_url"] or c["url"] or "").strip(),
                url_wan=(c["url"] if c["lan_url"] else "").strip(),
                icon=icon,
                description=(c["description"] or "").strip(),
            )
            print(f"    + {c['title']}  {c['lan_url'] or c['url']}")

    ov = hd.overview()
    print(
        f"\n完成：HomDeck 现有 {len(ov['groups'])} 个分组 / {len(ov['items'])} 张卡片，"
        f"图标 {len(ov['icons'])} 个"
    )


if __name__ == "__main__":
    main()