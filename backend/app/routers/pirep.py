"""虚拟航司 · 飞行报告与薪酬 API，2026-10-11 从 routers/airlines.py 抽出，P3 第二刀

包含：报告提交，ACARS 自动核验 → 自动发薪/转人工/拒绝、报告列表、CEO 人工审核发薪、
薪酬 CSV 导出。经济规则本身在 app/economy.py；本模块只负责编排与鉴权。

沿用 /api/airlines 前缀，同前缀多 router 在仓库里已有先例，由 main.py 注册。
辅助函数，_require_manager / _report_row / _airline_or_404 / _audit 暂由 airlines 模块提供，
后续可进一步下沉到共享模块 —— 目前 airlines 不反向引用本模块，不存在循环导入。

导入清单由脚本静态分析这 4 个函数的实际引用生成，不是靠肉眼猜，
缺漏再由 ruff 的 F821 兜底 —— 上次误搬 POSITION_OPTIONS 正是 F821 抓出来的。
"""
import csv

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth
from ..economy import (CARGO_RATE_PER_KG_NM, DEFAULT_LOAD_FACTOR, PAYOUT_PER_REPORT_CAP,
                       REVENUE_PER_PAX_NM, _payout_guard, _report_wage, _verify_flight_report)
from ..mailer import notify_user
from ..ratelimit import enforce
from ..text import clean, csv_safe
from .airlines import (FLEET_CATALOG, ReportBody, ReviewReportBody, _airline_or_404, _audit,
                       _report_row, _require_manager)

router = APIRouter(prefix="/api/airlines", tags=["airlines"])


@router.post("/{airline_id}/reports")
def submit_report(airline_id: int, body: ReportBody, request: Request,
                        user: dict = Depends(require_auth)):
    enforce(request, "pirep", 30, 3600)
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可提交飞行报告")

        # 平台 ACARS v1：报告必须关联自己的签派单，且时间线已走到「落地」
        if not body.dispatchId:
            raise HTTPException(400, "请关联签派单后提交报告，先在签派单页完成起飞/落地上报")
        d = conn.execute(
            "SELECT * FROM dispatches WHERE id = ? AND airline_id = ?",
            (body.dispatchId, airline_id),
        ).fetchone()
        if not d:
            raise HTTPException(400, "关联的签派单不存在")
        if d["user_id"] != user["id"]:
            raise HTTPException(403, "只能关联自己的签派单")
        if d["flight_state"] != "landed":
            raise HTTPException(400, "请先在签派单页完成「起飞」与「落地」上报，再提交飞行报告")

        kind = d["kind"] if "kind" in d.keys() else "line"
        r = None
        if kind == "line":
            r = conn.execute(
                "SELECT * FROM airline_routes WHERE id = ? AND airline_id = ?", (body.routeId, airline_id)
            ).fetchone()
            if not r:
                raise HTTPException(400, "请选择本航司的航线")
            if body.routeId != d["route_id"]:
                raise HTTPException(400, "报告航线与签派单航线不一致，请核对")
        elif kind == "charter":
            # 包机：无航线概念，传了航线直接拒绝，防借包机名义乱飞
            if body.routeId:
                raise HTTPException(400, "包机任务无关联航线，请清空航线选择后提交")
        elif kind == "ferry":
            # 转场：同样无航线概念，与包机口径对齐
            if body.routeId:
                raise HTTPException(400, "转场飞行无需选择航线")

        # 合理性评分：>=80 自动通过；60-79 转 CEO 复核；<60 自动拒绝
        score, reasons = _verify_flight_report(conn, airline_id, user["id"], body.routeId, body.hours, d)
        verify_status = "auto_pass" if score >= 80 else ("needs_review" if score >= 60 else "auto_rejected")

        distance = (d["distance_nm"] if "distance_nm" in d.keys() and d["distance_nm"] else 0) or (r["distance_nm"] if r else 0)
        base_salary = r["base_salary"] if r else 0
        flight_no = d["flight_no"] or ("FERRY" if kind == "ferry" else "CHTR")

        # 自动核验通过时先做发薪前置校验，上限/每日额度/公司余额。
        # 公司余额不足不再拦死提交：报告照常入库并转 CEO 审核，待公司补足余额后发薪。
        wage = 0
        wage_capped = False
        wage_deferred = False
        if verify_status == "auto_pass":
            computed_wage = _report_wage(
                conn, airline_id, kind, body.hours, distance, base_salary,
            )
            try:
                wage, wage_capped = _payout_guard(conn, airline_id, user["id"], computed_wage)
            except HTTPException as exc:
                if "公司余额不足" not in str(exc.detail):
                    raise
                wage = min(computed_wage, PAYOUT_PER_REPORT_CAP)
                wage_capped = computed_wage > PAYOUT_PER_REPORT_CAP
                wage_deferred = True
                verify_status = "needs_review"
                reasons.append("公司余额不足，报告已提交并转 CEO 审核，公司补足余额后发薪")

        # 并发双报告防护：签派单占用改为条件更新，仅 open 状态可被置为 flown；
        # 报告插入与结算全部放在占用成功之后
        cur_d = conn.execute(
            "UPDATE dispatches SET status = 'flown', flown_at = datetime('now','localtime')"
            " WHERE id = ? AND status = 'open'",
            (d["id"],),
        )
        if cur_d.rowcount == 0:
            raise HTTPException(409, "该签派单已提交报告")

        cur = conn.execute(
            "INSERT INTO flight_reports (airline_id, user_id, route_id, dep, arr, flight_no,"
            " aircraft, hours, flight_date, base_salary, notes, distance_nm, dispatch_id,"
            " verify_score, verify_status, verify_detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (airline_id, user["id"], r["id"] if r else None, d["dep"], d["arr"], flight_no,
             clean(body.aircraft, 16).upper() or d["aircraft"], round(body.hours, 2),
             clean(body.flightDate, 10), base_salary, clean(body.notes, 200), distance,
             d["id"], score, verify_status, "；".join(reasons)),
        )
        report_id = cur.lastrowid
        # 报告关联签派 → 飞机归队并落在任务目的地机场
        if d["fleet_id"]:
            conn.execute(
                "UPDATE airline_fleet SET status = 'available', location = ?"
                " WHERE id = ? AND status = 'dispatched'",
                (d["arr"], d["fleet_id"]),
            )

        if verify_status == "auto_pass":
            # 自动核验通过：直接结算，工资已在签派占用前经 _payout_guard 封顶与校验。
            # 工资公式按任务类型区分：航线=底薪+时薪+里程；转场=里程×0.8，调机补贴；
            # 包机=时薪×1.2，自由任务溢价+里程。转场为公司成本，无收入，包机有 1.5× 溢价收入。
            pax = d["pax"] or 0
            cargo = d["cargo"] or 0
            if kind == "line" and pax <= 0:
                spec = FLEET_CATALOG.get(r["aircraft"], {})
                pax = int(round(spec.get("pax", 0) * DEFAULT_LOAD_FACTOR))
            if kind == "ferry":
                revenue = 0
            elif kind == "charter":
                revenue = int(round(pax * distance * REVENUE_PER_PAX_NM * 1.5)) \
                    + int(round(cargo * distance * CARGO_RATE_PER_KG_NM * 1.5))
            else:
                revenue = int(round(pax * distance * REVENUE_PER_PAX_NM)) + int(round(cargo * distance * CARGO_RATE_PER_KG_NM))
            label = {"ferry": "转场调机", "charter": "包机"}.get(kind, "航班")
            conn.execute(
                "UPDATE flight_reports SET status = 'approved', amount = ?, verify_status = 'auto_pass',"
                " reviewed_by = NULL, reviewed_at = datetime('now','localtime') WHERE id = ?",
                (wage, report_id),
            )
            w = conn.execute("SELECT user_id FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
            if w:
                conn.execute(
                    "UPDATE wallets SET balance = balance + ?, total_hours = total_hours + ? WHERE user_id = ?",
                    (wage, body.hours, user["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, ?, ?)",
                    (user["id"], wage, body.hours),
                )
            conn.execute(
                "INSERT INTO wallet_records (user_id, amount, type, note, report_id)"
                " VALUES (?, ?, 'wage', ?, ?)",
                (user["id"], wage, f"{label}工资，ACARS 自动核验 {score} 分", report_id),
            )
            # 公司余额与 CEO 人工审批口径对齐：净额，收入-工资进公司账上
            conn.execute(
                "UPDATE airlines SET balance = balance + ? WHERE id = ?",
                (revenue - wage, airline_id),
            )
            if kind == "ferry":
                # 转场无收入：调机补贴计为公司支出，账本一行
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'expense', ?, ?)",
                    (airline_id, -wage, f"{d['dep']}→{d['arr']} 调机补贴，自动核验", report_id),
                )
            else:
                # 账本统一口径：收入一行 + 负支出一行，不记净额，与 CEO 人工审批一致
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'revenue', ?, ?)",
                    (airline_id, revenue,
                     f"{flight_no} {'包机' if kind == 'charter' else '航班'}收入，{pax} 客 + {cargo}kg 货", report_id),
                )
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'expense', ?, ?)",
                    (airline_id, -wage, f"{flight_no} 飞行员工资 {body.hours}h，自动核验", report_id),
                )
            return {
                "ok": True, "id": report_id, "score": score,
                "message": f"自动核验通过，{score} 分，工资 {wage} 已发放至钱包"
                           + ("已达单份报告工资上限，超额部分未发放" if wage_capped else ""),
            }

        if verify_status == "auto_rejected":
            conn.execute(
                "UPDATE flight_reports SET status = 'rejected', reject_reason = ? WHERE id = ?",
                ("自动核验未通过，" + "；".join(reasons) + "）", report_id),
            )
            log_event("report", "auto_reject", actor=user["id"],
                      target_type="flight_report", target_id=report_id,
                      detail=f"score={score} reasons={'；'.join(reasons)[:150]}")
            return {
                "ok": False, "id": report_id, "score": score,
                "message": "自动核验未通过：" + "；".join(reasons) + "。如有疑问请联系航司 CEO 申诉。",
            }

        return {
            "ok": True, "id": report_id, "score": score,
            "message": (
                "公司余额不足，报告已提交，等待 CEO 审核；公司补足余额后发放工资"
                if wage_deferred else
                f"报告已提交，核验 {score} 分，等待 CEO 审核"
            ),
        }

@router.get("/{airline_id}/reports")
def list_reports(airline_id: int, scope: str = "mine", user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        # 报告列表：CEO 与部长可看全航司，scope=all，成员仅看自己的
        is_manager = bool(m) and m["status"] == "active" and (
            m["role"] == "ceo" or bool(m["minister"])
        )

        where, args = "airline_id = ?", [airline_id]
        if not (is_manager and scope == "all"):
            where += " AND user_id = ?"
            args.append(user["id"])

        reports = conn.execute(
            f"SELECT r.*, u.username, u.cid, u.avatar_url FROM flight_reports r"
            f" JOIN users u ON u.id = r.user_id WHERE {where} ORDER BY r.id DESC LIMIT 200",
            args,
        ).fetchall()
    return {"ok": True, "reports": [dict(r) for r in reports]}

@router.post("/{airline_id}/reports/{report_id}/review")
def review_report(airline_id: int, report_id: int, body: ReviewReportBody, request: Request,
                        user: dict = Depends(require_auth)):
    # 成就钩子用：记下本次通过审核的飞行员，事务提交后再结算成就
    approved_uid = 0
    result: dict = {}
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        r = _report_row(conn, report_id, airline_id)

        if body.action == "approve":
            distance = r["distance_nm"] or 0
            # 任务类型：工资公式与公司收支按 kind 区分，航线/转场/包机
            d0 = conn.execute("SELECT * FROM dispatches WHERE id = ?", (r["dispatch_id"],)).fetchone() \
                if r["dispatch_id"] else None
            kind = (d0["kind"] if d0 and "kind" in d0.keys() else "line") or "line"
            # 工资统一走共享公式 + 经济上限/每日额度/公司余额校验，对 CEO 自审同样生效
            wage, wage_capped = _payout_guard(
                conn, airline_id, r["user_id"],
                _report_wage(conn, airline_id, kind, r["hours"], distance, r["base_salary"] or 0),
            )

            # 公司收支：航线=客运+货运，签派优先，无签派按客座率估算；
            # 包机=1.5× 溢价费率；转场=纯成本，调机补贴。
            pax = 0
            cargo = 0
            if d0:
                pax = d0["pax"] or 0
                cargo = d0["cargo"] or 0
            if kind == "ferry":
                pax, cargo = 0, 0
            if kind == "line" and pax <= 0:
                spec = FLEET_CATALOG.get(r["aircraft"], {})
                pax = int(round(spec.get("pax", 0) * DEFAULT_LOAD_FACTOR))
            premium = 1.5 if kind == "charter" else 1.0
            revenue = 0
            if kind != "ferry":
                pax_revenue = int(round(pax * distance * REVENUE_PER_PAX_NM * premium))
                cargo_revenue = int(round(cargo * distance * CARGO_RATE_PER_KG_NM * premium))
                revenue = pax_revenue + cargo_revenue
            company_net = revenue - wage

            # 并发双审防护：条件更新仅 pending 可置为 approved，双方只有一方成功；
            # 钱包/公司余额/账本/通知等入账逻辑全部放在 rowcount > 0 之后
            cur = conn.execute(
                "UPDATE flight_reports SET status = 'approved', amount = ?, reject_reason = '',"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (wage, user["id"], r["id"]),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该报告已被处理")
            # 钱包入账，飞行员工资+ 累计时长
            w = conn.execute("SELECT user_id FROM wallets WHERE user_id = ?", (r["user_id"],)).fetchone()
            if w:
                conn.execute(
                    "UPDATE wallets SET balance = balance + ?, total_hours = total_hours + ? WHERE user_id = ?",
                    (wage, r["hours"], r["user_id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, ?, ?)",
                    (r["user_id"], wage, r["hours"]),
                )
            conn.execute(
                "INSERT INTO wallet_records (user_id, amount, type, note, report_id)"
                " VALUES (?, ?, 'salary', ?, ?)",
                (r["user_id"], wage, f"{r['dep']}-{r['arr']} {r['hours']}h {'调机补贴' if kind == 'ferry' else ('包机工资' if kind == 'charter' else '飞行工资')}", r["id"]),
            )
            # 公司账本：收入 + 工资支出，净额进公司余额，亏损则扣账上
            conn.execute("UPDATE airlines SET balance = balance + ? WHERE id = ?", (company_net, airline_id))
            if kind == "ferry":
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'expense', ?, ?)",
                    (airline_id, -wage, f"{r['dep']}-{r['arr']} 调机补贴，转场", r["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'revenue', ?, ?)",
                    (airline_id, revenue,
                     f"{r['dep']}-{r['arr']} {'包机' if kind == 'charter' else '运输'}收入，{pax} 客 + {cargo}kg 货", r["id"]),
                )
                conn.execute(
                    "INSERT INTO airline_ledger (airline_id, amount, type, note, report_id)"
                    " VALUES (?, ?, 'expense', ?, ?)",
                    (airline_id, -wage, f"{r['dep']}-{r['arr']} 飞行员工资 {r['hours']}h", r["id"]),
                )
            # 飞机归队并落在任务目的地机场
            if d0 and d0["fleet_id"]:
                conn.execute(
                    "UPDATE airline_fleet SET status = 'available', location = ?"
                    " WHERE id = ? AND status = 'dispatched'",
                    (d0["arr"], d0["fleet_id"]),
                )
            _audit(request, "airline", "审核通过飞行报告并结算", actor=user, target_id=airline_id,
                   detail=f"{r['dep']}-{r['arr']} · {r['hours']}h · 工资 {wage} · 运输收入 {revenue}，{pax} 客/{cargo}kg 货 · 公司净 {company_net}"
                          + (" · 单份报告封顶" if wage_capped else ""))
            notify_user(
                r["user_id"], "你的飞行报告已通过审核",
                f"报告 {r['dep']}-{r['arr']}，{r['hours']} 小时，已通过审核，"
                f"飞行工资 {wage} 已存入你的钱包。",
            )
            approved_uid = r["user_id"]
            result = {"ok": True, "amount": wage, "revenue": revenue, "companyNet": company_net,
                      "message": f"已发放飞行工资 {wage}，公司票款收入 {revenue}，净 {company_net}"
                                 + ("已达单份报告工资上限，超额部分未发放" if wage_capped else "")}

        elif body.action == "reject":
            if not body.reason.strip():
                raise HTTPException(400, "请填写驳回原因")
            cur = conn.execute(
                "UPDATE flight_reports SET status = 'rejected', reject_reason = ?,"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (clean(body.reason, 200), user["id"], r["id"]),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该报告已被处理")
            _audit(request, "airline", "驳回飞行报告", actor=user, target_id=airline_id,
                   detail=f"{r['dep']}-{r['arr']} · {clean(body.reason, 100)}")
            notify_user(
                r["user_id"], "你的飞行报告被驳回",
                f"报告 {r['dep']}-{r['arr']}（{r['hours']} 小时）被管理层驳回，本次不计薪。\n"
                f"驳回原因：{clean(body.reason, 200)}",
            )
            return {"ok": True, "message": "已驳回报告"}

        else:
            raise HTTPException(400, "无效操作")

    # 走到这里说明事务已提交，with 退出时 commit：此时再结算成就，避免嵌套写锁
    if approved_uid:
        from .achievements import check_achievements

        check_achievements(approved_uid, "flight_approved")
    return result

@router.get("/{airline_id}/payroll/export")
def export_payroll(airline_id: int, month: str = "", user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        a = _airline_or_404(conn, airline_id)
        rows = conn.execute(
            "SELECT u.cid, u.username, r.dep, r.arr, r.flight_no, r.aircraft,"
            " r.flight_date, r.hours, r.distance_nm, r.base_salary, r.amount, r.reviewed_at"
            " FROM flight_reports r JOIN users u ON u.id = r.user_id"
            " WHERE r.airline_id = ? AND r.status = 'approved'"
            " AND strftime('%Y-%m', r.reviewed_at) = ?"
            " ORDER BY r.reviewed_at",
            (airline_id, month),
        ).fetchall()

    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["CID", "飞行员", "航线", "航班号", "机型", "飞行日期", "时长 h", "距离 NM", "基础工资", "工资合计"])
    total = 0
    for r in rows:
        total += r["amount"] or 0
        writer.writerow([
            csv_safe(r["cid"]), csv_safe(r["username"]), csv_safe(f'{r["dep"]}-{r["arr"]}'),
            csv_safe(r["flight_no"]), csv_safe(r["aircraft"]), csv_safe(r["flight_date"]),
            r["hours"], "" if r["distance_nm"] is None else round(r["distance_nm"], 1),
            r["base_salary"], r["amount"] or 0,
        ])
    writer.writerow([])
    writer.writerow(["合计", "", "", "", "", "", "", "", "", total])

    content = "\ufeff" + buf.getvalue()  # UTF-8 BOM，Excel 直接打开不乱码
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="payroll-{a["icao"]}-{month or "all"}.csv"'},
    )
