set -u
echo "=== certbot 管理的证书清单 ==="
certbot certificates 2>/dev/null
echo
echo "=== 旧站证书 SAN 和签发者 ==="
openssl x509 -in /etc/nginx/ssl/ccflysim/ccflysim.cn.fullchain.crt -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null
echo
echo "=== letsencrypt live 目录内容 ==="
ls -l /etc/letsencrypt/live/ccflysim.cn/ 2>/dev/null
echo "--- live/ccflysim.cn 证书信息 ---"
openssl x509 -in /etc/letsencrypt/live/ccflysim.cn/cert.pem -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null || echo "read fail"
echo
echo "=== certbot renewal 配置 ==="
ls -l /etc/letsencrypt/renewal/ 2>/dev/null
for f in /etc/letsencrypt/renewal/*.conf; do echo "--- $f"; cat "$f"; echo; done