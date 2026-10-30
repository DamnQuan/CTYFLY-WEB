"""日志保留：官网只留 30 天 + 过期前先归档到服务器，logretention.py

站长要求，2026-10-18：「所有的日志要在服务器留档，官网保留 30d」。
对应实现两点，本文件逐条锁住：
1. 过期行**先写 gzip 归档、再删库**；归档文件可被 gzip/zcat 正常解压成 JSONL；
2. 归档失败时**绝不删除**，数据留在库里等下一轮重试，且重复运行不会重复归档同一批行。
"""
import gzip
import json

import pytest

from app import logretention

TABLES = logretention.TABLES


@pytest.fixture()
def archive_dir(tmp_path, monkeypatch):
    target = tmp_path / "log-archive"
    monkeypatch.setattr(logretention, "ARCHIVE_DIR", target)
    return target


def _insert(conn, table: str, created_at: str | None) -> None:
    """在各日志表插入一行；created_at 为 None 时用表默认值，当前时间"""
    rows = {
        "login_logs": {
            "old": "INSERT INTO login_logs (username, ip, created_at) VALUES ('u', '1.2.3.4', ?)",
            "new": "INSERT INTO login_logs (username, ip) VALUES ('u_new', '1.2.3.4')",
        },
        "register_logs": {
            "old": "INSERT INTO register_logs (username, ip, created_at) VALUES ('r', '1.2.3.4', ?)",
            "new": "INSERT INTO register_logs (username, ip) VALUES ('r_new', '1.2.3.4')",
        },
        "audit_logs": {
            "old": "INSERT INTO audit_logs (category, action, ip, created_at)"
                   " VALUES ('auth', 'old', '1.2.3.4', ?)",
            "new": "INSERT INTO audit_logs (category, action, ip) VALUES ('auth', 'new', '1.2.3.4')",
        },
        "api_access_log": {
            "old": "INSERT INTO api_access_log (method, path, ip, created_at)"
                   " VALUES ('GET', '/api/old', '1.2.3.4', ?)",
            "new": "INSERT INTO api_access_log (method, path, ip) VALUES ('GET', '/api/new', '1.2.3.4')",
        },
    }[table]
    if created_at is None:
        conn.execute(rows["new"])
    else:
        conn.execute(rows["old"], (created_at,))


def _expired_ts(conn, days: int) -> str:
    return conn.execute(
        "SELECT datetime('now', ?, 'localtime') AS t", (f"-{days} day",)
    ).fetchone()["t"]


def test_expired_rows_archived_then_deleted(db, archive_dir):
    with db.get_conn() as conn:
        for table in TABLES:
            _insert(conn, table, _expired_ts(conn, 40))   # 过期
            _insert(conn, table, None)                     # 未过期
        # 聚合表不含个人信息，永不清理
        conn.execute("INSERT INTO api_metrics (day, method, path, status, count)"
                     " VALUES ('2026-01-01', 'GET', '/api/x', 200, 1)")
        conn.commit()

    summary = logretention.purge_old_logs()
    with db.get_conn() as conn:
        for table in TABLES:
            assert conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 1
            assert summary[table]["archived"] == 1
            assert summary[table]["deleted"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM api_metrics").fetchone()["c"] == 1

    # 归档文件按「表 / 月份」生成，内容是可读 JSONL，保留原始字段，便于事后取证
    for table in TABLES:
        files = list((archive_dir / table).glob("*.jsonl.gz"))
        assert files, f"{table} 缺少归档文件"
        with gzip.open(files[0], "rt", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        assert len(rows) == 1
        assert "created_at" in rows[0]
        assert rows[0]["ip"] == "1.2.3.4"

    # state.json 记录高水位，manifest 记录本次归档动作
    state = json.loads((archive_dir / "state.json").read_text("utf-8"))
    assert all(state.get(t) for t in TABLES)
    manifest = (archive_dir / "manifest.log").read_text("utf-8").strip().splitlines()
    assert len(manifest) == len(TABLES)
    assert all(json.loads(m)["table"] in TABLES for m in manifest)


def test_archive_is_idempotent(db, archive_dir):
    with db.get_conn() as conn:
        _insert(conn, "api_access_log", _expired_ts(conn, 40))
        conn.commit()

    logretention.purge_old_logs()
    path = next((archive_dir / "api_access_log").glob("*.jsonl.gz"))
    first_size = path.stat().st_size

    # 第二次运行：没有新的过期行，不能把同一批数据再写一遍
    summary = logretention.purge_old_logs()
    assert summary["api_access_log"]["archived"] == 0
    assert path.stat().st_size == first_size


def test_archive_failure_keeps_rows(db, archive_dir, monkeypatch):
    with db.get_conn() as conn:
        _insert(conn, "audit_logs", _expired_ts(conn, 40))
        conn.commit()

    def boom(*_a, **_kw):
        raise OSError("磁盘只读")

    monkeypatch.setattr(logretention, "_archive_rows", boom)
    summary = logretention.purge_old_logs()

    # 归档失败 → 本轮不删除，数据仍在库里，下一轮重试
    assert summary["audit_logs"]["deleted"] == 0
    assert "磁盘只读" in summary["audit_logs"]["error"]
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM audit_logs").fetchone()["c"] == 1


def test_recent_rows_are_kept(db, archive_dir):
    with db.get_conn() as conn:
        # 29 天：仍在 30 天窗口内，不应归档/删除
        _insert(conn, "login_logs", _expired_ts(conn, 29))
        conn.commit()

    summary = logretention.purge_old_logs()
    assert summary["login_logs"]["deleted"] == 0
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM login_logs").fetchone()["c"] == 1
    assert not (archive_dir / "login_logs").exists()
