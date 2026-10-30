#!/usr/bin/env bash
# CTY 飞控 · 服务器部署步骤 5：校验导航库、重启服务、验证航路规划端到端
set -u

echo "=== 1. 导航库完整性 ==="
LOCAL_MD5="4f0636cd643b32a62e2799a1c0e3b2ce"
SERVER_MD5=$(md5sum /opt/ctyfly/backend/navdata-planner/Navdata/nd.db3 | cut -d' ' -f1)
SERVER_SIZE=$(stat -c %s /opt/ctyfly/backend/navdata-planner/Navdata/nd.db3)
echo "  服务器 md5: $SERVER_MD5  大小: $SERVER_SIZE"
echo "  本地   md5: $LOCAL_MD5"
[ "$LOCAL_MD5" = "$SERVER_MD5" ] && echo "  >>> 校验一致 ✓" || echo "  >>> 不一致，需重传"

echo "=== 2. 重启服务（拉起航路 sidecar）==="
systemctl restart ctyfly
sleep 12
systemctl is-active ctyfly
echo "  sidecar 进程: $(pgrep -fc 'node.*server.js' || echo 0) 个"
ss -tlnp 2>/dev/null | grep -q ':4173' && echo "  sidecar 端口 4173 已监听 ✓" || echo "  sidecar 端口未监听"
journalctl -u ctyfly -n 6 --no-pager | grep -E 'navdata|sidecar|spa|smtp' | tail -3

echo "=== 3. 端到端接口验证（用同密钥签发的临时 token）==="
cd /opt/ctyfly/backend
./venv/bin/python - <<'PY'
import json, time, urllib.request
from pathlib import Path
import jwt

secret = ""
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line.startswith("JWT_SECRET="):
        secret = line.split("=", 1)[1].strip()

token = jwt.encode(
    {"uid": 1, "cid": "1000", "role": "admin", "ver": 0, "exp": int(time.time()) + 600},
    secret, algorithm="HS256",
)

def call(method, path, body=None, timeout=180):
    req = urllib.request.Request(
        "http://127.0.0.1:3015" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

print("  /api/nav/status:", json.dumps(call("GET", "/api/nav/status"), ensure_ascii=False)[:160])
print("  /api/airlines:", "ok" if call("GET", "/api/airlines").get("ok") else "失败")

plan = call("POST", "/api/nav/routes/plan", {"origin": "ZGGG", "destination": "ZUUU"})
route = plan.get("routeString", "")
print("  ZGGG→ZUUU 规划:", route[:70], "...")
print("  距离:", plan.get("distanceNM") or plan.get("distance") or "见响应", "NM" if route else "")
print("  >>> 航路规划链路正常 ✓" if route else "  >>> 规划失败")
PY

