"""启动自检：账本不变量，2026-10-11 收尾验收时发现的真实问题

背景：验收时对测试环境做只读对账，发现 1 家航司「账本净额 8000 / 余额 6000」不一致。
追查后确认：4 行 `expense` 被存成**正数**，+200/+300 各两行，差额正好 2×1000 ——
这是修 `_airline_fund_move` 的 `abs amount ` 符号 bug **之前**留下的数据。
生产环境同时核对过：15 家航司全部对平、错符号 0 行，该 bug 未污染生产数据。

问题在于：这类脏数据此前**没有任何机制能发现** —— 界面照常显示，直到有人对账才暴露。
于是在 app 启动时加一条只读自检，`main._check_ledger_invariant`，有问题就告警。
本文件确保这道自检真的有效，并且不会因为数据异常而挡住启动。
"""

from tests.conftest import make_airline, make_user


def test_check_passes_on_healthy_data(db, capsys):
    from app.main import _check_ledger_invariant

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7601", username="ledger_ok")
        aid = make_airline(conn, owner_id=uid, balance=3000, name="对平航空")
        conn.execute("INSERT INTO airline_ledger (airline_id, amount, type, note)"
                     " VALUES (?, 3000, 'revenue', '基础金')", (aid,))

    _check_ledger_invariant()
    out = capsys.readouterr().out
    assert "对平" in out, f"健康数据应报告全部对平，实际输出：{out}"


def test_check_detects_mis_signed_rows(db, capsys):
    """把支出写成正数，正是生产上出过的 bug 形态，自检必须发现"""
    from app.main import _check_ledger_invariant

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7602", username="ledger_bad")
        aid = make_airline(conn, owner_id=uid, balance=2800, name="符号异常航空")
        conn.execute("INSERT INTO airline_ledger (airline_id, amount, type, note)"
                     " VALUES (?, 3000, 'revenue', '基础金')", (aid,))
        # 支出写成正数：账本净额会变成 3200，而余额是 2800
        conn.execute("INSERT INTO airline_ledger (airline_id, amount, type, note)"
                     " VALUES (?, 200, 'expense', '应为负数却写成正数')", (aid,))

    _check_ledger_invariant()
    out = capsys.readouterr().out
    assert "⚠️" in out and "账本不变量不成立" in out, f"未发现脏数据，实际输出：{out}"
    assert "符号异常航空" in out


def test_check_detects_mis_signed_rows_even_when_balance_matches(db, capsys):
    """即使余额被同步改坏「凑平」，错符号行也应被单独点出来"""
    from app.main import _check_ledger_invariant

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7603", username="ledger_bad2")
        aid = make_airline(conn, owner_id=uid, balance=3200, name="凑平但符号错航空")
        conn.execute("INSERT INTO airline_ledger (airline_id, amount, type, note)"
                     " VALUES (?, 3000, 'revenue', '基础金')", (aid,))
        conn.execute("INSERT INTO airline_ledger (airline_id, amount, type, note)"
                     " VALUES (?, 200, 'expense', '符号错了但总额对')", (aid,))

    _check_ledger_invariant()
    out = capsys.readouterr().out
    assert "符号异常" in out, f"未点出符号异常行，实际输出：{out}"


def test_check_never_raises_on_broken_db(db, monkeypatch, capsys):
    """自检本身出问题也绝不能挡住启动"""
    import app.database as database
    from app.main import _check_ledger_invariant

    def boom():
        raise RuntimeError("模拟取连接失败")

    monkeypatch.setattr(database, "get_conn", boom)
    _check_ledger_invariant()          # 不应抛异常
    assert "自检失败" in capsys.readouterr().out


def test_airline_fund_move_writes_signed_amount(db):
    """正本清源：资金变动接口必须写入带符号金额，支出为负—— 这是脏数据的根源"""
    from app.routers.admin import _airline_fund_move

    with db.get_conn() as conn:
        uid = make_user(conn, cid="7604", username="fund_sign")
        aid = make_airline(conn, owner_id=uid, balance=0, name="符号正确航空")
        _airline_fund_move(conn, aid, 500, "【测试】发放")
        _airline_fund_move(conn, aid, -200, "【测试】扣除")
        rows = conn.execute(
            "SELECT amount FROM airline_ledger WHERE airline_id = ? ORDER BY id", (aid,)
        ).fetchall()
        balance = conn.execute("SELECT balance FROM airlines WHERE id = ?", (aid,)).fetchone()["balance"]

    assert [r["amount"] for r in rows] == [500, -200], "支出必须写负数，不能取绝对值"
    assert balance == 300
    assert sum(r["amount"] for r in rows) == balance
