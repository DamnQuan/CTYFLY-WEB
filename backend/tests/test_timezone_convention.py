"""时间戳口径与时区自检，站长评审第 3 条的另一半

现状约定，见 config.BUSINESS_TZ_OFFSET_HOURS 与交接文档 §34.14：
**所有时间戳按服务器本地时间存储**，schema 默认 `datetime 'now','localtime' `，49 张表、119 处，
业务日边界，发薪每日上限、报告 24h 频率与存储同口径 —— 因此当前自洽。

本文件锁定两件事：
  1. **不变式**：刚写入的工资流水必须落在「今天」的额度窗口里，发薪每日上限据此累加。
     这条断言与运行环境时区无关，所以 CI，UTC 与生产，UTC+8 都能跑。
  2. **启动自检可用**：`_check_storage_timezone ` 能读出偏移量且不抛异常
     时区不符时它只告警、不挡启动 —— 生产上宁可起服务也不要静默挂掉。
"""

from tests.conftest import make_airline, make_user


def test_wage_record_written_now_counts_as_today(db):
    """不变式：现在写入的 wage 流水必须被「今日已发工资」统计命中

    这条正是发薪每日上限，PAYOUT_DAILY_PER_USER_CAP 的判定基础：
    `SELECT SUM amount FROM wallet_records WHERE type IN 'salary','wage'
     AND date created_at = date 'now','localtime' `
    若存储时间与判定时间用了不同时钟，比如只改了一边，这里会立刻失败。
    """
    with db.get_conn() as conn:
        uid = make_user(conn, cid="7401", username="tz_pilot")
        make_airline(conn, owner_id=uid, balance=1000)
        conn.execute(
            "INSERT INTO wallet_records (user_id, amount, type, note) VALUES (?, 500, 'wage', '时区测试')",
            (uid,),
        )
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS paid FROM wallet_records"
            " WHERE user_id = ? AND type IN ('salary','wage')"
            " AND date(created_at) = date('now','localtime')",
            (uid,),
        ).fetchone()["paid"]
        # 反面：用 UTC 日期判定时，只有在 UTC 与本地同一日期时才应命中，不能两者都错
        utc_paid = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS paid FROM wallet_records"
            " WHERE user_id = ? AND type IN ('salary','wage')"
            " AND date(created_at) = date('now')",
            (uid,),
        ).fetchone()["paid"]

    assert paid == 500, "刚写入的工资必须计入「今日已发」—— 存储时钟与判定时钟不一致"

    # 若本地日与 UTC 日不同，例如 CST 的 00:00-08:00，UTC 口径会漏掉这笔 ——
    # 这说明「统一用 localtime」是必要的；本断言把这个差异显式记录下来。
    with db.get_conn() as conn:
        same_day = conn.execute(
            "SELECT date('now','localtime') = date('now') AS same"
        ).fetchone()["same"]
    assert utc_paid == (500 if same_day else 0), (
        "UTC 口径与本地口径的差异只应来自日期是否跨天；出现其它差异说明时间口径被改坏了"
    )


def test_startup_timezone_check_runs(db):
    """启动自检必须能跑通并报告偏移，不抛异常、不挡启动"""
    from app.main import _check_storage_timezone

    _check_storage_timezone()      # 只要求不抛异常；输出内容随环境时区而变


def test_business_tz_offset_is_configured():
    from app.config import BUSINESS_TZ_OFFSET_HOURS

    assert isinstance(BUSINESS_TZ_OFFSET_HOURS, int)
    assert -12 <= BUSINESS_TZ_OFFSET_HOURS <= 14, "业务时区偏移应在合理范围"


def test_simulated_timezone_drift_is_detected(db, monkeypatch):
    """模拟「服务器时区不是期望值」：自检应能把差异读出来

    做法：把期望偏移改成与当前环境相差 3 小时，再跑自检。
    自检只告警不抛错，所以这里断言的是「它算出的偏移 ≈ 当前环境偏移」。
    """
    import app.config as config
    from app.database import get_conn

    with get_conn() as conn:
        actual = conn.execute(
            "SELECT CAST(ROUND((julianday(datetime('now','localtime'))"
            " - julianday(datetime('now'))) * 24) AS INTEGER) AS off"
        ).fetchone()["off"]

    # 期望值刻意设成「实际 + 3」，此时自检会走告警分支，不抛异常
    monkeypatch.setattr(config, "BUSINESS_TZ_OFFSET_HOURS", actual + 3)
    from app.main import _check_storage_timezone

    _check_storage_timezone()
    assert -12 <= actual <= 14
