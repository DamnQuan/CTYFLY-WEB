"""ASGI 中间件：安全响应头、请求体大小限制、全局每 IP 限流、API 访问量统计、按请求访问日志"""
import os
import re
import threading
import time
from collections import deque

from starlette.responses import JSONResponse

from .audit import log_event
from .config import (
    ANOMALY_COOLDOWN,
    ANOMALY_ENABLED,
    ANOMALY_MAX_PATHS,
    ANOMALY_MAX_REQ,
    ANOMALY_WINDOW,
    RATE_LIMIT_ENABLED,
)
from .ratelimit import client_ip_scope, hit

_ID_RE = re.compile(r"/\d+(?=/|$)")

# ---------- 行为异常检测，2026-10-10 新增，见运维手册 §6.8----------
# 只看「窗口内请求数 / 不同接口数」有没有超出人类操作范围 → **只写风险事件，绝不自动封禁**。
# 为什么不封：正常用户一次页面加载也会连打十几个接口，自动化判定的假阳性率不允许直接封 IP；
# 留痕 + 后台可见 + 告警邮件才是这一层的正确产出，真要封由人在管理后台点。
_WATCH_MAX_KEYS = 5000
_watch: dict[str, deque] = {}
_watch_last_alert: dict[str, float] = {}
_watch_lock = threading.Lock()


def _watch_anomaly(scope, user_id) -> None:
    """滑动窗口统计；命中阈值 → 记一条 risk 事件，同一主体有冷却，避免刷日志"""
    if not ANOMALY_ENABLED:
        return
    path = scope.get("path", "")
    if not path.startswith("/api/"):
        return
    # 忽略轮询类高频只读接口，它们天然密集，不算异常
    if path.startswith(("/api/status", "/api/notifications", "/api/dashboard")):
        return
    key = f"u:{user_id}" if user_id else f"ip:{client_ip_scope(scope)}"
    now = time.time()
    tripped = None
    with _watch_lock:
        if len(_watch) >= _WATCH_MAX_KEYS:
            # 内存自保：清掉已过窗口的 key
            for k in [k for k, dq in _watch.items() if not dq or now - dq[-1][0] > ANOMALY_WINDOW]:
                _watch.pop(k, None)
            if len(_watch) >= _WATCH_MAX_KEYS:
                _watch.clear()
        dq = _watch.setdefault(key, deque())
        dq.append((now, path))
        while dq and now - dq[0][0] > ANOMALY_WINDOW:
            dq.popleft()
        reqs = len(dq)
        paths = len({p for _, p in dq})
        if reqs > ANOMALY_MAX_REQ or paths > ANOMALY_MAX_PATHS:
            if now - _watch_last_alert.get(key, 0.0) >= ANOMALY_COOLDOWN:
                _watch_last_alert[key] = now
                tripped = (reqs, paths)
    if not tripped:
        return
    reqs, paths = tripped
    log_event(
        "risk", "疑似自动化行为",
        actor={"id": user_id} if user_id else None,
        target_type="ip" if not user_id else "user",
        target_id=str(user_id) if user_id else key[3:],
        detail=(f"{ANOMALY_WINDOW}s 内 {reqs} 次请求 / {paths} 个不同接口"
                f"，阈值 {ANOMALY_MAX_REQ} 次 或 {ANOMALY_MAX_PATHS} 个 · 仅留痕未封禁"),
        ip=key[3:] if key.startswith("ip:") else "",
    )

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


class SecurityHeadersMiddleware:
    """为所有响应附加安全头，最外层，429/413 也能带上"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {k.lower() for k, _ in headers}
                for k, v in SECURITY_HEADERS:
                    if k not in existing:
                        headers.append((k, v))
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """限制请求体大小，默认 128KB，普通 JSON 接口远达不到

    上传类接口需要放宽，通过 path_limits 按前缀指定更大的上限：
        path_limits = {"/api/events/": 5.5MB} # 只放宽
        path_limits = {"/api/events/": 5.5MB, "图片大小不能超过 5 MB" } # 放宽 + 自定义文案
    匹配时取最长前缀，未命中则用默认值。

    错误码统一，2026-10-18：超限一律返回 413 + `{"error": "..."}`；
    有自定义文案就用它，如「图片大小不能超过 5 MB，请压缩后再上传」，
    否则按实际上限生成「请求体过大：本接口单次上限 X MB」。
    这样前端 `api.js` 的 `data.error` 能直接把原因展示出来，不用再猜。

    防 chunked 绕过：客户端用 Transfer-Encoding: chunked 时可以不报
    Content-Length，或报一个假的，所以除了读 body 前先查一次声明的
    Content-Length，还把 receive 包装成逐块计数器——累计超限立即代发 413
    并向应用返回 http.disconnect，不依赖客户端自报的长度。
    """

    def __init__(self, app, max_bytes: int = 128 * 1024, path_limits: dict | None = None):
        self.app = app
        self.max_bytes = max_bytes
        # 统一规整成 {前缀: 上限字节, 自定义文案 }；兼容只给数字的旧写法
        self.path_limits: dict[str, tuple[int, str]] = {}
        for prefix, rule in (path_limits or {}).items():
            if isinstance(rule, (tuple, list)) and len(rule) == 2:
                self.path_limits[prefix] = (int(rule[0]), str(rule[1] or ""))
            else:
                self.path_limits[prefix] = (int(rule), "")

    @staticmethod
    def _fmt_size(n: int) -> str:
        mb = n / (1024 * 1024)
        if mb >= 1:
            return f"{mb:.0f} MB" if abs(mb - round(mb)) < 0.05 else f"{mb:.1f} MB"
        return f"{max(1, round(n / 1024))} KB"

    def _rule_for(self, path: str) -> tuple[int, str]:
        """取「最长匹配前缀」的规则；未命中用默认上限 + 空文案"""
        best_len, rule = -1, (self.max_bytes, "")
        for prefix, candidate in self.path_limits.items():
            if path.startswith(prefix) and len(prefix) > best_len:
                best_len, rule = len(prefix), candidate
        return rule

    def _limit_for(self, path: str) -> int:
        """取「最长匹配前缀」的上限，未命中用默认值

        修复，2026-10-11，由 ruff 的 F841 顶出来：原实现是
            best_prefix, best = "", -1
            if path.startswith prefix and len prefix > best:
                best_prefix, best = prefix, limit
            return best if best > 0 else self.max_bytes
        `best` 存的是**上限值**，却拿 `len prefix `，长度去比较 —— 两套量纲混用，
        结果是「第一个匹配到的前缀」而不是「最长前缀」，与文档字符串承诺不符。
        当前两个前缀互不重叠，所以还没造成实际影响；但一旦出现
        `/api/` + `/api/uploads/` 这类嵌套配置，就会按短前缀的宽松上限放行。
        """
        return self._rule_for(path)[0]

    def _too_large(self, limit: int, message: str) -> JSONResponse:
        """统一的 413 响应体：优先用接口自定义文案，否则按上限生成"""
        text = message or f"请求体过大：本接口单次请求上限 {self._fmt_size(limit)}"
        return JSONResponse({"error": text}, status_code=413)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # 只包一层 HTTP 生命周期，websocket / lifespan 原样透传
            await self.app(scope, receive, send)
            return

        limit, message = self._rule_for(scope.get("path", ""))
        content_length = next(
            (v for k, v in scope.get("headers", []) if k == b"content-length"), None
        )
        if content_length is not None:
            try:
                declared = int(content_length)
            except (TypeError, ValueError):
                declared = None  # 畸形 Content-Length 不至于 500，交给逐块计数兜底
            if declared is not None and declared > limit:
                await self._too_large(limit, message)(scope, receive, send)
                return

        state = {"total": 0, "over": False}

        async def counting_receive():
            message = await receive()
            if state["over"]:
                # 已超限并代发 413：之后一律伪装成客户端断开，应用不会再读到 body
                return {"type": "http.disconnect"}
            if message["type"] == "http.request":
                body = message.get("body") or b""
                state["total"] += len(body)
                if state["total"] > limit:
                    state["over"] = True
                    await self._too_large(limit, message)(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def send_wrapper(message):
            if state["over"]:
                # 413 已由本中间件发出；吞掉应用后续的响应消息，
                # 避免对同一请求发送两次 response.start 让 ASGI 服务器报错
                return
            await send(message)

        await self.app(scope, counting_receive, send_wrapper)


class GlobalRateLimitMiddleware:
    """全局兜底限流：单 IP 300 次/分钟，正常用户远达不到"""

    LIMIT = 300
    WINDOW = 60.0

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and RATE_LIMIT_ENABLED:
            path = scope.get("path", "")
            if path.startswith("/api/"):
                ip = client_ip_scope(scope)
                ok = hit(f"global:{ip}", self.LIMIT, self.WINDOW)
                if not ok:
                    # 限流触发记入审计，同 IP 每分钟只记一次，避免刷爆日志
                    log_event(
                        "risk", "触发全局限流", ip=ip, detail=f"{scope.get('method')} {path}",
                        target_type="api", target_id=path, dedupe_key=f"429:{ip}",
                    )
                    resp = JSONResponse(
                        {"error": "请求过于频繁，请稍后再试"},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
                    await resp(scope, receive, send)
                    return
        await self.app(scope, receive, send)


class AccessLogMiddleware:
    """按请求访问日志，/api：溯源能力的关键一层。

    APOC 平台 2026-08 事件的溯源即依赖「HTTP 全量日志 + 会话/身份关联」：
    本中间件为每个 /api 请求记录 时间/IP/方法/路径/查询串/状态/耗时/UA/Referer/user_id，
    使任意 IP 的行为可回放、任意异常可归因到账号。

    隐私：仅记录 /api 请求、保留 30 天，与隐私政策承诺一致、由 logretention 清理。
    性能：行先入内存缓冲，每 3 秒或攒满 200 行批量落库，当前量级 ~400 请求/天，开销可忽略。
    """

    FLUSH_INTERVAL = 3.0
    FLUSH_ROWS = 200

    def __init__(self, app):
        self.app = app
        self._buffer: list[tuple] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()

    @staticmethod
    def _dec(raw: bytes | None, limit: int) -> str:
        if not raw:
            return ""
        return raw.decode("utf-8", "replace").replace("\n", " ").replace("\r", " ")[:limit]

    def _record(self, scope, status: int, duration_ms: int, user_id) -> None:
        try:
            _watch_anomaly(scope, user_id)
        except Exception:
            pass  # 异常检测失败绝不影响访问日志
        try:
            headers = {k.decode().lower(): v.decode("utf-8", "replace") for k, v in scope.get("headers", [])}
            row = (
                user_id,
                os.getpid(),
                client_ip_scope(scope)[:64],
                scope.get("method", "")[:8],
                scope.get("path", "")[:160],
                self._dec(scope.get("query_string", b""), 300),
                status,
                duration_ms,
                headers.get("user-agent", "")[:200],
                headers.get("referer", "")[:200],
            )
            flush_now = False
            with self._lock:
                self._buffer.append(row)
                if len(self._buffer) >= self.FLUSH_ROWS or time.time() - self._last_flush > self.FLUSH_INTERVAL:
                    flush_now = True
                    pending = list(self._buffer)
                    self._buffer.clear()
                    self._last_flush = time.time()
            if flush_now:
                self._flush(pending)
        except Exception:
            pass  # 日志失败绝不影响业务

    def _flush(self, pending: list) -> None:
        try:
            from .database import get_conn

            with get_conn() as conn:
                conn.executemany(
                    "INSERT INTO api_access_log"
                    " (user_id, pid, ip, method, path, query, status, duration_ms, ua, referer)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    pending,
                )
        except Exception:
            pass  # 日志失败不影响业务

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        status_holder = {"code": 0}
        t0 = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            try:
                self._record(
                    scope, status_holder["code"] or 500,
                    int((time.perf_counter() - t0) * 1000),
                    state.get("user_id"),
                )
            except Exception:
                pass  # 任何日志异常都不外泄


class ApiMetricsMiddleware:
    """汇总 /api 访问量，按 天+方法+路径+状态码 聚合，每 5 秒批量落库"""

    FLUSH_INTERVAL = 5.0

    def __init__(self, app):
        self.app = app
        self._buffer: dict[tuple, int] = {}
        self._lock = threading.Lock()
        self._last_flush = time.time()

    def _record(self, method: str, path: str, status: int) -> None:
        normalized = _ID_RE.sub("/{id}", path)[:120]
        # 用本地日界：admin.py 的 /logs/network 统计查询按 date 'now','localtime'
        # 对齐口径，服务器的本地时区，若这里用 UTC 日记录，两侧按天聚合会错位
        day = time.strftime("%Y-%m-%d")
        key = (day, method, normalized, status)
        flush_now = False
        with self._lock:
            self._buffer[key] = self._buffer.get(key, 0) + 1
            if time.time() - self._last_flush > self.FLUSH_INTERVAL:
                self._last_flush = time.time()
                flush_now = True
                pending = list(self._buffer.items())
                self._buffer.clear()
        if flush_now:
            self._flush(pending)

    def _flush(self, pending: list) -> None:
        try:
            from .database import get_conn

            with get_conn() as conn:
                for (day, method, path, status), count in pending:
                    conn.execute(
                        "INSERT INTO api_metrics (day, method, path, status, count, last_at)"
                        " VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))"
                        " ON CONFLICT(day, method, path, status) DO UPDATE SET"
                        " count = count + excluded.count, last_at = excluded.last_at",
                        (day, method, path, status, count),
                    )
        except Exception:
            pass  # 统计失败不影响业务

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            code = status_holder["code"] or 500
            self._record(scope.get("method", "GET"), scope.get("path", ""), code)
