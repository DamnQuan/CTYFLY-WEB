#!/usr/bin/env bash
# CTYFLY 前端换目录助手：由 deploy.ps1 通过 scp 上传后在服务器执行
# 用法: ctyfly-swap.sh <时间戳>
# 原子换目录：先解包到 dist.new-$TS，成功后才把旧 dist 改名备份、新目录改名生效；
# 解包失败时旧 dist 原封不动，set -e 保证脚本立即退出。
set -eu
TS="${1:?missing timestamp}"
cd /opt/ctyfly/frontend
# 首部署 dist 可能还不存在：先兜底建空目录，保证下面取属主、换名流程统一可走
[ -d dist ] || mkdir -p dist
OWNER=$(stat -c '%U:%G' dist)

rm -rf "dist.new-$TS"
mkdir "dist.new-$TS"
tar -xzf /tmp/ctyfly-dist.tar.gz -C "dist.new-$TS"
rm -f /tmp/ctyfly-dist.tar.gz
chown -R "$OWNER" "dist.new-$TS"
rm -rf "dist-bak-$TS"
mv dist "dist-bak-$TS"
mv "dist.new-$TS" dist
# 只保留最近 3 份备份
ls -dt dist-bak-* 2>/dev/null | tail -n +4 | xargs -r rm -rf

echo "BACKUP=dist-bak-$TS"
echo "ENTRY=$(grep -o 'assets/index-[a-zA-Z0-9._-]*\.js' dist/index.html)"
