"""轻量级内存限流：滑动窗口 + 线程安全。
阈值设计宽松，只拦截机器滥用，不影响正常用户。
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import RATE_LIMIT_ENABLED, TRUST_PROXY
from .requestinfo import normalize_ip, xff_last_ip

_lock = threading.Lock()
_buckets: dict[str, deque] = defaultdict(deque)
_last_sweep = 0.0


def hit(key: str, limit: int, window: float) -> bool:
    """记录一次访问并判断是否放行"""
    global _last_sweep
    now = time.time()
    with _lock:
        q = _buckets[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        # 周期性清理冷数据，防止内存无限增长
        if now - _last_sweep > 300:
            _last_sweep = now
            for k in list(_buckets.keys()):
                dq = _buckets[k]
                while dq and now - dq[0] > 3600:
                    dq.popleft()
                if not dq:
                    del _buckets[k]
        return True


def client_ip(request: Request) -> str:
    """获取客户端 IP，IPv4/IPv6 均已规范化；仅当显式配置 TRUST_PROXY=true 时信任 X-Forwarded-For。

    XFF 统一取最后一段，nginx 追加的真实地址+ 格式校验，
    逻辑与 requestinfo.xff_last_ip 保持一致，防止伪造首段绕过限流。
    """
    fallback = request.client.host if request.client else "unknown"
    if TRUST_PROXY:
        return xff_last_ip(request.headers.get("x-forwarded-for"), fallback)
    return normalize_ip(fallback) or fallback


def client_ip_scope(scope) -> str:
    fallback_host = scope.get("client")
    fallback = fallback_host[0] if fallback_host else "unknown"
    if TRUST_PROXY:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        return xff_last_ip(headers.get("x-forwarded-for"), fallback)
    return normalize_ip(fallback) or fallback


def enforce(request: Request, bucket: str, limit: int, window: float) -> None:
    """敏感端点限流；超限返回 429"""
    if not RATE_LIMIT_ENABLED:
        return
    if not hit(f"{bucket}:{client_ip(request)}", limit, window):
        raise HTTPException(429, "操作过于频繁，请稍后再试")
