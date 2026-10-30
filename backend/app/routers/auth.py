"""认证 API：验证码、CID、注册、登录、重置密码、个人资料"""
import ipaddress
import os
import random
import re
import sqlite3
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..captcha import require_pow_verification
from ..config import IPV6_PROBE_ENABLED, UA_ANOMALY_ENABLED, smtp_enabled
from ..database import get_conn
from ..deps import public_user, require_auth, with_capabilities
from ..mailer import CODE_TTL_MS, consume_verification_code, notify_user, send_verification_code
from ..ratelimit import enforce
from ..requestinfo import (browser_header_anomalies, classify_ua, clean_fingerprint,
                           client_ip_from_request, geo_cached_or_async,
                           is_local_request, normalize_ip, user_agent)
from ..security import hash_password, needs_rehash, sign_token, verify_password
from ..text import clean

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
USERNAME_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_]{2,16}$")
QQ_RE = re.compile(r"^[1-9][0-9]{4,10}$")
CID_RE = re.compile(r"^\d{4}$")

# 登录失败限制，进程内存级
# key 格式为 f"{account}:{ip}"：若只按账号锁定，攻击者可以拿任意受害者账号名
# 疯狂输错密码，把全站账号，尤其是管理员锁死 10 分钟——等于「锁号 DoS」。
# 叠加 IP 维度后，只有「同一 IP 对同一账号」连续失败才会触发锁定，
# 正常用户的跨 IP 登录不受他人恶意行为牵连。
_login_lock = threading.Lock()
_login_attempts: dict[str, dict] = {}
_LOGIN_ATTEMPTS_MAX_KEYS = 10000  # 防 key 无界增长，撞库字典攻击会造出海量 key

MAX_RANDOM_PER_SID = 15


class SendCodeBody(BaseModel):
    email: str = Field("", max_length=254)
    purpose: str = Field("", max_length=16)


class RegisterBody(BaseModel):
    cid: str = Field("", max_length=8)
    username: str = Field("", max_length=64)
    email: str = Field("", max_length=254)
    qq: str | None = Field("", max_length=16)
    code: str = Field("", max_length=8)
    password: str = Field("", max_length=128)
    confirmPassword: str | None = Field(None, max_length=128)
    fingerprint: str = Field("", max_length=64)


class LoginBody(BaseModel):
    account: str = Field("", max_length=64)
    password: str = Field("", max_length=128)
    fingerprint: str = Field("", max_length=64)


class ResetBody(BaseModel):
    email: str = Field("", max_length=254)
    code: str = Field("", max_length=8)
    password: str = Field("", max_length=128)
    confirmPassword: str | None = Field(None, max_length=128)


class ProfileBody(BaseModel):
    username: str | None = Field(None, max_length=64)
    qq: str | None = Field(None, max_length=16)


class ChangePasswordBody(BaseModel):
    oldPassword: str = Field("", max_length=128)
    password: str = Field("", max_length=128)
    confirmPassword: str | None = Field(None, max_length=128)


def _bump_token_ver(conn, user_id: int) -> None:
    """令牌版本 +1：该用户所有已签发 JWT 立即失效"""
    conn.execute("UPDATE users SET token_ver = token_ver + 1 WHERE id = ?", (user_id,))


def _validate_password(password: str, confirm: str | None) -> str:
    if not 8 <= len(password) <= 64:
        raise HTTPException(400, "密码长度需 8-64 位")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(400, "密码需同时包含字母和数字")
    if confirm is not None and confirm != password:
        raise HTTPException(400, "两次输入的密码不一致")
    return password


def _is_locked(key: str) -> bool:
    rec = _login_attempts.get(key)
    return bool(rec and rec["until"] > time.time())


def _record_fail(key: str) -> None:
    with _login_lock:
        # 字典上限：key 数超限时先清一遍已过期的锁定项，TTL 清理，
        # 仍超限才整体清空——宁可让攻击者的计数归零，也不能让字典吃光内存
        if len(_login_attempts) >= _LOGIN_ATTEMPTS_MAX_KEYS:
            now = time.time()
            for k in [k for k, rec in _login_attempts.items() if rec["until"] <= now]:
                _login_attempts.pop(k, None)
            if len(_login_attempts) >= _LOGIN_ATTEMPTS_MAX_KEYS:
                _login_attempts.clear()
        rec = _login_attempts.setdefault(key, {"count": 0, "until": 0})
        rec["count"] += 1
        if rec["count"] >= 5:
            rec["until"] = time.time() + 10 * 60
            rec["count"] = 0


def _clear_fail(key: str) -> None:
    _login_attempts.pop(key, None)


def _clear_account_fails(account: str) -> None:
    """成功登录后清除该账号相关的全部失败记录，所有 IP 维度的 key。

    保持原有清理语义：计数归零，不会因历史失败影响后续正常登录。
    """
    prefix = f"{account}:"
    with _login_lock:
        for k in [k for k in _login_attempts if k.startswith(prefix)]:
            _login_attempts.pop(k, None)


@router.post("/send-code")
def send_code(body: SendCodeBody, request: Request,
              _pow: None = Depends(require_pow_verification)):
    enforce(request, "sendcode", 10, 3600)  # 每 IP 每小时 10 封，正常用户足够
    # 人机验证由 require_pow_verification 依赖先完成，这里只做格式校验
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "邮箱格式不正确")
    if body.purpose not in ("register", "reset"):
        raise HTTPException(400, "参数错误")

    # 防邮箱枚举：不再按「该邮箱已被注册 / 未绑定账号」区分响应。
    # 注册与找回分支都在内部正常执行，验证码照发、后续校验照做，
    # 对外统一返回同一句话，攻击者无法凭响应差异探测某个邮箱是否注册过。
    if not smtp_enabled() and not is_local_request(request):
        # SMTP 未配置 + 公网来源：绝不能把验证码直接回给请求者
        #那等于把「注册任意邮箱 / 重置任意密码」的能力公开，
        # 直接拒绝比静默吞掉更安全——用户能明确知道服务不可用。
        raise HTTPException(503, "邮件服务未配置，请联系管理员")

    # 注册/找回分支都不再按邮箱是否存在区分行为：验证码照发，后续校验照做
    try:
        result = send_verification_code(email, body.purpose, allow_dev=is_local_request(request))
    except Exception:
        raise HTTPException(500, "邮件发送失败，请稍后重试")
    if not result.get("ok"):
        raise HTTPException(429, result.get("error", "发送失败"))
    return {"ok": True, "message": "若该邮箱有效，验证码已发送",
            "expiresAt": result.get("expiresAt")}


@router.get("/cid/check")
def cid_check(cid: str = ""):
    if not CID_RE.match(cid):
        return {"valid": False, "available": False, "message": "CID 必须是 4 位数字"}
    with get_conn() as conn:
        available = conn.execute("SELECT 1 FROM users WHERE cid = ?", (cid,)).fetchone() is None
    return {"valid": True, "available": available,
            "message": "该 CID 可用" if available else "该 CID 已被占用"}


@router.get("/cid/random")
def cid_random(request: Request, sid: str = ""):
    enforce(request, "cidrandom", 40, 3600)
    sid = sid[:64]
    if not sid:
        raise HTTPException(400, "缺少会话标识")

    with get_conn() as conn:
        log = conn.execute("SELECT count FROM cid_random_log WHERE sid = ?", (sid,)).fetchone()
        count = log["count"] if log else 0
        if count >= MAX_RANDOM_PER_SID:
            raise HTTPException(429, f"本会话随机 CID 次数已用完，{MAX_RANDOM_PER_SID} 次，请手动输入")

        used = {r["cid"] for r in conn.execute("SELECT cid FROM users").fetchall()}
        cid = None
        for _ in range(200):
            candidate = str(random.randint(1000, 9999))
            if candidate not in used:
                cid = candidate
                break
        if not cid:
            raise HTTPException(500, "CID 号段已耗尽")

        if log:
            conn.execute(
                'UPDATE cid_random_log SET count = count + 1, updated_at = datetime("now","localtime") WHERE sid = ?',
                (sid,),
            )
        else:
            conn.execute("INSERT INTO cid_random_log (sid, count) VALUES (?, 1)", (sid,))

    return {"cid": cid, "remaining": MAX_RANDOM_PER_SID - 1 - count}


def _ban_ip(conn, ip: str, reason: str, *, days: int | None = None,
            source: str = "auto", note: str = "") -> None:
    """脚本/爬虫自动封禁：写 IP 黑名单，注册/登录入口每次校验

    days=None 时取配置的自动封禁天数，默认 90，0/负数为永久；
    管理后台手动封禁传自己的天数，None→由调用方显式指定，permanent 用 0。
    带到期时间是为了动态 IP 被回收后再分配给真实用户时不会永久误伤。
    """
    if days is None:
        from ..config import BAN_AUTO_DAYS
        days = BAN_AUTO_DAYS
    if days and days > 0:
        expires_sql = f"datetime('now','localtime','+{int(days)} days')"
    else:
        expires_sql = "NULL"
    conn.execute(
        "INSERT INTO banned_ips (ip, reason, created_at, expires_at, source, note)"
        f" VALUES (?, ?, datetime('now','localtime'), {expires_sql}, ?, ?)"
        " ON CONFLICT(ip) DO UPDATE SET reason = excluded.reason,"
        " expires_at = excluded.expires_at, source = excluded.source, note = excluded.note",
        (ip, reason, source, note),
    )


def _ban_account(conn, user_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE users SET status = 'banned', token_ver = token_ver + 1 WHERE id = ?",
        (user_id,),
    )


def _ip_banned(conn, ip: str) -> bool:
    """白名单优先；已封禁但已到期视为未封，顺手清理过期行，避免表无限增长"""
    if conn.execute("SELECT 1 FROM ip_whitelist WHERE ip = ?", (ip,)).fetchone():
        return False
    row = conn.execute("SELECT expires_at FROM banned_ips WHERE ip = ?", (ip,)).fetchone()
    if not row:
        return False
    exp = row["expires_at"]
    if exp:
        now = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        if exp <= now:
            conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
            return False
    return True


@router.post("/register")
def register(body: RegisterBody, request: Request,
             _pow: None = Depends(require_pow_verification)):
    # 黑名单排最前，与登录入口一致：被封 IP 应当明确得到「已封禁」而不是限流 429
    reg_ip = client_ip_from_request(request)
    reg_ua = user_agent(request)
    _, reg_bot = classify_ua(reg_ua)
    with get_conn() as conn:
        ip_banned = _ip_banned(conn, reg_ip)
    if ip_banned:
        log_event("risk", "已封禁 IP 尝试注册", actor=None, target_type="ip",
                  target_id=reg_ip, ip=reg_ip, ua=reg_ua, dedupe_key=f"bannedreg:{reg_ip}")
        raise HTTPException(403, "该 IP 已被封禁")
    enforce(request, "register", 10, 3600)  # 每 IP 每小时 10 次注册尝试
    # 客户端特征自洽性：UA 不像脚本、但请求头/指纹不像浏览器 → 留痕，不封禁，见 §6.8
    if UA_ANOMALY_ENABLED and not reg_bot:
        reg_reasons = browser_header_anomalies(dict(request.headers), reg_ua, clean_fingerprint(body.fingerprint))
        if len(reg_reasons) >= 2:
            log_event("risk", "疑似自动化客户端，注册", actor=None, target_type="ip",
                      target_id=reg_ip, detail="；".join(reg_reasons), ip=reg_ip, ua=reg_ua,
                      dedupe_key=f"uaano-reg:{reg_ip}")
    if reg_bot:
        with get_conn() as conn:
            _ban_ip(conn, reg_ip, "脚本/爬虫注册，UA 识别")
        log_event("risk", "脚本注册自动封禁 IP", actor=None, target_type="ip",
                  target_id=reg_ip, detail=f"UA: {reg_ua[:80]}", ip=reg_ip, ua=reg_ua)
        raise HTTPException(403, "检测到脚本/爬虫行为，该 IP 已被封禁")
    cid = body.cid.strip()
    username = clean(body.username, 64)
    # 邮箱统一小写：与 send-code 落库、reset 流程保持同一形式，users.email 列本身 NOCASE，
    # 但验证码表比对、审计日志、展示都要口径一致
    email = body.email.strip().lower()
    qq = clean(body.qq or "", 16)

    if not CID_RE.match(cid):
        raise HTTPException(400, "CID 必须是 4 位数字")
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "用户名需 2-16 位，支持中文、字母、数字、下划线")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "邮箱格式不正确")
    if qq and not QQ_RE.match(qq):
        raise HTTPException(400, "QQ 号格式不正确")

    password = _validate_password(body.password, body.confirmPassword)

    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE cid = ?", (cid,)).fetchone():
            raise HTTPException(400, "该 CID 已被占用")
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise HTTPException(400, "用户名已被占用")

    check = consume_verification_code(email, "register", body.code)
    if not check["ok"]:
        raise HTTPException(400, check["error"])

    avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100" if qq else ""
    password_hash = hash_password(password)
    ip = client_ip_from_request(request)
    geo = geo_cached_or_async(ip)
    fp = clean_fingerprint(body.fingerprint)
    ua = user_agent(request)
    ua_label, ua_bot = classify_ua(ua)

    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO users (cid, username, email, password_hash, qq, avatar_url, rating,"
                " reg_ip, reg_geo, reg_fingerprint, reg_ua) VALUES (?, ?, ?, ?, ?, ?, '飞行员', ?, ?, ?, ?)",
                (cid, username, email, password_hash, qq, avatar_url, ip, geo, fp, ua),
            )
        except sqlite3.IntegrityError:
            # 并发/竞态兜底：上方 SELECT 检查与 INSERT 之间别人可能抢先注册，
            # 唯一索引冲突不能变成 500
            raise HTTPException(400, "用户名/CID/邮箱已被占用")
        row = conn.execute("SELECT * FROM users WHERE cid = ?", (cid,)).fetchone()
        conn.execute(
            "INSERT INTO register_logs (user_id, cid, username, email, ip, geo, fingerprint, ua, ua_label, ua_bot)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], cid, username, email, ip, geo, fp, ua, ua_label, 1 if ua_bot else 0),
        )

    log_event("auth", "用户注册", actor={"id": row["id"], "username": username, "role": row["role"]},
              target_type="user", target_id=row["id"], detail=f"CID {cid} · {email}",
              ip=ip, ua=ua)
    return {"ok": True, "token": sign_token(row), "user": with_capabilities(public_user(row))}


@router.post("/login")
def login(body: LoginBody, request: Request,
          _pow: None = Depends(require_pow_verification)):
    # 依赖顺序固定：工作量证明依赖先执行，然后进入黑名单 → 限流 → 参数 → 凭据。
    # 黑名单排在限流前：被封 IP 应当明确知道是「已封禁」，而不是先撞上限流 429
    #2026-10-10 验证时发现顺序颠倒会让提示指向错误原因。
    _login_ip = client_ip_from_request(request)
    with get_conn() as conn:
        if _ip_banned(conn, _login_ip):
            log_event("risk", "已封禁 IP 尝试登录", actor=None, target_type="ip",
                      target_id=_login_ip, ip=_login_ip, ua=user_agent(request),
                      dedupe_key=f"bannedlogin:{_login_ip}")
            raise HTTPException(403, "该 IP 已被封禁")
    enforce(request, "login", 30, 600)  # 每 IP 每 10 分钟 30 次，防跨账号撞库
    if not body.account or not body.password:
        raise HTTPException(400, "请填写账号与密码")

    account = body.account.strip().lower()
    ip = client_ip_from_request(request)
    # 锁定 key 叠加 IP：只锁「该 IP 对该账号」的失败组合，防止拿别人账号名锁号
    key = f"{account}:{ip}"
    geo = geo_cached_or_async(ip)
    fp = clean_fingerprint(body.fingerprint)
    ua = user_agent(request)
    ua_label, ua_bot = classify_ua(ua)

    def record_login(row, success: bool, reason: str = ""):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO login_logs (user_id, cid, username, ip, geo, fingerprint, ua,"
                " ua_label, ua_bot, success, reason, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"] if row else None, row["cid"] if row else "",
                 row["username"] if row else body.account[:32],
                 ip, geo, fp, ua, ua_label, 1 if ua_bot else 0, 1 if success else 0, reason[:100],
                 os.getpid()),
            )
            if success and row:
                conn.execute(
                    "UPDATE users SET last_login_ip = ?, last_login_geo = ?,"
                    " last_login_fingerprint = ?, last_login_at = datetime('now','localtime') WHERE id = ?",
                    (ip, geo, fp, row["id"]),
                )

    if _is_locked(key):
        record_login(None, False, "登录失败次数过多，账号锁定")
        raise HTTPException(429, "失败次数过多，请 10 分钟后再试")

    with get_conn() as conn:
        # IP 黑名单：脚本/爬虫自动封禁后，该 IP 的登录直接拒绝
        if _ip_banned(conn, ip):
            record_login(None, False, "IP 已被封禁")
            raise HTTPException(403, "该 IP 已被封禁")
        row = conn.execute(
            "SELECT * FROM users WHERE cid = ? OR username = ?", (body.account, body.account)
        ).fetchone()

    # 客户端特征自洽性：UA 不像脚本、但请求头/指纹不像浏览器 → 留痕，不封禁，见 §6.8
    if UA_ANOMALY_ENABLED and not ua_bot:
        reasons = browser_header_anomalies(dict(request.headers), ua, fp)
        if len(reasons) >= 2:
            log_event("risk", "疑似自动化客户端，登录",
                      actor={"id": row["id"], "username": row["username"]} if row else None,
                      target_type="user", target_id=row["id"] if row else "",
                      detail="；".join(reasons), ip=ip, ua=ua,
                      dedupe_key=f"uaano-login:{ip}:{account}")

    if not row or not verify_password(body.password, row["password_hash"]):
        _record_fail(key)
        record_login(row, False, "账号或密码错误")
        # 脚本探测登录，UA 识别：不等 5 次计数，IP 直接封禁
        if ua_bot:
            with get_conn() as conn:
                _ban_ip(conn, ip, "脚本/爬虫登录探测，UA 识别")
            log_event("risk", "脚本登录探测自动封禁 IP", actor=None, target_type="ip",
                      target_id=ip, detail=f"账号 {body.account[:32]} · UA: {ua[:60]}",
                      ip=ip, ua=ua, dedupe_key=f"botlogin:{key}")
            raise HTTPException(403, "检测到脚本行为，该 IP 已被封禁")
        log_event("auth", "登录失败", actor={"id": row["id"], "username": row["username"], "role": row["role"]} if row else None,
                  target_type="user", target_id=row["id"] if row else "",
                  detail=f"账号 {body.account[:32]} · 密码错误", ip=ip, ua=ua,
                  dedupe_key=f"loginfail:{key}")
        raise HTTPException(401, "账号或密码错误")
    # 凭据正确但 UA 是脚本 → 封 IP + 封账号，该账号已被脚本控制，属应急封禁
    if ua_bot:
        with get_conn() as conn:
            _ban_ip(conn, ip, "脚本/爬虫登录且凭据正确，UA 识别")
            _ban_account(conn, row["id"], "脚本登录自动封禁")
        log_event("risk", "脚本登录自动封禁", actor={"id": row["id"], "username": row["username"]},
                  target_type="user", target_id=row["id"],
                  detail="凭据正确但 UA 为脚本 · IP 已同时封禁", ip=ip, ua=ua)
        notify_user(row["id"], "你的账号已被封禁",
                    "检测到你的账号通过脚本/爬虫登录，账号与来源 IP 已被自动封禁。\n"
                    "如非本人操作，说明密码已泄露，请通过邮箱联系管理员申诉。")
        raise HTTPException(403, "检测到脚本行为，相关账号与 IP 已被封禁")
    if row["status"] == "banned":
        record_login(row, False, "账号已被封禁")
        raise HTTPException(403, "账号已被封禁，请联系管理员")
    if row["status"] == "deleted":
        record_login(row, False, "账号已注销")
        raise HTTPException(403, "账号已注销")

    _clear_fail(key)
    _clear_account_fails(account)  # 成功登录：清除该账号在所有 IP 下的失败计数

    # 透明升级：旧成本因子的哈希在成功登录后重哈希到当前强度，用户无感知
    if needs_rehash(row["password_hash"]):
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(body.password), row["id"]),
                )
        except Exception:
            pass  # 升级失败不影响本次登录，下次登录会再次尝试

    record_login(row, True)
    log_event("auth", "登录成功",
              actor={"id": row["id"], "username": row["username"], "role": row["role"]},
              target_type="user", target_id=row["id"], detail=f"IP {ip}", ip=ip, ua=ua)
    return {"ok": True, "token": sign_token(row), "user": with_capabilities(public_user(row))}


@router.post("/reset-password")
def reset_password(body: ResetBody, request: Request,
                   _pow: None = Depends(require_pow_verification)):
    enforce(request, "reset", 10, 3600)
    # 邮箱统一小写：与 send-code 落库形式一致，验证码表按 email 比对必须同口径
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "邮箱格式不正确")

    password = _validate_password(body.password, body.confirmPassword)

    check = consume_verification_code(email, "reset", body.code)
    if not check["ok"]:
        raise HTTPException(400, check["error"])

    with get_conn() as conn:
        result = conn.execute(
            "UPDATE users SET password_hash = ?, token_ver = token_ver + 1 WHERE email = ?",
            (hash_password(password), email),
        )
        if result.rowcount == 0:
            raise HTTPException(400, "该邮箱未绑定任何账号")
        row = conn.execute("SELECT id, username, role FROM users WHERE email = ?", (email,)).fetchone()

    log_event("auth", "邮箱重置密码",
              actor={"id": row["id"], "username": row["username"], "role": row["role"]},
              target_type="user", target_id=row["id"], detail=email,
              ip=client_ip_from_request(request), ua=user_agent(request))
    # 安全提醒：重置密码会踢掉所有已登录会话
    notify_user(
        row["id"], "你的密码已重置",
        "你的账号密码刚刚通过「忘记密码」流程重置，所有已登录会话已失效。\n"
        "如果这不是你的操作，说明有人持有你的邮箱验证码，请立即联系管理员处理。",
    )

    return {"ok": True, "message": "密码重置成功，请使用新密码登录"}


@router.get("/me")
def me(user: dict = Depends(require_auth)):
    return {"user": with_capabilities(user), "codeTtlMs": CODE_TTL_MS,
            "smtpEnabled": smtp_enabled(), "ipv6ProbeEnabled": IPV6_PROBE_ENABLED}


class IpProbeBody(BaseModel):
    ipv6: str = Field("", max_length=64)


@router.post("/ip-probe")
def report_ipv6(body: IpProbeBody, request: Request, user: dict = Depends(require_auth)):
    """记录浏览器主动探测到的公网 IPv6，WebRTC/STUN 方案，见 frontend/src/ipv6Probe.js

    为什么需要单独上报：站点目前只有 IPv4 入口，服务器无全局 IPv6、DNS 无 AAAA，
    HTTP 连接层只能拿到 IPv4；客户端自身的 IPv6 只能由浏览器探测后回传。
    只接受**公网** IPv6，拒绝私网/链路本地/文档地址，同一账号每小时最多 10 次。
    存储位置：`users.last_ip_v6` + `last_ip_v6_at`，并写一条审计，谁在什么时候报的 v6。
    """
    if not IPV6_PROBE_ENABLED:
        raise HTTPException(404, "该功能未启用")
    enforce(request, "ip-probe", 10, 3600)

    raw = normalize_ip(body.ipv6)
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        raise HTTPException(400, "IPv6 地址格式不正确")
    if not isinstance(addr, ipaddress.IPv6Address) or not addr.is_global:
        raise HTTPException(400, "只接受公网 IPv6 地址")

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_ip_v6 = ?, last_ip_v6_at = datetime('now','localtime')"
            " WHERE id = ?",
            (str(addr), user["id"]),
        )
    log_event("auth", "记录探测到的公网 IPv6", actor=user, target_type="user",
              target_id=user["id"], detail=str(addr),
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "ipv6": str(addr)}



@router.patch("/profile")
def update_profile(body: ProfileBody, user: dict = Depends(require_auth)):
    updates, args = [], []

    if body.username is not None:
        username = body.username.strip()
        if not USERNAME_RE.match(username):
            raise HTTPException(400, "用户名需 2-16 位，支持中文、字母、数字、下划线")
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE username = ? AND id != ?", (username, user["id"])
            ).fetchone()
        if exists:
            raise HTTPException(400, "用户名已被占用")
        updates.append("username = ?")
        args.append(username)

    if body.qq is not None:
        qq = body.qq.strip()
        if qq and not QQ_RE.match(qq):
            raise HTTPException(400, "QQ 号格式不正确")
        avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100" if qq else ""
        updates.extend(["qq = ?", "avatar_url = ?"])
        args.extend([qq, avatar_url])

    if not updates:
        raise HTTPException(400, "没有需要更新的内容")

    args.append(user["id"])
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", args)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()

    return {"ok": True, "user": with_capabilities(public_user(row))}


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request,
                          user: dict = Depends(require_auth)):
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not verify_password(body.oldPassword, row["password_hash"]):
        raise HTTPException(400, "当前密码不正确")

    password = _validate_password(body.password, body.confirmPassword)
    with get_conn() as conn:
        # 令牌版本 +1：其他已登录会话，含泄露的 token 全部失效
        _bump_token_ver(conn, user["id"])
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user["id"])
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()

    log_event("auth", "修改密码", actor=user, target_type="user", target_id=user["id"],
              detail="其他会话已失效", ip=client_ip_from_request(request), ua=user_agent(request))
    # 安全提醒：密码被修改，其他会话已全部失效，若非本人操作可凭此邮件察觉
    notify_user(
        user["id"], "你的密码已修改",
        "你的账号密码刚刚被修改，其它已登录的会话已全部失效。\n"
        "如果这不是你的操作，请立即通过「忘记密码」重置密码，并联系管理员。",
    )
    # 给当前会话签发新令牌，避免自己被登出
    return {"ok": True, "message": "密码修改成功", "token": sign_token(row)}
