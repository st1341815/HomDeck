#!/usr/bin/env python3
"""把 item 的内网/外网地址按 URL 性质重新归位。

背景：从 Sun-Panel 导入时，原 `url` 字段一律写进了 url_lan，导致公网域名
（deepseek / github / cloudflare …）也被当成内网地址。结果是手动切到「外网」
模式时这些卡片无外网地址可用，切换等于没切。

规则：
- 主机是私有 IP / 回环 / .local / localhost → 属于 url_lan
- 其余（公网域名、公网 IP、域名后缀）        → 属于 url_wan
- 两边都有值且性质冲突时，按上述规则各归各位；相同时清掉 url_wan
- 空值不动

用法：
  python3 scripts/fix_url_split.py --hd-base http://192.168.1.10:3302 \
      --hd-user admin --hd-pass '***' [--dry-run]
"""
from __future__ import annotations

import argparse
import ipaddress
import sys
from urllib.parse import urlparse

import requests


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hd-base", required=True)
    p.add_argument("--hd-user", default="admin")
    p.add_argument("--hd-pass", required=True)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def is_private_url(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").strip().lower()
    if not host:
        return True  # 相对路径/无主机，保持原样当内网
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or host.endswith(".local")
    return ip.is_private or ip.is_loopback or ip.is_link_local


def classify(item: dict) -> tuple[str, str]:
    lan = (item.get("url_lan") or "").strip()
    wan = (item.get("url_wan") or "").strip()
    if lan and wan and lan == wan:
        return lan, ""
    # 把放错位置的地址搬回去
    if lan and not is_private_url(lan):
        if not wan:
            return "", lan
        return lan, wan  # 两边都非私有：不动，交给人判断
    if wan and is_private_url(wan):
        if not lan:
            return wan, ""
        return lan, wan
    return lan, wan


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

    def overview(self):
        r = self.s.get(f"{self.base}/api/admin/overview", timeout=10)
        r.raise_for_status()
        return r.json()

    def patch_item(self, item_id: int, body: dict):
        r = self.s.patch(
            f"{self.base}/api/admin/items/{item_id}",
            json=body,
            headers={"X-CSRF-Token": self.csrf},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


def main():
    args = parse_args()
    hd = HomDeck(args.hd_base, args.hd_user, args.hd_pass)
    items = hd.overview()["items"]
    changed = 0
    for it in items:
        lan, wan = classify(it)
        if lan == (it.get("url_lan") or "") and wan == (it.get("url_wan") or ""):
            continue
        changed += 1
        print(
            f"{'[dry] ' if args.dry_run else ''}{it['name']}: "
            f"lan={it.get('url_lan')!r}→{lan!r}  wan={it.get('url_wan')!r}→{wan!r}"
        )
        if not args.dry_run:
            hd.patch_item(
                it["id"],
                {
                    "name": it["name"],
                    "url_lan": lan,
                    "url_wan": wan,
                    "icon": it["icon"],
                    "description": it["description"],
                    "target": it["target"],
                },
            )
    print(f"完成：检查 {len(items)} 张卡片，需要调整 {changed} 张")


if __name__ == "__main__":
    main()