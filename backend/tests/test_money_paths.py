"""经济系统其余「钱出口」的回归测试：CEO 人工审核发薪 + 航司商城扣款/退款

为什么单独一个文件：`airline_ledger` 的口径是「amount 带符号，收入为正、支出为负」，
且 `net = SUM amount ` 应恒等于 `airlines.balance`。2026-10-11 已在报告结算与后台发放
两处发现符号写反，一个写 +wage 当支出、一个写 abs amount，因此把**每一条动钱的路径**
都用同一条不变量钉住 —— 之后重构 airlines.py 才有安全网。

覆盖：
  · CEO 人工审核 approve → 发工资，航线 / 转场两种公式
  · CEO 人工审核 reject → 一分钱不动
  · 非管理者审核 → 403
  · 航司商城购买：钱包扣款、公司入账、账本收入行
  · 钱包余额不足 → 400，原子条件扣款
  · 商城订单取消退款：钱包退回、公司扣回、账本支出记为负数
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (make_airline, make_dispatch, make_route, make_user)


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)   # 不进上下文管理器 → 不触发 lifespan，不拉 sidecar / 定时任务


@pytest.fixture()
def scene(conn):
    """航司 + CEO + 一名普通成员，用于商城购买

    初始资金**走账本发放**，而不是直接写 balance—— 生产里航司就是从 0 起、钱都从账本进，
    这样「账本净额 == 余额」才是可断言的绝对不变量，直接写 balance 会让账本缺一笔期初。
    """
    from app.routers.admin import _airline_fund_move

    ceo = make_user(conn, cid="7101", username="money_ceo")
    member = make_user(conn, cid="7102", username="money_member")
    aid = make_airline(conn, owner_id=ceo, balance=0, hourly_rate=100, distance_rate=1)
    _airline_fund_move(conn, aid, 100000, "【测试】航司期初资金")
    conn.execute(
        "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, 'ceo', 'active')",
        (aid, ceo),
    )
    conn.execute(
        "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, 'pilot', 'active')",
        (aid, member),
    )
    conn.execute("INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, 10000, 0)", (member,))
    rid = make_route(conn, airline_id=aid, distance_nm=860)
    conn.commit()
    return {"conn": conn, "ceo": ceo, "member": member, "airline_id": aid, "route_id": rid}


# ---------- 工具 ----------

def headers(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def balance_of(conn, airline_id):
    return conn.execute("SELECT balance FROM airlines WHERE id = ?", (airline_id,)).fetchone()["balance"]


def ledger_net(conn, airline_id):
    return conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM airline_ledger WHERE airline_id = ?",
        (airline_id,),
    ).fetchone()["s"]


def wallet_of(conn, user_id):
    w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    return w["balance"] if w else 0


def make_item(conn, airline_id, *, name="测试商品", price=300, stock=-1, created_by=0) -> int:
    cur = conn.execute(
        "INSERT INTO airline_shop_items (airline_id, name, description, price, stock, created_by)"
        " VALUES (?, ?, '', ?, ?, ?)",
        (airline_id, name, price, stock, created_by),
    )
    conn.commit()
    return cur.lastrowid


def make_pending_report(conn, scene, *, kind="line", distance=860, hours=2.0,
                        base_salary=200) -> int:
    """造一份「待人工审核」的报告，含真实签派单，因为审核要读 dispatch 判定 kind"""
    aid = scene["airline_id"]
    d = make_dispatch(conn, airline_id=aid, kind=kind, distance_nm=distance,
                      route_id=(scene["route_id"] if kind == "line" else None),
                      user_id=scene["member"])
    conn.execute(
        "UPDATE dispatches SET flight_state='landed', status='flown', pax=150, cargo=2000,"
        " aircraft='A20N', flight_no='CT9001' WHERE id = ?", (d["id"],),
    )
    cur = conn.execute(
        "INSERT INTO flight_reports (airline_id, user_id, route_id, dep, arr, flight_no, aircraft,"
        " hours, flight_date, base_salary, distance_nm, dispatch_id, verify_score, verify_status,"
        " status)"
        " VALUES (?, ?, ?, 'ZBAA', 'ZSPD', 'CT9001', 'A20N', ?, '2026-10-01', ?, ?, ?, 65,"
        " 'needs_review', 'pending')",
        (aid, scene["member"], scene["route_id"] if kind == "line" else None, hours,
         base_salary, distance, d["id"]),
    )
    conn.commit()
    return cur.lastrowid


def approve(client, scene, report_id):
    return client.post(
        f"/api/airlines/{scene['airline_id']}/reports/{report_id}/review",
        json={"action": "approve", "reason": "回归测试"},
        headers=headers(scene["conn"], scene["ceo"]),
    )


# ---------- CEO 人工审核发薪 ----------

def test_review_approve_line_pays_wage_and_keeps_invariant(client, scene):
    from app.economy import _report_wage

    conn, aid = scene["conn"], scene["airline_id"]
    rid = make_pending_report(conn, scene)
    before_wallet = wallet_of(conn, scene["member"])

    r = approve(client, scene, rid)
    assert r.status_code == 200, r.text

    bs = conn.execute("SELECT base_salary FROM airline_routes WHERE id = ?", (scene["route_id"],)).fetchone()["base_salary"]
    wage = _report_wage(conn, aid, "line", 2.0, 860, bs)
    # 成就系统，2026-10-18 第二批在报告审核通过后会结算「首飞纪念」并发奖励，
    # 所以钱包增量 = 工资 + 首飞奖励。显式算出来，避免以后把成就奖励误判成「多发了工资」。
    reward = conn.execute(
        "SELECT reward FROM achievement_defs WHERE code = 'first_flight'"
    ).fetchone()["reward"]
    assert wallet_of(conn, scene["member"]) - before_wallet == wage + reward, "审核通过必须发工资进钱包"
    rep = conn.execute("SELECT status, amount FROM flight_reports WHERE id = ?", (rid,)).fetchone()
    assert rep["status"] == "approved"
    assert rep["amount"] == wage
    # ★ 账本恒等式
    assert ledger_net(conn, aid) == balance_of(conn, aid)   # 期初走账本 → 绝对不变量


def test_review_approve_ferry_keeps_invariant(client, scene):
    """转场：公司只有支出，调机补贴，账本必须记负数 —— 这里曾写反"""
    conn, aid = scene["conn"], scene["airline_id"]
    rid = make_pending_report(conn, scene, kind="ferry", distance=1000)
    before = balance_of(conn, aid)

    assert approve(client, scene, rid).status_code == 200
    delta = balance_of(conn, aid) - before
    assert delta < 0
    row = conn.execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id DESC LIMIT 1", (aid,)
    ).fetchone()
    assert row["type"] == "expense"
    assert row["amount"] < 0, "支出必须记负数"
    assert ledger_net(conn, aid) == balance_of(conn, aid)


def test_review_reject_moves_no_money(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    rid = make_pending_report(conn, scene)
    before = (balance_of(conn, aid), wallet_of(conn, scene["member"]), ledger_net(conn, aid))

    r = client.post(
        f"/api/airlines/{aid}/reports/{rid}/review",
        json={"action": "reject", "reason": "测试驳回"},
        headers=headers(conn, scene["ceo"]),
    )
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT status FROM flight_reports WHERE id = ?", (rid,)).fetchone()["status"] == "rejected"
    assert (balance_of(conn, aid), wallet_of(conn, scene["member"]), ledger_net(conn, aid)) == before


def test_review_requires_manager(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    rid = make_pending_report(conn, scene)
    r = client.post(
        f"/api/airlines/{aid}/reports/{rid}/review",
        json={"action": "approve"},
        headers=headers(conn, scene["member"]),      # 普通成员不是管理者
    )
    assert r.status_code == 403


def test_review_does_not_exceed_company_balance(client, scene):
    """公司余额不足时审核不能造出负余额，发薪前置校验"""
    conn, aid = scene["conn"], scene["airline_id"]
    rid = make_pending_report(conn, scene)
    conn.execute("UPDATE airlines SET balance = 0 WHERE id = ?", (aid,))
    conn.commit()
    r = approve(client, scene, rid)
    assert r.status_code == 400
    assert "余额不足" in (r.json().get("error") or r.json().get("detail") or "")


# ---------- 航司商城：购买 ----------

def test_shop_buy_moves_money_and_keeps_invariant(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, name="涂装包", price=300, created_by=scene["ceo"])
    before_airline, before_wallet = balance_of(conn, aid), wallet_of(conn, scene["member"])

    r = client.post(f"/api/airlines/{aid}/shop/buy/{item}",
                    headers=headers(conn, scene["member"]))
    assert r.status_code == 200, r.text

    assert wallet_of(conn, scene["member"]) - before_wallet == -300, "会员钱包应扣款"
    assert balance_of(conn, aid) - before_airline == 300, "公司应收到货款"
    assert ledger_net(conn, aid) == balance_of(conn, aid)
    rec = conn.execute(
        "SELECT amount, type FROM wallet_records WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (scene["member"],),
    ).fetchone()
    assert (rec["type"], rec["amount"]) == ("purchase", -300)
    row = conn.execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id DESC LIMIT 1", (aid,)
    ).fetchone()
    assert (row["type"], row["amount"]) == ("revenue", 300)


def test_shop_buy_rejected_when_wallet_insufficient(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, price=999999, created_by=scene["ceo"])   # 远超钱包 10000
    before = (balance_of(conn, aid), wallet_of(conn, scene["member"]), ledger_net(conn, aid))
    r = client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=headers(conn, scene["member"]))
    assert r.status_code == 400
    assert (balance_of(conn, aid), wallet_of(conn, scene["member"]), ledger_net(conn, aid)) == before


def test_shop_buy_twice_rejected(client, scene):
    """同一商品限购一件，唯一约束兜底"""
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, price=100, created_by=scene["ceo"])
    h = headers(conn, scene["member"])
    assert client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=h).status_code == 200
    second = client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=h)
    assert second.status_code == 400


# ---------- 航司商城：取消退款 ----------

def test_shop_cancel_refunds_and_keeps_invariant(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, price=300, created_by=scene["ceo"])
    h = headers(conn, scene["member"])
    assert client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=h).status_code == 200

    order = conn.execute(
        "SELECT id FROM airline_shop_orders WHERE airline_id = ? ORDER BY id DESC LIMIT 1", (aid,)
    ).fetchone()["id"]
    before_airline, before_wallet = balance_of(conn, aid), wallet_of(conn, scene["member"])

    r = client.post(
        f"/api/airlines/{aid}/shop/orders/{order}/handle",
        json={"action": "cancel"},
        headers=headers(conn, scene["ceo"]),
    )
    assert r.status_code == 200, r.text

    assert wallet_of(conn, scene["member"]) - before_wallet == 300, "退款应回到钱包"
    assert balance_of(conn, aid) - before_airline == -300, "公司应扣回货款"
    # 期初资金走账本，所以这里可以直接断言绝对不变量
    assert ledger_net(conn, aid) == balance_of(conn, aid)
    row = conn.execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id DESC LIMIT 1", (aid,)
    ).fetchone()
    assert row["type"] == "expense"
    assert row["amount"] == -300, "退款支出必须记负数"


def test_shop_cancel_twice_rejected(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, price=100, created_by=scene["ceo"])
    h = headers(conn, scene["member"])
    client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=h)
    order = conn.execute(
        "SELECT id FROM airline_shop_orders WHERE airline_id = ? ORDER BY id DESC LIMIT 1", (aid,)
    ).fetchone()["id"]
    body = {"action": "cancel"}
    assert client.post(f"/api/airlines/{aid}/shop/orders/{order}/handle",
                       json=body, headers=headers(conn, scene["ceo"])).status_code == 200
    second = client.post(f"/api/airlines/{aid}/shop/orders/{order}/handle",
                         json=body, headers=headers(conn, scene["ceo"]))
    assert second.status_code == 400


def test_shop_buy_only_members_of_that_airline(client, scene):
    """别家航司的会员不能在本航司商城下单"""
    conn, aid = scene["conn"], scene["airline_id"]
    item = make_item(conn, aid, price=100, created_by=scene["ceo"])
    outsider = make_user(conn, cid="7103", username="outsider2")
    conn.execute("INSERT INTO wallets (user_id, balance) VALUES (?, 10000)", (outsider,))
    conn.commit()
    r = client.post(f"/api/airlines/{aid}/shop/buy/{item}", headers=headers(conn, outsider))
    assert r.status_code in (400, 403)
