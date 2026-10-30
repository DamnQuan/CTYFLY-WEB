"""ACARS 合理性评分引擎回归测试，`_verify_flight_report`

这是经济系统的第一道闸门：分数决定「自动发工资 / 转人工复核 / 直接拒绝」。
5 个评分项 30+20+20+15+15 = 满分 100，判定：>=80 自动通过；60-79 人工复核；<60 拒绝。
这些数字一旦被改动，用户的钱就会变 —— 必须有回归测试钉住。

夹具注意：`kind='line'`，航线签派必须带真实航线，否则会额外命中「报告航线与签派航线不一致」
-20，那是夹具问题不是业务问题；转场/包机，ferry/charter 没有航线概念，自动给满。
"""
import pytest

from tests.conftest import (add_event, add_report, make_airline, make_dispatch,
                            make_route, make_user)


@pytest.fixture()
def env(conn):
    """最小可用场景：航司 + 成员 + 一条真实航线"""
    uid = make_user(conn, cid="8001", username="pilot1")
    aid = make_airline(conn, owner_id=uid)
    rid = make_route(conn, airline_id=aid, distance_nm=860)
    return {"conn": conn, "user_id": uid, "airline_id": aid, "route_id": rid}


def line_dispatch(env, **kw):
    """航线签派，默认 860nm = 430kt 巡航 2h，route_id 与 env 的航线一致"""
    kw.setdefault("route_id", env["route_id"])
    kw.setdefault("distance_nm", 860)
    return make_dispatch(env["conn"], airline_id=env["airline_id"], kind="line", **kw)


def score_of(env, dispatch, hours, route_id=None):
    from app.economy import _verify_flight_report

    if route_id is None:
        route_id = dispatch["route_id"] or 0
    return _verify_flight_report(
        env["conn"], env["airline_id"], env["user_id"], route_id, hours, dispatch
    )


def timeline(env, dispatch, dep: str, arr: str):
    for etype, when in (("depart", dep), ("arrive", arr)):
        add_event(env["conn"], dispatch_id=dispatch["id"], airline_id=env["airline_id"],
                  user_id=env["user_id"], event_type=etype, server_time=when)


# ---------- 基线 ----------

def test_perfect_line_flight_scores_100(env):
    """2 小时、860nm、时间线一致、航线一致 → 满分"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 100, reasons
    assert reasons == []


def test_score_never_negative(env):
    """极端违规下分数下限为 0"""
    d = line_dispatch(env, distance_nm=0)
    score, _ = score_of(env, d, hours=99.0, route_id=12345)
    assert score >= 0


# ---------- 逐项扣分 ----------

def test_missing_timeline_costs_30(env):
    """没有起飞/落地时间线 → 扣 30，无时间线时距离项不参与"""
    d = line_dispatch(env)
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 70, reasons
    assert any("时间线" in r for r in reasons)


def test_hours_mismatch_costs_30(env):
    """报告 5 小时、时间线实际 2 小时 → 超出 ±25% 容差，扣 30"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=5.0)
    assert score == 70, reasons
    assert any("偏差过大" in r for r in reasons)


def test_hours_within_tolerance_passes(env):
    """2.2 小时 vs 时间线 2 小时：在 ±25% 容差内，0.5h，不扣分"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.2)
    assert score == 100, reasons


def test_zero_or_negative_timeline_costs_30(env):
    """起飞与落地同刻，间隔 <= 0→ 时间线异常，扣 30"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 10:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 70, reasons
    assert any("时间线异常" in r for r in reasons)


def test_distance_implausible_costs_20(env):
    """飞了 2 小时但任务只有 100nm，典型 0.23h→ 超出 0.5x-2.0x 容差带，扣 20"""
    d = line_dispatch(env, distance_nm=100)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 80, reasons
    assert any("不匹配" in r for r in reasons)


def test_missing_distance_costs_20(env):
    """转场，无航线概念+ 任务距离缺失 → 扣 20，无法核验时长，不额外扣航线分"""
    d = make_dispatch(env["conn"], airline_id=env["airline_id"], kind="ferry", distance_nm=None)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 80, reasons
    assert any("距离数据缺失" in r for r in reasons)


def test_route_mismatch_costs_20_only_for_line(env):
    """航线签派：报告航线与签派航线不一致 → 扣 20；转场无航线概念 → 不扣"""
    other_route = make_route(env["conn"], airline_id=env["airline_id"],
                             dep="ZSPD", arr="ZBAA", distance_nm=860)
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score_mismatch, reasons = score_of(env, d, hours=2.0, route_id=other_route)
    assert score_mismatch == 80, reasons
    assert any("航线不一致" in r for r in reasons)

    ferry = make_dispatch(env["conn"], airline_id=env["airline_id"], kind="ferry", distance_nm=860)
    timeline(env, ferry, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score_ferry, reasons_ferry = score_of(env, ferry, hours=2.0, route_id=999999)
    assert score_ferry == 100, reasons_ferry


def test_early_departure_costs_15(env):
    """起飞时间早于计划起飞 15 分钟以上 → 扣 15"""
    d = line_dispatch(env, sched_dep="2026-10-01 13:00")
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 85, reasons
    assert any("早于计划" in r for r in reasons)


def test_sched_dep_within_15min_passes(env):
    """早于计划 10 分钟：在容差内，不扣分"""
    d = line_dispatch(env, sched_dep="2026-10-01 10:10")
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 100, reasons


def test_too_many_reports_costs_15(env):
    """24 小时内已有 5 份报告 → 视为刷分，扣 15"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    for _ in range(5):
        add_report(env["conn"], airline_id=env["airline_id"], user_id=env["user_id"])
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 85, reasons
    assert any("报告过多" in r for r in reasons)


def test_old_reports_do_not_count(env):
    """24 小时以前的报告不计入频率判定，边界：应为 4 份新 + 3 份旧 = 不扣分"""
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    for _ in range(4):
        add_report(env["conn"], airline_id=env["airline_id"], user_id=env["user_id"])
    for _ in range(3):
        add_report(env["conn"], airline_id=env["airline_id"], user_id=env["user_id"],
                   created_at="2026-09-01 10:00:00")
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 100, reasons


def test_other_users_reports_do_not_count(env):
    """频率判定只统计同一用户，别人刷报告不影响我"""
    other = make_user(env["conn"], cid="8002", username="pilot2")
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    for _ in range(8):
        add_report(env["conn"], airline_id=env["airline_id"], user_id=other)
    score, reasons = score_of(env, d, hours=2.0)
    assert score == 100, reasons


# ---------- 判定阈值，分数 → 走向----------

def test_serious_violation_drops_below_reject_threshold(env):
    """时长严重不符 + 航线不一致 → 低于 60，应走「自动拒绝」；否则会白送工资"""
    other_route = make_route(env["conn"], airline_id=env["airline_id"],
                             dep="ZSPD", arr="ZBAA", distance_nm=860)
    d = line_dispatch(env)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    score, reasons = score_of(env, d, hours=9.0, route_id=other_route)
    assert score < 60, (score, reasons)


def test_review_band_is_60_to_79(env):
    """缺时间线，-30+ 刷分，-15→ 55，仍落在拒绝区；再加一个 -20 就是 35。
    这里构造一个恰好落在 60-79「人工复核」带的场景：距离不符 -20 + 刷分 -15 = 65"""
    d = line_dispatch(env, distance_nm=100)
    timeline(env, d, "2026-10-01 10:00:00", "2026-10-01 12:00:00")
    for _ in range(5):
        add_report(env["conn"], airline_id=env["airline_id"], user_id=env["user_id"])
    score, reasons = score_of(env, d, hours=2.0)
    assert 60 <= score <= 79, (score, reasons)
    assert score == 65
