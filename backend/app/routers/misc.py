"""公开数据与仪表盘 API"""
import time
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request

from ..captcha import challenge_info
from ..database import get_conn
from ..deps import has_capability, require_auth
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request

router = APIRouter(tags=["misc"])

# 进程启动时间戳：公开状态页用它计算运行时长，main.py 无现成启动时间，这里模块加载时记录
_START_TIME = time.time()


@router.get("/api/config")
def public_config(request: Request):
    """前端启动配置，公开，不含任何密钥

    pow.enabled 按请求者 IP 判定：本机开发豁免的客户端直接拿到 false，
    前端就不必等安全校验，避免「显示要验证、后端却放行」的自相矛盾。
    """
    return {
        "ok": True,
        "pow": challenge_info(client_ip_from_request(request)),
    }


@router.get("/api/health")
def health():
    from datetime import datetime

    return {"ok": True, "name": "CTYFLY API", "time": datetime.now().isoformat()}


@router.get("/api/version")
def build_version():
    """当前前端构建标识，公开。

    前端用它检测「页面停留期间是否发布了新构建」：旧页面引用的 chunk 一旦被
    新构建删除，路由懒加载会 404 并卡住界面，提前提示刷新可以避免。
    标识取自 dist/index.html 的修改时间与大小——每次构建都会变，且无需额外文件。
    """
    from ..main import SPA_DIST

    index = SPA_DIST / "index.html"
    try:
        st = index.stat()
        build = f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        build = "dev"
    return {"ok": True, "build": build}


@router.get("/api/status")
def public_status(request: Request):
    """公开状态页，无需登录：只输出脱敏指标，绝不暴露路径/版本/内部细节。

    统计口径复用 /api/dashboard 与管理后台的现有定义，不发明新口径：
    - 在线用户 = 最近 5 分钟内有 API 请求的独立账号，同 dashboard
    - 总用户 = users 全表，同 dashboard
    - 请求量/错误率 = api_metrics 按本地日界，day 字段回看 1 天，同 /api/admin/logs/network
    """
    enforce(request, "status", 30, 60)
    with get_conn() as conn:
        # 数据库连通性：实测一次 SELECT 1 的耗时，毫秒，整数
        t0 = time.perf_counter()
        conn.execute("SELECT 1")
        db_ping_ms = int(round((time.perf_counter() - t0) * 1000))

        # 最近 24h，按 api_metrics 的本地日界近似请求量与错误率：
        # 该表只有 count 字段、无响应时间列，因此不提供平均响应时间
        metrics = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS total,"
            " COALESCE(SUM(CASE WHEN status >= 400 THEN count ELSE 0 END), 0) AS errors"
            " FROM api_metrics WHERE day >= date('now','localtime','-1 day')"
        ).fetchone()
        requests_24h = metrics["total"]
        error_rate_pct = round(metrics["errors"] / requests_24h * 100, 1) if requests_24h else 0.0

        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        # 在线用户：与 /api/dashboard 完全同一条 SQL 的口径
        online_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) c FROM api_access_log"
            " WHERE user_id > 0 AND created_at >= datetime('now','localtime','-5 minutes')"
        ).fetchone()["c"]
        total_airlines = conn.execute(
            "SELECT COUNT(*) c FROM airlines WHERE status = 'approved'"
        ).fetchone()["c"]
        server_time = conn.execute("SELECT datetime('now','localtime') AS t").fetchone()["t"]

    return {
        "ok": True,
        "apiOk": True,
        "dbPingMs": db_ping_ms,
        "uptimeHours": round((time.time() - _START_TIME) / 3600, 1),
        "requests24h": requests_24h,
        "errorRatePct": error_rate_pct,
        "totalUsers": total_users,
        "onlineUsers": online_users,
        "totalAirlines": total_airlines,
        "serverTime": server_time,
    }


@router.get("/api/changelogs")
def public_changelogs(request: Request):
    """更新日志，公开，无需登录：按发布日期倒序取最新 50 条"""
    enforce(request, "changelogs", 60, 60)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, version, title, body, released_at FROM changelogs"
            " ORDER BY released_at DESC, id DESC LIMIT 50"
        ).fetchall()
    return {"ok": True, "changelogs": [dict(r) for r in rows]}


@router.get("/api/home")
def home():
    with get_conn() as conn:
        notices = conn.execute(
            "SELECT id, title, content, pinned, created_at FROM notices"
            " ORDER BY pinned DESC, id DESC LIMIT 5"
        ).fetchall()
        events = conn.execute(
            "SELECT e.id, e.title, e.dep, e.arr, e.start_time, e.end_time, e.status,"
            " (SELECT COUNT(*) FROM event_signups s WHERE s.event_id = e.id) AS signup_count"
            " FROM events e WHERE e.status IN ('upcoming','ongoing') ORDER BY e.start_time LIMIT 6"
        ).fetchall()
    return {"ok": True, "notices": [dict(n) for n in notices], "events": [dict(e) for e in events]}


@router.get("/api/partners")
def public_partners():
    """首页合作伙伴展示位，公开，无需登录"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, url, logo FROM partners"
            " WHERE enabled = 1 ORDER BY sort, id"
        ).fetchall()
    return {"ok": True, "partners": [dict(r) for r in rows]}


@router.get("/api/dashboard")
def dashboard(user: dict = Depends(require_auth)):
    uid = user["id"]
    with get_conn() as conn:
        my_tickets = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE user_id = ? AND status != 'closed'", (uid,)
        ).fetchone()["c"]
        pending_apps = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE user_id = ? AND status = 'pending'", (uid,)
        ).fetchone()["c"]
        my_signups = conn.execute(
            "SELECT e.title, e.start_time, e.dep, e.arr FROM event_signups s"
            " JOIN events e ON e.id = s.event_id"
            " WHERE s.user_id = ? AND e.status IN ('upcoming','ongoing')"
            " ORDER BY e.start_time LIMIT 5",
            (uid,),
        ).fetchall()
        upcoming = conn.execute(
            "SELECT id, title, dep, arr, start_time, status FROM events"
            " WHERE status IN ('upcoming','ongoing') ORDER BY start_time LIMIT 5"
        ).fetchall()
        notices = conn.execute(
            "SELECT id, title, created_at FROM notices ORDER BY pinned DESC, id DESC LIMIT 5"
        ).fetchall()
        # 与「管理后台 · 数据概览」保持完全一致的口径，避免两个页面数字对不上：
        # 用户总数 = users 全表；管制员总数 = is_controller = 1，SUP/ADM 不计入
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        total_controllers = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE is_controller = 1"
        ).fetchone()["c"]
        # 在线用户数：最近 5 分钟内有过 API 请求的独立账号，访问日志有 uid+时间索引
        online_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) c FROM api_access_log"
            " WHERE user_id > 0 AND created_at >= datetime('now','localtime','-5 minutes')"
        ).fetchone()["c"]
        # 飞行时长榜，仪表盘：累计小时前 10
        top_pilots = conn.execute(
            "SELECT u.username, u.cid, u.avatar_url, w.total_hours"
            " FROM wallets w JOIN users u ON u.id = w.user_id"
            " WHERE w.total_hours > 0 ORDER BY w.total_hours DESC LIMIT 10"
        ).fetchall()
        # 活动月历：全部活动，客户端按月过滤
        calendar_events = conn.execute(
            "SELECT id, title, dep, arr, start_time, status FROM events ORDER BY start_time LIMIT 500"
        ).fetchall()

        # ---------- 角色感知：个人数据 / 待办 / 最近飞行 ----------
        w = conn.execute("SELECT total_hours, balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        me_hours = w["total_hours"] if w else 0
        me_balance = w["balance"] if w else 0
        me_flights = conn.execute(
            "SELECT COUNT(*) c FROM flight_reports WHERE user_id = ? AND status = 'approved'", (uid,)
        ).fetchone()["c"]
        my_airline = conn.execute(
            "SELECT a.name, a.icao, m.role, m.position FROM airline_members m"
            " JOIN airlines a ON a.id = m.airline_id"
            " WHERE m.user_id = ? AND m.status = 'active' LIMIT 1",
            (uid,),
        ).fetchone()

        # 在飞的签派单，待完成上报的
        my_open = conn.execute(
            "SELECT id, flight_no, dep, arr, flight_state FROM dispatches"
            " WHERE user_id = ? AND status = 'open' ORDER BY id DESC LIMIT 5",
            (uid,),
        ).fetchall()

        # 待办清单，按身份生成，只放用户当前能直接处理的
        todos = []
        for d in my_open:
            state_text = {"issued": "待起飞上报", "departed": "已起飞 · 落地后可上报", "landed": "已落地 · 待提交报告"}
            st = state_text.get(d["flight_state"], "")
            todos.append({"text": f"签派单 {d['flight_no'] or d['dep'] + '-' + d['arr']}：{st}", "link": "/va/dispatch"})
        if my_airline:
            aid = conn.execute(
                "SELECT airline_id FROM airline_members"
                " WHERE user_id = ? AND status = 'active' LIMIT 1", (uid,)
            ).fetchone()["airline_id"]
            am_role = conn.execute(
                "SELECT role FROM airline_members WHERE user_id = ? AND airline_id = ? AND status = 'active'",
                (uid, aid),
            ).fetchone()
            if am_role and am_role["role"] == "ceo":
                pending_reports = conn.execute(
                    "SELECT COUNT(*) c FROM flight_reports WHERE airline_id = ? AND status = 'pending'", (aid,)
                ).fetchone()["c"]
                if pending_reports:
                    todos.append({"text": f"有 {pending_reports} 份飞行报告待审核", "link": f"/airlines/{aid}"})
                pending_members = conn.execute(
                    "SELECT COUNT(*) c FROM airline_members WHERE airline_id = ? AND status = 'pending'", (aid,)
                ).fetchone()["c"]
                if pending_members:
                    todos.append({"text": f"有 {pending_members} 位成员申请待审批", "link": f"/airlines/{aid}"})
        if has_capability(user, "manage_tickets"):
            # 只数 status='open'，新工单或用户回复后待跟进。
            # 'replied' 是管理员已回复、等用户跟进的，不算管理员的待办，否则点进去无事可做
            open_tickets = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE status = 'open'"
            ).fetchone()["c"]
            if open_tickets:
                todos.append({"text": f"有 {open_tickets} 张工单待回复", "link": "/admin/tickets"})
        if has_capability(user, "review_applications"):
            # 按类型分开计数并跳对应页：申请页按 type 过滤，混合计数会「点过去找不到」
            for app_type, label, link in (
                ("controller", "管制员", "/admin/applications/controller"),
                ("staff", "职员", "/admin/applications/staff"),
            ):
                c = conn.execute(
                    "SELECT COUNT(*) c FROM applications WHERE status = 'pending' AND type = ?",
                    (app_type,),
                ).fetchone()["c"]
                if c:
                    todos.append({"text": f"有 {c} 份{label}申请待审核", "link": link})

        # 最近飞行记录，全平台已通过的报告
        recent_flights = conn.execute(
            "SELECT r.dep, r.arr, r.hours, r.flight_date, u.username, u.avatar_url"
            " FROM flight_reports r JOIN users u ON u.id = r.user_id"
            " WHERE r.status = 'approved' ORDER BY r.id DESC LIMIT 8"
        ).fetchall()

    return {
        "ok": True,
        "user": user,
        "me": {
            "hours": me_hours,
            "balance": me_balance,
            "flights": me_flights,
            "airline": dict(my_airline) if my_airline else None,
            "openDispatches": [dict(d) for d in my_open],
        },
        "todos": todos,
        "recentFlights": [dict(r) for r in recent_flights],
        "counters": {
            "myTickets": my_tickets,
            "pendingApps": pending_apps,
            "totalUsers": total_users,
            "totalControllers": total_controllers,
            "onlineUsers": online_users,
        },
        "mySignups": [dict(s) for s in my_signups],
        "upcomingEvents": [dict(e) for e in upcoming],
        "notices": [dict(n) for n in notices],
        "topPilots": [dict(t) for t in top_pilots],
        "calendarEvents": [dict(e) for e in calendar_events],
    }


@router.get("/api/dashboard/trend")
def dashboard_trend(days: int = 14, user: dict = Depends(require_auth)):
    """近 N 天站内活跃趋势，仪表盘主模块的图表数据源。

    只回聚合数字，不含任何个人信息：
      requests = 当日 API 请求量，api_metrics，与 /api/status 同源口径
      users = 当日新增注册
      reports = 当日飞行报告数，按 flight_date 归日，与排行榜口径一致
      hours = 当日飞行小时合计
    必须补零：没有数据的日期也要返回，否则前端 x 轴被压缩、趋势会被看错。
    """
    days = max(7, min(30, int(days or 14)))
    since = f"-{days - 1} days"
    with get_conn() as conn:
        req = {r["day"]: r["c"] for r in conn.execute(
            "SELECT day, SUM(count) c FROM api_metrics"
            " WHERE day >= date('now','localtime',?) GROUP BY day", (since,)
        ).fetchall()}
        usr = {r["d"]: r["c"] for r in conn.execute(
            "SELECT date(created_at) d, COUNT(*) c FROM users"
            " WHERE date(created_at) >= date('now','localtime',?) GROUP BY d", (since,)
        ).fetchall()}
        rep = {r["d"]: r["c"] for r in conn.execute(
            "SELECT flight_date d, COUNT(*) c FROM flight_reports"
            " WHERE flight_date >= date('now','localtime',?) GROUP BY d", (since,)
        ).fetchall()}
        hrs = {r["d"]: r["h"] for r in conn.execute(
            "SELECT flight_date d, COALESCE(SUM(hours), 0) h FROM flight_reports"
            " WHERE flight_date >= date('now','localtime',?) GROUP BY d", (since,)
        ).fetchall()}
        today = conn.execute("SELECT date('now','localtime') d").fetchone()["d"]

    end = date.fromisoformat(today)
    series = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        series.append({
            "day": d,
            "requests": req.get(d, 0),
            "users": usr.get(d, 0),
            "reports": rep.get(d, 0),
            "hours": round(hrs.get(d, 0.0), 1),
        })
    return {
        "ok": True,
        "days": series,
        "totals": {
            "requests": sum(x["requests"] for x in series),
            "users": sum(x["users"] for x in series),
            "reports": sum(x["reports"] for x in series),
            "hours": round(sum(x["hours"] for x in series), 1),
        },
    }
