"""第二批功能回归：航线竞标 / 成就徽章 / 二手市场 / 事故记录

重点锁死三件最容易「看起来对、其实会出事」的东西：
1. **资金原子性**：二手成交、竞标冻结/退款全部是「条件 UPDATE + rowcount 判定」，
   中途任何一步失败都必须整体回滚 —— 所以每个失败用例都断言「钱和飞机都没动」。
2. **账本不变量**：改过 airlines.balance 的每一笔都要有 airline_ledger 对应行，
   否则 main._check_ledger_invariant 会在启动时报「账实不平行」。这里对每个结束状态
   都断言 SUM ledger.amount == airlines.balance。
3. **幂等**：成就只解锁一次，奖励只发一次；竞标结算重复调用不重复退款。
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_airline, make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


def auth(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def fund(conn, airline_id, amount, note="【测试】期初资金"):
    """走后台同一套余额+账本同事务写入，保证不变量从一开始就成立"""
    from app.routers.admin import _airline_fund_move

    _airline_fund_move(conn, airline_id, amount, note)
    conn.commit()


def balance(conn, airline_id):
    return conn.execute("SELECT balance FROM airlines WHERE id = ?", (airline_id,)).fetchone()["balance"]


def ledger_net(conn, airline_id):
    return conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS v FROM airline_ledger WHERE airline_id = ?",
        (airline_id,),
    ).fetchone()["v"]


def assert_ledger_reconciled(conn, airline_id):
    assert ledger_net(conn, airline_id) == balance(conn, airline_id), "账本净额与余额不一致"


def make_ceo_airline(conn, *, cid, username, icao, balance=0):
    """CEO 用户 + 已通过航司 + active 成员关系，CEO 才允许挂牌/竞标/买入"""
    uid = make_user(conn, cid=cid, username=username)
    aid = make_airline(conn, owner_id=uid, balance=0, icao=icao)
    conn.execute(
        "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, 'ceo', 'active')",
        (aid, uid),
    )
    conn.commit()
    if balance:
        fund(conn, aid, balance)
    return uid, aid


def seed_plane(conn, airline_id, *, aircraft="A20N", reg="B-TEST"):
    cur = conn.execute(
        "INSERT INTO airline_fleet (airline_id, aircraft, reg, status, location)"
        " VALUES (?, ?, ?, 'available', 'ZSPD')",
        (airline_id, aircraft, reg),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- 二手市场

def test_market_buy_moves_money_plane_and_ledger(client, conn):
    seller_uid, seller_aid = make_ceo_airline(
        conn, cid="8101", username="mk_seller", icao="T801", balance=0)
    buyer_uid, buyer_aid = make_ceo_airline(
        conn, cid="8102", username="mk_buyer", icao="T802", balance=100000)
    fleet_id = seed_plane(conn, seller_aid, reg="B-8001")

    resp = client.post("/api/market/list", headers=auth(conn, seller_uid),
                       json={"airlineId": seller_aid, "fleetId": fleet_id, "price": 60000,
                             "conditionPct": 85, "description": "测试挂牌"})
    assert resp.status_code == 200, resp.text
    listing_id = resp.json()["id"]

    resp = client.post(f"/api/market/{listing_id}/buy", headers=auth(conn, buyer_uid),
                       json={"airlineId": buyer_aid})
    assert resp.status_code == 200, resp.text
    assert resp.json()["fee"] == 3000            # 5% 手续费

    # 钱：买家 -60000，卖家 +57000，扣 5% 手续费
    assert balance(conn, buyer_aid) == 40000
    assert balance(conn, seller_aid) == 57000
    # 飞机：所有权转移且可用
    f = conn.execute("SELECT * FROM airline_fleet WHERE id = ?", (fleet_id,)).fetchone()
    assert f["airline_id"] == buyer_aid
    assert f["status"] == "available"
    # 挂牌已售 + 成交流水
    m = conn.execute("SELECT * FROM market_listings WHERE id = ?", (listing_id,)).fetchone()
    assert m["status"] == "sold" and m["buyer_airline_id"] == buyer_aid and m["sold_price"] == 60000
    trade = conn.execute("SELECT * FROM market_trades WHERE listing_id = ?", (listing_id,)).fetchone()
    assert trade["price"] == 60000 and trade["fee"] == 3000 and trade["seller_received"] == 57000
    # 账本不变量：双方都对平
    assert_ledger_reconciled(conn, buyer_aid)
    assert_ledger_reconciled(conn, seller_aid)


def test_market_buy_insufficient_balance_rolls_back_everything(client, conn):
    seller_uid, seller_aid = make_ceo_airline(
        conn, cid="8111", username="mk_seller2", icao="T811", balance=0)
    buyer_uid, buyer_aid = make_ceo_airline(
        conn, cid="8112", username="mk_buyer2", icao="T812", balance=1000)
    fleet_id = seed_plane(conn, seller_aid, reg="B-8011")

    listing_id = client.post("/api/market/list", headers=auth(conn, seller_uid),
                             json={"airlineId": seller_aid, "fleetId": fleet_id,
                                   "price": 60000}).json()["id"]

    resp = client.post(f"/api/market/{listing_id}/buy", headers=auth(conn, buyer_uid),
                       json={"airlineId": buyer_aid})
    assert resp.status_code == 400
    assert "余额不足" in resp.json()["error"]

    # 关键：失败后挂牌必须回到 listed，事务回滚，钱和飞机都没动
    m = conn.execute("SELECT status FROM market_listings WHERE id = ?", (listing_id,)).fetchone()
    assert m["status"] == "listed"
    assert balance(conn, buyer_aid) == 1000
    assert balance(conn, seller_aid) == 0
    f = conn.execute("SELECT airline_id FROM airline_fleet WHERE id = ?", (fleet_id,)).fetchone()
    assert f["airline_id"] == seller_aid
    assert_ledger_reconciled(conn, buyer_aid)
    assert_ledger_reconciled(conn, seller_aid)


def test_market_second_buy_is_rejected(client, conn):
    seller_uid, seller_aid = make_ceo_airline(
        conn, cid="8121", username="mk_seller3", icao="T821", balance=0)
    buyer_uid, buyer_aid = make_ceo_airline(
        conn, cid="8122", username="mk_buyer3", icao="T822", balance=200000)
    fleet_id = seed_plane(conn, seller_aid, reg="B-8021")
    listing_id = client.post("/api/market/list", headers=auth(conn, seller_uid),
                             json={"airlineId": seller_aid, "fleetId": fleet_id,
                                   "price": 60000}).json()["id"]

    first = client.post(f"/api/market/{listing_id}/buy", headers=auth(conn, buyer_uid),
                        json={"airlineId": buyer_aid})
    assert first.status_code == 200
    bal_after_first = balance(conn, buyer_aid)

    second = client.post(f"/api/market/{listing_id}/buy", headers=auth(conn, buyer_uid),
                         json={"airlineId": buyer_aid})
    assert second.status_code == 400
    # 第二次尝试不能重复扣款
    assert balance(conn, buyer_aid) == bal_after_first
    assert_ledger_reconciled(conn, buyer_aid)


def test_market_cannot_buy_own_plane(client, conn):
    uid, aid = make_ceo_airline(conn, cid="8131", username="mk_solo", icao="T831", balance=100000)
    fleet_id = seed_plane(conn, aid, reg="B-8031")
    listing_id = client.post("/api/market/list", headers=auth(conn, uid),
                             json={"airlineId": aid, "fleetId": fleet_id,
                                   "price": 60000}).json()["id"]
    resp = client.post(f"/api/market/{listing_id}/buy", headers=auth(conn, uid),
                       json={"airlineId": aid})
    assert resp.status_code == 400
    assert "自己的飞机" in resp.json()["error"]


def test_market_list_rejects_price_out_of_range(client, conn):
    uid, aid = make_ceo_airline(conn, cid="8141", username="mk_price", icao="T841", balance=0)
    fleet_id = seed_plane(conn, aid, reg="B-8041")
    # A20N 目录价 600000：下限 60000，上限 900000 → 1 游戏币必须被拒
    resp = client.post("/api/market/list", headers=auth(conn, uid),
                       json={"airlineId": aid, "fleetId": fleet_id, "price": 1})
    assert resp.status_code == 400
    assert "挂牌价" in resp.json()["error"]


# ---------------------------------------------------------------- 航线竞标

def make_tender(conn, *, dep="ZSPD", arr="RJAA", start=50000, step=5000, closes_in="+1 hour"):
    cur = conn.execute(
        "INSERT INTO bid_tenders (dep, arr, flight_no, distance_nm, start_price, min_step, closes_at)"
        " VALUES (?, ?, ?, 1000, ?, ?, datetime('now','localtime', ?))",
        (dep, arr, f"{dep}{arr}", start, step, closes_in),
    )
    conn.commit()
    return cur.lastrowid


def test_bidding_freeze_and_settle_refunds_losers(client, conn):
    uid1, aid1 = make_ceo_airline(conn, cid="8201", username="bid_a", icao="T851", balance=200000)
    uid2, aid2 = make_ceo_airline(conn, cid="8202", username="bid_b", icao="T852", balance=200000)
    tender = make_tender(conn)

    r1 = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid1),
                     json={"airlineId": aid1, "amount": 60000})
    assert r1.status_code == 200, r1.text
    # 冻结：余额立刻减少
    assert balance(conn, aid1) == 140000

    r2 = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid2),
                     json={"airlineId": aid2, "amount": 90000})
    assert r2.status_code == 200, r2.text
    assert balance(conn, aid2) == 110000

    # 出价必须高于当前最高 + 最小加价
    low = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid1),
                      json={"airlineId": aid1, "amount": 91000})
    assert low.status_code == 400
    assert "至少需要" in low.json()["error"]

    # 把截止时间拨到过去，再结算，幂等接口可重复调用
    conn.execute("UPDATE bid_tenders SET closes_at = datetime('now','localtime','-1 minute')"
                 " WHERE id = ?", (tender,))
    conn.commit()
    resp = client.post("/api/bids/settle", headers=auth(conn, uid1))
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1

    # 中标方，金额最高的冻结款不退；未中标方全额退回
    assert balance(conn, aid2) == 110000            # 中标 90000 已花掉
    assert balance(conn, aid1) == 200000            # 60000 退回
    offers = {
        r["airline_id"]: r["status"]
        for r in conn.execute("SELECT * FROM bid_offers WHERE tender_id = ?", (tender,))
    }
    assert offers[aid2] == "won"
    assert offers[aid1] == "refunded"
    t = conn.execute("SELECT * FROM bid_tenders WHERE id = ?", (tender,)).fetchone()
    assert t["status"] == "settled" and t["winner_airline_id"] == aid2 and t["settle_price"] == 90000
    # 中标航线入网
    route = conn.execute(
        "SELECT * FROM airline_routes WHERE airline_id = ? AND dep = ? AND arr = ?",
        (aid2, "ZSPD", "RJAA"),
    ).fetchone()
    assert route is not None
    # 账本对平，冻结=支出、退款=收入
    assert_ledger_reconciled(conn, aid1)
    assert_ledger_reconciled(conn, aid2)

    # 重复结算：不能重复退款
    again = client.post("/api/bids/settle", headers=auth(conn, uid1))
    assert again.status_code == 200
    assert again.json()["count"] == 0
    assert balance(conn, aid1) == 200000


def test_bidding_rebid_refunds_previous_offer(client, conn):
    uid, aid = make_ceo_airline(conn, cid="8211", username="bid_re", icao="T861", balance=200000)
    tender = make_tender(conn)
    first = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid),
                        json={"airlineId": aid, "amount": 60000})
    assert first.status_code == 200
    assert balance(conn, aid) == 140000

    second = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid),
                         json={"airlineId": aid, "amount": 80000})
    assert second.status_code == 200, second.text
    # 旧冻结退回、新冻结扣掉，净效果 = 只冻结 80000
    assert balance(conn, aid) == 120000
    active = conn.execute(
        "SELECT COUNT(*) AS c FROM bid_offers WHERE tender_id = ? AND airline_id = ?"
        " AND status = 'active'", (tender, aid)).fetchone()["c"]
    assert active == 1
    assert_ledger_reconciled(conn, aid)


def test_bidding_withdraw_refunds(client, conn):
    uid, aid = make_ceo_airline(conn, cid="8221", username="bid_wd", icao="T871", balance=100000)
    tender = make_tender(conn)
    offer_id = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid),
                           json={"airlineId": aid, "amount": 50000}).json()["id"]
    assert balance(conn, aid) == 50000
    resp = client.post(f"/api/bids/offers/{offer_id}/withdraw", headers=auth(conn, uid))
    assert resp.status_code == 200, resp.text
    assert balance(conn, aid) == 100000
    assert_ledger_reconciled(conn, aid)


def test_bidding_insufficient_balance_is_rejected(client, conn):
    uid, aid = make_ceo_airline(conn, cid="8231", username="bid_poor", icao="T881", balance=1000)
    tender = make_tender(conn, start=50000)
    resp = client.post(f"/api/bids/tenders/{tender}/offers", headers=auth(conn, uid),
                       json={"airlineId": aid, "amount": 60000})
    assert resp.status_code == 400
    assert "余额不足" in resp.json()["error"]
    assert balance(conn, aid) == 1000
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM bid_offers WHERE tender_id = ?", (tender,)
    ).fetchone()["c"] == 0
    assert_ledger_reconciled(conn, aid)


# ---------------------------------------------------------------- 成就徽章

def test_achievement_unlock_is_idempotent(conn):
    from app.routers.achievements import check_achievements

    uid = make_user(conn, cid="8301", username="ach_pilot")
    aid = make_airline(conn, owner_id=uid, balance=0, icao="T891")
    conn.execute(
        "INSERT INTO flight_reports (airline_id, user_id, hours, status) VALUES (?, ?, 2.0, 'approved')",
        (aid, uid),
    )
    conn.commit()

    first = check_achievements(uid, "flight_approved")
    assert any(a["code"] == "first_flight" for a in first)

    second = check_achievements(uid, "flight_approved")
    assert second == []                     # 已解锁的不再重复返回

    w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    assert w["balance"] == 1000             # 奖励只发一次
    paid = conn.execute(
        "SELECT COUNT(*) AS c FROM wallet_records WHERE user_id = ? AND type = 'achievement'",
        (uid,),
    ).fetchone()["c"]
    assert paid == 1


def test_achievement_unknown_event_is_noop(conn):
    from app.routers.achievements import check_achievements

    uid = make_user(conn, cid="8302", username="ach_none")
    assert check_achievements(uid, "") == []
    assert check_achievements(uid, "not_a_real_event") == []


# ---------------------------------------------------------------- 事故记录

def test_incident_records_request_trace(client, conn):
    uid = make_user(conn, cid="8401", username="inc_pilot")
    resp = client.post("/api/incidents", headers=auth(conn, uid),
                       json={"summary": "起飞滑跑偏出跑道边缘", "severity": "serious",
                             "phase": "起飞", "flightNo": "CTY900", "dep": "ZSPD", "arr": "RJAA"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reportNo"].startswith("INC-")

    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (body["id"],)).fetchone()
    assert row["severity"] == "serious"
    assert row["status"] == "open"
    # 溯源字段：IP/UA/UA 分类/进程号 全部落库，requestinfo 口径
    assert row["ip"]
    assert row["ua"]
    assert row["ua_label"]
    assert row["pid"] > 0


def test_incident_detail_only_visible_to_owner_or_staff(client, conn):
    owner = make_user(conn, cid="8411", username="inc_owner")
    other = make_user(conn, cid="8412", username="inc_other")
    iid = client.post("/api/incidents", headers=auth(conn, owner),
                      json={"summary": "落地重着陆，结构疑似受损", "severity": "accident"}).json()["id"]

    ok = client.get(f"/api/incidents/{iid}", headers=auth(conn, owner))
    assert ok.status_code == 200
    denied = client.get(f"/api/incidents/{iid}", headers=auth(conn, other))
    assert denied.status_code == 403


def test_incident_severity_validated(client, conn):
    uid = make_user(conn, cid="8421", username="inc_bad")
    resp = client.post("/api/incidents", headers=auth(conn, uid),
                       json={"summary": "随便写点什么内容", "severity": "not-a-level"})
    assert resp.status_code == 400


# ---------------------------------------------------------------- 列表接口烟测

def test_batch2_read_endpoints_return_200(client, conn):
    uid = make_user(conn, cid="8501", username="b2_reader")
    for path in ("/api/market", "/api/market/my", "/api/bids/tenders",
                 "/api/achievements", "/api/incidents"):
        resp = client.get(path, headers=auth(conn, uid))
        assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"
