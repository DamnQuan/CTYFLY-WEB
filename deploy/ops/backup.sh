#!/usr/bin/env bash
# CTYFLY 服务器数据备份，每日 04:00 由 cron 调用
#
# 2026-10-18 更新：站长要求「所有日志在服务器留档，官网保留 30 天」。
# - 官网日志，登录/注册/审计/API 访问由 app/logretention.py 归档到
#     backend/data/log-archive/ 并从库里清理到 30 天；
#   - 本脚本把 log-archive 一起打包进每日备份，配合本机计划任务
#D:\CTYFLY-BACKUPS\pull-backup.ps1 异地拉取，避免单盘损坏丢归档。
#
# 备份内容：数据库一致性快照 + 上传文件 + 日志归档
# 保留期：本机 14 天，配合异地拉取，异地同样保留 14 天
set -u
DIR=/opt/ctyfly/backups
DB=/opt/ctyfly/backend/data/ctyfly.db
DATA=/opt/ctyfly/backend/data
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$DIR"

# 1 数据库：sqlite3 .backup 做一致性快照，服务运行中也可安全备份
if [ -f "$DB" ]; then
  if command -v sqlite3 >/dev/null; then
    sqlite3 "$DB" ".backup '$DIR/ctyfly-$STAMP.db'"
  else
    cp "$DB" "$DIR/ctyfly-$STAMP.db"
  fi
fi

# 2 用户上传文件，航司 Logo / 工单附件 / 活动海报
if [ -d "$DATA/uploads" ]; then
  tar -czf "$DIR/uploads-$STAMP.tar.gz" -C "$DATA" uploads 2>/dev/null || true
fi

# 3 已归档日志，logretention 产出的 gzip JSONL；体积很小
if [ -d "$DATA/log-archive" ]; then
  tar -czf "$DIR/log-archive-$STAMP.tar.gz" -C "$DATA" log-archive 2>/dev/null || true
fi

# 4 只保留最近 14 天
find "$DIR" -type f -mtime +14 -delete
echo "[$(date '+%F %T')] 备份完成 ctyfly-$STAMP.db（保留 14 天）"
