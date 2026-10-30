"""请求元信息：客户端 IP、User-Agent，含脚本/爬虫识别、设备指纹、IP 地理位置"""
import ipaddress
import re
import threading
import time

import httpx

from .config import TRUST_PROXY

_GEO_TTL = 24 * 3600
_geo_cache: dict[str, tuple[float, str]] = {}
_geo_lock = threading.Lock()

# ---------- User-Agent 解析 ----------

# 爬虫，按名称优先识别
_CRAWLERS = (
    ("googlebot", "Googlebot"), ("bingbot", "Bingbot"), ("baiduspider", "Baiduspider"),
    ("yandexbot", "YandexBot"), ("bytespider", "Bytespider"), ("petalbot", "PetalBot"),
    ("duckduckbot", "DuckDuckBot"), ("facebookexternalhit", "Facebook 抓取"),
    ("bot", "爬虫 Bot"), ("spider", "爬虫 Spider"), ("crawl", "爬虫 Crawler"),
)

# 脚本 / 命令行 / 自动化工具
_SCRIPTS = (
    (("python-urllib", "python-requests", "python/", "httpx/", "aiohttp/"), "Python 脚本"),
    (("curl/",), "curl"),
    (("wget/",), "wget"),
    (("go-http-client",), "Go 客户端"),
    (("okhttp/", "java/"), "Java 客户端"),
    (("axios/", "node-fetch", "undici", "node.js"), "Node 客户端"),
    (("postmanruntime",), "Postman"),
    (("powershell", "winhttp"), "Windows 脚本"),
    (("httpie/", "libwww-perl", "apache-httpclient", "httpclient/"), "HTTP 客户端库"),
    (("scrapy/",), "Scrapy 爬虫"),
    (("sqlmap", "nmap", "zgrab", "masscan"), "扫描工具"),
    (("headlesschrome",), "无头浏览器"),
    (("phantomjs",), "PhantomJS"),
    (("selenium", "playwright", "puppeteer"), "自动化浏览器"),
)

_BROWSERS = (
    ("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"), ("Safari/", "Safari"),
)
_OS = (
    ("Windows NT", "Windows"), ("Android", "Android"), ("iPhone", "iOS"),
    ("iPad", "iOS"), ("Mac OS X", "macOS"), ("Linux", "Linux"),
)


def _version_after(text: str, token: str) -> str:
    m = re.search(re.escape(token) + r"([\d.]+)", text)
    return m.group(1).split(".")[0] if m else ""


def classify_ua(ua: str) -> tuple[str, bool]:
    """解析 User-Agent，返回 可读标签, 是否脚本/爬虫

    浏览器：如 "Chrome 140 · Windows"
    脚本/爬虫：如 "Python 脚本"、"Googlebot"，第二项为 True
    """
    s = (ua or "").strip()
    if not s:
        return "无 User-Agent", True

    low = s.lower()
    for key, name in _CRAWLERS:
        if key in low:
            return name, True
    for keys, name in _SCRIPTS:
        if any(k in low for k in keys):
            return name, True

    browser = next((n for t, n in _BROWSERS if t in s), "")
    if not browser:
        # 未知客户端 ≠ 爬虫：QQ/微信等 App 内置 WebView 的 UA 不含标准浏览器
        # 标记，如 Safari/，曾把真实 iPhone QQ 用户误判为爬虫，2026-10-05。
        # 已知爬虫/脚本已在上方 _CRAWLERS/_SCRIPTS 拦截，这里只做「未知」标记。
        return "未知客户端", False

    if browser == "Safari":
        # Safari 的版本号在 Version/ 字段里，Safari/ 后面是 WebKit 构建号
        version = _version_after(s, "Version/") or _version_after(s, "Safari/")
    else:
        version_token = next(t for t, n in _BROWSERS if n == browser)
        version = _version_after(s, version_token)
    os_name = next((n for t, n in _OS if t in s), "")
    parts = [p for p in (f"{browser} {version}".strip(), os_name) if p]
    return " · ".join(parts) or browser, False


def browser_header_anomalies(headers: dict, ua: str, fingerprint: str = "") -> list[str]:
    """UA 与请求头/指纹不自洽的疑点，返回原因列表，空列表=正常

    用途：**只记风险事件，不据此封禁**。真实浏览器会带一串固定请求头，
    自动化工具，Playwright/Puppeteer/requests 往往缺其中几项，或版本号对不上。

    刻意做得保守：单个疑点不算，命中 ≥2 项才值得留痕；因为
    - 部分 App 内置 WebView、老浏览器、公司代理会剥掉 sec-ch-ua；
    - 我们自己的验证脚本，curl/无头浏览器也会缺头，不能误封。
    """
    reasons: list[str] = []
    h = {str(k).lower(): (v or "") for k, v in (headers or {}).items()}
    s = ua or ""
    chromium = any(t in s for t in ("Chrome/", "Edg/", "OPR/", "HeadlessChrome"))
    if chromium:
        if not h.get("sec-ch-ua"):
            reasons.append("Chromium UA 无 sec-ch-ua")
        if not h.get("sec-fetch-mode"):
            reasons.append("Chromium UA 无 Sec-Fetch-Mode")
        # 版本自洽：UA 里的 Chrome 主版本应与 sec-ch-ua 声明一致
        m = re.search(r"Chrome/(\d+)", s)
        sec = h.get("sec-ch-ua", "")
        if m and sec:
            declared = re.findall(r'"(\d+)"', sec)
            if declared and m.group(1) not in declared:
                reasons.append(f"UA 声明 Chrome {m.group(1)} 与 sec-ch-ua 不符")
    if not h.get("accept-language"):
        reasons.append("缺少 Accept-Language")
    if not h.get("accept"):
        reasons.append("缺少 Accept")
    if not fingerprint:
        reasons.append("浏览器指纹为空")
    return reasons


def normalize_ip(raw: str) -> str:
    """把各种来源的 IP 字符串规范成可入库形式；无法解析返回 ""。

    需要覆盖的形态，代理头/日志里真实会出现：
      "2001:db8::1" nginx `$remote_addr` 的 IPv6 原样
      "[2001:db8::1]" URL / 部分代理的方括号写法
      "[2001:db8::1]:443" 带端口
      "2001:db8::1%eth0" 带 zone id，链路本地
      "::ffff:203.0.113.10" 双栈 socket 上的 IPv4 映射地址
    统一后：IPv4 映射地址折回 IPv4，其余走 ipaddress 的压缩规范形式 ——
    这样限流/封禁/去重不会把同一个客户端当成两个不同地址。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return ""
        s = s[1:end]
    s = s.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(s)
    except ValueError:
        # 兜底：IPv4:port，只认「三段点分 + 纯数字端口」，避免把 IPv6 误拆
        head, sep, port = s.rpartition(":")
        if sep and port.isdigit() and head.count(".") == 3:
            try:
                return str(ipaddress.IPv4Address(head))
            except ValueError:
                return ""
        return ""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def xff_last_ip(xff: str | None, fallback: str) -> str:
    """从 X-Forwarded-For 取可信客户端 IP：最后一段 + 格式校验，IPv4/IPv6 都支持。

    为什么取最后一段：生产 nginx 配置的是
    `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`，追加模式——
    客户端可以自带一个伪造的 XFF 头，nginx 只会把自己的 remote_addr
    **追加到末尾**，不会清洗已有内容。因此首段，以及中间任意段都是
    攻击者可控的伪造值，只有最后一段才是 nginx 实际看到的地址。
    伪造头直接取首段会导致限流/封禁/审计全部指向假 IP，可被随意栽赃或绕过。

    最后一段仍要做格式校验：内网直连，TRUST_PROXY=true 但流量没经过 nginx
    时该头可能不存在；即便是代理转来的，也防御畸形段。解析失败一律回退
    fallback，通常是 request.client.host。返回值一律经 normalize_ip 规范，
    IPv6，含方括号/端口/映射地址与 IPv4 都能正确入库。
    """
    if TRUST_PROXY and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            normalized = normalize_ip(parts[-1])
            if normalized:
                return normalized
    return normalize_ip(fallback) or fallback


def client_ip_from_request(request) -> str:
    fallback = request.client.host if request.client else "unknown"
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff_last_ip(xff, fallback)
    return normalize_ip(fallback) or fallback


def is_local_request(request) -> bool:
    """请求是否来自本机/内网，回环或私网地址。

    用于开发模式兜底：SMTP 未配置时仅对本机/内网来源返回 devCode，
    公网请求一律不给验证码，防止「SMTP 故障 = 任何人可自助注册/改密」。
    注意不能直接用 request.client.host：生产 nginx 与应用同机时 TCP 对端恒为
    127.0.0.1，会把所有公网请求误判为本地。这里用 client_ip_from_request
    解析出的真实客户端地址，TRUST_PROXY=true 时即 XFF 最后一段。
    """
    host = client_ip_from_request(request)
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def user_agent(request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def clean_fingerprint(value: str) -> str:
    """设备指纹只保留 8-64 位十六进制字符"""
    s = "".join(ch for ch in (value or "") if ch.isalnum())[:64]
    return s if 8 <= len(s) <= 64 else ""


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local)


def lookup_geo(ip: str) -> str:
    """返回 "国家 省 城市 · ISP"；内网/回环地址与查询失败返回 ''"""
    if not _is_public_ip(ip):
        return ""
    now = time.time()
    with _geo_lock:
        hit = _geo_cache.get(ip)
        if hit and now - hit[0] < _GEO_TTL:
            return hit[1]

    geo = ""
    try:
        with httpx.Client(timeout=5, trust_env=True) as client:
            resp = client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,regionName,city,isp", "lang": "zh-CN"},
            )
            data = resp.json()
            if data.get("status") == "success":
                parts = [data.get("country", ""), data.get("regionName", ""), data.get("city", "")]
                geo = " ".join(p for p in parts if p)
                if data.get("isp"):
                    geo = f"{geo} · {data['isp']}" if geo else data["isp"]
    except Exception:
        geo = ""

    with _geo_lock:
        _geo_cache[ip] = (now, geo)
    return geo


def geo_cached_or_async(ip: str) -> str:
    """命中缓存直接返回；未命中则后台异步查询，本次返回空字符串，不阻塞登录"""
    if not _is_public_ip(ip):
        return ""
    now = time.time()
    with _geo_lock:
        hit = _geo_cache.get(ip)
        if hit and now - hit[0] < _GEO_TTL:
            return hit[1]
    threading.Thread(target=lookup_geo, args=(ip,), daemon=True).start()
    return ""
