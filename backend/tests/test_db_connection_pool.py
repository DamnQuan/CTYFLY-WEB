"""连接池语义测试，2026-10-11，P3 最后一项

`database.get_conn ` 从「每请求新建 + 关闭」改成「线程本地复用」。复用带来性能收益，
但也引入三个必须钉死的风险，本文件逐个验证：

  1. **不串库**：测试会 monkeypatch `DB_PATH`。若复用旧路径的连接，用例之间会互相污染
     读到上一个用例的数据，且极难排查。
  2. **嵌套不共用**：同一线程内嵌套 `with get_conn ` 必须拿到不同连接 ——
     否则内层的 commit/rollback 会替外层结束事务，出现「外层还没写完就被提交」或
     「内层异常把外层的写入一起回滚」。
  3. **事务语义不变**：成功 commit、异常 rollback，与改造前一致。

另外用一条不变式证明「复用确实发生了」：同一线程连续两次 get_conn 拿到的是同一条连接。
"""
import sqlite3
import threading

import pytest

from tests.conftest import make_airline, make_user


def test_connection_is_reused_within_thread(db):
    """同一线程连续取连接应是同一条，复用生效"""
    with db.get_conn() as c1:
        first = id(c1)
    with db.get_conn() as c2:
        second = id(c2)
    assert first == second, "连接没有被复用 —— 池没生效（或每请求仍在新建）"


def test_commit_persists_and_rollback_discards(db):
    """事务语义：正常退出 commit、抛异常 rollback"""
    with db.get_conn() as conn:
        uid = make_user(conn, cid="7501", username="pool_ok")

    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM users WHERE id = ?", (uid,)).fetchone()["c"] == 1

    with pytest.raises(RuntimeError):
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET username = 'changed' WHERE id = ?", (uid,))
            raise RuntimeError("模拟业务异常")

    with db.get_conn() as conn:
        assert conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()["username"] == "pool_ok", \
            "异常路径必须回滚，改动不得落库"


def test_nested_get_conn_uses_separate_connection(db):
    """嵌套调用必须拿到不同连接，且内层异常不得回滚外层的写入"""
    with db.get_conn() as outer:
        uid = make_user(outer, cid="7502", username="pool_outer")

        with db.get_conn() as inner:
            assert inner is not outer, "嵌套时共用了连接 —— 内层提交/回滚会破坏外层事务"

        # 内层异常：外层之前的写入仍应保留，因为外层还没提交，随外层一起提交
        try:
            with db.get_conn() as inner2:
                inner2.execute("UPDATE users SET username = 'inner' WHERE id = ?", (uid,))
                raise RuntimeError("内层失败")
        except RuntimeError:
            pass

    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM users WHERE id = ?", (uid,)).fetchone()["c"] == 1
        assert conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()["username"] == "pool_outer", \
            "内层失败不应影响外层；外层正常提交后应是外层的值"


def test_db_path_change_does_not_leak_between_connections(db, tmp_path, monkeypatch):
    """换 DB_PATH 必须拿到新连接，否则测试之间会串库"""
    with db.get_conn() as conn:
        make_user(conn, cid="7503", username="in_first_db")
        first_id = id(conn)

    second_path = tmp_path / "another.db"
    monkeypatch.setattr(db, "DB_PATH", second_path, raising=True)
    db.init_db()

    with db.get_conn() as conn2:
        assert id(conn2) != first_id, "换了库却复用了旧连接 —— 会串库"
        # 新库应为空，只有种子管理员，看不到上一个库的用户
        assert conn2.execute("SELECT COUNT(*) c FROM users WHERE username = 'in_first_db'").fetchone()["c"] == 0


def test_pool_is_per_thread(db):
    """不同线程各自持有连接，sqlite3 连接不能跨线程使用"""
    ids = {}

    def worker(name):
        with db.get_conn() as c:
            ids[name] = id(c)
            c.execute("SELECT 1")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t1.join()
    t2.start(); t2.join()

    assert set(ids) == {"a", "b"}
    assert ids["a"] != ids["b"], "不同线程拿到了同一条连接 —— 违反 sqlite3 的线程归属"


def test_residual_transaction_is_cleaned_before_reuse(db):
    """手工制造「上次用完留下未结束事务」，复用前应被清理干净"""
    with db.get_conn() as conn:
        uid = make_user(conn, cid="7504", username="pool_residual")
        aid = make_airline(conn, owner_id=uid, balance=0, name="残留事务航空")

    # 绕过 get_conn 的提交，直接在同一线程的连接上开一个写事务然后丢弃
    pool_conn = db._pool()[str(db.DB_PATH)]
    pool_conn.execute("UPDATE airlines SET balance = 999 WHERE id = ?", (aid,))
    assert pool_conn.in_transaction, "构造失败：应当处于未提交状态"

    with db.get_conn() as conn:
        # 复用前会 rollback，因此读到的是 0 而不是 999
        bal = conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"]
    assert bal == 0, "复用前未清理残留事务，脏数据会被带进下一个请求"


def test_foreign_keys_pragma_survives_reuse(db):
    """连接复用后 PRAGMA foreign_keys 仍为开启状态，否则外键约束会静默失效"""
    with db.get_conn() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with db.get_conn() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "复用后外键约束丢了"

    with pytest.raises(sqlite3.IntegrityError):
        with db.get_conn() as conn:
            conn.execute("INSERT INTO airline_members (airline_id, user_id, role, status)"
                         " VALUES (999999, 999999, 'pilot', 'active')")
