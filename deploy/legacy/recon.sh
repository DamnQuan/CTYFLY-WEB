set -u
echo "=== ACME 客户端现状 ==="
which certbot acme.sh 2>/dev/null || true
[ -d /root/.acme.sh ] && echo "acme.sh dir exists" || echo "no /root/.acme.sh"
certbot --version 2>/dev/null || echo "certbot not found"
echo
echo "=== 现有证书文件 ==="
ls -l /etc/nginx/ssl/ccflysim/ 2>/dev/null
echo
echo "=== 现有证书有效期 ==="
for f in /etc/nginx/ssl/ccflysim/*.crt; do
  [ -f "$f" ] && echo "--- $f" && openssl x509 -in "$f" -noout -subject -dates 2>/dev/null
done
echo
echo "=== letsencrypt live ==="
ls -l /etc/letsencrypt/live/ 2>/dev/null
echo
echo "=== certbot 自动续期 ==="
systemctl is-enabled certbot.timer 2>/dev/null || echo "no certbot.timer"
systemctl is-active certbot.timer 2>/dev/null || true
echo
echo "=== 外网可达性（acme.sh 安装源）==="
for u in https://get.acme.sh https://raw.githubusercontent.com https://gitee.com; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 "$u" 2>/dev/null)
  echo "$u -> $code"
done
echo
echo "=== nginx 版本 / 系统 ==="
nginx -v 2>&1
. /etc/os-release && echo "$PRETTY_NAME  $(uname -m)"
python3 --version