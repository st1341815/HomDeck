"""从网址自动抓图标。

顺序：apple-touch-icon → 最大的 rel=icon → og:image / twitter:image → /favicon.ico。
内网服务是本项目的主场景，所以：
  - 允许私有地址（192.168/10/172.16）——这正是要抓的对象，不做 SSRF 白名单；
    接口本身要求管理员登录 + 限流，滥用面等于管理员自己的权限。
  - 允许自签名 HTTPS（verify 关掉）：内网 https 自签是常态，且这里只读图片。
不引第三方库，只用标准库 urllib，失败就抛 FetchError 给前端一句人话。
"""
from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 HomDeck"
)
TIMEOUT = 6
MAX_HTML = 512 * 1024          # 只需要 <head>，百度首页也在这之内
MAX_IMAGE = 1024 * 1024

LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"""
)

# 常见位图魔数：拿不到 Content-Type 时兜底判断
MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"\x00\x00\x01\x00", b"BM")


class FetchError(Exception):
    """抓取失败，消息直接给用户看。"""


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise FetchError("地址为空")
    if url.startswith("//"):
        url = "http:" + url
    elif not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchError("只支持 http / https 地址")
    return url


def _opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def _get(url: str, limit: int, truncate: bool = False) -> tuple[bytes, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Connection": "close",
        },
    )
    try:
        resp = _opener().open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"对方返回 HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"连不上（{reason}）")
    except Exception as exc:  # 超时/证书/协议错误一律收敛成一句话
        raise FetchError(f"连不上（{exc.__class__.__name__}）")

    with resp:
        data = resp.read(limit + 1)
        final = resp.geturl()
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if len(data) > limit:
        if not truncate:
            raise FetchError("响应太大，放弃了")
        data = data[:limit]  # HTML 只解析头部，后面的正文没意义
    return data, ctype, final


def _attrs(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(tag):
        out[m.group(1).lower()] = unescape(m.group(2) or m.group(3) or m.group(4) or "")
    return out


def _is_image(data: bytes, ctype: str) -> bool:
    # SVG 在这里算"不是可用图片"：Pillow 解不了，也没有转码器，
    # 不如继续找下一个候选（多数站点同时提供 png 的 apple-touch-icon）
    if "svg" in ctype:
        return False
    if ctype.startswith("image/"):
        return True
    return any(data.startswith(magic) for magic in MAGIC)


def candidates(html: str, base: str) -> list[str]:
    """按优先级排序的候选图标地址。"""
    scored: dict[str, int] = {}

    def push(url: str, score: int) -> None:
        if not url:
            return
        if score > scored.get(url, -9999):
            scored[url] = score

    for tag in LINK_RE.findall(html):
        a = _attrs(tag)
        rel = (a.get("rel") or "").lower()
        if "icon" not in rel:
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue
        url = urllib.parse.urljoin(base, href)
        size = 0
        m = re.search(r"(\d+)\s*[xX]\s*(\d+)", a.get("sizes") or "")
        if m:
            size = max(int(m.group(1)), int(m.group(2)))
        score = size
        if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
            score = max(size, 180) + 60  # 通常是方形 logo，最像"应用图标"
        if size and size <= 32:
            score -= 40  # 16/32 的 ico 放大就糊
        if "mask-icon" in rel or href.endswith(".svg"):
            score -= 500  # Pillow 解不了 SVG，排到最后
        push(url, score)

    for tag in META_RE.findall(html):
        a = _attrs(tag)
        key = (a.get("property") or a.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image"):
            content = (a.get("content") or "").strip()
            if content:
                push(urllib.parse.urljoin(base, content), 20)

    root = urllib.parse.urlparse(base)
    if root.scheme and root.netloc:
        push(f"{root.scheme}://{root.netloc}/favicon.ico", -100)

    return [url for url, _ in sorted(scored.items(), key=lambda kv: -kv[1])]


def fetch_icon(raw_url: str) -> tuple[bytes, str]:
    """返回 (图片字节, 来源地址)。失败抛 FetchError。"""
    url = normalize_url(raw_url)
    data, ctype, final = _get(url, MAX_HTML, truncate=True)

    # 用户直接给了图片地址
    if _is_image(data, ctype) and "html" not in ctype:
        return data, final

    looks_html = "html" in ctype or data.lstrip()[:1] == b"<"
    if not looks_html:
        raise FetchError("这个地址返回的不是网页也不是图片")

    html = data.decode("utf-8", "replace")
    if not html.strip():
        raise FetchError("页面是空的")

    tried: list[str] = []
    last_error = ""
    for cand in candidates(html, final):
        tried.append(cand)
        try:
            blob, blob_type, _ = _get(cand, MAX_IMAGE)
        except FetchError as exc:
            last_error = str(exc)
            continue
        if _is_image(blob, blob_type):
            return blob, cand
        last_error = "不是图片"

    if last_error:
        raise FetchError(f"找到 {len(tried)} 个候选图标但都取不到：{last_error}")
    raise FetchError("页面里没有声明图标，也没有 /favicon.ico")
