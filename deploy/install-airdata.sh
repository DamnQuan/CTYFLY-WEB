#!/bin/bash
# AIRAC 数据换装 worker，由 install-airdata.ps1 上传后执行
# 用法: bash install-airdata.sh <暂存目录> <cycle> <时间戳> <force:0|1> <targets:main|test|both> <skip_restart:0|1>
#
# 为什么这么多讲究，都是本项目真实踩过的坑：
#  - sidecar 全局只有一个实例监听 127.0.0.1:4173，由「先启动的那个后端」拉起，两个环境共用它。
#    因此两个环境的 Navdata 必须同 cycle，且重启顺序固定为「先主站、后 test」。
#  - 换数据必须在服务停止时做：否则 sidecar 仍持有旧文件句柄。
#  - 不能把 nd.db3-shm / nd.db3-wal 带过去：别处的 SQLite WAL 副产物会导致加锁失败或
#    「database disk image is malformed」。
# - 校验读库要用 mode=ro，只读：否则 root 会生成 root 属主的 -wal/-shm，污染目录属主。
set -u

SRC="$1"; CYCLE="$2"; STAMP="$3"; FORCE="$4"; TARGETS="$5"; SKIP_RESTART="$6"
MAIN_BASE=/opt/ctyfly
TEST_BASE=/opt/ctyfly-test

envs() {
  case "$TARGETS" in
    main) echo "main" ;;
    test) echo "test" ;;
    both) echo "main test" ;;
    *)    echo "" ;;
  esac
}

env_base() { case "$1" in main) echo "$MAIN_BASE" ;; test) echo "$TEST_BASE" ;; esac; }
env_svc()  { case "$1" in main) echo "ctyfly" ;; test) echo "ctyfly-test" ;; esac; }

cur_cycle() { grep -m1 'AIRAC cycle' "$1/cycle_info.txt" 2>/dev/null | tr -dc '0-9'; }

SWAPPED=""

echo "===== 换装 AIRAC cycle $CYCLE → [$TARGETS] ====="

# 安全闸：只装 test 时，主站仍是旧 cycle 会出现「test 界面显示新、实际算的是主站旧数据」
if [ "$TARGETS" = "test" ]; then
  MAIN_NAV="$MAIN_BASE/backend/navdata-planner/Navdata"
  mc=$(cur_cycle "$MAIN_NAV")
  if [ "$mc" != "$CYCLE" ]; then
    echo "⚠️  警告：你只换 test，但主站当前是 cycle ${mc:-未知}，而 sidecar 是两站共用的。"
    echo "    若主站的 sidecar 持有 4173，test 的规划实际仍会走主站数据（看似更新、实则没变）。"
    echo "    除非你随后也会换主站，否则建议用 -Target both。"
  fi
fi

# ---------- 1 换文件，停服做 ----------
for e in $(envs); do
  BASE=$(env_base "$e"); SVC=$(env_svc "$e"); NAV="$BASE/backend/navdata-planner/Navdata"
  cur=$(cur_cycle "$NAV")
  echo "--- [$e] 当前 cycle=${cur:-无}  →  目标 $CYCLE"
  if [ "$cur" = "$CYCLE" ] && [ "$FORCE" != "1" ]; then
    echo "    已是同 cycle，跳过（要强制重装加 -Force）"
    continue
  fi
  systemctl stop "$SVC"
  if [ -d "$NAV" ]; then
    BAK="$NAV-bak-${cur:-unknown}-$STAMP"
    mv "$NAV" "$BAK"
    echo "    旧目录已备份: $(basename "$BAK")"
  fi
  mkdir -p "$NAV"
  cp "$SRC/nd.db3" "$SRC/cycle_info.txt" "$SRC/cycle.json" "$NAV/" || { echo "    ✗ 复制失败"; exit 1; }
  rm -f "$NAV/nd.db3-shm" "$NAV/nd.db3-wal"
  chown -R ctyfly:ctyfly "$BASE/backend/navdata-planner"
  echo "    ✓ 已换入 cycle $CYCLE"
  SWAPPED="$SWAPPED $e"
done

if [ -z "$SWAPPED" ] && [ "$SKIP_RESTART" != "1" ]; then
  echo "没有任何环境需要换装（都是同 cycle），跳过重启。"
fi

# ---------- 2 启动：固定顺序 先主站 后 test，决定 4173 归属 ----------
if [ "$SKIP_RESTART" != "1" ] && [ -n "$SWAPPED" ]; then
  echo "--- 重启服务（先主站，后 test）"
  for e in main test; do
    case " $SWAPPED " in *" $e "*) systemctl start "$(env_svc "$e")"; echo "    started $(env_svc "$e")"; sleep 1;; esac
  done
  for i in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q '127.0.0.1:4173' && break
    sleep 1
  done
fi

# ---------- 3 校验 ----------
echo
echo "===== 校验 ====="
for e in $(envs); do
  BASE=$(env_base "$e"); NAV="$BASE/backend/navdata-planner/Navdata"; SVC=$(env_svc "$e")
  echo "--- [$e]"
  printf "    文件 cycle_info: "; grep -m1 'AIRAC cycle' "$NAV/cycle_info.txt" 2>/dev/null || echo "(缺失)"
  printf "    库内 CycleName: "
  python3 - "$NAV/nd.db3" <<'PY'
import sqlite3, sys
try:
    c = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
    row = c.execute("SELECT val FROM config WHERE key='CycleName'").fetchone()
    print(row[0] if row else "(无)")
except Exception as e:
    print("读取失败:", e)
PY
  printf "    服务状态: "; systemctl is-active "$SVC"
  printf "    sidecar 进程 cwd: "
  pid=$(pgrep -f "[s]erver.js" | head -1)
  [ -n "$pid" ] && readlink "/proc/$pid/cwd" || echo "(无 sidecar 进程)"
done

echo
echo "--- 规划器实际在用的数据（/api/status）"
curl -s --max-time 10 http://127.0.0.1:4173/api/status || echo "  调用失败"
echo
echo "--- 端到端：规划 ZGGG→ZBAA，读回它自己报告的 cycle"
curl -s --max-time 25 -X POST http://127.0.0.1:4173/api/routes \
  -H 'Content-Type: application/json' \
  -d '{"origin":"ZGGG","destination":"ZBAA"}' \
  | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
    print('    规划 cycle = %s | route = %s | costs = %s' % (d.get('cycle'), d.get('routeString'), d.get('costs')))
except Exception as e:
    print('    解析失败:', e)"
echo
echo "===== 完成。回滚（如需）：把 Navdata-bak-<旧cycle>-$STAMP 改回 Navdata 并重启对应服务 ====="
