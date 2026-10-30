#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 4：数据库备份 + 服务验证
set -u

echo "=== 安装 sqlite3（用于一致性备份）==="
command -v sqlite3 >/dev/null || apt-get install -y -qq sqlite3 >/dev/null 2>&1
command -v sqlite3 >/dev/null && echo "sqlite3 可用" || echo "sqlite3 不可用（将退化为文件复制）"

echo "=== 写入备份脚本 ==="
cat > /opt/ctyfly/backup.sh <<'EOS'
#!/usr/bin/env bash
# CTY 飞控数据备份：数据库，一致性快照+ 上传文件，保留 14 天
set -u
DIR=/opt/ctyfly/backups
DB=/opt/ctyfly/backend/data/ctyfly.db
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$DIR"

if [ -f "$DB" ]; then
  if command -v sqlite3 >/dev/null; then
    sqlite3 "$DB" ".backup '$DIR/ctyfly-$STAMP.db'"
  else
    cp "$DB" "$DIR/ctyfly-$STAMP.db"
  fi
fi

if [ -d /opt/ctyfly/backend/data/uploads ]; then
  tar -czf "$DIR/uploads-$STAMP.tar.gz" -C /opt/ctyfly/backend/data uploads 2>/dev/null || true
fi

find "$DIR" -type f -mtime +14 -delete
echo "[$(date '+%F %T')] 备份完成 ctyfly-$STAMP.db（保留 14 天）"
EOS
chmod +x /opt/ctyfly/backup.sh

echo "=== 注册每日 04:00 定时任务 ==="
CRON_LINE="0 4 * * * /opt/ctyfly/backup.sh >> /var/log/ctyfly-backup.log 2>&1"
crontab -l 2>/dev/null | grep -qF '/opt/ctyfly/backup.sh' || { crontab -l 2>/dev/null; echo "$CRON_LINE"; } | crontab -
crontab -l 2>/dev/null | grep -F 'ctyfly/backup.sh' && echo "定时任务已注册"

echo "=== 立即执行一次备份 ==="
/opt/ctyfly/backup.sh
ls -lh /opt/ctyfly/backups/ | tail -4

echo "=== 服务状态 ==="
systemctl is-active ctyfly
echo "=== 服务器上端到端登录测试 ==="
ADMIN_PWD=$(grep '^ADMIN_PASSWORD=' /opt/ctyfly/backend/.env | cut -d= -f2-)
RESP=$(curl -s -m 20 -X POST http://127.0.0.1:3015/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"account\":\"1000\",\"password\":\"$ADMIN_PWD\"}")
echo "$RESP" | head -c 120
echo
echo "$RESP" | grep -q '"token"' && echo ">>> 管理员登录成功（认证链路正常）" || echo ">>> 登录失败，需检查"
