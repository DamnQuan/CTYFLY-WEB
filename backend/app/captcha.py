"""
流程只有三步：
1. 服务端发 challenge 与难度，难度表示哈希十六进制结果需要的前导 0 位数；
2. 浏览器在 Web Worker 里枚举 nonce，直到 challenge 拼接 nonce 的 sha256 满足难度；
3. 服务端复算一次哈希，校验 challenge 未过期、未被用过、失败次数未超限，
   然后签发一枚短期一次性令牌，业务接口凭这枚令牌放行。

部署约束：
challenge 与已用令牌保存在当前进程的模块级字典里，进程重启即失效，多 worker 部署时
各进程互相验不到对方的 challenge 与令牌。这套实现只能跑单进程。
需要水平扩容时，必须先把这两类状态迁到 Redis 或改用粘性会话，迁移方案见交接文档。
限流与登录锁定同样是进程内状态，受同一约束。
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import threading
import time

from fastapi import HTTPException, Request

from .config import (POW_CAPTCHA_ALLOW_LOCALHOST, POW_CAPTCHA_CHALLENGE_TTL,
                     POW_CAPTCHA_DIFFICULTY, POW_CAPTCHA_ENABLED,
                     POW_CAPTCHA_SECRET, POW_CAPTCHA_TOKEN_TTL)
from .requestinfo import client_ip_from_request, normalize_ip

_LOCK = threading.Lock()
_CHALLENGES: dict[str, dict] = {}
_TOKENS: dict[str, dict] = {}
_LOG = logging.getLogger("ctyfly.pow")
# 失败原因只写服务端日志，返回给前端的永远是同一句话，避免暴露校验机制
_PUBLIC_FAILURE = "请求校验未通过，请稍后重试"
# 内存上限：公开接口任何人都能请求 challenge，不设上限等于给内存放大攻击开门
_MAX_CHALLENGES = 20000
_MAX_TOKENS = 20000
# 单个 challenge 允许的失败提交次数，防止有人拿一个 challenge 反复试探
_MAX_ATTEMPTS = 20


def _now() -> float:
    return time.time()


def is_local_network(ip: str | None) -> bool:
    """回环、私网与链路本地地址视为本地来源"""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not addr.is_global


def captcha_required(ip: str | None) -> bool:
    """该来源是否必须完成工作量证明"""
    if not POW_CAPTCHA_ENABLED:
        return False
    if POW_CAPTCHA_ALLOW_LOCALHOST and is_local_network(ip):
        return False
    return True


def _prune_locked(now: float) -> None:
    for challenge in [k for k, v in _CHALLENGES.items() if v["exp"] <= now]:
        _CHALLENGES.pop(challenge, None)
    for jti in [k for k, v in _TOKENS.items() if v["exp"] <= now]:
        _TOKENS.pop(jti, None)
    if len(_CHALLENGES) > _MAX_CHALLENGES:
        for challenge in list(_CHALLENGES)[: len(_CHALLENGES) - _MAX_CHALLENGES]:
            _CHALLENGES.pop(challenge, None)
    if len(_TOKENS) > _MAX_TOKENS:
        for jti in list(_TOKENS)[: len(_TOKENS) - _MAX_TOKENS]:
            _TOKENS.pop(jti, None)


def issue_challenge(ip: str | None) -> dict:
    """签发一个 challenge；不需要验证的来源返回 required=False"""
    if not captcha_required(ip):
        return {"required": False, "challenge": "", "difficulty": 0, "expiresIn": 0}
    now = _now()
    with _LOCK:
        _prune_locked(now)
        challenge = secrets.token_urlsafe(24)
        _CHALLENGES[challenge] = {
            "difficulty": POW_CAPTCHA_DIFFICULTY,
            "exp": now + POW_CAPTCHA_CHALLENGE_TTL,
            "attempts": 0,
        }
    return {
        "required": True,
        "challenge": challenge,
        "difficulty": POW_CAPTCHA_DIFFICULTY,
        "expiresIn": POW_CAPTCHA_CHALLENGE_TTL,
    }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: str) -> str:
    mac = hmac.new(POW_CAPTCHA_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256)
    return _b64(mac.digest())


def _issue_token(challenge: str, ip: str | None) -> tuple[str, int]:
    """challenge 验证通过后签发一次性令牌，令牌绑定来源 IP 并带过期时间"""
    now = _now()
    jti = secrets.token_hex(16)
    payload = {
        "jti": jti,
        "cid": challenge,
        "exp": int(now + POW_CAPTCHA_TOKEN_TTL),
        "ip": normalize_ip(ip) or (ip or ""),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    token = "v1." + body + "." + _sign(body)
    with _LOCK:
        _prune_locked(now)
        _TOKENS[jti] = {"exp": payload["exp"], "ip": payload["ip"]}
    return token, POW_CAPTCHA_TOKEN_TTL


def verify_solution(challenge: str, nonce: str, ip: str | None) -> tuple[bool, str, str, int]:
    """校验工作量证明答案，成功时作废 challenge 并签发一次性令牌"""
    if not captcha_required(ip):
        return True, "", "", 0
    challenge = (challenge or "").strip()
    nonce = (nonce or "").strip()
    if not challenge or not nonce.isdigit():
        return False, "人机验证参数不完整", "", 0
    now = _now()
    with _LOCK:
        entry = _CHALLENGES.get(challenge)
        if entry is None or entry["exp"] <= now:
            return False, "人机验证已过期，请刷新页面重试", "", 0
        digest = hashlib.sha256(f"{challenge}{nonce}".encode("utf-8")).hexdigest()
        if not digest.startswith("0" * entry["difficulty"]):
            entry["attempts"] += 1
            if entry["attempts"] >= _MAX_ATTEMPTS:
                _CHALLENGES.pop(challenge, None)
                return False, "人机验证失败次数过多，请刷新页面重试", "", 0
            return False, "人机验证未通过", "", 0
        # 成功的 challenge 必须立刻出队，保证同一个 challenge 只能兑换一次令牌
        _CHALLENGES.pop(challenge, None)
    token, expires_in = _issue_token(challenge, ip)
    return True, "", token, expires_in


def verify_token(token: str, ip: str | None) -> tuple[bool, str]:
    """校验一次性令牌；校验通过即消费，重复提交会被拒绝"""
    if not captcha_required(ip):
        return True, ""
    token = (token or "").strip()
    if not token:
        return False, "请完成人机验证"
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        return False, "人机验证令牌无效，请刷新页面重试"
    try:
        expected = _sign(parts[1])
        if not hmac.compare_digest(expected, parts[2]):
            return False, "人机验证令牌无效，请刷新页面重试"
        payload = json.loads(_unb64(parts[1]).decode("utf-8"))
        jti = str(payload["jti"])
        exp = int(payload["exp"])
        token_ip = str(payload.get("ip") or "")
    except Exception:
        return False, "人机验证令牌无效，请刷新页面重试"
    now = _now()
    if exp <= now:
        return False, "人机验证已过期，请刷新页面重试"
    request_ip = normalize_ip(ip) or (ip or "")
    if token_ip and request_ip and token_ip != request_ip:
        return False, "人机验证令牌与当前网络不匹配，请刷新页面重试"
    with _LOCK:
        _prune_locked(now)
        entry = _TOKENS.pop(jti, None)
    if entry is None:
        return False, "人机验证令牌已使用，请刷新页面重试"
    return True, ""


async def require_pow_verification(request: Request) -> None:
    """业务接口依赖：读取 X-PoW-Token 头并静默校验，失败统一返回同一句泛化提示"""
    ip = client_ip_from_request(request)
    if not captcha_required(ip):
        return
    ok, reason = verify_token(request.headers.get("x-pow-token", ""), ip)
    if not ok:
        _LOG.warning("人机校验未通过 ip=%s reason=%s", ip, reason)
        raise HTTPException(400, _PUBLIC_FAILURE)


def challenge_info(ip: str | None) -> dict:
    """给前端配置接口用的公开信息，不含任何密钥"""
    required = captcha_required(ip)
    return {
        "enabled": required,
        "algorithm": "SHA-256",
        "difficulty": POW_CAPTCHA_DIFFICULTY if required else 0,
        "challengeTtl": POW_CAPTCHA_CHALLENGE_TTL,
    }
