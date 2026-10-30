"""航司端点级烟测：让每个端点的**处理函数真的跑起来**

为什么需要它，2026-10-11 的教训：抽取 economy.py 时误把航司域常量 POSITION_OPTIONS 一起搬走，
**69 项测试全绿也没发现** —— 因为缺名字只在请求时才触发，导入期不报错，是 ruff 的 F821 抓出来的。
所以除了「纯函数测试」和「lint」，还需要一层**端点级执行**的网：只要 handler 跑过一遍，
这类 NameError / 属性拼错 / 提前 return 的坑就会当场暴露。

本文件覆盖 P3 接下来要拆的两块，报告与薪酬、签派与机队，作为重构的安全网：
  · 报告与薪酬：reports / stats / payroll-export / ledger / members position & review
  · 签派与机队：fleet / fleet purchase / routes / dispatches +events / ferry / charter
断言原则：读接口要求 200；写接口要求「不是 5xx」，业务性 4xx 可接受。
"""
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_airline, make_route, make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def scene(conn):
    """航司 + CEO + 成员 + 一条航线 + 两架可用飞机 + CEO 有钱包余额"""
    from app.routers.admin import _airline_fund_move
    from app.routers.airlines import _seed_fleet

    ceo = make_user(conn, cid="7201", username="smoke_ceo")
    member = make_user(conn, cid="7202", username="smoke_member")
    aid = make_airline(conn, owner_id=ceo, balance=0, hourly_rate=100, distance_rate=1)
    _airline_fund_move(conn, aid, 200000, "【测试】航司期初资金")
    for uid, role in ((ceo, "ceo"), (member, "pilot")):
        conn.execute(
            "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, ?, 'active')",
            (aid, uid, role),
        )
    conn.execute("INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, 500000, 0)", (ceo,))
    conn.execute("INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, 10000, 0)", (member,))
    rid = make_route(conn, airline_id=aid, distance_nm=860)
    _seed_fleet(conn, aid, aircraft="A20N", count=2)
    conn.commit()
    return {"conn": conn, "ceo": ceo, "member": member, "airline_id": aid, "route_id": rid}


def auth(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def fleet_row(conn, aid, *, available=True):
    return conn.execute(
        "SELECT * FROM airline_fleet WHERE airline_id = ?"
        + (" AND status = 'available'" if available else "")
        + " ORDER BY id LIMIT 1",
        (aid,),
    ).fetchone()


# ---------- 读取类端点：必须 200 ----------

def test_read_endpoints_return_200(client, scene):
    conn, aid, ceo = scene["conn"], scene["airline_id"], scene["ceo"]
    h = auth(conn, ceo)
    for path in ("/fleet", "/routes", "/dispatches", "/reports", "/stats",
                 "/payroll/export", "/ledger", "/posts", "/exams"):
        r = client.get(f"/api/airlines/{aid}{path}", headers=h)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:160]}"


def test_fleet_list_contains_seeded_aircraft(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.get(f"/api/airlines/{aid}/fleet", headers=auth(conn, scene["ceo"]))
    assert r.status_code == 200
    fleet = r.json()["fleet"]
    assert len(fleet) == 2 and all(f["aircraft"] == "A20N" for f in fleet)


def test_airline_detail_exposes_position_options(client, scene):
    """出事那个接口：GET /{id} 会返回 POSITION_OPTIONS —— 常量缺失时这里就是 500"""
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.get(f"/api/airlines/{aid}", headers=auth(conn, scene["ceo"]))
    assert r.status_code == 200, r.text[:200]
    assert r.json()["positionOptions"], "职位选项必须由 airlines 模块提供"


def test_wallet_endpoint(client, scene):
    conn, ceo = scene["conn"], scene["ceo"]
    r = client.get("/api/wallet", headers=auth(conn, ceo))
    assert r.status_code == 200
    # 注意返回结构是 {"ok":true,"wallet":{...}}，不是扁平字段
    assert r.json()["wallet"]["balance"] == 500000


# ---------- 成员职位 / 审核，覆盖 KPI 常量所在路径----------

def membership_id(conn, aid, user_id):
    """职位/审核类端点的 {member_id} 是 airline_members.id，不是用户 id，踩过"""
    return conn.execute(
        "SELECT id FROM airline_members WHERE airline_id = ? AND user_id = ?", (aid, user_id)
    ).fetchone()["id"]


def test_member_position_accepts_valid_option(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.put(f"/api/airlines/{aid}/members/{membership_id(conn, aid, scene['member'])}/position",
                   json={"position": "机长"}, headers=auth(conn, scene["ceo"]))
    assert r.status_code == 200, r.text[:200]
    got = conn.execute("SELECT position FROM airline_members WHERE airline_id = ? AND user_id = ?",
                       (aid, scene["member"])).fetchone()["position"]
    assert got == "机长"


def test_member_position_rejects_unknown_value(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.put(f"/api/airlines/{aid}/members/{membership_id(conn, aid, scene['member'])}/position",
                   json={"position": "不存在"}, headers=auth(conn, scene["ceo"]))
    assert r.status_code == 400


# ---------- 签派 / 机队，写接口：要求不是 5xx----------

def test_dispatch_lifecycle(client, scene):
    """建签派 → 列表可见 → 上报起飞 → 删除"""
    conn, aid, ceo = scene["conn"], scene["airline_id"], scene["ceo"]
    h = auth(conn, ceo)
    f = fleet_row(conn, aid)

    r = client.post(f"/api/airlines/{aid}/dispatches",
                    json={"routeId": scene["route_id"], "fleetId": f["id"], "captain": "SMOKE",
                          "callsign": "CT9001", "pax": 150, "cargo": 2000},
                    headers=h)
    assert r.status_code < 500, r.text[:300]
    if r.status_code != 200:
        pytest.skip(f"建签派未成功（业务性拒绝 {r.status_code}）：{r.text[:120]}")
    did = r.json()["id"]

    lst = client.get(f"/api/airlines/{aid}/dispatches", headers=h)
    assert lst.status_code == 200
    assert any(d["id"] == did for d in lst.json()["dispatches"])

    token = conn.execute("SELECT flight_token FROM dispatches WHERE id = ?", (did,)).fetchone()["flight_token"]
    ev = client.post(f"/api/airlines/{aid}/dispatches/{did}/events",
                     json={"type": "depart", "token": token}, headers=h)
    assert ev.status_code < 500, ev.text[:300]

    dele = client.delete(f"/api/airlines/{aid}/dispatches/{did}", headers=h)
    assert dele.status_code < 500, dele.text[:300]


def test_ferry_creation(client, scene):
    """转场任务：需要一个可用机位 + 目标机场"""
    conn, aid, ceo = scene["conn"], scene["airline_id"], scene["ceo"]
    f = fleet_row(conn, aid)
    r = client.post(
        f"/api/airlines/{aid}/fleet/{f['id']}/ferry",
        json={"frm": f["location"] or "ZBAA", "to": "ZSPD"},
        headers=auth(conn, ceo),
    )
    assert r.status_code < 500, r.text[:300]


def test_charter_creation(client, scene):
    conn, aid, ceo = scene["conn"], scene["airline_id"], scene["ceo"]
    f = fleet_row(conn, aid)
    r = client.post(f"/api/airlines/{aid}/charters",
                    json={"dep": "ZBAA", "arr": "ZSPD", "fleetId": f["id"], "pax": 100, "cargo": 0},
                    headers=auth(conn, ceo))
    assert r.status_code < 500, r.text[:300]


def test_fleet_purchase_uses_ceo_wallet_and_keeps_ledger_invariant(client, scene):
    """CEO 用个人钱包购置飞机：钱包减少，且不破坏「账本净额 == 航司余额」"""
    conn, aid, ceo = scene["conn"], scene["airline_id"], scene["ceo"]
    before_wallet = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (ceo,)).fetchone()["balance"]
    before_balance = conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"]

    r = client.post(f"/api/airlines/{aid}/fleet/purchase", json={"aircraft": "A20N"},
                    headers=auth(conn, ceo))
    assert r.status_code < 500, r.text[:300]

    after_wallet = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (ceo,)).fetchone()["balance"]
    after_balance = conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"]
    ledger_net = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) s FROM airline_ledger WHERE airline_id = ?", (aid,)
    ).fetchone()["s"]
    assert ledger_net == after_balance, "账本恒等式（期初走账本 → 绝对不变量）"
    if r.status_code == 200:
        assert after_wallet < before_wallet, "购置应扣 CEO 个人钱包"
        assert before_balance == after_balance, "购置飞机不动公司余额"


# ---------- 薪酬报表 ----------

def test_payroll_export_is_csv(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.get(f"/api/airlines/{aid}/payroll/export", headers=auth(conn, scene["ceo"]))
    assert r.status_code == 200
    assert "csv" in r.headers.get("content-type", "").lower() or r.text.lstrip().startswith(("飞行", "CID", "cid"))


def test_ledger_view_reports_reconciled(client, scene):
    conn, aid = scene["conn"], scene["airline_id"]
    r = client.get(f"/api/airlines/{aid}/ledger", headers=auth(conn, scene["ceo"]))
    assert r.status_code == 200
    data = r.json()
    assert data["reconciled"] is True, f"账实自检应为 True：{json.dumps(data)[:200]}"
