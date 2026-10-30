"""邮件验证码：SMTP 发信，smtplib、冷却限流、校验消费、防爆破

发信性能设计，实测踩过的坑：
- 腾讯企业邮箱对「新建 SMTP 连接」有明显冷启动惩罚，实测首连 TCP 可达 17s+，
  同 IP 后续连接 0.03s。因此这里维持一条**常驻复用连接**：后台线程每 45s NOOP
  保活，断线自动重连，发信时直接在热连接上 sendmail，毫秒级完成。
- 发信不阻塞 HTTP 请求：send_verification_code 只做限流校验和落库，把邮件丢进
  内存队列后立即返回「已发送」；真正的 SMTP 交互在后台线程完成，失败自动重试
  3 次，递增退避，全程写 journalctl，[mailer] 前缀便于排查。
"""
import hmac
import html
import queue
import random
import smtplib
import threading
import time
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from urllib.parse import urlsplit

from .config import (SITE_PUBLIC_URL, SMTP_FROM, SMTP_HOST, SMTP_PASS,
                     SMTP_PORT, SMTP_USER, smtp_enabled)
from .database import get_conn

CODE_TTL_MS = 10 * 60 * 1000          # 10 分钟
RESEND_COOLDOWN_MS = 60 * 1000        # 60 秒
DAILY_LIMIT = 10                      # 每日上限，按邮箱
MAX_CODE_ATTEMPTS = 5                 # 单个验证码最多可尝试次数

SEND_RETRIES = 3                      # 单封邮件后台重试次数
KEEPALIVE_SECS = 45                   # 常驻连接保活间隔
SMTP_CONNECT_TIMEOUT = 30             # 冷连接可能很慢，超时放宽

# 内存级错误次数计数：key = f"{email}:{purpose}"
_code_attempts: dict[str, int] = {}

# ---------- 常驻 SMTP 连接，同一进程内复用，锁保护 ----------
_smtp_lock = threading.Lock()
_smtp_server = None

# 待发邮件队列：元素 to, subject, html
_mail_queue: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
_threads_started = False
_threads_lock = threading.Lock()


# 所有系统邮件统一页脚：版权声明 + 免回复提示
_EMAIL_FOOTER = (
    '<p style="color:#86868b;font-size:11px;margin:22px 0 0;'
    'padding-top:14px;border-top:1px solid #e5e5ea;text-align:center;">'
    '© 2026 CTYFLY - All rights reserved&nbsp;&nbsp;&nbsp;此邮件由系统自动发送，请勿直接回复</p>'
)


def _build_html(code: str, purpose: str) -> str:
    """验证码邮件：与通知邮件同一套黑白灰简洁配色，无彩色元素"""
    scene = "注册账号" if purpose == "register" else "重置密码"
    # 插值全部转义：code 虽由服务端生成，但转义是模板的固定纪律，防未来改动引入注入
    code = html.escape(code)
    scene = html.escape(scene)
    return f"""
  <div style="font-family:-apple-system,'SF Pro Text','PingFang SC',Helvetica,Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;background:#f5f5f7;border-radius:20px;">
    <h2 style="color:#1d1d1f;font-weight:600;font-size:22px;margin:0 0 8px;">CTYFLY</h2>
    <div style="background:#ffffff;border-radius:14px;padding:24px;">
      <p style="color:#1d1d1f;font-size:16px;font-weight:600;margin:0 0 14px;">您正在进行{scene}操作</p>
      <p style="color:#3a3a3c;font-size:14px;line-height:1.8;margin:0 0 14px;">您的验证码如下，10 分钟内有效：</p>
      <div style="background:#f5f5f7;border-radius:10px;padding:20px;text-align:center;letter-spacing:10px;font-size:28px;font-weight:700;color:#1d1d1f;">
        {code}
      </div>
      <p style="color:#86868b;font-size:12px;margin:14px 0 0;">若非本人操作，请忽略此邮件。</p>
    </div>
    {_EMAIL_FOOTER}
  </div>"""


def _build_notice_html(title: str, body_text: str) -> str:
    """站内通知类邮件，审核结果 / 安全提醒等的通用模板

    title / body_text 可能含用户可控内容，如工单标题、审批理由，
    所有插值必须 html.escape，防止通过邮件内容做钓鱼/HTML 注入。
    """
    title = html.escape(title)
    lines = "".join(
        f'<p style="color:#3a3a3c;font-size:14px;line-height:1.8;margin:0 0 10px;">{html.escape(ln)}</p>'
        for ln in body_text.split("\n") if ln.strip()
    )
    # 站点域名从配置读取，SITE_PUBLIC_URL，.env 可覆盖，不再写死测试域名
    site_host = urlsplit(SITE_PUBLIC_URL).netloc or SITE_PUBLIC_URL
    site_host = html.escape(site_host)
    return f"""
  <div style="font-family:-apple-system,'SF Pro Text','PingFang SC',Helvetica,Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;background:#f5f5f7;border-radius:20px;">
    <h2 style="color:#1d1d1f;font-weight:600;font-size:22px;margin:0 0 8px;">CTYFLY</h2>
    <div style="background:#ffffff;border-radius:14px;padding:24px;">
      <p style="color:#1d1d1f;font-size:16px;font-weight:600;margin:0 0 14px;">{title}</p>
      {lines}
      <p style="color:#86868b;font-size:12px;margin:18px 0 0;">请登录 {site_host} 查看详情。若对结果有疑问，可通过工单联系管理员。</p>
    </div>
    {_EMAIL_FOOTER}
  </div>"""


def notify_user(user_id: int, subject: str, body_text: str) -> None:
    """给站内用户发一封通知邮件，走同一个常驻连接队列，异步发送。

    任何失败都只写日志、绝不抛错 —— 通知是锦上添花，不能拖垮主流程事务。
    """
    try:
        if not smtp_enabled():
            return
        with get_conn() as conn:
            row = conn.execute("SELECT email, status FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not row["email"] or row["status"] == "deleted":
            return
        _ensure_threads()
        _mail_queue.put((row["email"], f"CTYFLY · {subject}", _build_notice_html(subject, body_text)))
    except Exception as exc:   # noqa: BLE001
        print(f"[mailer] 通知入队失败 uid={user_id}: {exc!r}")


def _smtp_connect() -> smtplib.SMTP:
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT)
        server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    return server


def _smtp_close() -> None:
    global _smtp_server
    srv, _smtp_server = _smtp_server, None
    if srv is not None:
        try:
            srv.quit()
        except Exception:
            pass


def _smtp_send_on_pooled(to: str, body: str) -> None:
    """在常驻连接上发一封；连接不存在/已死时重连，调用方持有 _smtp_lock"""
    global _smtp_server
    srv = _smtp_server
    if srv is None:
        print("[mailer] 无可用连接，重新连接 SMTP…")
        _smtp_server = srv = _smtp_connect()
    try:
        srv.sendmail(SMTP_FROM, [to], body)
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPNotSupportedError, OSError):
        # 连接被服务端掐掉，长时间空闲等：换新连接重试一次
        _smtp_close()
        print("[mailer] 连接已失效，重连后重发…")
        _smtp_server = srv = _smtp_connect()
        srv.sendmail(SMTP_FROM, [to], body)


def _deliver(to: str, subject: str, html: str) -> bool:
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_FROM
    msg["To"] = to
    body = msg.as_string()

    last_err: Exception | None = None
    for attempt in range(1, SEND_RETRIES + 1):
        t0 = time.time()
        try:
            with _smtp_lock:
                _smtp_send_on_pooled(to, body)
            print(f"[mailer] 已发送 to={to} subject={subject!r}"
                  f" 耗时={time.time() - t0:.2f}s 第{attempt}次尝试")
            return True
        except Exception as exc:   # noqa: BLE001 —— 记录后重试
            last_err = exc
            with _smtp_lock:
                _smtp_close()
            print(f"[mailer] 第{attempt}次发送失败 to={to}: {exc!r}")
            if attempt < SEND_RETRIES:
                time.sleep(3 * attempt)
    print(f"[mailer] 发送最终失败 to={to} subject={subject!r}: {last_err!r}")
    return False


def _sender_worker() -> None:
    while True:
        to, subject, html = _mail_queue.get()
        try:
            _deliver(to, subject, html)
        except Exception as exc:   # 兜底：绝不让后台线程死掉
            print(f"[mailer] 发送线程异常: {exc!r}")
        finally:
            _mail_queue.task_done()


def _keepalive_worker() -> None:
    """保活常驻连接：空闲时 NOOP，断线自动重连。

    腾讯企业邮箱对新建连接有冷启动惩罚，实测可达 17s+，保活让每次发信
    都落在热连接上。连续失败时退避，避免 journal 刷屏。
    """
    global _smtp_server
    fails = 0
    while True:
        time.sleep(KEEPALIVE_SECS * min(1 + fails, 6))
        if not smtp_enabled():
            continue
        with _smtp_lock:
            try:
                if _smtp_server is None:
                    _smtp_server = _smtp_connect()
                    fails = 0
                    print("[mailer] SMTP 连接预热完成")
                else:
                    _smtp_server.noop()
                    fails = 0
            except Exception as exc:   # noqa: BLE001
                fails += 1
                _smtp_close()
                print(f"[mailer] 保活失败，第{fails}次，将退避重试: {exc!r}")


def _ensure_threads() -> None:
    global _threads_started
    with _threads_lock:
        if _threads_started:
            return
        threading.Thread(target=_sender_worker, name="mailer-sender", daemon=True).start()
        threading.Thread(target=_keepalive_worker, name="mailer-keepalive", daemon=True).start()
        _threads_started = True
        print("[mailer] 后台发送/保活线程已启动")


def prewarm() -> None:
    """应用启动时调用：立即启动后台线程并预热 SMTP 连接，失败不影响启动"""
    try:
        _ensure_threads()
    except Exception as exc:   # noqa: BLE001 —— 预热失败不影响服务启动
        print(f"[mailer] 预热失败，首次发信时会自动重试: {exc!r}")


def send_verification_code(email: str, purpose: str, allow_dev: bool = False) -> dict:
    """发送验证码并落库。返回 {ok, devCode?, error?, expiresAt}

    email 统一 strip + 小写：与 send-code / register / reset 的归一口径一致，
    保证冷却/每日上限/验证码比对都落在同一条记录上。

    allow_dev：仅当请求来源是本机/内网时由调用方置 True。
    SMTP 未配置时 devCode 只允许返回给本地/内网来源——公网请求拿不到验证码，
    否则 SMTP 一旦故障，「注册任意邮箱 / 重置任意密码」就对全网开放了。
    """
    email = (email or "").strip().lower()
    with get_conn() as conn:
        last = conn.execute(
            "SELECT created_at FROM verification_codes WHERE email = ? ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
        if last:
            last_ts = datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S").timestamp()
            if (time.time() - last_ts) * 1000 < RESEND_COOLDOWN_MS:
                return {"ok": False, "error": "发送过于频繁，请 60 秒后再试"}

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily = conn.execute(
            "SELECT COUNT(*) c FROM verification_codes WHERE email = ? AND created_at >= ?",
            (email, today_start.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
        if daily["c"] >= DAILY_LIMIT:
            return {"ok": False, "error": "今日验证码发送次数已达上限，请明天再试"}

    code = f"{random.randint(0, 999999):06d}"
    result: dict = {"ok": True, "expiresAt": int(time.time() * 1000) + CODE_TTL_MS}

    # 先落库，冷却 / 每日上限都靠这张表，再交后台发信 —— 请求立即返回
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO verification_codes (email, code, purpose, expires_at) VALUES (?, ?, ?, ?)",
            (email, code, purpose, result["expiresAt"]),
        )

    if smtp_enabled():
        scene = "注册" if purpose == "register" else "密码重置"
        subject = f"CTYFLY · 您的{scene}验证码：{code}"
        _ensure_threads()
        _mail_queue.put((email, subject, _build_html(code, purpose)))
    elif allow_dev:
        # 仅本机/内网开发请求：SMTP 未配置时直接把验证码返回，方便联调
        result["devCode"] = code
        print(f"[smtp][dev] {email} 的验证码: {code}")
    else:
        # 公网来源 + SMTP 未配置：不落 devCode，验证码已入库但不会外泄。
        # auth.send-code 已提前 503，这里仅为纵深防御。
        result["ok"] = False
        result["error"] = "邮件服务未配置，请联系管理员"
        print(f"[smtp] 未配置 SMTP 且来源非本地，拒绝返回验证码 email={email}")

    return result


def consume_verification_code(email: str, purpose: str, code: str) -> dict:
    """校验并消费验证码。返回 {ok} 或 {ok: False, error}

    防爆破：常量时间比较 + 累计错 5 次强制作废当前验证码。
    """
    # 与 send_verification_code 相同的小写归一：attempt_key、DB 比对、删除范围都一致
    email = (email or "").strip().lower()
    attempt_key = f"{email}:{purpose}"
    if _code_attempts.get(attempt_key, 0) >= MAX_CODE_ATTEMPTS:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM verification_codes WHERE email = ? AND purpose = ?", (email, purpose)
            )
        _code_attempts.pop(attempt_key, None)
        return {"ok": False, "error": "错误次数过多，该验证码已作废，请重新获取"}

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM verification_codes WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
            (email, purpose),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "请先获取验证码"}
        if time.time() * 1000 > row["expires_at"]:
            return {"ok": False, "error": "验证码已过期，请重新获取"}
        if not hmac.compare_digest(str(row["code"]), str(code).strip()):
            tries = _code_attempts.get(attempt_key, 0) + 1
            _code_attempts[attempt_key] = tries
            left = MAX_CODE_ATTEMPTS - tries
            msg = "验证码错误"
            if left > 0:
                msg += f"，还可尝试 {left} 次"
            return {"ok": False, "error": msg}
        conn.execute("DELETE FROM verification_codes WHERE id = ?", (row["id"],))
    _code_attempts.pop(attempt_key, None)
    return {"ok": True}
