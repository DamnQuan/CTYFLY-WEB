"""虚拟航司 · 签派与机队 API，2026-10-11 从 routers/airlines.py 抽出，P3 第三刀

包含：机队列表与购置、转场调机、包机、签派单创建/列表/取消、飞行节点上报，平台 ACARS。
经济规则在 app/economy.py，报告与薪酬在 routers/pirep.py，本模块只管签派链路。

沿用 /api/airlines 前缀，同前缀多 router 在本仓库已有先例，由 main.py 注册。
模型与辅助函数，_require_ceo / _gen_reg / _audit / FLEET_CATALOG 与各 Body 由 airlines 提供；
airlines 不反向引用本模块，故无循环导入。导入清单由 ast 分析实际引用生成，不手写。
"""
import secrets

from .. import navdistance
from ..database import get_conn
from ..deps import require_auth
from ..ratelimit import enforce
from ..text import clean
from fastapi import APIRouter, Depends, HTTPException, Request

from .airlines import (CharterBody, DispatchBody, FLEET_CATALOG, FerryBody, FleetPurchaseBody, FlightEventBody, _audit, _gen_reg, _require_ceo)


router = APIRouter(prefix="/api/airlines", tags=["airlines"])

@router.get("/{airline_id}/fleet")
def list_fleet(airline_id: int, user: dict = Depends(require_auth)):
    """机队列表 + 机型目录，成员可看；目录含价格供 CEO 购置"""
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可查看机队")
        fleet = conn.execute(
            "SELECT * FROM airline_fleet WHERE airline_id = ? ORDER BY status, id",
            (airline_id,),
        ).fetchall()
    return {"ok": True, "fleet": [dict(f) for f in fleet], "catalog": FLEET_CATALOG}

@router.post("/{airline_id}/fleet/purchase")
def purchase_aircraft(airline_id: int, body: FleetPurchaseBody, request: Request,
                            user: dict = Depends(require_auth)):
    """CEO 用个人钱包购置飞机进机队"""
    enforce(request, "fleet-buy", 5, 3600)
    key = body.aircraft.strip().upper()
    if key not in FLEET_CATALOG:
        raise HTTPException(400, "无效机型")
    spec = FLEET_CATALOG[key]
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        # 原子扣费：条件更新防并发双花
        cur_w = conn.execute(
            "UPDATE wallets SET balance = balance - ?"
            " WHERE user_id = ? AND balance >= ?",
            (spec["price"], user["id"], spec["price"]),
        )
        if cur_w.rowcount == 0:
            w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
            raise HTTPException(400, f"钱包余额不足，购置 {spec['name']} 需要 {spec['price']}，当前 {w['balance'] if w else 0}")
        reg = _gen_reg(conn)
        conn.execute(
            "INSERT INTO wallet_records (user_id, amount, type, note) VALUES (?, ?, 'purchase', ?)",
            (user["id"], -spec["price"], f"购置 {spec['name']} {reg}"),
        )
        # 运营地理：新飞机交付到主基地，未设主基地则先要求设定
        a_row = conn.execute("SELECT hub FROM airlines WHERE id = ?", (airline_id,)).fetchone()
        hub = (a_row["hub"] if a_row else "") or ""
        if not hub:
            raise HTTPException(400, "请先在航司设置中设定主基地机场，再购置飞机")
        cur = conn.execute(
            "INSERT INTO airline_fleet (airline_id, aircraft, reg, location) VALUES (?, ?, ?, ?)",
            (airline_id, key, reg, hub),
        )
        _audit(request, "airline", "购置飞机", actor=user, target_id=airline_id,
               detail=f"{spec['name']} {reg} · {spec['price']} · 交付 {hub}")
    return {"ok": True, "id": cur.lastrowid, "reg": reg, "message": f"购置成功：{spec['name']} {reg}，已交付主基地 {hub}"}

@router.post("/{airline_id}/dispatches")
def create_dispatch(airline_id: int, body: DispatchBody, request: Request,
                          user: dict = Depends(require_auth)):
    enforce(request, "dispatch", 200, 3600)
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可创建签派单")
        r = conn.execute(
            "SELECT * FROM airline_routes WHERE id = ? AND airline_id = ?",
            (body.routeId, airline_id),
        ).fetchone()
        if not r:
            raise HTTPException(400, "请选择本航司的航线")

        # 签派必须使用本公司机队的可用飞机；签派期间飞机占用，报告提交或取消签派后释放
        f = conn.execute(
            "SELECT * FROM airline_fleet WHERE id = ? AND airline_id = ?",
            (body.fleetId, airline_id),
        ).fetchone()
        if not f:
            raise HTTPException(400, "请选择本公司的飞机")
        spec = FLEET_CATALOG.get(f["aircraft"], {})
        if body.pax > spec.get("pax", 600):
            raise HTTPException(400, f"{f['aircraft']} 最多承载 {spec.get('pax', 600)} 名旅客")
        # 运营地理：飞机必须位于航线起飞机场，不在本场请先转场调机
        fleet_loc = (f["location"] if "location" in f.keys() else "") or ""
        if fleet_loc and fleet_loc != r["dep"]:
            raise HTTPException(
                400,
                f"{f['aircraft']} {f['reg']} 当前位于 {fleet_loc}，不在起飞机场 {r['dep']}——请先执行转场调机",
            )
        if not fleet_loc:
            # 未设定位置的老飞机：视为位于起飞机场并落档，一次性归位
            conn.execute("UPDATE airline_fleet SET location = ? WHERE id = ?", (r["dep"], f["id"]))

        # 并发双签派防护：条件更新占住飞机，仅 available 可被置为 dispatched
        cur_f = conn.execute(
            "UPDATE airline_fleet SET status = 'dispatched' WHERE id = ? AND status = 'available'",
            (f["id"],),
        )
        if cur_f.rowcount == 0:
            raise HTTPException(409, "该飞机已被占用")

        cur = conn.execute(
            "INSERT INTO dispatches (airline_id, user_id, route_id, fleet_id, flight_no, dep, arr,"
            " aircraft, captain, callsign, sched_dep, pax, cargo, copilot, ci, dep_rwy, arr_rwy,"
            " cruise_alt, fuel_kg, alternate, remarks, flight_token, flight_state, kind, distance_nm, route_string)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', 'line', ?, ?)",
            (airline_id, user["id"], r["id"], f["id"], r["flight_no"], r["dep"], r["arr"],
             f["aircraft"], clean(body.captain, 32) or user["username"],
             clean(body.callsign, 16).upper() or r["flight_no"],
             clean(body.schedDep, 16), body.pax, body.cargo, clean(body.copilot, 32), body.ci,
             clean(body.depRwy, 8).upper(), clean(body.arrRwy, 8).upper(),
             body.cruiseAlt, body.fuelKg, clean(body.alternate, 8).upper(), clean(body.remarks, 200),
             secrets.token_hex(16), r["distance_nm"], clean(body.routeString, 600)),
        )
    # 成就钩子：**必须在 with 块结束之后**，事务已提交。
    # 成就结算内部要写 user_achievements / wallets / audit_logs，走的是另一条连接；
    # 在未提交的写事务里再开写连接会在 SQLite 单写锁上等到超时。
    from .achievements import check_achievements

    check_achievements(user["id"], "dispatch_created")
    return {"ok": True, "id": cur.lastrowid, "message": "签派单已生成，飞机进入占用状态"}

@router.post("/{airline_id}/fleet/{fleet_id}/ferry")
def create_ferry(airline_id: int, fleet_id: int, body: FerryBody, request: Request,
                       user: dict = Depends(require_auth)):
    """转场调机：把空闲飞机调往目标机场的空机航班。

    无客货、不产生运输收入；工资 = 距离 × 里程补贴 × 0.8，调机补贴，ACARS 核验照常。
    """
    enforce(request, "ferry", 20, 3600)
    to = body.to.strip().upper()
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可执行转场")
        f = conn.execute(
            "SELECT * FROM airline_fleet WHERE id = ? AND airline_id = ?",
            (fleet_id, airline_id),
        ).fetchone()
        if not f:
            raise HTTPException(404, "飞机不存在")
        frm = (f["location"] if "location" in f.keys() else "") or ""
        if not frm:
            raise HTTPException(400, "该飞机未登记所在机场——请 CEO 在航司设置中设定主基地后重试")
        if not (len(to) == 4 and to.isalnum()):
            raise HTTPException(400, "目标机场需为 4 位 ICAO 代码")
        if to == frm:
            raise HTTPException(400, f"飞机已经在 {frm}")
        dist = navdistance.airport_distance_nm(frm, to)
        if dist is None:
            raise HTTPException(400, f"机场 {frm} 或 {to} 不在导航数据中，请检查 ICAO")
        if dist < 10:
            raise HTTPException(400, "转场距离过短，<10nm，直接飞就行啦")

        # 并发双签派防护：条件更新占住飞机，仅 available 可被置为 dispatched
        cur_f = conn.execute(
            "UPDATE airline_fleet SET status = 'dispatched' WHERE id = ? AND status = 'available'",
            (f["id"],),
        )
        if cur_f.rowcount == 0:
            raise HTTPException(409, "该飞机已被占用")

        cur = conn.execute(
            "INSERT INTO dispatches (airline_id, user_id, route_id, fleet_id, flight_no, dep, arr,"
            " aircraft, captain, callsign, kind, distance_nm, remarks, flight_token, flight_state)"
            " VALUES (?, ?, NULL, ?, 'FERRY', ?, ?, ?, ?, 'FERRY', 'ferry', ?, '转场调机', ?, 'issued')",
            (airline_id, user["id"], f["id"], frm, to, f["aircraft"],
             clean(user["username"], 32), round(dist, 1), secrets.token_hex(16)),
        )
    _audit(request, "airline", "创建转场任务", actor=user, target_id=airline_id,
           detail=f"{f['aircraft']} {f['reg']} {frm}→{to} {dist:.0f}nm")
    return {"ok": True, "id": cur.lastrowid, "distance": round(dist, 1),
            "message": f"转场任务已创建：{frm} → {to}，{dist:.0f}nm，完成上报后发放调机补贴"}

@router.post("/{airline_id}/charters")
def create_charter(airline_id: int, body: CharterBody, request: Request,
                         user: dict = Depends(require_auth)):
    """包机：自选起降机场的自由任务，不依赖 CEO 航线。

    包机溢价：公司按 1.5× 运输费率向客户计费，飞行员按 1.2× 时薪 + 里程补贴结算。
    同样必须走 ACARS 时间线核验。
    """
    enforce(request, "charter", 20, 3600)
    dep, arr = body.dep.strip().upper(), body.arr.strip().upper()
    if not (len(dep) == 4 and dep.isalnum() and len(arr) == 4 and arr.isalnum()):
        raise HTTPException(400, "起降机场需为 4 位 ICAO 代码")
    if dep == arr:
        raise HTTPException(400, "起飞与到达机场不能相同")
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可承接包机")
        f = conn.execute(
            "SELECT * FROM airline_fleet WHERE id = ? AND airline_id = ?",
            (body.fleetId, airline_id),
        ).fetchone()
        if not f:
            raise HTTPException(400, "请选择本公司的飞机")
        floc = (f["location"] if "location" in f.keys() else "") or ""
        if not floc:
            raise HTTPException(400, "该飞机未登记所在机场——请 CEO 先设定主基地")
        if floc != dep:
            raise HTTPException(400, f"{f['aircraft']} {f['reg']} 位于 {floc}，需先转场至 {dep} 才能承接该包机")
        spec = FLEET_CATALOG.get(f["aircraft"], {})
        if body.pax > spec.get("pax", 600):
            raise HTTPException(400, f"{f['aircraft']} 最多承载 {spec.get('pax', 600)} 名旅客")
        dist = navdistance.airport_distance_nm(dep, arr)
        if dist is None:
            raise HTTPException(400, "起降机场不在导航数据中，请检查 ICAO")
        if dist < 30:
            raise HTTPException(400, "包机航程过短，<30nm")

        # 并发双签派防护：条件更新占住飞机，仅 available 可被置为 dispatched
        cur_f = conn.execute(
            "UPDATE airline_fleet SET status = 'dispatched' WHERE id = ? AND status = 'available'",
            (f["id"],),
        )
        if cur_f.rowcount == 0:
            raise HTTPException(409, "该飞机已被占用")

        cur = conn.execute(
            "INSERT INTO dispatches (airline_id, user_id, route_id, fleet_id, flight_no, dep, arr,"
            " aircraft, captain, callsign, kind, distance_nm, pax, cargo, remarks, flight_token, flight_state)"
            " VALUES (?, ?, NULL, ?, 'CHTR', ?, ?, ?, ?, 'CHTR', 'charter', ?, ?, ?, '包机任务', ?, 'issued')",
            (airline_id, user["id"], f["id"], dep, arr, f["aircraft"],
             clean(user["username"], 32), round(dist, 1), body.pax, body.cargo,
             secrets.token_hex(16)),
        )
    _audit(request, "airline", "承接包机", actor=user, target_id=airline_id,
           detail=f"{f['aircraft']} {f['reg']} {dep}→{arr} {dist:.0f}nm pax={body.pax} cargo={body.cargo}")
    return {"ok": True, "id": cur.lastrowid, "distance": round(dist, 1),
            "message": f"包机任务已创建：{dep} → {arr}，{dist:.0f}nm，完成上报后按包机溢价结算"}

@router.post("/{airline_id}/dispatches/{dispatch_id}/events")
def report_flight_event(airline_id: int, dispatch_id: int, body: FlightEventBody,
                              request: Request, user: dict = Depends(require_auth)):
    """平台 ACARS：飞行节点上报，起飞 depart / 落地 arrive。

    时间线是报告核验的基准：服务器记录接收时间，提交报告时由评分引擎交叉校验。
    令牌校验 + 首次上报绑定用户，防代报；状态机 issued → departed → landed。
    """
    enforce(request, "flightevent", 60, 3600)
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可上报飞行事件")
        d = conn.execute(
            "SELECT * FROM dispatches WHERE id = ? AND airline_id = ?",
            (dispatch_id, airline_id),
        ).fetchone()
        if not d:
            raise HTTPException(404, "签派单不存在")
        if d["user_id"] != user["id"]:
            raise HTTPException(403, "只能上报自己的签派单")
        if d["status"] != "open":
            raise HTTPException(400, "该签派单已结束")
        if not d["flight_token"] or body.token.strip() != d["flight_token"]:
            raise HTTPException(403, "飞行令牌不正确，请从签派单页获取")

        if body.type == "depart":
            # 并发双上报防护：条件更新占住状态机 issued → departed，只有一方成功
            cur_e = conn.execute(
                "UPDATE dispatches SET flight_state = 'departed'"
                " WHERE id = ? AND flight_state = 'issued'",
                (dispatch_id,),
            )
            if cur_e.rowcount == 0:
                raise HTTPException(409, "该签派单已起飞上报，勿重复操作")
            conn.execute(
                "INSERT INTO flight_events (dispatch_id, airline_id, user_id, event_type)"
                " VALUES (?, ?, ?, 'depart')",
                (dispatch_id, airline_id, user["id"]),
            )
            msg = "起飞已记录，祝飞行顺利"
        else:
            # 同理 departed → landed 条件更新，未起飞/重复落地均失败
            cur_e = conn.execute(
                "UPDATE dispatches SET flight_state = 'landed'"
                " WHERE id = ? AND flight_state = 'departed'",
                (dispatch_id,),
            )
            if cur_e.rowcount == 0:
                raise HTTPException(409, "请先上报起飞，再上报落地")
            dep_row = conn.execute(
                "SELECT server_time FROM flight_events WHERE dispatch_id = ? AND event_type = 'depart'",
                (dispatch_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO flight_events (dispatch_id, airline_id, user_id, event_type)"
                " VALUES (?, ?, ?, 'arrive')",
                (dispatch_id, airline_id, user["id"]),
            )
            msg = f"落地已记录，起飞 {dep_row['server_time'] if dep_row else '?'}，可提交飞行报告"
    return {"ok": True, "message": msg}

@router.get("/{airline_id}/dispatches")
def list_dispatches(airline_id: int, scope: str = "mine", user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        is_ceo = bool(m) and m["role"] == "ceo" and m["status"] == "active"
        where, args = "d.airline_id = ?", [airline_id]
        if not (is_ceo and scope == "all"):
            where += " AND d.user_id = ?"
            args.append(user["id"])
        rows = conn.execute(
            f"SELECT d.*, u.username, u.cid, f.reg AS fleet_reg, f.status AS fleet_status"
            f" FROM dispatches d"
            f" JOIN users u ON u.id = d.user_id"
            f" LEFT JOIN airline_fleet f ON f.id = d.fleet_id"
            f" WHERE {where}"
            f" ORDER BY d.id DESC LIMIT 100",
            args,
        ).fetchall()
    return {"ok": True, "dispatches": [dict(r) for r in rows]}

@router.delete("/{airline_id}/dispatches/{dispatch_id}")
def cancel_dispatch(airline_id: int, dispatch_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        is_ceo = bool(m) and m["role"] == "ceo" and m["status"] == "active"
        d = conn.execute(
            "SELECT * FROM dispatches WHERE id = ? AND airline_id = ?",
            (dispatch_id, airline_id),
        ).fetchone()
        if not d:
            raise HTTPException(404, "签派单不存在")
        if d["user_id"] != user["id"] and not is_ceo:
            raise HTTPException(403, "只能取消自己的签派单")
        if d["status"] != "open":
            raise HTTPException(400, "该签派单已结束，不能取消")
        conn.execute("UPDATE dispatches SET status = 'cancelled' WHERE id = ?", (dispatch_id,))
        if d["fleet_id"]:
            conn.execute(
                "UPDATE airline_fleet SET status = 'available' WHERE id = ? AND status = 'dispatched'",
                (d["fleet_id"],),
            )
    return {"ok": True, "message": "签派单已取消，飞机已归队"}
