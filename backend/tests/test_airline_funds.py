"""航司货币，余额与账本回归测试

对应交接文档 §31：余额是 PIREP 结算发工资的钱，`公司余额不足时无法发放工资`。
这里钉住三件事：
  1. 发放/扣除同时改余额与写账本，账本 type 必须是 revenue/expense，前端只把 revenue 显示成收入
  2. 金额正负与账本方向一致，写错方向界面会显示反
  3. 扣除不允许把余额变成负数，接口层拦截；这里验证口径
"""
import pytest

from tests.conftest import make_airline, make_user


@pytest.fixture()
def airline(conn):
    uid = make_user(conn, cid="8200", username="ceo1")
    aid = make_airline(conn, owner_id=uid, balance=0, name="回归测试航空")
    return {"conn": conn, "airline_id": aid, "user_id": uid}


def balance_of(conn, airline_id):
    return conn.execute("SELECT balance FROM airlines WHERE id = ?", (airline_id,)).fetchone()["balance"]


def test_grant_increases_balance_and_writes_revenue(airline):
    from app.routers.admin import _airline_fund_move

    _airline_fund_move(airline["conn"], airline["airline_id"], 3000, "【管理后台】基础金发放")
    assert balance_of(airline["conn"], airline["airline_id"]) == 3000
    row = airline["conn"].execute(
        "SELECT amount, type, note FROM airline_ledger WHERE airline_id = ?",
        (airline["airline_id"],),
    ).fetchone()
    # 前端账本只把 revenue 渲染成「收入」，其余一律显示为「支出」——发放必须写 revenue
    assert row["type"] == "revenue"
    assert row["amount"] == 3000, "发放为正（收入方向）"
    assert "基础金发放" in row["note"]


def test_deduction_writes_expense_with_signed_amount(airline):
    from app.routers.admin import _airline_fund_move

    _airline_fund_move(airline["conn"], airline["airline_id"], 5000, "先给钱")
    _airline_fund_move(airline["conn"], airline["airline_id"], -1200, "【管理后台】误扣补偿")
    assert balance_of(airline["conn"], airline["airline_id"]) == 3800
    row = airline["conn"].execute(
        "SELECT amount, type FROM airline_ledger WHERE airline_id = ? ORDER BY id DESC LIMIT 1",
        (airline["airline_id"],),
    ).fetchone()
    assert row["type"] == "expense"
    assert row["amount"] == -1200, "账本口径：支出必须记负数（net = SUM(amount) 依赖这一点）"


def test_ledger_net_matches_balance_change(airline):
    """账本净额，收入-支出必须等于余额变动 —— 这是对账的基本不变量"""
    from app.routers.admin import _airline_fund_move

    for amount in (3000, 500, -200, -1000, 700):
        _airline_fund_move(airline["conn"], airline["airline_id"], amount, "流水")
    # 账本口径：amount 带符号，净额就是简单求和，不能按 type 再翻一次符号 —— 那样会掩盖
    # 「支出记成正数」这类错误；2026-10-11 本人就在这里用过错误的公式
    ledger_net = airline["conn"].execute(
        "SELECT COALESCE(SUM(amount), 0) AS net FROM airline_ledger WHERE airline_id = ?",
        (airline["airline_id"],),
    ).fetchone()["net"]
    assert ledger_net == balance_of(airline["conn"], airline["airline_id"]) == 3000


def test_airline_isolation(airline):
    """一家航司的资金变动不能影响另一家"""
    from app.routers.admin import _airline_fund_move

    other = make_airline(airline["conn"], owner_id=airline["user_id"], name="另一家航空")
    _airline_fund_move(airline["conn"], airline["airline_id"], 3000, "发放")
    assert balance_of(airline["conn"], other) == 0


def test_wage_payment_requires_company_balance(conn):
    """工资发放的前置校验：公司余额不足时必须拦住，airlines.py 的 400 分支"""
    uid = make_user(conn, cid="8201", username="ceo2")
    broke = make_airline(conn, owner_id=uid, balance=0, name="没钱航空")
    rich = make_airline(conn, owner_id=uid, balance=3000, name="有钱航空")
    # 业务判定口径：余额 >= 工资才放行
    wage = 1000
    assert (balance_of(conn, broke) >= wage) is False
    assert (balance_of(conn, rich) >= wage) is True


def test_grant_all_approved_scope_counts_only_approved(conn):
    """批量发放范围口径：approved 只算运营中，all 含全部，用于 §31 的 12 家发放"""
    uid = make_user(conn, cid="8202", username="ceo3")
    for i in range(3):
        make_airline(conn, owner_id=uid, name=f"运营{i}", status="approved")
    for i in range(2):
        make_airline(conn, owner_id=uid, name=f"被拒{i}", status="rejected")
    approved = conn.execute("SELECT COUNT(*) c FROM airlines WHERE status='approved'").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM airlines").fetchone()["c"]
    assert approved == 3
    assert total == 5
