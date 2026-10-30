#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 4：数据备份 + 服务验证
#
# 2026-10-18：备份脚本改为从仓库 deploy/ops/backup.sh 安装，单一来源，不再内嵌 heredoc。
# 备份内容：数据库一致性快照 + 上传文件 + 日志归档，backend/data/log-archive。
set -u

echo "=== 安装 sqlite3（用于一致性备份）==="
command -v sqlite3 >/dev/null || apt-get install -y -qq sqlite3 >/dev/null 2>&1
command -v sqlite3 >/dev/null && echo "sqlite3 可用" || echo "sqlite3 不可用（将退化为文件复制）"

echo "=== 安装备份脚本（来源：仓库 deploy/ops/backup.sh）==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 755 "$SCRIPT_DIR/../ops/backup.sh" /opt/ctyfly/backup.sh
echo "已安装 /opt/ctyfly/backup.sh"

echo "=== 注册每日 04:00 定时任务 ==="
CRON_LINE="0 4 * * * /opt/ctyfly/backup.sh >> /var/log/ctyfly-backup.log 2>&1"
crontab -l 2>/dev/null | grep -qF '/opt/ctyfly/backup.sh' || { crontab -l 2>/dev/null; echo "$CRON_LINE"; } | crontab -
crontab -l 2>/dev/null | grep -F 'ctyfly/backup.sh' && echo "定时任务已注册"

echo "=== 立即执行一次备份 ==="
/opt/ctyfly/backup.sh
ls -lh /opt/ctyfly/backups/ | tail -5

echo "=== 服务状态 ==="
systemctl is-active ctyfly
echo "=== 服务器端到端登录测试 ==="
# 密码经环境变量传给 python3，用 json.dumps 构造请求体。
# 避免明文密码直接拼接 JSON，密码含引号/反斜杠等特殊字符时会破坏 JSON 甚至注入。
ADMIN_PWD=$(grep '^ADMIN_PASSWORD=' /opt/ctyfly/backend/.env | cut -d= -f2- | tr -d '\r')
BODY=$(ADMIN_PWD="$ADMIN_PWD" python3 -c 'import json,os; print(json.dumps({"account":"1000","password":os.environ["ADMIN_PWD"]}))')
RESP=$(curl -s -m 20 -X POST http://127.0.0.1:3015/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$BODY")
echo "$RESP" | head -c 120
echo
echo "$RESP" | grep -q '"token"' && echo ">>> 管理员登录成功（认证链路正常）" || echo ">>> 登录失败，需检查"
