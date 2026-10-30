#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 3：重试签发证书，机房对 80 端口的拦截是间歇性的
set -u
DOMAIN=test.ccflysim.cn
EMAIL=noreply@ccflysim.cn

for i in 1 2 3 4; do
  echo "===== 第 $i 次尝试 ====="
  out=$(certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" \
        --redirect --keep-until-expiring 2>&1)
  if echo "$out" | grep -qE 'Successfully received certificate|Certificate not yet due for renewal'; then
    echo "$out" | tail -6
    echo ">>> 证书签发成功"
    break
  fi
  echo "$out" | grep -E 'Detail:|Type:|failed|Successfully' | head -4
  echo ">>> 本次未成功（多为拦截页干扰），等待 8 秒后重试"
  sleep 8
done

echo "=== 证书列表 ==="
certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' | head -8

echo "=== HTTPS 与跳转验证（本机）==="
printf '  https 首页: '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 -k "https://$DOMAIN/" --resolve "$DOMAIN:443:127.0.0.1"
printf '  https /api/health: '; curl -s -k -m 20 "https://$DOMAIN/api/health" --resolve "$DOMAIN:443:127.0.0.1"; echo
printf '  http 跳转: '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 "http://$DOMAIN/" --resolve "$DOMAIN:80:127.0.0.1"
