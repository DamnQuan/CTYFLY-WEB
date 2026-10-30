"""报告结算端到端回归测试，钱的最终出口

覆盖：报告提交 → ACARS 评分 → 自动核验通过 → 工资入账 → 航司余额与账本变动。

核心不变量，本文件最重要的断言：
    **航司余额的变动量 == 该公司账本的净额**
账本口径由 `airline_ledger_view` 的文档字符串定义：amount 带符号、收入为正、支出为负，
因此 `net = SUM revenue + SUM expense `；`reconciled` 字段即账实自检。
只要某个结算分支把支出记成正数，这条恒等式立刻不成立 —— 这正是 2026-10-11 发现的问题
转场调机补贴当时记成 +wage，见本文件 test_ferry_settlement_keeps_ledger_balanced。

HTTP 层用 TestClient 且**不进上下文管理器** → 不触发 lifespan，不会拉起 navdata sidecar 或定时任务。
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (add_event, make_airline, make_dispatch, make_route, make_user)


@pytest.fixture()
def caps():
    """经济参数，单报告上限 / 每日上限从模块读取，避免把平衡性数字写死在测试里"""
    from app import economy as A

    return {"per_report": A.PAYOUT_PER_REPORT_CAP, "daily": A.PAYOUT_DAILY_PER_USER_CAP}


@pytest.fixture()
def client(db):
    from app.main import app

    # 不用 with：跳过 lifespan，启动 sidecar / 定时清理都不是本测试要验的东西
    return TestClient(app)


@pytest.fixture()
def scene(conn):
    """一个可结算的最小场景：航司 + CEO 成员 + 航线 + 已落地的签派单"""
    uid = make_user(conn, cid="7001", username="settle_pilot", role="user")
    aid = make_airline(conn, owner_id=uid, balance=100000, hourly_rate=100, distance_rate=1)
    conn.execute(
        "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, 'ceo', 'active')",
        (aid, uid),
    )
    rid = make_route(conn, airline_id=aid, distance_nm=860)
    return {"conn": conn, "user_id": uid, "airline_id": aid, "route_id": rid}


def landed_dispatch(scene, *, kind="line", hours_pair=("2026-10-01 10:00:00", "2026-10-01 12:00:00"),
                    distance=860, pax=150, cargo=2000, route_id=None):
    """建一张「已完成起飞/落地」的签派单，flight_state=landed，status=open 才能被报告占用"""
    conn, aid, uid = scene["conn"], scene["airline_id"], scene["user_id"]
    d = make_dispatch(conn, airline_id=aid, kind=kind, distance_nm=distance,
                      route_id=(route_id if route_id is not None else (scene["route_id"] if kind == "line" else None)),
                      user_id=uid)
    conn.execute(
        "UPDATE dispatches SET flight_state = 'landed', pax = ?, cargo = ?, aircraft = 'A20N',"
        " flight_no = ? WHERE id = ?",
        (pax, cargo, "CT1234" if kind == "line" else "", d["id"]),
    )
    if kind == "line":
        for etype, when in (("depart", hours_pair[0]), ("arrive", hours_pair[1])):
            add_event(conn, dispatch_id=d["id"], airline_id=aid, user_id=uid,
                      event_type=etype, server_time=when)
    else:
        for etype, when in (("depart", hours_pair[0]), ("arrive", hours_pair[1])):
            add_event(conn, dispatch_id=d["id"], airline_id=aid, user_id=uid,
                      event_type=etype, server_time=when)
    return conn.execute("SELECT * FROM dispatches WHERE id = ?", (d["id"],)).fetchone()


def auth_headers(conn, user_id):
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


def submit(client, scene, dispatch, hours=2.0, route_id=None):
    body = {
        "dispatchId": dispatch["id"],
        "routeId": (route_id if route_id is not None else (scene["route_id"] if dispatch["kind"] == "line" else 0)),
        "hours": hours,
        "aircraft": "A20N",
        "flightDate": "2026-10-01",
        "notes": "回归测试",
    }
    return client.post(f"/api/airlines/{scene['airline_id']}/reports",
                       json=body, headers=auth_headers(scene["conn"], scene["user_id"]))


# ---------- 工资公式，纯函数，自动核验与人工审核共用----------

def test_report_wage_line_formula(scene):
    from app.economy import _report_wage

    conn, aid = scene["conn"], scene["airline_id"]
    # 航线 = 底薪 + 时薪×小时 + 里程×里程补贴
    assert _report_wage(conn, aid, "line", 2.0, 860, 500) == int(round(500 + 2.0 * 100 + 860 * 1))


def test_report_wage_ferry_formula(scene):
    from app.economy import _report_wage

    conn, aid = scene["conn"], scene["airline_id"]
    # 转场 = 距离 × 里程补贴 × 0.8，无底薪、无时薪
    assert _report_wage(conn, aid, "ferry", 2.0, 1000, 9999) == int(round(1000 * 1 * 0.8))


def test_report_wage_charter_formula(scene):
    from app.economy import _report_wage

    conn, aid = scene["conn"], scene["airline_id"]
    # 包机 = 时薪 × 1.2 + 里程，无底薪
    assert _report_wage(conn, aid, "charter", 3.0, 500, 9999) == int(round(3.0 * 100 * 1.2 + 500 * 1))


# ---------- 发薪前置校验，上限 / 每日额度 / 公司余额----------

def test_payout_guard_passes_within_limits(scene):
    from app.economy import _payout_guard

    wage, capped = _payout_guard(scene["conn"], scene["airline_id"], scene["user_id"], 1000)
    assert (wage, capped) == (1000, False)


def test_payout_guard_caps_single_report(scene, caps):
    from app.economy import _payout_guard

    wage, capped = _payout_guard(scene["conn"], scene["airline_id"], scene["user_id"],
                                 caps["per_report"] + 5000)
    assert wage == caps["per_report"]
    assert capped is True


def test_payout_guard_rejects_when_company_broke(scene):
    from fastapi import HTTPException

    from app.economy import _payout_guard

    scene["conn"].execute("UPDATE airlines SET balance = 0 WHERE id = ?", (scene["airline_id"],))
    with pytest.raises(HTTPException) as ei:
        _payout_guard(scene["conn"], scene["airline_id"], scene["user_id"], 1000)
    assert "余额不足" in str(ei.value.detail)


def test_payout_guard_rejects_over_daily_cap(scene, caps):
    from fastapi import HTTPException

    from app.economy import _payout_guard

    conn, uid = scene["conn"], scene["user_id"]
    conn.execute(
        "INSERT INTO wallet_records (user_id, amount, type, note) VALUES (?, ?, 'wage', '已发工资')",
        (uid, caps["daily"]),
    )
    with pytest.raises(HTTPException) as ei:
        _payout_guard(conn, scene["airline_id"], uid, 1)
    assert "每日上限" in str(ei.value.detail)


# ---------- 端到端结算，含账本恒等式----------

def test_line_flight_auto_pass_pays_wage_and_keeps_ledger_balanced(client, scene):
    conn, aid, uid = scene["conn"], scene["airline_id"], scene["user_id"]
    d = landed_dispatch(scene)
    before_balance, before_wallet = balance_of(conn, aid), wallet_of(conn, uid)

    r = submit(client, scene, d, hours=2.0)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["score"] >= 80
    assert "已发放至钱包" in payload["message"]

    from app.economy import _report_wage

    # 与业务同一套公式算期望工资：底薪取航线实际值，airline_routes.base_salary 有非 0 默认值，
    # 不能假定为 0 —— 之前按 0 算导致断言假失败 1260 vs 1060
    base_salary = conn.execute(
        "SELECT base_salary FROM airline_routes WHERE id = ?", (scene["route_id"],)
    ).fetchone()["base_salary"]
    wage = _report_wage(conn, aid, "line", 2.0, 860, base_salary)
    rep = conn.execute(
        "SELECT amount, status, verify_status FROM flight_reports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert rep["status"] == "approved"
    assert rep["verify_status"] == "auto_pass"
    assert rep["amount"] == wage

    assert wallet_of(conn, uid) - before_wallet == wage
    rec = conn.execute(
        "SELECT amount, type, report_id FROM wallet_records WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (uid,),
    ).fetchone()
    assert (rec["type"], rec["amount"]) == ("wage", wage)
    assert rec["report_id"] is not None, "工资流水必须关联报告，便于溯源"

    # ★ 账本恒等式：余额变动 == 账本净额，收入为正、支出为负的口径
    delta = balance_of(conn, aid) - before_balance
    assert ledger_net(conn, aid) == delta, "账本净额与余额变动不一致（reconciled 会显示 False）"


def test_ferry_settlement_keeps_ledger_balanced(client, scene):
    """转场：公司无收入，余额减少 = 调机补贴；账本净额必须等于该负值。

    这条断言就是 2026-10-11 抓出的问题：转场补贴当时记成 `+wage`，支出记成正数，
    导致账本净额 = +wage 而余额变动 = -wage，恒等式不成立、账实自检报 False。
    """
    conn, aid, uid = scene["conn"], scene["airline_id"], scene["user_id"]
    d = landed_dispatch(scene, kind="ferry", distance=1000)
    before_balance = balance_of(conn, aid)

    r = submit(client, scene, d, hours=2.0)
    assert r.status_code == 200, r.text
    assert r.json()["score"] >= 80

    delta = balance_of(conn, aid) - before_balance
    assert delta < 0, "转场无收入，公司余额必须减少"
    row = conn.execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id DESC LIMIT 1",
        (aid,),
    ).fetchone()
    assert row["type"] == "expense"
    assert row["amount"] < 0, "账本口径：支出必须记负数（airline_ledger_view 的 net 依赖这一点）"
    assert ledger_net(conn, aid) == delta
    assert wallet_of(conn, uid) > 0, "转场也要给飞行员发调机补贴"


def test_line_flight_revenue_and_wage_rows(client, scene):
    """航线航班：账本应为「收入一行 + 工资支出，负数一行」，两行相加等于余额变动"""
    conn, aid = scene["conn"], scene["airline_id"]
    d = landed_dispatch(scene)
    before = balance_of(conn, aid)
    assert submit(client, scene, d, hours=2.0).status_code == 200

    rows = conn.execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id", (aid,)
    ).fetchall()
    assert [r["type"] for r in rows] == ["revenue", "expense"]
    assert rows[0]["amount"] > 0 and rows[1]["amount"] < 0
    assert sum(r["amount"] for r in rows) == balance_of(conn, aid) - before


def test_low_score_report_is_auto_rejected_and_moves_no_money(client, scene):
    """评分 <60 → 自动拒绝，一分钱都不动，报告、钱包、余额、账本全不变"""
    conn, aid, uid = scene["conn"], scene["airline_id"], scene["user_id"]
    # 时间线与报告时长严重不符，2h 时间线报 10h→ 至少 -30；再叠加距离不符 → <60
    d = landed_dispatch(scene, distance=100)
    before = (balance_of(conn, aid), wallet_of(conn, uid), ledger_net(conn, aid))

    r = submit(client, scene, d, hours=10.0)
    assert r.status_code == 200, r.text
    assert r.json()["score"] < 60

    row = conn.execute("SELECT status, verify_status FROM flight_reports ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["status"], row["verify_status"]) == ("rejected", "auto_rejected")
    assert (balance_of(conn, aid), wallet_of(conn, uid), ledger_net(conn, aid)) == before


def test_dispatch_cannot_be_reported_twice(client, scene):
    """同一签派单只能提交一次报告，并发/重复提交防护：条件更新 status=open → flown"""
    d = landed_dispatch(scene)
    assert submit(client, scene, d, hours=2.0).status_code == 200
    second = submit(client, scene, d, hours=2.0)
    assert second.status_code == 409
    assert "已提交" in second.json().get("error", "") + second.json().get("detail", "")


def test_non_member_cannot_submit(client, scene):
    """非航司成员不能提交报告，403"""
    conn = scene["conn"]
    outsider = make_user(conn, cid="7002", username="outsider")
    d = landed_dispatch(scene)
    r = client.post(
        f"/api/airlines/{scene['airline_id']}/reports",
        json={"dispatchId": d["id"], "routeId": scene["route_id"], "hours": 2.0},
        headers=auth_headers(conn, outsider),
    )
    assert r.status_code == 403
