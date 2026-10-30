"""经济核心：ACARS 评分、工资公式、发薪上限、结算参数，2026-10-11 从 routers/airlines.py 抽出

为什么单独成模块：这些是**纯逻辑 + 常量**，不依赖 FastAPI 路由，却是整个经济系统的判定核心
评分决定自动发工资 / 人工复核 / 拒绝；工资公式与上限决定发多少钱。
抽出来之后：airlines.py 只负责编排路由，经济规则可以单独测试与演进。

测试：tests/test_acars_score.py，19 项、test_report_settlement.py，15 项、
test_money_paths.py，11 项—— 抽取前后都必须全绿。
"""
from datetime import datetime, timedelta

from fastapi import HTTPException

def _verify_flight_report(conn, airline_id: int, user_id: int, route_id: int, hours: float,
                          dispatch: dict) -> tuple[int, list[str]]:
    """平台 ACARS 合理性评分引擎，v1，满分 100，kind-aware。

    返回 score, 失分原因列表。分数决定报告走向：
      >=80 自动通过发放工资；60-79 转 CEO 人工复核；<60 自动拒绝。
    时间线容差设计依据：RFS 无法取数，节点为人工上报，必须留出合理误差空间。
    转场/包机没有航线概念，「航线一致」项自动给满，距离用创建时存档的大圆距离。
    """
    reasons: list[str] = []
    score = 100
    kind = dispatch["kind"] if "kind" in dispatch.keys() else "line"

    ev = conn.execute(
        "SELECT event_type, server_time FROM flight_events"
        " WHERE dispatch_id = ? ORDER BY id",
        (dispatch["id"],),
    ).fetchall()
    dep_ev = next((e for e in ev if e["event_type"] == "depart"), None)
    arr_ev = next((e for e in ev if e["event_type"] == "arrive"), None)

    # 1 报告时长 vs 时间线实际间隔，30 分：±25% 或 15 分钟内视为一致
    elapsed_h = 0.0
    if not dep_ev or not arr_ev:
        score -= 30
        reasons.append("缺少完整的起飞/落地时间线")
    else:
        t0 = datetime.strptime(dep_ev["server_time"], "%Y-%m-%d %H:%M:%S")
        t1 = datetime.strptime(arr_ev["server_time"], "%Y-%m-%d %H:%M:%S")
        elapsed_h = (t1 - t0).total_seconds() / 3600
        tol = max(0.25, 0.25 * elapsed_h)
        if elapsed_h <= 0:
            score -= 30
            reasons.append("时间线异常：起飞与落地间隔过短或时间顺序错误")
        elif abs(hours - elapsed_h) > tol:
            score -= 30
            reasons.append(
                f"报告时长 {hours:.2f}h 与时间线间隔 {elapsed_h:.2f}h 偏差过大，允许 ±{tol:.2f}h"
            )

    # 2 时间线间隔 vs 任务距离，20 分：按 430kt 巡航典型速度，0.5x-2.0x 容差带
    r0 = conn.execute(
        "SELECT distance_nm FROM airline_routes WHERE id = ?", (dispatch["route_id"],)
    ).fetchone() if dispatch["route_id"] else None
    distance = (dispatch["distance_nm"] if "distance_nm" in dispatch.keys() and dispatch["distance_nm"] else 0) \
        or ((r0["distance_nm"] if r0 else 0) or 0)
    if distance and elapsed_h > 0:
        expected_h = distance / 430.0
        if not (0.5 * expected_h <= elapsed_h <= 2.0 * expected_h):
            score -= 20
            reasons.append(
                f"飞行 {elapsed_h:.2f}h 与任务距离 {distance:.0f}nm 的典型用时 {expected_h:.2f}h 不匹配"
            )
    elif elapsed_h > 0:
        score -= 20
        reasons.append("任务距离数据缺失，无法核验飞行时长")

    # 3 报告航线与签派航线一致，20 分—— 仅航线签派；转场/包机无航线概念，自动给满
    if kind == "line":
        if route_id != dispatch["route_id"]:
            score -= 20
            reasons.append("报告航线与签派单航线不一致")

    # 4 起飞时间不早于计划，15 分：早于计划 15 分钟以上视为异常；未填计划时间放行
    if dep_ev:
        t0 = datetime.strptime(dep_ev["server_time"], "%Y-%m-%d %H:%M:%S")
        sched = (dispatch["sched_dep"] or "").strip()
        ok = True
        if sched:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
                try:
                    sd = datetime.strptime(sched, fmt)
                    if t0 < sd - timedelta(minutes=15):
                        ok = False
                    break
                except ValueError:
                    continue
        if t0 > datetime.now() + timedelta(minutes=5):
            ok = False
        if not ok:
            score -= 15
            reasons.append("起飞上报时间早于计划起飞，或晚于当前时间")

    # 5 提交频率，15 分：同用户 24 小时内 >5 份报告视为刷分，覆盖转场/包机
    recent = conn.execute(
        "SELECT COUNT(*) c FROM flight_reports"
        " WHERE user_id = ? AND created_at >= datetime('now','localtime','-1 day')",
        (user_id,),
    ).fetchone()
    if recent and recent["c"] >= 5:
        score -= 15
        reasons.append("24 小时内报告过多，进入人工核验")

    return max(0, score), reasons
# ---------- 经济上限，防刷钱天花板 ----------
# 单份报告工资硬上限：时薪上限 2000 ×24h×补贴叠加仍可能铸出天价工资，
# 再乘以每小时 30 份的报告限额等于无限刷钱。对自动核验与 CEO 人工审批，含自审
# 一视同仁：超出部分不发并在返回消息中提示。需要调整游戏平衡时改这个常量即可。
PAYOUT_PER_REPORT_CAP = 20000

# 每成员每日发薪总额上限，按服务器 localtime 的自然日计：
# 发薪前统计当日已发工资总和，钱包流水 salary/wage 口径，超限拒绝入账并提示次日再试。
PAYOUT_DAILY_PER_USER_CAP = 200000


def _report_wage(conn, airline_id: int, kind: str, hours: float, distance: int,
                 base_salary: int) -> int:
    """工资公式，自动核验与 CEO 人工审批共用一套口径：
    航线 = 底薪 + 飞行时薪 + 里程津贴；转场 = 距离 × 里程补贴 × 0.8，调机补贴；
    包机 = 时薪 × 1.2，自由任务溢价+ 里程。"""
    airline = conn.execute(
        "SELECT hourly_rate, distance_rate FROM airlines WHERE id = ?", (airline_id,)
    ).fetchone()
    if kind == "ferry":
        return int(round(distance * airline["distance_rate"] * 0.8))
    if kind == "charter":
        return int(round(hours * airline["hourly_rate"] * 1.2 + distance * airline["distance_rate"]))
    return int(round(base_salary + hours * airline["hourly_rate"] + distance * airline["distance_rate"]))


def _payout_guard(conn, airline_id: int, user_id: int, wage: int) -> tuple[int, bool]:
    """发薪前置校验，自动核验与 CEO 人工审批共用：
    1 单报告硬上限封顶，超额部分不发；
    2 每成员每日发薪总额上限，超限拒绝入账并提示次日再试；
    3 公司余额必须足以支付工资。
    返回 封顶后的工资, 是否触发封顶；任一检查不过直接 raise，事务回滚不入账。
    """
    capped = False
    if wage > PAYOUT_PER_REPORT_CAP:
        wage = PAYOUT_PER_REPORT_CAP
        capped = True
    paid_today = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS paid FROM wallet_records"
        " WHERE user_id = ? AND type IN ('salary','wage')"
        " AND date(created_at) = date('now','localtime')",
        (user_id,),
    ).fetchone()["paid"]
    if paid_today + wage > PAYOUT_DAILY_PER_USER_CAP:
        raise HTTPException(
            400,
            f"该飞行员今日已发放工资 {paid_today}，达到每日上限 {PAYOUT_DAILY_PER_USER_CAP}，请次日再试",
        )
    a = conn.execute("SELECT balance FROM airlines WHERE id = ?", (airline_id,)).fetchone()
    if not a or (a["balance"] or 0) < wage:
        raise HTTPException(400, "公司余额不足，无法发放工资")
    return wage, capped
# ---------- 现实化经济结算 ----------
# 现实中飞行员拿固定工资，底薪+飞行时薪+里程津贴，公司挣客票+货运收入再付工资和成本。
# 公司票款收入 = 实载旅客 × 航程 nm × 每客每海里票款率 + 货载 kg × 航程 × 每公斤每海里货运费率；
# 无签派旅客数据时按典型客座率估算，无签派货载数据时不计货运，保守。
#
# 数据来源与游戏化说明，这两处是全套数据里刻意偏离现实的值，不是疏漏：
# · REVENUE_PER_PAX_NM：真实国内客运收益率约 ¥0.93/客公里 ≈ $0.126/客海里，民航局统计口径
# 的客公里收入水平。按机队价格锚，1 单位 ≈ $184 折算应为 0.0007 单位/客海里，
# 那样一架飞机需约 8,800 班才回本，现实正确、游戏不可玩。此处放大为 0.6，
#   使 A320 一班净收约 5 万、购机约 12 班回本——游戏节奏可接受。
# · CARGO_RATE_PER_KG_NM：现实国内货运约 ¥2/kg，千余公里航段，约为客运摊平后每公斤
# 收益，¥6.4/kg 的 31%；按客运相同的 775× 游戏化倍率折算即 0.002 单位/kg 海里。
# · DEFAULT_LOAD_FACTOR：参照中国民航全行业客座率，近年常态约 80%-83%取整 0.8。
REVENUE_PER_PAX_NM = 0.6
CARGO_RATE_PER_KG_NM = 0.002
DEFAULT_LOAD_FACTOR = 0.8

