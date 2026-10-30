#!/usr/bin/env python3
"""CTYFLY 服务器告警邮件：读 backend/.env 的 SMTP 配置发信，与站内同一凭据。

告警失败必须可见：SMTP 未配置或发送失败都会把「时间 + 原因」追加写入
/var/log/ctyfly-alert-fail.log，避免告警静默丢失。
退出码：0 = 发送成功；1 = 未配置 / 读取失败 / 发送失败。
"""
import re
import smtplib
import sys
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText

ENV = "/opt/ctyfly/backend/.env"
TO = "support@ccflysim.cn"
FAIL_LOG = "/var/log/ctyfly-alert-fail.log"


def log_fail(reason: str) -> None:
    """把失败原因落到失败日志，写不进去也要打到 stderr，做到可见。"""
    line = "[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), reason)
    try:
        with open(FAIL_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        print("cannot write %s: %s" % (FAIL_LOG, exc), file=sys.stderr)
    print(line.strip(), file=sys.stderr)


subject = sys.argv[1] if len(sys.argv) > 1 else "CTYFLY 服务器告警"
body = sys.argv[2] if len(sys.argv) > 2 else ""

cfg = {}
try:
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASS|SMTP_FROM)=(.*)$", line.strip())
            if m:
                cfg[m.group(1)] = m.group(2)
except OSError as exc:
    log_fail("无法读取 %s: %s（subject=%s）" % (ENV, exc, subject))
    sys.exit(1)

if not cfg.get("SMTP_HOST") or not cfg.get("SMTP_USER") or not cfg.get("SMTP_PASS"):
    missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS") if not cfg.get(k)]
    log_fail("SMTP 未配置（backend/.env 缺少 %s），告警未发出: %s" % (",".join(missing), subject))
    sys.exit(1)

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = Header("CTYFLY · " + subject, "utf-8")
msg["From"] = cfg.get("SMTP_FROM", "noreply@ccflysim.cn")
msg["To"] = TO
try:
    smtp = smtplib.SMTP_SSL(cfg["SMTP_HOST"], int(cfg.get("SMTP_PORT", "465")), timeout=20)
    smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
    smtp.sendmail(cfg["SMTP_FROM"], [TO], msg.as_string())
    smtp.quit()
except Exception as exc:
    log_fail("告警邮件发送失败: %s（subject=%s）" % (exc, subject))
    sys.exit(1)
sys.exit(0)
