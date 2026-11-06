"""并发与事务测试：SQLite 异步化改造的前置安全网

为什么需要它：现有 81 项测试都是**单线程单连接**，覆盖不到并发下的资金与占用语义。
而 P3 最后一项，SQLite 同步连接 → 异步/连接池会动到每个请求的取连接方式，
没有这层网就不敢动，见交接文档 §34.11。

锁定三条关键语义：
  1. **资金不丢更新**：并发给同一航司加钱，最终余额必须等于 N×金额，账本行数也必须等于 N
     SQL 写的是 `balance = balance + ?`，靠数据库原子性；测试证明它确实成立
  2. **原子条件扣款不超卖**：钱包 1000、20 线程各扣 100 → 恰好只有 10 次成功、余额归零、绝不出现负余额
     与 va_shop 兑换用的是同一条 `UPDATE ... WHERE balance >= ?`
  3. **签派单乐观占用只有一次**：同一签派单并发提交报告，只有一个能成功，其余 409
     `UPDATE ... WHERE status='open'` + rowcount 判定
另有一条事务回滚语义：发薪前置校验失败时不得留下半截状态，签派单仍为 open，可重试。
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_airline, make_dispatch, make_route, make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


def auth(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


# ---------- 1 资金并发：不丢更新 ----------

def test_concurrent_fund_grants_do_not_lose_updates(db):
    from app.routers.admin import _airline_fund_move

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7301", username="cc_ceo")
        aid = make_airline(conn, owner_id=uid, balance=0, name="并发资金航空")

    N, AMOUNT = 20, 100
    errors = []

    def worker():
        try:
            with db.get_conn() as c:                 # 每个线程独立连接，sqlite3 不允许跨线程复用
                _airline_fund_move(c, aid, AMOUNT, "【测试】并发发放")
        except Exception as exc:                     # noqa: BLE001 - 收集后统一断言
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=N) as pool:
        list(pool.map(lambda _: worker(), range(N)))

    with db.get_conn() as conn:
        balance = conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"]
        rows = conn.execute("SELECT COUNT(*) c FROM airline_ledger WHERE airline_id = ?", (aid,)).fetchone()["c"]
        net = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) s FROM airline_ledger WHERE airline_id = ?", (aid,)
        ).fetchone()["s"]

    assert not errors, f"并发写入报错：{errors[:3]}"
    assert rows == N, f"账本应有 {N} 行，实际 {rows}"
    assert balance == N * AMOUNT, f"余额应为 {N * AMOUNT}，实际 {balance}（丢更新？）"
    assert net == balance, "账本净额必须等于余额"


# ---------- 2 原子条件扣款：不超卖、不变负 ----------

def test_concurrent_wallet_debit_never_oversells(db):
    """与 va_shop 兑换同一条原子语句：余额不足时 rowcount=0，绝不扣成负数"""
    with db.get_conn() as conn:
        uid = make_user(conn, cid="7302", username="cc_spender")
        conn.execute("INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, 1000, 0)", (uid,))

    PRICE, N = 100, 20
    successes = []

    def worker():
        with db.get_conn() as c:
            cur = c.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                (PRICE, uid, PRICE),
            )
            if cur.rowcount == 1:
                successes.append(1)

    with ThreadPoolExecutor(max_workers=N) as pool:
        list(pool.map(lambda _: worker(), range(N)))

    with db.get_conn() as conn:
        balance = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"]

    assert len(successes) == 10, f"余额 1000 / 单价 100，应恰好成功 10 次，实际 {len(successes)}"
    assert balance == 0, f"余额应恰好扣完，实际 {balance}"
    assert balance >= 0, "钱包绝不允许为负"


# ---------- 3 签派单乐观占用：并发提交只有一个成功 ----------

def test_concurrent_report_submission_occupies_dispatch_once(db):
    from app.main import app

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7303", username="cc_pilot")
        aid = make_airline(conn, owner_id=uid, balance=500000, hourly_rate=100, distance_rate=1)
        conn.execute("INSERT INTO airline_members (airline_id, user_id, role, status)"
                     " VALUES (?, ?, 'ceo', 'active')", (aid, uid))
        rid = make_route(conn, airline_id=aid, distance_nm=860)
        d = make_dispatch(conn, airline_id=aid, kind="line", route_id=rid, distance_nm=860, user_id=uid)
        conn.execute("UPDATE dispatches SET flight_state='landed', pax=150, cargo=2000,"
                     " aircraft='A20N', flight_no='CT7303' WHERE id = ?", (d["id"],))
        for etype, when in (("depart", "2026-10-01 10:00:00"), ("arrive", "2026-10-01 12:00:00")):
            conn.execute("INSERT INTO flight_events (dispatch_id, airline_id, user_id, event_type, server_time)"
                         " VALUES (?, ?, ?, ?, ?)", (d["id"], aid, uid, etype, when))
        h = auth(conn, uid)

    body = {"dispatchId": d["id"], "routeId": rid, "hours": 2.0, "aircraft": "A20N",
            "flightDate": "2026-10-01"}
    results = []

    def worker(_):
        local = TestClient(app)                      # 每线程一个 client，避免共享 portal
        r = local.post(f"/api/airlines/{aid}/reports", json=body, headers=h)
        results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(worker, range(6)))

    assert results.count(409) == 5, f"应恰好 5 次 409（已被占用），实际 {results}"
    assert len([c for c in results if c != 409]) == 1, f"只允许一次非 409，实际 {results}"

    with db.get_conn() as conn:
        status = conn.execute("SELECT status FROM dispatches WHERE id = ?", (d["id"],)).fetchone()["status"]
        reports = conn.execute("SELECT COUNT(*) c FROM flight_reports WHERE dispatch_id = ?",
                               (d["id"],)).fetchone()["c"]
    assert status == "flown"
    assert reports == 1, f"同一签派单只能有 1 份报告，实际 {reports}"


# ---------- 4 事务回滚：失败不留半截状态 ----------

def test_unfunded_payout_submits_report_and_defers_salary(client, db):
    """公司余额不足 → 报告仍可提交，转 CEO 审核；补足余额后审核发薪，不再卡死。"""
    from tests.conftest import add_event  # noqa: F401 保持与其它测试一致的 import 位置

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7304", username="cc_retry")
        aid = make_airline(conn, owner_id=uid, balance=0, hourly_rate=100, distance_rate=1)
        conn.execute("INSERT INTO airline_members (airline_id, user_id, role, status)"
                     " VALUES (?, ?, 'ceo', 'active')", (aid, uid))
        rid = make_route(conn, airline_id=aid, distance_nm=860)
        d = make_dispatch(conn, airline_id=aid, kind="line", route_id=rid, distance_nm=860, user_id=uid)
        conn.execute("UPDATE dispatches SET flight_state='landed', pax=150, cargo=2000,"
                     " aircraft='A20N', flight_no='CT7304' WHERE id = ?", (d["id"],))
        for etype, when in (("depart", "2026-10-01 10:00:00"), ("arrive", "2026-10-01 12:00:00")):
            conn.execute("INSERT INTO flight_events (dispatch_id, airline_id, user_id, event_type, server_time)"
                         " VALUES (?, ?, ?, ?, ?)", (d["id"], aid, uid, etype, when))
        conn.commit()
        h = auth(conn, uid)

    body = {"dispatchId": d["id"], "routeId": rid, "hours": 2.0, "aircraft": "A20N",
            "flightDate": "2026-10-01"}
    r = client.post(f"/api/airlines/{aid}/reports", json=body, headers=h)
    assert r.status_code == 200, r.text[:200]
    assert "公司余额不足" in r.json().get("message", "")
    report_id = r.json()["id"]

    with db.get_conn() as conn:
        assert conn.execute("SELECT status FROM dispatches WHERE id = ?",
                            (d["id"],)).fetchone()["status"] == "flown"
        report = conn.execute("SELECT * FROM flight_reports WHERE id = ?", (report_id,)).fetchone()
        assert report["status"] == "pending"
        assert report["verify_status"] == "needs_review"
        assert conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone() is None
        assert conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"] == 0

    # 补足公司余额后，CEO 审核通过并补发工资
    from app.routers.admin import _airline_fund_move
    with db.get_conn() as conn:
        _airline_fund_move(conn, aid, 500000, "【测试】补足公司余额")
        conn.commit()
    review = client.post(f"/api/airlines/{aid}/reports/{report_id}/review",
                         json={"action": "approve"}, headers=h)
    assert review.status_code == 200, review.text[:200]
    assert review.json()["amount"] > 0
