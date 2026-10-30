"""事故记录：飞行员上报飞行事故/事件，管理员调查处置并留痕

溯源设计，与 login_logs / audit_logs / api_access_log 同一套 requestinfo 口径：
- 上报瞬间把 **IP、UA、UA 分类，classify_ua 判定是否脚本/爬虫、进程号** 一并落库。
  事故上报是低频、高价值的写入，事后要能回答「这条记录是谁、在什么客户端、从哪报的」；
  只靠 api_access_log 的 30 天保留期不够，事故档案要长期留存。
- 处置动作，受理/结案/备注写 incident_updates 并同步写 audit_logs，双重留痕。
- 读取侧做分级：普通用户只看自己报的，职员/管理员才能看全部与 IP/UA 溯源字段。

状态机：open，待受理 → investigating，调查中 → closed，结案。
流转用条件 UPDATE，WHERE status = 当前状态，并发/重复点击只会有一方成功。
"""
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth, require_staff
from ..ratelimit import enforce
from ..requestinfo import classify_ua, client_ip_from_request, user_agent
from ..text import clean

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

# 硬编码分页，红线：分页大小由服务端决定
INCIDENT_PAGE_SIZE = 15
INCIDENT_MAX_PAGE = 2000

SEVERITIES = {
    "incident": "事件",
    "serious": "严重事件",
    "accident": "事故",
    "hull_loss": "全损事故",
}
PHASES = ("地面", "起飞", "爬升", "巡航", "下降", "进近", "落地")
STATUSES = {"open": "待受理", "investigating": "调查中", "closed": "已结案"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?$")


def _audit(request: Request, action: str, *, actor, target_type: str, target_id,
           detail: str) -> None:
    log_event("risk", action, actor=actor, target_type=target_type, target_id=target_id,
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))


def _view(row) -> dict:
    d = dict(row)
    d["severityLabel"] = SEVERITIES.get(d.get("severity"), d.get("severity", ""))
    d["statusLabel"] = STATUSES.get(d.get("status"), d.get("status", ""))
    return d


def _trace_fields(row) -> dict:
    """溯源字段单独给管理员看，普通用户接口里不返回"""
    d = dict(row)
    return {
        "ip": d.get("ip", ""),
        "ua": d.get("ua", ""),
        "uaLabel": d.get("ua_label", ""),
        "uaBot": bool(d.get("ua_bot")),
        "pid": d.get("pid", 0),
    }


class IncidentBody(BaseModel):
    dispatchId: int = Field(0, ge=0)
    flightNo: str = Field("", max_length=16)
    dep: str = Field("", max_length=8)
    arr: str = Field("", max_length=8)
    aircraft: str = Field("", max_length=16)
    reg: str = Field("", max_length=16)
    severity: str = Field("incident", max_length=16)
    phase: str = Field("", max_length=8)
    occurredAt: str = Field("", max_length=19)
    location: str = Field("", max_length=64)
    summary: str = Field(..., max_length=200)
    detail: str = Field("", max_length=2000)


class UpdateBody(BaseModel):
    action: str = Field("", max_length=16)
    note: str = Field("", max_length=500)
    conclusion: str = Field("", max_length=500)


@router.post("")
def report_incident(body: IncidentBody, request: Request, user: dict = Depends(require_auth)):
    """上报事故/事件：落库时记录 IP/UA/UA 分类/进程号，可长期溯源"""
    enforce(request, "incident-report", 5, 3600)
    if body.severity not in SEVERITIES:
        raise HTTPException(400, "无效的事故等级")
    phase = body.phase.strip()
    if phase and phase not in PHASES:
        raise HTTPException(400, "无效的飞行阶段")
    summary = clean(body.summary, 200)
    if len(summary) < 5:
        raise HTTPException(400, "请至少用 5 个字描述发生了什么")
    occurred_at = body.occurredAt.strip().replace("T", " ")
    if occurred_at and not DATE_RE.match(occurred_at.replace(" ", "T")):
        raise HTTPException(400, "发生时间格式应为 YYYY-MM-DDTHH:mm")

    ip = client_ip_from_request(request)
    ua = user_agent(request)
    ua_label, ua_bot = classify_ua(ua)

    with get_conn() as conn:
        # 关联签派单：必须是自己名下的任务，并自动带出航班信息，避免手填漂移
        dep = body.dep.strip().upper()
        arr = body.arr.strip().upper()
        aircraft, reg, flight_no = body.aircraft.strip().upper(), body.reg.strip().upper(), body.flightNo.strip().upper()
        airline_id = None
        dispatch_id = None
        if body.dispatchId:
            d = conn.execute(
                "SELECT * FROM dispatches WHERE id = ? AND user_id = ?",
                (body.dispatchId, user["id"]),
            ).fetchone()
            if not d:
                raise HTTPException(404, "签派单不存在或不属于你")
            dispatch_id, airline_id = d["id"], d["airline_id"]
            dep, arr = d["dep"], d["arr"]
            aircraft = d["aircraft"] or aircraft
            flight_no = d["flight_no"] or flight_no
        if not airline_id:
            m = conn.execute(
                "SELECT airline_id FROM airline_members WHERE user_id = ? AND status = 'active'"
                " ORDER BY id DESC LIMIT 1",
                (user["id"],),
            ).fetchone()
            airline_id = m["airline_id"] if m else None

        today = conn.execute(
            "SELECT strftime('%Y%m%d','now','localtime') AS d"
        ).fetchone()["d"]
        seq = conn.execute(
            "SELECT COUNT(*) AS c FROM incidents WHERE report_no LIKE ?", (f"INC-{today}-%",)
        ).fetchone()["c"] + 1
        report_no = f"INC-{today}-{seq:03d}"
        cur = conn.execute(
            "INSERT INTO incidents (report_no, user_id, airline_id, dispatch_id, flight_no, dep, arr,"
            " aircraft, reg, severity, phase, occurred_at, location, summary, detail,"
            " ip, ua, ua_label, ua_bot, pid)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (report_no, user["id"], airline_id, dispatch_id, flight_no, dep, arr, aircraft, reg,
             body.severity, phase, occurred_at, clean(body.location, 64), summary,
             clean(body.detail, 2000), ip, ua, ua_label, 1 if ua_bot else 0, os.getpid()),
        )
        incident_id = cur.lastrowid
        conn.execute(
            "INSERT INTO incident_updates (incident_id, actor_id, actor_name, action, note, ip, ua)"
            " VALUES (?, ?, ?, 'report', '提交事故报告', ?, ?)",
            (incident_id, user["id"], user["username"], ip, ua),
        )
    _audit(request, "上报飞行事故", actor=user, target_type="incident", target_id=incident_id,
           detail=f"{report_no} · {SEVERITIES[body.severity]} · {summary[:60]}")
    # 成就钩子：事务外调用，内部另开连接
    from .achievements import check_achievements

    check_achievements(user["id"], "incident_reported")
    return {
        "ok": True,
        "id": incident_id,
        "reportNo": report_no,
        "message": f"事故报告已提交，编号 {report_no}，管理员会尽快跟进",
    }


@router.get("")
def list_incidents(page: int = 1, scope: str = "mine", status: str = "",
                   user: dict = Depends(require_auth)):
    """事故列表：普通用户只看自己；职员/管理员可看全部，含 IP/UA 溯源字段"""
    page = max(1, min(int(page or 1), INCIDENT_MAX_PAGE))
    offset = (page - 1) * INCIDENT_PAGE_SIZE
    is_staff = user["role"] in ("admin", "sup")

    where = ["1 = 1"]
    params: list = []
    if not (is_staff and scope == "all"):
        where.append("i.user_id = ?")
        params.append(user["id"])
    if status in STATUSES:
        where.append("i.status = ?")
        params.append(status)
    where_sql = " AND ".join(where)

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM incidents i WHERE {where_sql}", params
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT i.*, u.username, u.cid, a.name AS airline_name"
            " FROM incidents i JOIN users u ON u.id = i.user_id"
            " LEFT JOIN airlines a ON a.id = i.airline_id"
            f" WHERE {where_sql} ORDER BY i.id DESC LIMIT {INCIDENT_PAGE_SIZE} OFFSET ?",
            (*params, offset),
        ).fetchall()
        stats = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM incidents GROUP BY status"
            )
        }
    items = []
    for r in rows:
        d = _view(r)
        if is_staff:
            d["trace"] = _trace_fields(r)
        items.append(d)
    return {
        "ok": True,
        "items": items,
        "total": total,
        "page": page,
        "pageSize": INCIDENT_PAGE_SIZE,
        "isStaff": is_staff,
        "severities": SEVERITIES,
        "phases": list(PHASES),
        "statuses": STATUSES,
        "stats": stats,
    }


@router.get("/{incident_id}")
def incident_detail(incident_id: int, user: dict = Depends(require_auth)):
    """事故详情 + 处置时间线，本人或职员/管理员可看"""
    is_staff = user["role"] in ("admin", "sup")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT i.*, u.username, u.cid, a.name AS airline_name, a.icao AS airline_icao"
            " FROM incidents i JOIN users u ON u.id = i.user_id"
            " LEFT JOIN airlines a ON a.id = i.airline_id WHERE i.id = ?",
            (incident_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "事故记录不存在")
        if not is_staff and row["user_id"] != user["id"]:
            raise HTTPException(403, "无权查看该事故记录")
        updates = conn.execute(
            "SELECT id, actor_id, actor_name, action, note, created_at FROM incident_updates"
            " WHERE incident_id = ? ORDER BY id",
            (incident_id,),
        ).fetchall()
    out = _view(row)
    out["updates"] = [dict(u) for u in updates]
    if is_staff:
        out["trace"] = _trace_fields(row)
    return {"ok": True, "incident": out}


@router.post("/{incident_id}/updates")
def update_incident(incident_id: int, body: UpdateBody, request: Request,
                    staff: dict = Depends(require_staff)):
    """管理员处置：受理调查 / 结案 / 追加备注，每次动作都留 IP/UA 痕迹"""
    enforce(request, "incident-update", 60, 3600)
    action = body.action.strip()
    note = clean(body.note, 500)
    conclusion = clean(body.conclusion, 500)

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, "事故记录不存在")

        if action == "investigate":
            cur = conn.execute(
                "UPDATE incidents SET status = 'investigating', updated_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'open'",
                (incident_id,),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该记录已不在「待受理」状态")
            label = "受理并进入调查"
        elif action == "close":
            if not conclusion:
                raise HTTPException(400, "结案必须填写调查结论")
            cur = conn.execute(
                "UPDATE incidents SET status = 'closed', conclusion = ?,"
                " updated_at = datetime('now','localtime') WHERE id = ? AND status != 'closed'",
                (conclusion, incident_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该记录已结案")
            label = "结案"
        elif action == "comment":
            if len(note) < 2:
                raise HTTPException(400, "备注内容太短")
            label = "追加调查备注"
        else:
            raise HTTPException(400, "无效操作")

        conn.execute(
            "INSERT INTO incident_updates (incident_id, actor_id, actor_name, action, note, ip, ua)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (incident_id, staff["id"], staff["username"], action,
             conclusion if action == "close" else note,
             client_ip_from_request(request), user_agent(request)),
        )
    _audit(request, f"事故处置：{label}", actor=staff, target_type="incident",
           target_id=incident_id, detail=f"{row['report_no']} · {label}")
    return {"ok": True, "message": f"已{label}"}
