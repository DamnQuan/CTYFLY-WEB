#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 1：清理 BOM、校验并加载 nginx、验证两个站点互不影响
set -u

strip_bom() {
  local f="$1"
  [ -f "$f" ] || return 0
  if [ "$(head -c3 "$f" | od -An -tx1 | tr -d ' \n')" = "efbbbf" ]; then
    tail -c +4 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "已去除 BOM: $f"
  fi
}

strip_bom /etc/nginx/sites-available/test.ccflysim.cn.conf
strip_bom /opt/ctyfly/backend/.env

echo "=== nginx 配置校验 ==="
if nginx -t 2>&1 | tail -2; then
  nginx -t >/dev/null 2>&1 && { systemctl reload nginx && echo "nginx 已重载"; }
else
  echo "nginx 配置有误，未重载"
  exit 1
fi

sleep 2
echo "=== 新站 test.ccflysim.cn ==="
printf '  首页 HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 15 -H 'Host: test.ccflysim.cn' http://127.0.0.1/
printf '  /api/health: '; curl -s -m 15 -H 'Host: test.ccflysim.cn' http://127.0.0.1/api/health; echo
printf '  SPA 深层路由 /admin/notices HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 15 -H 'Host: test.ccflysim.cn' http://127.0.0.1/admin/notices
printf '  静态资源: '; asset=$(curl -s -m 15 -H 'Host: test.ccflysim.cn' http://127.0.0.1/ | grep -oE '/assets/index-[^"]+\.js' | head -1); curl -s -o /dev/null -w "HTTP %{http_code} ($asset)\n" -m 15 -H 'Host: test.ccflysim.cn' "http://127.0.0.1$asset"

echo "=== 旧官网 ccflysim.cn（必须不受影响）==="
printf '  首页 HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 15 -H 'Host: ccflysim.cn' http://127.0.0.1/
printf '  首页 HTTP '; curl -s -o /dev/null -w '%{http_code}\n' -m 15 -H 'Host: www.ccflysim.cn' http://127.0.0.1/

echo "=== 后端服务 ==="
systemctl is-active ctyfly
