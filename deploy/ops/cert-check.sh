#!/usr/bin/env bash
# 证书到期检查：剩余 <21 天发告警，certbot 挂了的兜底
for d in ccflysim.cn test.ccflysim.cn; do
  END=$(echo | openssl s_client -connect 127.0.0.1:443 -servername $d 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  [ -z "$END" ] && continue
  DAYS=$(( ( $(date -d "$END" +%s) - $(date +%s) ) / 86400 ))
  if [ $DAYS -lt 21 ]; then
    /opt/ctyfly/alert-mail.py "证书 $d 仅剩 ${DAYS} 天" "证书 $d 将于 $END 过期，请检查 certbot 续期（泛域名需 /etc/letsencrypt/aliyun-dns.ini 凭据有效）。" 2>/dev/null
  fi
done
