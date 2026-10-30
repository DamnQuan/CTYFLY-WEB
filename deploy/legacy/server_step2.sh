#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 2：申请并安装 Let's Encrypt 证书，HTTPS
set -u

DOMAIN=test.ccflysim.cn
EMAIL=noreply@ccflysim.cn

echo "=== certbot nginx 插件 ==="
if ! certbot plugins 2>/dev/null | grep -q nginx; then
  echo "安装 python3-certbot-nginx ..."
  apt-get install -y -qq python3-certbot-nginx >/dev/null 2>&1 || true
fi
certbot plugins 2>/dev/null | grep -q nginx && echo "nginx 插件可用" || echo "警告：未检测到 nginx 插件"

echo "=== 申请证书（首次签发，HTTP-01 校验）==="
certbot --nginx -d "$DOMAIN" \
  --non-interactive --agree-tos -m "$EMAIL" --redirect --keep-until-expiring 2>&1 | tail -12

echo "=== 证书状态 ==="
certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' | head -6

echo "=== HTTPS 验证 ==="
printf '  https 首页 HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 "https://$DOMAIN/" --resolve "$DOMAIN:443:127.0.0.1"
printf '  https /api/health: '; curl -s -m 20 "https://$DOMAIN/api/health" --resolve "$DOMAIN:443:127.0.0.1"; echo
printf '  http 自动跳转 HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 20 "http://$DOMAIN/" --resolve "$DOMAIN:80:127.0.0.1"

echo "=== 旧官网仍正常 ==="
printf '  ccflysim.cn HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 15 -H 'Host: ccflysim.cn' http://127.0.0.1/
