#!/bin/bash
# 服务器 IPv6 就绪自检，只读，不改任何配置
# 用法：bash ipv6-check.sh
# 输出里出现「全局 IPv6 地址 + 默认路由 + AAAA + 本机 curl -6 200」才算真正可采集 IPv6。
echo "== 1. 全局 IPv6 地址 =="
ip -6 addr show scope global || true

echo
echo "== 2. IPv6 默认路由 =="
ip -6 route show default || true

echo
echo "== 3. IPv6 出网 =="
curl -6 -s --max-time 6 https://ifconfig.co 2>/dev/null || echo "（无 IPv6 出网）"

echo
echo "== 4. DNS AAAA 记录 =="
for d in ccflysim.cn test.ccflysim.cn; do
  printf '%-22s AAAA: %s\n' "$d" "$(dig +short AAAA "$d" @223.5.5.5 | tr '\n' ' ')"
done

echo
echo "== 5. nginx 是否监听 IPv6 =="
grep -rh 'listen \[::\]' /etc/nginx/sites-available/ccflysim \
  /etc/nginx/sites-available/test.ccflysim.cn.conf 2>/dev/null || echo "（未找到 listen [::]）"

echo
echo "== 6. 本机走 IPv6 访问自己（需 AAAA 已生效） =="
curl -6 -s -o /dev/null -w 'https://ccflysim.cn/api/health -> %{http_code}\n' --max-time 6 \
  https://ccflysim.cn/api/health 2>/dev/null || echo "（curl -6 失败：尚未就绪）"

echo
echo "== 7. 应用采集口径（代码已支持 IPv6，入库字段为 TEXT） =="
echo "nginx: proxy_set_header X-Forwarded-For \$remote_addr  →  app: requestinfo.normalize_ip()  →  各日志表 ip 列"
