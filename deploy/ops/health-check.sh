#!/usr/bin/env bash
# 健康自愈：失败自动重启；由健康转为失败时发告警邮件，边沿触发防轰炸
STATE=/var/run/ctyfly-health.state
PREV=$(cat $STATE 2>/dev/null || echo healthy)
if curl -fsS -m 10 http://127.0.0.1:3015/api/health >/dev/null 2>&1; then
  echo healthy > $STATE
  if [ "$PREV" = "unhealthy" ]; then
    echo "[$(date '+%F %T')] 已恢复" >> /var/log/ctyfly-health.log
    /opt/ctyfly/alert-mail.py "CTYFLY 已恢复" "健康检查恢复正常。" 2>/dev/null
  fi
  exit 0
fi
if [ "$PREV" != "unhealthy" ]; then
  echo "[$(date '+%F %T')] 健康检查失败，重启 ctyfly" >> /var/log/ctyfly-health.log
  /opt/ctyfly/alert-mail.py "CTYFLY 健康检查失败" "健康检查失败，已自动重启 ctyfly；若持续失败将再次告警。" 2>/dev/null
fi
echo unhealthy > $STATE
systemctl restart ctyfly
