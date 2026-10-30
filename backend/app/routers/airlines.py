"""虚拟航司 API：创建，需管理员审核、加入/退出、CEO 自治，成员审批/航线管理、
飞行报告与薪酬，CEO 审核发薪、飞行员等级、钱包、排行榜"""
import csv
import random
import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..database import get_conn
from ..deps import require_admin, require_auth
from .. import navdistance
from ..audit import log_event
from ..mailer import notify_user
from ..permissions import PILOT_RANKS
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent
from ..text import clean


def _audit(request, category: str, action: str, *, actor, target_type: str = "airline",
           target_id="", detail: str = "") -> None:
    log_event(category, action, actor=actor, target_type=target_type, target_id=target_id,
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))

router = APIRouter(prefix="/api/airlines", tags=["airlines"])

ICAO_RE = re.compile(r"^[A-Z0-9]{2,4}$")
ICAO_PER_USER = "一个用户只能拥有或加入一家虚拟航司"

# 成员职位：现实飞行部门的职位阶梯，CEO 可为每个成员设置，或留空 = 普通飞行员
# 注：2026-10-11 抽取 economy.py 时，这个常量因紧邻经济结算常量区被一并搬走，F821 抓出，
# 已放回本模块 —— 它属于航司域，不属于经济计算。
POSITION_OPTIONS = ["飞行教员", "机长", "副驾驶", "二副", "见习学员"]


def _name_taken(conn, name: str, exclude_id: int = 0) -> bool:
    """航司名称唯一性检查。

    - 待审核与已通过的航司都占用名称；被驳回的航司释放名称，可再次使用。
    - 英文忽略大小写，"Sky Air" 与 "sky air" 视为同名。
    """
    return conn.execute(
        "SELECT 1 FROM airlines WHERE id != ? AND name = ? COLLATE NOCASE"
        " AND status IN ('pending','approved') LIMIT 1",
        (exclude_id, name),
    ).fetchone() is not None


def rank_for(hours: float) -> str:
    if hours >= 200:
        return "教员"
    if hours >= 50:
        return "机长"
    if hours >= 10:
        return "副驾驶"
    return "学员"




def _membership(conn, user_id: int):
    return conn.execute(
        "SELECT m.*, a.icao, a.name, a.status AS airline_status, a.balance AS airline_balance,"
        " a.hourly_rate, a.distance_rate"
        " FROM airline_members m"
        " JOIN airlines a ON a.id = m.airline_id WHERE m.user_id = ?",
        (user_id,),
    ).fetchone()


# ---------- 机队 ----------
# ---------- 机队 ----------
# 机型目录：覆盖现实中主流民航客机，31 型。价格按真实目录价等比换算
#以 A320neo 目录价约 $110.6M = 600,000 为锚，即 100 万美元 ≈ 5,455；mfr=厂商。
# OEW/MTOW kg 为真实典型值；pax 为常见最大布局载客数；src=数据来源，前端展示。
# 数据说明：
# · C919: MTOW 72,500kg / 最大 174 座来自商飞官方与公开报道， STD 型；空重未官方公布，为估算
# · C909 ARJ21-700 : MTOW 40,500kg 为公开值；空重为估算
#   · B767-300ER / B737-700 / MAX9 等个别数值按 Boeing ACAP/常见资料，未逐项复核
FLEET_CATALOG = {
    # 国产 / 支线
    "ARJ21": {"mfr": "中国商飞", "name": "C909，ARJ21-700 翔凤", "price": 210000, "oew": 24900, "mtow": 40500, "pax": 90,
              "src": "商飞公开资料；价格取公开报道口径；空重为估算"},
    "C919":  {"mfr": "中国商飞", "name": "C919", "price": 540000, "oew": 46000, "mtow": 72500, "pax": 174,
              "src": "商飞 ACAP/科普中国：MTOW 72,500kg、最大 174 座；价格取东航采购单价，约 $0.99 亿；空重为估算"},
    "E290":  {"mfr": "巴航工业", "name": "E190-E2", "price": 330000, "oew": 33700, "mtow": 56400, "pax": 114,
              "src": "Embraer 公开资料，2018 价目表 $61.1M"},
    "E295":  {"mfr": "巴航工业", "name": "E195-E2", "price": 380000, "oew": 35900, "mtow": 61500, "pax": 146,
              "src": "Embraer 公开资料，2018 价目表 $69.9M"},
    # 空客
    "A319":  {"mfr": "空客", "name": "A319ceo", "price": 500000, "oew": 40800, "mtow": 75500, "pax": 156,
              "src": "空客 ACAP + 历史价目表，$92.3M"},
    "A19N":  {"mfr": "空客", "name": "A319neo", "price": 550000, "oew": 42800, "mtow": 75900, "pax": 156,
              "src": "空客 ACAP + 价目表，$101.5M"},
    "A320":  {"mfr": "空客", "name": "A320ceo", "price": 530000, "oew": 42600, "mtow": 77000, "pax": 180,
              "src": "空客 ACAP + 历史价目表，$98M"},
    "A20N":  {"mfr": "空客", "name": "A320neo", "price": 600000, "oew": 44300, "mtow": 79000, "pax": 186,
              "src": "空客 ACAP + 2018 价目表，$110.6M，全目录价格锚点"},
    "A321":  {"mfr": "空客", "name": "A321ceo", "price": 630000, "oew": 48500, "mtow": 83500, "pax": 220,
              "src": "空客 ACAP + 历史价目表，$114.9M"},
    "A21N":  {"mfr": "空客", "name": "A321neo", "price": 710000, "oew": 50100, "mtow": 93500, "pax": 244,
              "src": "空客 ACAP + 价目表，$129.5M"},
    "A333":  {"mfr": "空客", "name": "A330-300", "price": 1440000, "oew": 124500, "mtow": 242000, "pax": 335,
              "src": "空客 ACAP + 价目表，$264M，已停产"},
    "A339":  {"mfr": "空客", "name": "A330-900neo", "price": 1620000, "oew": 132400, "mtow": 251000, "pax": 300,
              "src": "空客 ACAP + 价目表，$296.4M"},
    "A359":  {"mfr": "空客", "name": "A350-900", "price": 1730000, "oew": 142400, "mtow": 280000, "pax": 325,
              "src": "空客 ACAP + 价目表，$317M"},
    "A35K":  {"mfr": "空客", "name": "A350-1000", "price": 2000000, "oew": 155000, "mtow": 316000, "pax": 410,
              "src": "空客 ACAP + 价目表，$366M"},
    "A388":  {"mfr": "空客", "name": "A380-800", "price": 2430000, "oew": 277000, "mtow": 575000, "pax": 555,
              "src": "空客 ACAP + 历史 2021 价目表，$445M，已停产"},
    # 波音
    "B737":  {"mfr": "波音", "name": "B737-700", "price": 490000, "oew": 37600, "mtow": 70080, "pax": 149,
              "src": "波音 737NG ACAP，D6-58329+ 价目表，$89.6M"},
    "B738":  {"mfr": "波音", "name": "B737-800", "price": 580000, "oew": 41400, "mtow": 79010, "pax": 189,
              "src": "波音 737NG ACAP + 价目表，$106.1M"},
    "B739":  {"mfr": "波音", "name": "B737-900ER", "price": 610000, "oew": 44700, "mtow": 85130, "pax": 215,
              "src": "波音 737NG ACAP + 价目表，约 $112M"},
    "B38M":  {"mfr": "波音", "name": "B737 MAX 8", "price": 660000, "oew": 43600, "mtow": 82200, "pax": 210,
              "src": "波音 MAX 公开资料，$121.6M"},
    "B39M":  {"mfr": "波音", "name": "B737 MAX 9", "price": 700000, "oew": 44900, "mtow": 88300, "pax": 220,
              "src": "波音 MAX 公开资料，$128.9M；MTOW 按公开常见值"},
    "B3XM":  {"mfr": "波音", "name": "B737 MAX 10", "price": 740000, "oew": 46800, "mtow": 90300, "pax": 230,
              "src": "波音 MAX 公开资料，$134.9M"},
    "B752":  {"mfr": "波音", "name": "B757-200", "price": 520000, "oew": 43500, "mtow": 115660, "pax": 200,
              "src": "波音历史 ACAP，已停产，历史目录价口径"},
    "B763":  {"mfr": "波音", "name": "B767-300ER", "price": 1020000, "oew": 90010, "mtow": 186880, "pax": 261,
              "src": "波音 767 ACAP + 价目表，$186M，客运型已停产"},
    "B77E":  {"mfr": "波音", "name": "B777-200ER", "price": 1470000, "oew": 138500, "mtow": 297560, "pax": 314,
              "src": "波音 777 ACAP + 价目表，$269M"},
    "B77W":  {"mfr": "波音", "name": "B777-300ER", "price": 2050000, "oew": 167800, "mtow": 351500, "pax": 396,
              "src": "波音 777 ACAP + 价目表，$375.5M，已停产"},
    "B788":  {"mfr": "波音", "name": "B787-8", "price": 1350000, "oew": 119950, "mtow": 227930, "pax": 248,
              "src": "波音 787 ACAP + 价目表，$248M"},
    "B789":  {"mfr": "波音", "name": "B787-9", "price": 1600000, "oew": 128850, "mtow": 254000, "pax": 296,
              "src": "波音 787 ACAP + 价目表，$292.5M"},
    "B78X":  {"mfr": "波音", "name": "B787-10", "price": 1850000, "oew": 135500, "mtow": 254000, "pax": 330,
              "src": "波音 787 ACAP + 价目表，$338.4M"},
    "B748":  {"mfr": "波音", "name": "B747-8I", "price": 2280000, "oew": 220100, "mtow": 447700, "pax": 467,
              "src": "波音 747-8 ACAP + 历史 2021 价目表，$418.4M，客运型已停产"},
}

# ---------- 机型建议时薪 ----------
# 官方建议时薪，游戏币/小时：按机型级别给 CEO 定薪的参考锚点，与 PAYOUT_PER_REPORT_CAP 无关。
# 键名以 FLEET_CATALOG 实际目录为准，29 型；值按机型级别从支线到旗舰递增，宁可保守。
SUGGESTED_HOURLY = {
    # 国产 / 支线
    "ARJ21": 80, "C919": 110, "E290": 85, "E295": 95,
    # 空客窄体
    "A319": 100, "A19N": 105, "A320": 110, "A20N": 115, "A321": 120, "A21N": 125,
    # 空客宽体
    "A333": 155, "A339": 160, "A359": 190, "A35K": 200, "A388": 230,
    # 波音窄体，737NG / MAX 家族
    "B737": 100, "B738": 110, "B739": 115, "B38M": 115, "B39M": 120, "B3XM": 125,
    # 波音 757/767
    "B752": 130, "B763": 140,
    # 波音 777
    "B77E": 170, "B77W": 175,
    # 波音 787 / 747-8
    "B788": 160, "B789": 165, "B78X": 170, "B748": 210,
}
for _k, _v in SUGGESTED_HOURLY.items():
    if _k in FLEET_CATALOG:
        FLEET_CATALOG[_k]["suggestedHourly"] = _v


def _gen_reg(conn) -> str:
    """生成未占用的国内注册号，B-xxxx。

    必须查重：不再使用不查重的随机 fallback，否则极端情况下会产生重复注册号；
    连续 200 次未命中说明号段已耗尽，直接报错而非静默发重复号。
    """
    for _ in range(200):
        reg = f"B-{random.randint(1, 9999):04d}"
        if not conn.execute("SELECT 1 FROM airline_fleet WHERE reg = ?", (reg,)).fetchone():
            return reg
    raise HTTPException(500, "注册号生成失败")


def _seed_fleet(conn, airline_id: int, aircraft: str = "A20N", count: int = 2):
    """初始机队：新航司审核通过时赠送，2 架 A320neo"""
    for _ in range(count):
        conn.execute(
            "INSERT INTO airline_fleet (airline_id, aircraft, reg) VALUES (?, ?, ?)",
            (airline_id, aircraft, _gen_reg(conn)),
        )


def _airline_or_404(conn, airline_id: int):
    row = conn.execute("SELECT * FROM airlines WHERE id = ?", (airline_id,)).fetchone()
    if not row:
        raise HTTPException(404, "虚拟航司不存在")
    return row


def _clean_logo_url(value: str) -> str:
    """Logo 地址白名单：本站上传路径或 http s 链接。

    该值会被前端写进 CSS url ...，必须挡掉 javascript:/data: 等可执行协议。
    """
    logo = (value or "").strip()[:300]
    if not logo:
        return ""
    if logo.startswith(("/uploads/", "http://", "https://")):
        return logo
    raise HTTPException(400, "Logo 地址无效，请重新上传图片")


def _require_ceo(conn, airline_id: int, user_id: int):
    m = conn.execute(
        "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
        (airline_id, user_id),
    ).fetchone()
    if not m or m["role"] != "ceo" or m["status"] != "active":
        raise HTTPException(403, "仅航司 CEO 可执行该操作")
    return m


def _require_manager(conn, airline_id: int, user_id: int):
    """航司管理操作鉴权：CEO 或 CEO 任命的部长均可。

    与 _require_ceo 的分工：解散 / 移除成员 / 任命部长 / 机队采购等敏感操作
    仍仅限 CEO；日常管理，审批 / 航线 / 设置 / 审核等允许部长代行。
    """
    m = conn.execute(
        "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
        (airline_id, user_id),
    ).fetchone()
    if not m or m["status"] != "active":
        raise HTTPException(403, "仅航司成员可执行该操作")
    if m["role"] != "ceo" and not m["minister"]:
        raise HTTPException(403, "仅航司 CEO 或部长可执行该操作")
    return m


def _summary(conn, a) -> dict:
    members = conn.execute(
        "SELECT COUNT(*) c FROM airline_members WHERE airline_id = ? AND status = 'active'",
        (a["id"],),
    ).fetchone()["c"]
    routes = conn.execute(
        "SELECT COUNT(*) c FROM airline_routes WHERE airline_id = ?", (a["id"],)
    ).fetchone()["c"]
    owner = conn.execute("SELECT username FROM users WHERE id = ?", (a["owner_id"],)).fetchone()
    return {
        "id": a["id"], "icao": a["icao"], "name": a["name"],
        "description": a["description"], "logo_url": a["logo_url"],
        "status": a["status"], "review_note": a["review_note"],
        "ceo": owner["username"] if owner else "",
        "member_count": members, "route_count": routes,
        "created_at": a["created_at"],
        # 对外主页自定义项，CEO 编辑器回填用
        "slogan": a["public_slogan"], "welcome": a["public_welcome"],
        "show_members": bool(a["show_members"]), "show_routes": bool(a["show_routes"]),
        "show_fleet": bool(a["show_fleet"]), "show_stats": bool(a["show_stats"]),
    }


class CreateBody(BaseModel):
    icao: str = Field("", max_length=8)
    name: str = Field("", max_length=40)
    description: str = Field("", max_length=300)
    logoUrl: str = Field("", max_length=300)


@router.get("")
def list_airlines(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM airlines WHERE status = 'approved' ORDER BY id DESC"
        ).fetchall()
        airlines = [_summary(conn, a) for a in rows]
        mine = _membership(conn, user["id"])
        # 我的待审批跳槽申请，含目标航司信息，用于列表页展示状态
        transfer = conn.execute(
            "SELECT t.*, a.icao AS to_icao, a.name AS to_name FROM airline_transfers t"
            " JOIN airlines a ON a.id = t.to_airline_id"
            " WHERE t.user_id = ? AND t.status = 'pending' ORDER BY t.id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    return {
        "ok": True,
        "airlines": airlines,
        "mine": dict(mine) if mine else None,
        "myTransfer": dict(transfer) if transfer else None,
    }


@router.get("/my/membership")
def my_membership(user: dict = Depends(require_auth)):
    """侧边栏/签派页用的轻量成员身份：已激活成员才返回，否则 null"""
    with get_conn() as conn:
        m = _membership(conn, user["id"])
        if not m or m["status"] != "active" or m["airline_status"] != "approved":
            return {"ok": True, "membership": None}
        return {
            "ok": True,
            "membership": {
                "airlineId": m["airline_id"], "icao": m["icao"], "name": m["name"], "role": m["role"],
                "balance": m["airline_balance"] or 0,
                "position": m["position"] or "",
                # 薪酬参数，结算公式公示用，CEO 在航司设置中调整
                "hourlyRate": m["hourly_rate"] if "hourly_rate" in m.keys() else 100,
                "distanceRate": m["distance_rate"] if "distance_rate" in m.keys() else 1,
            },
        }


@router.post("")
def create_airline(body: CreateBody, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "va-create", 5, 3600)
    icao = clean(body.icao, 8).upper()
    name = clean(body.name, 32)
    if not ICAO_RE.match(icao):
        raise HTTPException(400, "航司代码需 2-4 位字母/数字，如 CTY")
    if len(name) < 2:
        raise HTTPException(400, "请填写航司名称，至少 2 个字")

    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM airlines WHERE owner_id = ?", (user["id"],)).fetchone():
            raise HTTPException(400, "你已创建过虚拟航司")
        if _membership(conn, user["id"]):
            raise HTTPException(400, ICAO_PER_USER + "，请先退出当前航司")
        if conn.execute("SELECT 1 FROM airlines WHERE icao = ?", (icao,)).fetchone():
            raise HTTPException(400, f"航司代码 {icao} 已被使用")
        if _name_taken(conn, name):
            raise HTTPException(400, "航司名称已被使用，请换一个")

        cur = conn.execute(
            "INSERT INTO airlines (icao, name, description, logo_url, owner_id, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            (icao, name, clean(body.description, 300), _clean_logo_url(body.logoUrl), user["id"]),
        )
    _audit(request, "airline", "提交建司申请", actor=user, target_id=cur.lastrowid,
           detail=f"{icao} {name}")
    return {"ok": True, "id": cur.lastrowid, "message": "创建申请已提交，等待管理员审核"}


@router.get("/leaderboard")
def leaderboard(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        airlines = conn.execute(
            "SELECT a.id, a.icao, a.name, COUNT(m.id) AS members,"
            " COALESCE(SUM(w.total_hours), 0) AS hours FROM airlines a"
            " LEFT JOIN airline_members m ON m.airline_id = a.id AND m.status = 'active'"
            " LEFT JOIN wallets w ON w.user_id = m.user_id"
            " WHERE a.status = 'approved'"
            " GROUP BY a.id ORDER BY hours DESC, members DESC, a.id LIMIT 10"
        ).fetchall()
        pilots = conn.execute(
            "SELECT u.id, u.cid, u.username, u.avatar_url, u.equipped_title, u.equipped_badge,"
            " COUNT(*) AS events"
            " FROM event_signups s JOIN users u ON u.id = s.user_id"
            " GROUP BY s.user_id ORDER BY events DESC, u.id LIMIT 10"
        ).fetchall()
        hours = conn.execute(
            "SELECT w.user_id, u.cid, u.username, u.avatar_url, u.equipped_title, u.equipped_badge,"
            " w.total_hours AS hours"
            " FROM wallets w JOIN users u ON u.id = w.user_id"
            " WHERE w.total_hours > 0 ORDER BY w.total_hours DESC LIMIT 10"
        ).fetchall()
    return {
        "ok": True,
        "airlines": [dict(r) for r in airlines],
        "pilots": [dict(r) for r in pilots],
        "hours": [dict(r) for r in hours],
    }


@router.get("/{airline_id}")
def airline_detail(airline_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        a = _airline_or_404(conn, airline_id)
        if a["status"] == "pending" and user["id"] != a["owner_id"] and user["role"] != "admin":
            raise HTTPException(403, "该航司正在审核中")

        members = conn.execute(
            "SELECT m.id, m.role, m.status, m.position, m.minister, m.created_at, m.joined_at,"
            " u.id AS uid, u.cid, u.username, u.avatar_url, u.rating,"
            " u.pilot_rank, u.equipped_title, u.equipped_badge"
            " FROM airline_members m JOIN users u ON u.id = m.user_id"
            " WHERE m.airline_id = ? AND m.status = 'active' ORDER BY m.role = 'ceo' DESC, m.id",
            (airline_id,),
        ).fetchall()
        routes = conn.execute(
            "SELECT * FROM airline_routes WHERE airline_id = ? ORDER BY flight_no, id",
            (airline_id,),
        ).fetchall()
        my = _membership(conn, user["id"])
        is_ceo = bool(my) and my["airline_id"] == airline_id and my["role"] == "ceo"
        my_transfer = conn.execute(
            "SELECT * FROM airline_transfers WHERE user_id = ? AND to_airline_id = ?"
            " AND status = 'pending' LIMIT 1",
            (user["id"], airline_id),
        ).fetchone()
        # 加入申请：CEO 与部长均可查看，管理中心「待审批成员」数据源
        is_manager = is_ceo or (bool(my) and my["airline_id"] == airline_id
                                and my["status"] == "active" and bool(my["minister"]))
        applications = []
        if is_manager:
            applications = conn.execute(
                "SELECT m.id, m.created_at, u.cid, u.username, u.avatar_url, u.rating"
                " FROM airline_members m JOIN users u ON u.id = m.user_id"
                " WHERE m.airline_id = ? AND m.status = 'pending' ORDER BY m.id",
                (airline_id,),
            ).fetchall()
        summary = _summary(conn, a)

    return {
        "ok": True,
        "airline": summary,
        "hourlyRate": a["hourly_rate"],
        "distanceRate": a["distance_rate"],
        "positionOptions": POSITION_OPTIONS,
        "members": [dict(m) for m in members],
        "routes": [dict(r) for r in routes],
        "is_ceo": is_ceo,
        "my_membership": dict(my) if my else None,
        "my_transfer": dict(my_transfer) if my_transfer else None,
        "applications": [dict(x) for x in applications],
    }


@router.post("/{airline_id}/join")
def join_airline(airline_id: int, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "va-join", 10, 3600)
    with get_conn() as conn:
        a = _airline_or_404(conn, airline_id)
        if a["status"] != "approved":
            raise HTTPException(400, "该航司尚未通过审核")
        if _membership(conn, user["id"]):
            raise HTTPException(400, ICAO_PER_USER)
        if a["owner_id"] == user["id"]:
            raise HTTPException(400, "你是该航司的 CEO")

        my = _membership(conn, user["id"])
        if my:
            raise HTTPException(400, ICAO_PER_USER)
        conn.execute(
            "INSERT INTO airline_members (airline_id, user_id, role, status) VALUES (?, ?, 'pilot', 'pending')",
            (airline_id, user["id"]),
        )
    _audit(request, "airline", "申请加入航司", actor=user, target_id=airline_id,
           detail=f"{a['icao']} {a['name']}")
    # 邮件通知 CEO：有人申请加入
    notify_user(
        a["owner_id"],
        f"有人申请加入「{a['name']}」",
        f"飞行员 {user['username']}、CID {user['cid']}，申请加入你的航司「{a['name']}」。"
        f"\n请到 航司详情 → 成员管理 中审批。",
    )
    return {"ok": True, "message": "加入申请已提交，等待 CEO 审批"}


def _release_member_open_dispatches(conn, user_id: int) -> int:
    """成员离开航司前，取消其所有未完成，open 签派并释放占用的飞机。

    先查出受影响飞机 id 列表再更新，只释放本次取消的签派所占用、
    且仍处于 dispatched 状态的飞机，避免误放其他任务占用的飞机。
    返回取消的签派数量。
    """
    fleet_ids = [r["fleet_id"] for r in conn.execute(
        "SELECT fleet_id FROM dispatches WHERE user_id = ? AND status = 'open' AND fleet_id IS NOT NULL",
        (user_id,),
    ).fetchall()]
    if not fleet_ids:
        cur = conn.execute(
            "UPDATE dispatches SET status = 'cancelled' WHERE user_id = ? AND status = 'open'",
            (user_id,),
        )
        return cur.rowcount
    marks = ",".join("?" for _ in fleet_ids)
    cur = conn.execute(
        "UPDATE dispatches SET status = 'cancelled' WHERE user_id = ? AND status = 'open'",
        (user_id,),
    )
    conn.execute(
        f"UPDATE airline_fleet SET status = 'available' WHERE id IN ({marks}) AND status = 'dispatched'",
        fleet_ids,
    )
    return cur.rowcount


@router.post("/{airline_id}/leave")
def leave_airline(airline_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(404, "你不是该航司成员")
        if m["role"] == "ceo":
            raise HTTPException(400, "CEO 不能退出，可解散航司")
        # 退出前先处理其未完成的开放签派，防止悬挂签派占用机队
        _release_member_open_dispatches(conn, user["id"])
        conn.execute("DELETE FROM airline_members WHERE id = ?", (m["id"],))
    return {"ok": True, "message": "已退出该航司"}


@router.delete("/{airline_id}")
def disband_airline(airline_id: int, request: Request, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        a = _airline_or_404(conn, airline_id)
        if a["owner_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "仅 CEO 或管理员可解散航司")
        # 解散前取消全公司未完成签派并释放机队，避免悬挂签派/FK 残留
        conn.execute("UPDATE dispatches SET status = 'cancelled' WHERE airline_id = ? AND status = 'open'", (airline_id,))
        conn.execute(
            "UPDATE airline_fleet SET status = 'available' WHERE airline_id = ? AND status = 'dispatched'",
            (airline_id,),
        )
        # 通知全体成员，CEO 自己除外：航司已解散
        members = conn.execute(
            "SELECT user_id FROM airline_members WHERE airline_id = ? AND user_id != ?",
            (airline_id, user["id"]),
        ).fetchall()
        conn.execute("DELETE FROM airlines WHERE id = ?", (airline_id,))
    for mem in members:
        notify_user(
            mem["user_id"], f"航司「{a['name']}」已解散",
            f"你所在的虚拟航司「{a['name']}」（{a['icao']}）已被 CEO 解散。\n"
            f"你的未完成签派已自动取消，机队已归还公司。\n"
            f"欢迎加入其他航司，或创建属于你自己的航司。",
        )
    _audit(request, "airline", "解散航司", actor=user, target_id=airline_id,
           detail=f"{a['icao']} {a['name']}")
    return {"ok": True, "message": "航司已解散"}


# ---------- 跳槽，转司申请 ----------
#
# 设计：批准前仍留在原航司，避免审批期间出现「无航司」空档。
# 目标航司 CEO 批准后，系统原子地移除原成员关系并写入新成员关系。

def _transfer_row(conn, transfer_id: int):
    return conn.execute(
        "SELECT t.*, u.username, u.cid, u.avatar_url, u.rating, u.pilot_rank,"
        " u.equipped_title, u.equipped_badge"
        " FROM airline_transfers t JOIN users u ON u.id = t.user_id WHERE t.id = ?",
        (transfer_id,),
    ).fetchone()


class TransferBody(BaseModel):
    reason: str = Field("", max_length=200)


@router.post("/{airline_id}/transfer")
def request_transfer(airline_id: int, body: TransferBody, request: Request,
                           user: dict = Depends(require_auth)):
    """我是 A 航司成员，申请跳槽到 B 航司，等待 B 的 CEO 审批"""
    enforce(request, "va-transfer", 10, 3600)
    reason = clean(body.reason, 200)
    with get_conn() as conn:
        target = _airline_or_404(conn, airline_id)
        if target["status"] != "approved":
            raise HTTPException(400, "该航司尚未通过审核")
        if target["owner_id"] == user["id"]:
            raise HTTPException(400, "你是该航司的 CEO，无法跳槽到自己的航司")

        my = _membership(conn, user["id"])
        if not my:
            raise HTTPException(400, "你还未加入任何航司，请直接提交加入申请")
        if my["airline_id"] == airline_id:
            raise HTTPException(400, "你已经是该航司成员")
        if my["role"] == "ceo":
            raise HTTPException(400, "CEO 不能直接跳槽，请先解散航司或将职务移交")
        if my["status"] != "active":
            raise HTTPException(400, "你的加入申请仍在审核中，无法发起跳槽")

        dup = conn.execute(
            "SELECT 1 FROM airline_transfers WHERE user_id = ? AND status = 'pending'",
            (user["id"],),
        ).fetchone()
        if dup:
            raise HTTPException(400, "你已有一条待审批的跳槽申请")

        cur = conn.execute(
            "INSERT INTO airline_transfers"
            " (user_id, from_airline_id, from_icao, from_name, to_airline_id, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], my["airline_id"], my["icao"], my["name"], airline_id, reason),
        )
    _audit(request, "airline", "提交跳槽申请", actor=user, target_id=airline_id,
           detail=f"{my['icao']} → {target['icao']} · {reason}")
    # 邮件通知目标航司 CEO：有人申请跳槽进来
    notify_user(
        target["owner_id"],
        f"有人申请跳槽加入「{target['name']}」",
        f"飞行员 {user['username']}，CID {user['cid']}申请从 {my['icao']} 跳槽到你的航司「{target['name']}」"
        + (f"，理由：{reason}。" if reason else "。")
        + "\n请到 航司详情 → 跳槽审批 中处理。",
    )
    return {
        "ok": True, "id": cur.lastrowid,
        "message": f"跳槽申请已提交，等待 {target['icao']} 的 CEO 审批；审批通过前你仍在 {my['icao']}",
    }


@router.get("/{airline_id}/transfers")
def list_transfers(airline_id: int, user: dict = Depends(require_auth)):
    """CEO 看到本航司的转入申请；普通用户看到自己与该航司相关的申请"""
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        is_ceo = bool(m) and m["role"] == "ceo" and m["status"] == "active"
        if is_ceo:
            rows = conn.execute(
                "SELECT t.*, u.username, u.cid, u.avatar_url, u.rating, u.pilot_rank,"
                " u.equipped_title, u.equipped_badge FROM airline_transfers t"
                " JOIN users u ON u.id = t.user_id"
                " WHERE t.to_airline_id = ? ORDER BY t.status = 'pending' DESC, t.id DESC LIMIT 100",
                (airline_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.*, u.username, u.cid, u.avatar_url, u.rating, u.pilot_rank,"
                " u.equipped_title, u.equipped_badge FROM airline_transfers t"
                " JOIN users u ON u.id = t.user_id"
                " WHERE t.user_id = ? AND (t.to_airline_id = ? OR t.from_airline_id = ?)"
                " ORDER BY t.id DESC LIMIT 100",
                (user["id"], airline_id, airline_id),
            ).fetchall()
    return {"ok": True, "transfers": [dict(r) for r in rows], "isCeo": is_ceo}


class TransferReviewBody(BaseModel):
    action: str = Field("", max_length=8)
    reason: str = Field("", max_length=200)


@router.post("/{airline_id}/transfers/{transfer_id}/review")
def review_transfer(airline_id: int, transfer_id: int, body: TransferReviewBody,
                          request: Request, user: dict = Depends(require_auth)):
    """目标航司 CEO 审批跳槽申请；通过则原子完成转司"""
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        t = _transfer_row(conn, transfer_id)
        if not t or t["to_airline_id"] != airline_id:
            raise HTTPException(404, "跳槽申请不存在")

        if body.action == "reject":
            reason = clean(body.reason, 200)
            if not reason:
                raise HTTPException(400, "请填写驳回原因")
            cur = conn.execute(
                "UPDATE airline_transfers SET status = 'rejected', reject_reason = ?,"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (reason, user["id"], transfer_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该申请已处理")
            _audit(request, "airline", "驳回跳槽申请", actor=user, target_id=airline_id,
                   detail=f"uid={t['user_id']} · {reason}")
            to_name = conn.execute(
                "SELECT name FROM airlines WHERE id = ?", (airline_id,)
            ).fetchone()["name"]
            notify_user(
                t["user_id"], "你的跳槽申请未通过",
                f"你申请从「{t['from_name']}」跳槽至「{to_name}」的申请被对方 CEO 驳回。\n"
                f"驳回原因：{reason}",
            )
            return {"ok": True, "message": "已驳回该跳槽申请"}

        if body.action != "approve":
            raise HTTPException(400, "无效操作")

        # TOCTOU 复查：批准前在事务内确认飞行员没有其他 active 成员关系
        #如审批期间已加入别的航司，本申请作废，防止一人多司
        dup_member = conn.execute(
            "SELECT 1 FROM airline_members WHERE user_id = ? AND airline_id != ? AND status = 'active'",
            (t["user_id"], airline_id),
        ).fetchone()
        if dup_member:
            raise HTTPException(409, "该飞行员已加入其他航司，跳槽审批失效")

        # 先原子占住申请，仅 pending 可批准，并发双审时只有一方成功
        cur = conn.execute(
            "UPDATE airline_transfers SET status = 'approved', reject_reason = '',"
            " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
            " WHERE id = ? AND status = 'pending'",
            (user["id"], transfer_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "该申请已处理")
        # 移除原航司成员关系，若期间已自行退出则跳过
        if t["from_airline_id"]:
            conn.execute(
                "DELETE FROM airline_members WHERE airline_id = ? AND user_id = ? AND role != 'ceo'",
                (t["from_airline_id"], t["user_id"]),
            )
        # 写入目标航司成员关系
        exists = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, t["user_id"]),
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE airline_members SET role = 'pilot', status = 'active',"
                " joined_at = datetime('now','localtime') WHERE id = ?",
                (exists["id"],),
            )
        else:
            conn.execute(
                "INSERT INTO airline_members (airline_id, user_id, role, status, joined_at)"
                " VALUES (?, ?, 'pilot', 'active', datetime('now','localtime'))",
                (airline_id, t["user_id"]),
            )
        to_icao = conn.execute(
            "SELECT icao FROM airlines WHERE id = ?", (airline_id,)
        ).fetchone()["icao"]
    _audit(request, "airline", "批准跳槽申请", actor=user, target_id=airline_id,
           detail=f"uid={t['user_id']} · {t['from_icao']} → {to_icao}")
    notify_user(
        t["user_id"], "你的跳槽申请已通过",
        f"你从「{t['from_name']}」跳槽至「{to_icao}」的申请已被对方 CEO 接受，"
        f"原航司成员关系已解除，欢迎加入新航司。",
    )
    return {"ok": True, "message": f"已接收 {t['username']} 加入，原航司成员关系已解除"}


@router.post("/{airline_id}/transfers/{transfer_id}/cancel")
def cancel_transfer(airline_id: int, transfer_id: int, user: dict = Depends(require_auth)):
    """申请人撤销自己的跳槽申请"""
    with get_conn() as conn:
        t = conn.execute("SELECT * FROM airline_transfers WHERE id = ?", (transfer_id,)).fetchone()
        if not t or t["user_id"] != user["id"]:
            raise HTTPException(404, "跳槽申请不存在")
        if t["status"] != "pending":
            raise HTTPException(400, "该申请已处理，无法撤销")
        conn.execute(
            "UPDATE airline_transfers SET status = 'cancelled',"
            " reviewed_at = datetime('now','localtime') WHERE id = ?",
            (transfer_id,),
        )
    return {"ok": True, "message": "已撤销跳槽申请"}




class ReviewMemberBody(BaseModel):
    action: str = Field("", max_length=8)


@router.post("/{airline_id}/members/{member_id}/review")
def review_member(airline_id: int, member_id: int, body: ReviewMemberBody, request: Request,
                        user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        if body.action not in ("approve", "reject"):
            raise HTTPException(400, "无效操作")
        m = conn.execute(
            "SELECT * FROM airline_members WHERE id = ? AND airline_id = ?",
            (member_id, airline_id),
        ).fetchone()
        if not m:
            raise HTTPException(404, "申请不存在或已处理")
        if body.action == "approve":
            cur = conn.execute(
                "UPDATE airline_members SET status = 'active', joined_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (m["id"],),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该申请已被处理")
        else:
            conn.execute("DELETE FROM airline_members WHERE id = ? AND status = 'pending'", (m["id"],))
        airline_name = conn.execute(
            "SELECT name FROM airlines WHERE id = ?", (airline_id,)
        ).fetchone()["name"]
    passed = body.action == "approve"
    notify_user(
        m["user_id"],
        f"你加入「{airline_name}」的申请{'已通过' if passed else '未通过'}",
        (f"你申请加入航司「{airline_name}」的结果：{'已通过，欢迎加入' if passed else '被管理层驳回'}。"
         + ("" if passed else "\n可浏览其它航司后重新申请。")),
    )
    _audit(request, "airline", f"成员申请{'通过' if body.action == 'approve' else '拒绝'}",
           actor=user, target_id=airline_id, detail=f"成员 uid={m['user_id']}")
    return {"ok": True}


# 设置成员职位：CEO 专属；职位必须来自现实阶梯，或留空清除
class PositionBody(BaseModel):
    position: str = Field("", max_length=12)


@router.put("/{airline_id}/members/{member_id}/position")
def set_member_position(airline_id: int, member_id: int, body: PositionBody,
                              user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        m = conn.execute(
            "SELECT * FROM airline_members WHERE id = ? AND airline_id = ? AND status = 'active'",
            (member_id, airline_id),
        ).fetchone()
        if not m:
            raise HTTPException(404, "成员不存在")
        if m["role"] == "ceo":
            raise HTTPException(400, "CEO 的职位就是 CEO，无需设置")
        position = clean(body.position, 12)
        if position and position not in POSITION_OPTIONS:
            raise HTTPException(400, "职位无效，请从职位列表中选择")
        conn.execute("UPDATE airline_members SET position = ? WHERE id = ?", (position, m["id"]))
    return {"ok": True, "message": (f"职位已设为 {position}" if position else "已清除职位，默认飞行员")}


@router.delete("/{airline_id}/members/{user_id}")
def remove_member(airline_id: int, user_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user_id),
        ).fetchone()
        if not m:
            raise HTTPException(404, "该用户不是航司成员")
        if m["role"] == "ceo":
            raise HTTPException(400, "不能移除 CEO")
        # 移除前先处理其未完成的开放签派，防止悬挂签派占用机队
        _release_member_open_dispatches(conn, user_id)
        conn.execute("DELETE FROM airline_members WHERE id = ?", (m["id"],))
        a = conn.execute("SELECT name, icao FROM airlines WHERE id = ?", (airline_id,)).fetchone()
    notify_user(
        user_id, f"你已被移出「{a['name']}」",
        f"你已被 CEO 移出虚拟航司「{a['name']}」（{a['icao']}）。\n"
        f"你的未完成签派已自动取消，机队已归还公司。\n"
        f"如对此有异议，请联系航司 CEO，或通过工单中心联系我们。",
    )
    return {"ok": True, "message": "已移除该成员"}


class MinisterBody(BaseModel):
    on: bool = False


@router.post("/{airline_id}/members/{member_id}/minister")
def set_member_minister(airline_id: int, member_id: int, body: MinisterBody,
                              request: Request, user: dict = Depends(require_auth)):
    """任命 / 取消部长，仅 CEO。部长可代行航司日常管理，敏感操作仍限 CEO"""
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        m = conn.execute(
            "SELECT m.*, u.username FROM airline_members m"
            " JOIN users u ON u.id = m.user_id"
            " WHERE m.id = ? AND m.airline_id = ? AND m.status = 'active'",
            (member_id, airline_id),
        ).fetchone()
        if not m:
            raise HTTPException(404, "成员不存在")
        if m["role"] == "ceo":
            raise HTTPException(400, "CEO 无需任命部长")
        if m["minister"] == (1 if body.on else 0):
            return {"ok": True, "message": "状态未变化"}
        conn.execute(
            "UPDATE airline_members SET minister = ? WHERE id = ?",
            (1 if body.on else 0, member_id),
        )
        a = conn.execute("SELECT name FROM airlines WHERE id = ?", (airline_id,)).fetchone()
    log_event(
        "airline", ("任命部长" if body.on else "取消部长") + f"「{a['name']}」",
        actor=user, target_type="user", target_id=m["user_id"],
        detail=f"{m['username']}（uid {m['user_id']}）",
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    if body.on:
        notify_user(
            m["user_id"], f"你已被任命为「{a['name']}」部长",
            f"CEO 已任命你为虚拟航司「{a['name']}」的部长。\n"
            f"你可以代行航司日常管理（成员审批 / 航线 / 报告与考核审核 / 对外主页等），\n"
            f"解散、移除成员等敏感操作仍由 CEO 执行。",
        )
    return {"ok": True, "message": ("已任命为部长" if body.on else "已取消部长")}


class RouteBody(BaseModel):
    flightNo: str = Field("", max_length=10)
    dep: str = Field("", max_length=4)
    arr: str = Field("", max_length=4)
    aircraft: str = Field("", max_length=16)
    notes: str = Field("", max_length=200)
    baseSalary: int = Field(200, ge=0, le=10000)
    intl: bool = False


@router.post("/{airline_id}/routes")
def add_route(airline_id: int, body: RouteBody, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        dep, arr = clean(body.dep, 4).upper(), clean(body.arr, 4).upper()
        if not re.match(r"^[A-Z0-9]{4}$", dep) or not re.match(r"^[A-Z0-9]{4}$", arr):
            raise HTTPException(400, "出发与到达机场必须为 4 位 ICAO 代码")
        if dep == arr:
            raise HTTPException(400, "出发与到达机场不能相同")
        flight_no = clean(body.flightNo, 10).upper()
        distance = navdistance.airport_distance_nm(dep, arr)  # AIRAC 真实大圆距离，无数据时为 None
        cur = conn.execute(
            "INSERT INTO airline_routes (airline_id, flight_no, dep, arr, aircraft, notes, base_salary, distance_nm, intl)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (airline_id, flight_no, dep, arr, clean(body.aircraft, 16).upper(), clean(body.notes, 200),
             body.baseSalary, distance, 1 if body.intl else 0),
        )
    return {"ok": True, "id": cur.lastrowid, "distanceNm": distance}


@router.post("/{airline_id}/routes/import")
async def import_routes_csv(airline_id: int, request: Request, file: UploadFile = File(...),
                            user: dict = Depends(require_auth)):
    """CSV 批量导入航线，Newsky 排班表导出格式兼容。

    安全约束：仅限航司管理角色；文件 ≤512KB；≤500 行数据；
    逐行严格校验，航班号仅字母数字、机场 4 位 ICAO，杜绝 CSV 公式注入。
    """
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])

    raw = await file.read()
    if len(raw) > 512 * 1024:
        raise HTTPException(400, "文件过大，上限 512KB")
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "仅支持 .csv 文件")

    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")   # 跳过注释与空行
    ))
    if not rows:
        raise HTTPException(400, "未解析到有效数据行")
    if len(rows) > 500:
        raise HTTPException(400, f"单次最多导入 500 行，当前 {len(rows)} 行")
    if not all(k in rows[0] for k in ("number", "dep", "arr")):
        raise HTTPException(400, "CSV 缺少必需列：number / dep / arr")

    imported, skipped, errors = 0, 0, []
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        existing = {
            r["flight_no"] for r in conn.execute(
                "SELECT flight_no FROM airline_routes WHERE airline_id = ?", (airline_id,)
            ).fetchall()
        }
        seen = set()
        for i, row in enumerate(rows):
            line_no = i + 1
            no = (row.get("number") or "").strip().upper()
            dep = (row.get("dep") or "").strip().upper()
            arr = (row.get("arr") or "").strip().upper()
            ftype = (row.get("type") or "").strip().lower()[:16]
            if not no or not dep or not arr:
                errors.append(f"第 {line_no} 行：字段缺失")
                skipped += 1
                continue
            if not re.match(r"^[A-Z0-9]{1,10}$", no):
                errors.append(f"第 {line_no} 行：航班号「{no[:20]}」格式无效")
                skipped += 1
                continue
            if not re.match(r"^[A-Z0-9]{4}$", dep) or not re.match(r"^[A-Z0-9]{4}$", arr):
                errors.append(f"第 {line_no} 行：机场代码「{dep[:20]}→{arr[:20]}」格式无效")
                skipped += 1
                continue
            if dep == arr:
                errors.append(f"第 {line_no} 行：起降机场相同")
                skipped += 1
                continue
            if no in existing or no in seen:
                errors.append(f"第 {line_no} 行：航班号 {no} 重复，已跳过")
                skipped += 1
                continue
            distance = navdistance.airport_distance_nm(dep, arr)
            intl = 1 if (dep[:1] != "Z" or arr[:1] != "Z") else 0
            conn.execute(
                "INSERT INTO airline_routes (airline_id, flight_no, dep, arr, aircraft, notes, base_salary, distance_nm, intl)"
                " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (airline_id, no, dep, arr, "", f"机型类别：{ftype}" if ftype else "", distance, intl),
            )
            seen.add(no)
            imported += 1

    _audit(request, "airline", f"CSV 批量导入航线，成功 {imported} / 跳过 {skipped}",
           actor=user, target_id=airline_id, detail=f"文件 {file.filename}")
    return {
        "ok": True, "imported": imported, "skipped": skipped,
        "errors": errors[:20],
        "message": f"导入完成：成功 {imported} 条，跳过 {skipped} 条",
    }


class SettingsBody(BaseModel):
    # 经济上限：时薪/里程补贴收紧天花板，防止 CEO 调参自铸货币
    hourlyRate: int = Field(100, ge=1, le=2000)
    distanceRate: int = Field(1, ge=0, le=100)
    logoUrl: str | None = Field(None, max_length=300)
    hub: str | None = Field(None, max_length=4)


@router.put("/{airline_id}/settings")
def update_settings(airline_id: int, body: SettingsBody, request: Request,
                          user: dict = Depends(require_auth)):
    with get_conn() as conn:
        # 仅 CEO：时薪 / 距离补贴直接决定全公司工资支出，属资金敏感参数。
        # 2026-10-05 前这里是 _require_manager，等于部长也能改 —— 而 UI 那张卡一直是
        # v-if="isCeo"，形成「能改钱、没入口」的口径不一致。按站长决定收窄为 CEO。
        _require_ceo(conn, airline_id, user["id"])
        conn.execute(
            "UPDATE airlines SET hourly_rate = ?, distance_rate = ? WHERE id = ?",
            (body.hourlyRate, body.distanceRate, airline_id),
        )
        logo_changed = body.logoUrl is not None
        if logo_changed:
            conn.execute(
                "UPDATE airlines SET logo_url = ? WHERE id = ?",
                (_clean_logo_url(body.logoUrl or ""), airline_id),
            )
        hub_changed = body.hub is not None
        if hub_changed:
            hub = body.hub.strip().upper()
            if hub and (len(hub) != 4 or not hub.isalnum()):
                raise HTTPException(400, "主基地需为 4 位 ICAO 机场代码，如 ZBAA")
            conn.execute("UPDATE airlines SET hub = ? WHERE id = ?", (hub, airline_id))
            # 主基地变更：驻场飞机整体迁移到新主基地，仅限空闲飞机
            if hub:
                conn.execute(
                    "UPDATE airline_fleet SET location = ?"
                    " WHERE airline_id = ? AND location = '' AND status = 'available'",
                    (hub, airline_id),
                )
    _audit(request, "airline", "修改航司设置", actor=user, target_id=airline_id,
           detail=f"时薪={body.hourlyRate} 距离补贴={body.distanceRate}"
                  + (" · 更新 Logo" if logo_changed else "")
                  + (f" · 主基地={body.hub}" if hub_changed else ""))
    return {"ok": True, "hourlyRate": body.hourlyRate, "distanceRate": body.distanceRate,
            "hub": body.hub if hub_changed else None,
            "logoUrl": _clean_logo_url(body.logoUrl) if logo_changed else None}


@router.delete("/{airline_id}/routes/{route_id}")
def delete_route(airline_id: int, route_id: int, request: Request,
                       user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        row = conn.execute(
            "SELECT flight_no, dep, arr FROM airline_routes WHERE id = ? AND airline_id = ?",
            (route_id, airline_id),
        ).fetchone()
        conn.execute(
            "DELETE FROM airline_routes WHERE id = ? AND airline_id = ?", (route_id, airline_id)
        )
    # 删除航线此前完全不留痕：2026-10-05 生产 CWF 航司 78→75 条，缺 0173/0174/0151
    # 无法追溯是谁在何时删的，就是这里没有 _audit。仅在实际删到行时记录。
    if row:
        no = (row["flight_no"] or "").strip()
        _audit(request, "airline", "删除航线", actor=user, target_id=airline_id,
               detail=f"{no} · {row['dep']} → {row['arr']}" if no
               else f"{row['dep']} → {row['arr']}，无航班号")
    return {"ok": True}


# ---------- 飞行报告与薪酬 ----------

def _report_row(conn, rid: int, airline_id: int):
    r = conn.execute(
        "SELECT * FROM flight_reports WHERE id = ? AND airline_id = ?", (rid, airline_id)
    ).fetchone()
    if not r:
        raise HTTPException(404, "飞行报告不存在")
    return r


class ReportBody(BaseModel):
    routeId: int = Field(0, ge=0)
    aircraft: str = Field("", max_length=16)
    hours: float = Field(0, ge=0.1, le=24)
    flightDate: str = Field("", max_length=10)
    notes: str = Field("", max_length=200)
    dispatchId: int = Field(0, ge=0)


# ---------- 签派，放行单与机队 ----------



class FleetPurchaseBody(BaseModel):
    aircraft: str = Field("", max_length=8)




class DispatchBody(BaseModel):
    routeId: int = Field(0, ge=0)
    fleetId: int = Field(0, ge=0)
    captain: str = Field("", max_length=32)
    callsign: str = Field("", max_length=16)
    schedDep: str = Field("", max_length=16)
    pax: int = Field(0, ge=0, le=600)
    cargo: int = Field(0, ge=0, le=40000)
    copilot: str = Field("", max_length=32)
    ci: int = Field(0, ge=0, le=999)
    depRwy: str = Field("", max_length=8)
    arrRwy: str = Field("", max_length=8)
    cruiseAlt: int = Field(0, ge=0, le=60000)
    fuelKg: int = Field(0, ge=0, le=500000)
    alternate: str = Field("", max_length=8)
    remarks: str = Field("", max_length=200)
    routeString: str = Field("", max_length=600)


@router.get("/{airline_id}/routes")
def list_routes(airline_id: int, user: dict = Depends(require_auth)):
    """成员侧航线列表，CEO 在航司详情页维护，成员只读"""
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可查看航线列表")
        routes = conn.execute(
            "SELECT * FROM airline_routes WHERE airline_id = ? ORDER BY flight_no, id",
            (airline_id,),
        ).fetchall()
    return {"ok": True, "routes": [dict(r) for r in routes]}




class FerryBody(BaseModel):
    to: str = Field(..., min_length=4, max_length=4)




class CharterBody(BaseModel):
    dep: str = Field(..., min_length=4, max_length=4)
    arr: str = Field(..., min_length=4, max_length=4)
    fleetId: int = Field(0, ge=0)
    pax: int = Field(0, ge=0, le=600)
    cargo: int = Field(0, ge=0, le=40000)




class FlightEventBody(BaseModel):
    type: str = Field(..., pattern="^(depart|arrive)$")
    token: str = Field(..., min_length=8, max_length=64)








class ReviewReportBody(BaseModel):
    action: str = Field("", max_length=8)
    reason: str = Field("", max_length=200)


@router.get("/{airline_id}/stats")
def airline_stats(airline_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        totals = conn.execute(
            "SELECT COUNT(*) AS reports, COALESCE(SUM(hours), 0) AS hours,"
            " COALESCE(SUM(CASE WHEN status = 'approved' THEN amount ELSE 0 END), 0) AS payout"
            " FROM flight_reports WHERE airline_id = ? AND status = 'approved'",
            (airline_id,),
        ).fetchone()
        per_member = conn.execute(
            "SELECT u.username, u.cid, u.avatar_url, COALESCE(SUM(r.hours), 0) AS hours,"
            " COALESCE(SUM(r.amount), 0) AS earned"
            " FROM airline_members m JOIN users u ON u.id = m.user_id"
            " LEFT JOIN flight_reports r ON r.user_id = m.user_id AND r.airline_id = m.airline_id AND r.status = 'approved'"
            " WHERE m.airline_id = ? AND m.status = 'active'"
            " GROUP BY m.user_id ORDER BY hours DESC",
            (airline_id,),
        ).fetchall()
        arow = conn.execute(
            "SELECT hourly_rate, balance FROM airlines WHERE id = ?", (airline_id,)
        ).fetchone()
        hourly_rate = arow["hourly_rate"]
    return {
        "ok": True,
        "reports": totals["reports"], "totalHours": round(totals["hours"], 2),
        "totalPayout": totals["payout"], "hourlyRate": hourly_rate,
        "balance": arow["balance"] or 0,
        "perMember": [dict(r) for r in per_member],
    }


# ---------- 我的钱包 ----------


# ---------- 月度工资单导出，CSV ----------

# ---------- 公司资金账本，CEO / 部长，只读 ----------

# 账本每页条数：硬编码，不接受用户传入
#运维手册血泪清单 §8.7：「限定后端无用户可控分页参数，全部硬编码 LIMIT」；
# page 只是页码，按 admin.py 日志接口同款做 1..10000 钳制
LEDGER_PAGE_SIZE = 30




# ---------- 升级考核 ----------

# 等级与最低累计时长，等级取值即 permissions.PILOT_RANKS
RANK_REQUIREMENTS = {"机长": 50, "教员": 200}


def _total_hours(conn, user_id: int) -> float:
    w = conn.execute("SELECT total_hours FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    return w["total_hours"] if w else 0.0


def _next_rank(conn, user_id: int) -> str | None:
    """根据当前 pilot_rank 与累计时长，返回可申请的下一等级，无则 None"""
    u = conn.execute("SELECT pilot_rank FROM users WHERE id = ?", (user_id,)).fetchone()
    current = u["pilot_rank"] if u else PILOT_RANKS[0]
    hours = _total_hours(conn, user_id)
    if current in ("学员", "副驾驶") and hours >= RANK_REQUIREMENTS["机长"]:
        return "机长"
    if current == "机长" and hours >= RANK_REQUIREMENTS["教员"]:
        return "教员"
    return None


class ExamBody(BaseModel):
    flightDate: str = Field("", max_length=10)
    routeFlown: str = Field("", max_length=120)
    aircraft: str = Field("", max_length=16)
    notes: str = Field("", max_length=300)


@router.post("/{airline_id}/exams")
def submit_exam(airline_id: int, body: ExamBody, request: Request,
                      user: dict = Depends(require_auth)):
    enforce(request, "exam", 10, 3600)
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可提交考核")

        target = _next_rank(conn, user["id"])
        if not target:
            hours = _total_hours(conn, user["id"])
            raise HTTPException(400, f"暂无可申请的等级，或时长未达标，机长需 ≥50h，教员需 ≥200h，当前 {hours}h")

        dup = conn.execute(
            "SELECT 1 FROM rank_exams WHERE airline_id = ? AND user_id = ? AND target_rank = ? AND status = 'pending'",
            (airline_id, user["id"], target),
        ).fetchone()
        if dup:
            raise HTTPException(400, f"你已有一个待审核的{target}考核")

        cur = conn.execute(
            "INSERT INTO rank_exams (airline_id, user_id, target_rank, flight_date, route_flown, aircraft, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (airline_id, user["id"], target, clean(body.flightDate, 10),
             clean(body.routeFlown, 120), clean(body.aircraft, 16).upper(), clean(body.notes, 300)),
        )
    return {"ok": True, "id": cur.lastrowid, "targetRank": target, "message": f"{target}考核已提交，等待 CEO 审核"}


@router.get("/{airline_id}/exams")
def list_exams(airline_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        # 考核列表：CEO 与部长可看全航司，成员仅看自己的
        is_manager = bool(m) and m["status"] == "active" and (
            m["role"] == "ceo" or bool(m["minister"])
        )

        where, args = "airline_id = ?", [airline_id]
        if not is_manager:
            where += " AND user_id = ?"
            args.append(user["id"])
        rows = conn.execute(
            f"SELECT e.*, u.username, u.cid, u.avatar_url FROM rank_exams e"
            f" JOIN users u ON u.id = e.user_id WHERE {where} ORDER BY e.id DESC LIMIT 100",
            args,
        ).fetchall()

        # 本人晋升进度，成员与 CEO 各自看到自己的：当前等级 / 累计时长 / 下一考核目标
        u = conn.execute("SELECT pilot_rank FROM users WHERE id = ?", (user["id"],)).fetchone()
        rank = u["pilot_rank"] if u else PILOT_RANKS[0]
        hours = _total_hours(conn, user["id"])
        if rank in ("学员", "副驾驶"):
            target, target_hours = "机长", RANK_REQUIREMENTS["机长"]
        elif rank == "机长":
            target, target_hours = "教员", RANK_REQUIREMENTS["教员"]
        else:
            target, target_hours = None, None
        has_pending = bool(conn.execute(
            "SELECT 1 FROM rank_exams WHERE airline_id = ? AND user_id = ? AND status = 'pending'",
            (airline_id, user["id"]),
        ).fetchone())
    return {
        "ok": True,
        "exams": [dict(r) for r in rows],
        "me": {
            "pilotRank": rank,
            "totalHours": hours,
            "target": target,
            "targetHours": target_hours,
            "hasPending": has_pending,
        },
    }


class ExamReviewBody(BaseModel):
    action: str = Field("", max_length=10)
    reason: str = Field("", max_length=200)


@router.post("/{airline_id}/exams/{exam_id}/review")
def review_exam(airline_id: int, exam_id: int, body: ExamReviewBody, request: Request,
                      user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        e = conn.execute(
            "SELECT * FROM rank_exams WHERE id = ? AND airline_id = ?", (exam_id, airline_id)
        ).fetchone()
        if not e:
            raise HTTPException(404, "考核不存在")

        if body.action == "approve":
            cur = conn.execute(
                "UPDATE rank_exams SET status = 'approved', reject_reason = '',"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (user["id"], e["id"]),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该考核已被处理")
            conn.execute(
                "UPDATE users SET pilot_rank = ? WHERE id = ?", (e["target_rank"], e["user_id"]),
            )
            _audit(request, "airline", f"考核通过，晋升{e['target_rank']}", actor=user,
                   target_id=airline_id, detail=f"成员 uid={e['user_id']}")
            notify_user(
                e["user_id"], "恭喜，你的等级考核已通过",
                f"你的{e['target_rank']}考核已通过审核，等级已晋升为「{e['target_rank']}」。",
            )
            return {"ok": True, "message": f"已通过，{e['target_rank']}晋升生效"}

        if body.action == "reject":
            if not body.reason.strip():
                raise HTTPException(400, "请填写驳回原因")
            cur = conn.execute(
                "UPDATE rank_exams SET status = 'rejected', reject_reason = ?,"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime')"
                " WHERE id = ? AND status = 'pending'",
                (clean(body.reason, 200), user["id"], e["id"]),
            )
            if cur.rowcount == 0:
                raise HTTPException(409, "该考核已被处理")
            _audit(request, "airline", f"驳回{e['target_rank']}考核", actor=user,
                   target_id=airline_id, detail=f"uid={e['user_id']} · {clean(body.reason, 100)}")
            notify_user(
                e["user_id"], "你的等级考核未通过",
                f"你的{e['target_rank']}考核未通过本次评审。\n"
                f"评审意见：{clean(body.reason, 200)}\n可按要求准备后再次申请考核。",
            )
            return {"ok": True, "message": "已驳回"}

        raise HTTPException(400, "无效操作")


# ---------- 航司内部动态 ----------

@router.get("/{airline_id}/posts")
def list_posts(airline_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = conn.execute(
            "SELECT status FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可查看内部动态")

        posts = conn.execute(
            "SELECT p.*, u.username AS author_name, u.cid AS author_cid, u.avatar_url AS author_avatar,"
            " u.pilot_rank AS author_rank,"
            " (SELECT COUNT(*) FROM airline_post_likes l WHERE l.post_id = p.id) AS like_count,"
            " EXISTS(SELECT 1 FROM airline_post_likes l WHERE l.post_id = p.id AND l.user_id = ?) AS liked"
            " FROM airline_posts p JOIN users u ON u.id = p.author_id"
            " WHERE p.airline_id = ?"
            " ORDER BY p.pinned DESC, p.id DESC LIMIT 50",
            (user["id"], airline_id),
        ).fetchall()

        result = []
        for p in posts:
            item = dict(p)
            comments = conn.execute(
                "SELECT c.*, u.username, u.avatar_url FROM airline_post_comments c"
                " JOIN users u ON u.id = c.user_id WHERE c.post_id = ? ORDER BY c.id",
                (p["id"],),
            ).fetchall()
            item["comments"] = [dict(c) for c in comments]
            result.append(item)
    return {"ok": True, "posts": result}


class PostBody(BaseModel):
    content: str = Field("", max_length=1000)


@router.post("/{airline_id}/posts")
def create_post(airline_id: int, body: PostBody, request: Request,
                      user: dict = Depends(require_auth)):
    content = clean(body.content, 1000)
    if not content:
        raise HTTPException(400, "内容不能为空")
    with get_conn() as conn:
        m = conn.execute(
            "SELECT status FROM airline_members WHERE airline_id = ? AND user_id = ?",
            (airline_id, user["id"]),
        ).fetchone()
        if not m or m["status"] != "active":
            raise HTTPException(403, "仅航司成员可发布动态")
        cur = conn.execute(
            "INSERT INTO airline_posts (airline_id, author_id, content) VALUES (?, ?, ?)",
            (airline_id, user["id"], content),
        )
    _audit(request, "airline", "发布航司动态", actor=user, target_id=airline_id,
           detail=content[:80])
    return {"ok": True, "id": cur.lastrowid}


@router.post("/{airline_id}/posts/{post_id}/like")
def toggle_like(airline_id: int, post_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        # 越权防护：动态必须属于该航司，且操作者是该航司 active 成员
        if not conn.execute(
            "SELECT 1 FROM airline_posts WHERE id = ? AND airline_id = ?",
            (post_id, airline_id),
        ).fetchone():
            raise HTTPException(404, "动态不存在")
        m = conn.execute(
            "SELECT 1 FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可点赞")
        liked = conn.execute(
            "SELECT 1 FROM airline_post_likes WHERE post_id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if liked:
            conn.execute("DELETE FROM airline_post_likes WHERE post_id = ? AND user_id = ?", (post_id, user["id"]))
            return {"ok": True, "liked": False}
        conn.execute("INSERT INTO airline_post_likes (post_id, user_id) VALUES (?, ?)", (post_id, user["id"]))
    return {"ok": True, "liked": True}


class CommentBody(BaseModel):
    content: str = Field("", max_length=300)


@router.post("/{airline_id}/posts/{post_id}/comments")
def add_comment(airline_id: int, post_id: int, body: CommentBody,
                      user: dict = Depends(require_auth)):
    content = clean(body.content, 300)
    if not content:
        raise HTTPException(400, "评论不能为空")
    with get_conn() as conn:
        # 越权防护：动态必须属于该航司，且操作者是该航司 active 成员
        if not conn.execute(
            "SELECT 1 FROM airline_posts WHERE id = ? AND airline_id = ?",
            (post_id, airline_id),
        ).fetchone():
            raise HTTPException(404, "动态不存在")
        m = conn.execute(
            "SELECT 1 FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
            (airline_id, user["id"]),
        ).fetchone()
        if not m:
            raise HTTPException(403, "仅航司成员可评论")
        cur = conn.execute(
            "INSERT INTO airline_post_comments (post_id, user_id, content) VALUES (?, ?, ?)",
            (post_id, user["id"], content),
        )
        c = conn.execute(
            "SELECT c.*, u.username FROM airline_post_comments c JOIN users u ON u.id = c.user_id WHERE c.id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return {"ok": True, "comment": dict(c)}


@router.delete("/{airline_id}/posts/{post_id}")
def delete_post(airline_id: int, post_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        p = conn.execute(
            "SELECT * FROM airline_posts WHERE id = ? AND airline_id = ?", (post_id, airline_id)
        ).fetchone()
        if not p:
            raise HTTPException(404, "动态不存在")
        is_ceo = _require_manager(conn, airline_id, user["id"])
        if p["author_id"] != user["id"] and not is_ceo:
            raise HTTPException(403, "仅作者或 CEO 可删除")
        conn.execute("DELETE FROM airline_posts WHERE id = ?", (post_id,))
    return {"ok": True}


class PinBody(BaseModel):
    pinned: bool = False


@router.post("/{airline_id}/posts/{post_id}/pin")
def pin_post(airline_id: int, post_id: int, body: PinBody, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        # 越权防护：动态必须属于该航司，UPDATE 限定 airline_id
        if not conn.execute(
            "SELECT 1 FROM airline_posts WHERE id = ? AND airline_id = ?",
            (post_id, airline_id),
        ).fetchone():
            raise HTTPException(404, "动态不存在")
        conn.execute(
            "UPDATE airline_posts SET pinned = ? WHERE id = ? AND airline_id = ?",
            (1 if body.pinned else 0, post_id, airline_id),
        )
    return {"ok": True}


# ---------- 对外航司主页，无需登录 ----------

@router.get("/public/{icao}")
def public_airline(icao: str):
    icao = icao.strip().upper()[:4]
    with get_conn() as conn:
        a = conn.execute(
            "SELECT * FROM airlines WHERE icao = ? AND status = 'approved'", (icao,)
        ).fetchone()
        if not a:
            raise HTTPException(404, "虚拟航司不存在或未上线")

        members = conn.execute(
            "SELECT u.username, u.cid, u.pilot_rank, m.role,"
            " u.equipped_title, u.equipped_badge FROM airline_members m"
            " JOIN users u ON u.id = m.user_id"
            " WHERE m.airline_id = ? AND m.status = 'active'"
            " ORDER BY m.role = 'ceo' DESC, m.id",
            (a["id"],),
        ).fetchall()
        routes = conn.execute(
            "SELECT flight_no, dep, arr, aircraft, base_salary FROM airline_routes"
            " WHERE airline_id = ? ORDER BY flight_no, id",
            (a["id"],),
        ).fetchall()
        stats = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) AS total_hours, COUNT(*) AS total_flights"
            " FROM flight_reports WHERE airline_id = ? AND status = 'approved'",
            (a["id"],),
        ).fetchone()
        owner = conn.execute("SELECT username FROM users WHERE id = ?", (a["owner_id"],)).fetchone()

    fleet = sorted(set(r["aircraft"] for r in routes if r["aircraft"]))
    # 板块开关：关闭的板块连数据都不下发，访客看不到，也无法从接口拿
    show_members = bool(a["show_members"])
    show_routes = bool(a["show_routes"])
    show_fleet = bool(a["show_fleet"])
    show_stats = bool(a["show_stats"])
    return {
        "ok": True,
        "airline": {
            "icao": a["icao"], "name": a["name"], "description": a["description"],
            "logo_url": a["logo_url"], "ceo": owner["username"] if owner else "",
            "slogan": a["public_slogan"], "welcome": a["public_welcome"],
            "showMembers": show_members, "showRoutes": show_routes,
            "showFleet": show_fleet, "showStats": show_stats,
            "memberCount": len(members), "routeCount": len(routes),
            # 统计板块开关：关闭时不下发统计数值，与 members/routes 过滤口径一致
            "totalHours": round(stats["total_hours"], 1) if show_stats else None,
            "totalFlights": stats["total_flights"] if show_stats else None,
            "fleet": fleet if show_fleet else [], "createdAt": a["created_at"],
        },
        "members": [dict(m) for m in members] if show_members else [],
        "routes": [dict(r) for r in routes] if show_routes else [],
    }


class PublicPageBody(BaseModel):
    """对外主页自定义内容，仅 CEO 可改"""
    name: str = Field("", max_length=40)
    description: str = Field("", max_length=300)
    slogan: str = Field("", max_length=60)
    welcome: str = Field("", max_length=500)
    showMembers: bool = True
    showRoutes: bool = True
    showFleet: bool = True
    showStats: bool = True


@router.put("/{airline_id}/public-page")
def update_public_page(airline_id: int, body: PublicPageBody, request: Request,
                             user: dict = Depends(require_auth)):
    """CEO 自定义对外主页：名称/简介/标语/欢迎语 + 板块显示开关"""
    name = clean(body.name, 40)
    if len(name) < 2:
        raise HTTPException(400, "航司名称至少 2 个字")
    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        # 改名同样要唯一，排除自己，否则改回原名会被误判为重复
        if _name_taken(conn, name, exclude_id=airline_id):
            raise HTTPException(400, "航司名称已被使用，请换一个")
        conn.execute(
            "UPDATE airlines SET name = ?, description = ?, public_slogan = ?, public_welcome = ?,"
            " show_members = ?, show_routes = ?, show_fleet = ?, show_stats = ? WHERE id = ?",
            (name, clean(body.description, 300), clean(body.slogan, 60),
             clean(body.welcome, 500), 1 if body.showMembers else 0,
             1 if body.showRoutes else 0, 1 if body.showFleet else 0,
             1 if body.showStats else 0, airline_id),
        )
    sections = [label for label, flag in (("成员", body.showMembers), ("航线", body.showRoutes),
                                          ("机队", body.showFleet), ("统计", body.showStats)) if flag]
    visible_sections = "/".join(sections) if sections else "全部隐藏"
    _audit(request, "airline", "修改对外主页", actor=user, target_id=airline_id,
           detail=f"名称={name} · 板块={visible_sections}")
    return {"ok": True, "message": "对外主页已更新"}


# ---------- 管理员：建司审核 ----------

@router.get("/admin/list")
def admin_list(status: str = "pending", _: dict = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.*, u.username AS owner_name, u.cid AS owner_cid FROM airlines a"
            " JOIN users u ON u.id = a.owner_id"
            " WHERE (? = '' OR a.status = ?) ORDER BY a.id DESC LIMIT 200",
            (status, status),
        ).fetchall()
    return {"ok": True, "airlines": [dict(r) for r in rows]}


class ReviewAirlineBody(BaseModel):
    action: str = Field("", max_length=8)
    note: str = Field("", max_length=200)


@router.post("/admin/{airline_id}/review")
def admin_review(airline_id: int, body: ReviewAirlineBody, request: Request,
                       admin: dict = Depends(require_admin)):
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "无效操作")
    with get_conn() as conn:
        a = _airline_or_404(conn, airline_id)
        if a["status"] != "pending":
            raise HTTPException(400, "该申请已处理")

        if body.action == "approve":
            conn.execute(
                "UPDATE airlines SET status = 'approved', review_note = ?,"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
                (clean(body.note, 200), admin["id"], airline_id),
            )
            # 创建者自动成为 CEO 成员
            conn.execute(
                "INSERT INTO airline_members (airline_id, user_id, role, status, joined_at)"
                " VALUES (?, ?, 'ceo', 'active', datetime('now','localtime'))"
                " ON CONFLICT(airline_id, user_id) DO UPDATE SET role = 'ceo', status = 'active'",
                (airline_id, a["owner_id"]),
            )
            # 开业赠机：初始机队 2 架 A320
            _seed_fleet(conn, airline_id)
        else:
            conn.execute(
                "UPDATE airlines SET status = 'rejected', review_note = ?,"
                " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
                (clean(body.note, 200) or "未通过审核", admin["id"], airline_id),
            )

    _audit(request, "airline", f"建司审核{'通过' if body.action == 'approve' else '驳回'}",
           actor=admin, target_id=airline_id, detail=f"{a['icao']} {a['name']} · {clean(body.note, 100)}")
    return {"ok": True}
