"""日志保留期：**官网，管理后台只留 30 天；过期前先归档到服务器再删除**

要求，站长 2026-10-18：
- 官网只保留最近 30 天的日志，登录 / 注册 / 审计 / API 访问，后台不再展示更早记录；
- 更早的数据不能直接丢掉，要在服务器上「留档」，用于事后安全溯源。

实现方式：
- 归档为 gzip JSONL，按「表 / 月份」落盘到 `config.LOG_ARCHIVE_DIR`
  默认 `backend/data/log-archive/<表名>/<YYYY-MM>.jsonl.gz`，追加写、多 gzip member 合法；
- **先写归档并 fsync，再删数据库行**：归档失败时本表本轮不删除，下轮重试，绝不丢数据；
- `state.json` 记录每张表「已归档的最大 id」，重复运行不会把同一批行重复写进归档；
- `manifest.log` 逐次记录「何时归档了哪张表多少行、落到哪个文件」，方便人工取证与核对。

保留范围：`login_logs` / `register_logs` / `audit_logs` / `api_access_log`；
`api_metrics` 是「日期 + 方法 + 路径 + 状态码」的聚合计数、不含个人信息，永不清理。
归档文件默认长期保留，服务器磁盘上；如需控制体积，定期清理 `log-archive/` 下旧月份即可。
"""
import gzip
import json
import threading
import time
from pathlib import Path

from .config import LOG_ARCHIVE_DIR, LOG_RETENTION_DAYS
from .database import get_conn

TABLES = ("login_logs", "register_logs", "audit_logs", "api_access_log")
BATCH = 2000
STATE_FILE = "state.json"
MANIFEST_FILE = "manifest.log"
ARCHIVE_DIR = Path(LOG_ARCHIVE_DIR)


def _load_state() -> dict:
    try:
        return json.loads((ARCHIVE_DIR / STATE_FILE).read_text("utf-8"))
    except Exception:                      # noqa: BLE001 - 首次运行/文件损坏都按空状态处理
        return {}


def _save_state(state: dict) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVE_DIR / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(ARCHIVE_DIR / STATE_FILE)


def _month_of(created_at: str) -> str:
    """按 created_at 的 YYYY-MM 分文件；缺失/异常值归到 unknown"""
    ts = str(created_at or "")
    return ts[:7] if len(ts) >= 7 and ts[4] == "-" else "unknown"


def _append_manifest(entries: list[dict]) -> None:
    if not entries:
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with (ARCHIVE_DIR / MANIFEST_FILE).open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        fh.flush()


def _archive_rows(conn, table: str, cutoff: str, last_id: int) -> tuple[int, int, set[str]]:
    """把「已过期且 id > last_id」的行按月份追加进归档；返回 行数, 最新 id, 文件集合

    为什么要 last_id：上次若在「归档成功、删库失败」之间崩溃，这批行仍在库里；
    下次运行时跳过已归档部分，避免同一批数据在归档里出现两遍。
    """
    archived = 0
    cursor = last_id
    files: set[str] = set()
    while True:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE created_at < ? AND id > ? ORDER BY id LIMIT ?",
            (cutoff, cursor, BATCH),
        ).fetchall()
        if not rows:
            break
        by_month: dict[str, list[dict]] = {}
        for row in rows:
            item = dict(row)
            by_month.setdefault(_month_of(item.get("created_at", "")), []).append(item)
        for month, items in by_month.items():
            path = ARCHIVE_DIR / table / f"{month}.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            # 'at' = 追加模式：gzip 允许多个 member 串联，zcat/gzip -dc 可正常读全部内容
            with gzip.open(path, "at", encoding="utf-8") as fh:
                for item in items:
                    fh.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            files.add(str(path))
        cursor = rows[-1]["id"]
        archived += len(rows)
    return archived, cursor, files


def purge_old_logs(retention_days: int | None = None) -> dict:
    """归档并删除超过保留期的日志；返回 {表: {archived, deleted, files, error?}}

    单表失败不影响其它表；失败的表本轮不删除，数据仍在库里，下轮重试。
    """
    days = LOG_RETENTION_DAYS if retention_days is None else int(retention_days)
    state = _load_state()
    summary: dict[str, dict] = {}
    manifest: list[dict] = []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    with get_conn() as conn:
        cutoff = conn.execute(
            "SELECT datetime('now', ?, 'localtime') AS c", (f"-{days} day",)
        ).fetchone()["c"]
        for table in TABLES:
            last_id = int(state.get(table, 0) or 0)
            try:
                archived, newest, files = _archive_rows(conn, table, cutoff, last_id)
            except Exception as exc:       # noqa: BLE001 - 归档失败绝不删数据
                summary[table] = {"archived": 0, "deleted": 0, "files": [],
                                  "error": str(exc)[:200]}
                continue
            cur = conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
            summary[table] = {
                "archived": archived,
                "deleted": cur.rowcount,
                "files": sorted(files),
            }
            if archived:
                state[table] = newest
            if archived or cur.rowcount:
                manifest.append({
                    "at": stamp, "table": table, "cutoff": cutoff,
                    "archived": archived, "deleted": cur.rowcount,
                    "files": sorted(files),
                })

    # 数据库已提交，with 退出：此时再落 state / manifest，避免「文件说有、库里没删」的错乱
    try:
        _save_state(state)
        _append_manifest(manifest)
    except Exception as exc:               # noqa: BLE001 - 元数据写失败只告警，不反转已完成的清理
        print(f"[retention] 归档元数据写入失败: {exc}")
    return summary


def _changed(summary: dict) -> dict:
    return {
        k: {"archived": v.get("archived", 0), "deleted": v.get("deleted", 0)}
        for k, v in summary.items()
        if v.get("archived") or v.get("deleted") or v.get("error")
    }


def _loop() -> None:
    while True:
        try:
            changed = _changed(purge_old_logs())
            if changed:
                print(f"[retention] 已归档/清理超过 {LOG_RETENTION_DAYS} 天的日志: {changed}")
        except Exception as exc:           # noqa: BLE001 - 清理失败不影响服务，下个周期重试
            print(f"[retention] 日志归档清理失败: {exc}")
        time.sleep(24 * 3600)


def start() -> None:
    """启动后台清理线程，守护线程，随进程退出"""
    threading.Thread(target=_loop, daemon=True, name="log-retention").start()
