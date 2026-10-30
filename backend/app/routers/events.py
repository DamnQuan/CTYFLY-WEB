"""连飞活动 API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth, require_capability
from ..permissions import PILOT_RATING, STAFF_RATINGS, rating_rank
from ..requestinfo import client_ip_from_request, user_agent
from ..text import clean

router = APIRouter(prefix="/api/events", tags=["events"])

EVENT_STATUSES = ("upcoming", "ongoing", "ended", "cancelled")


@router.get("")
def list_events(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.*, u.username AS creator,"
            " (SELECT COUNT(*) FROM event_signups s WHERE s.event_id = e.id) AS signup_count,"
            " (SELECT COUNT(*) FROM event_signups s WHERE s.event_id = e.id AND s.user_id = ?) AS signed,"
            " (SELECT COUNT(*) FROM event_briefings b WHERE b.event_id = e.id) AS has_briefing"
            " FROM events e LEFT JOIN users u ON u.id = e.created_by"
            " ORDER BY e.start_time DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "events": [dict(r) for r in rows]}


@router.get("/signups/mine")
def my_signups(user: dict = Depends(require_auth)):
    """我的全部报名记录，含已结束活动，用于历史报名页"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.event_id, s.callsign, s.role, s.created_at AS signed_at,"
            " e.title, e.dep, e.arr, e.start_time, e.end_time, e.status"
            " FROM event_signups s JOIN events e ON e.id = s.event_id"
            " WHERE s.user_id = ?"
            " ORDER BY e.start_time DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "signups": [dict(r) for r in rows]}


@router.get("/{event_id}")
def event_detail(event_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT e.*, u.username AS creator, u.cid AS creator_cid FROM events e"
            " LEFT JOIN users u ON u.id = e.created_by WHERE e.id = ?",
            (event_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "活动不存在")
        # 报名名单：带机型与占用席位名，管制员名单展示席位用
        signups = conn.execute(
            "SELECT s.*, u.cid, u.username, u.avatar_url, u.rating,"
            " p.name AS position_name"
            " FROM event_signups s"
            " JOIN users u ON u.id = s.user_id"
            " LEFT JOIN event_atc_positions p ON p.id = s.position_id"
            " WHERE s.event_id = ? ORDER BY s.id",
            (event_id,),
        ).fetchall()
        mine = conn.execute(
            "SELECT callsign, aircraft, role, position_id FROM event_signups"
            " WHERE event_id = ? AND user_id = ?",
            (event_id, user["id"]),
        ).fetchone()
        # 本活动管制席位列表，含占用信息：报名者 cid/username 或 None
        pos_rows = conn.execute(
            "SELECT p.*, s.user_id AS taken_user_id, u.cid AS taken_cid,"
            " u.username AS taken_username, s.callsign AS taken_callsign"
            " FROM event_atc_positions p"
            " LEFT JOIN event_signups s ON s.position_id = p.id"
            " LEFT JOIN users u ON u.id = s.user_id"
            " WHERE p.event_id = ?"
            " ORDER BY p.sort, p.id",
            (event_id,),
        ).fetchall()
        poster = conn.execute(
            "SELECT i.id FROM event_briefing_images i"
            " JOIN event_briefings b ON b.id = i.briefing_id"
            " WHERE b.event_id = ? ORDER BY i.id LIMIT 1",
            (event_id,),
        ).fetchone()
    signup_list = [dict(s) for s in signups]
    # 席位列表输出，taken 信息序列化为前端友好的字段；
    # eligible = 当前用户是否满足该席位的等级门槛
    my_rank = rating_rank(user.get("rating") or "")
    my_is_controller = (
        user.get("rating") in STAFF_RATINGS
        or bool(user.get("is_controller")) and user.get("rating") != PILOT_RATING
    )
    positions = []
    for p in pos_rows:
        d = dict(p)
        taken = d.pop("taken_user_id") is not None
        d["taken"] = {
            "cid": d.pop("taken_cid"), "username": d.pop("taken_username"),
            "callsign": d.pop("taken_callsign"),
        } if taken else None
        required = (d.get("rating") or "").strip()
        d["eligible"] = my_is_controller and (
            not required or my_rank >= rating_rank(required)
        )
        positions.append(d)
    return {
        "ok": True,
        "event": dict(row),
        "signups": signup_list,
        # 本活动管制席位，席位制报名
        "atcPositions": positions,
        # 分角色报名统计，简报页统计卡用
        "pilotCount": sum(1 for s in signup_list if s["role"] != "atc"),
        "atcCount": sum(1 for s in signup_list if s["role"] == "atc"),
        # 当前用户报名状态，已报名则展示取消报名；atc 时附席位 id
        "my": {
            "signed": mine is not None,
            "role": mine["role"] if mine else "",
            "callsign": mine["callsign"] if mine else "",
            "aircraft": mine["aircraft"] if mine else "",
            "positionId": mine["position_id"] if mine else None,
        },
        # 活动简报第一张截图，海报大图用，未发布简报时为 None
        "posterImageId": poster["id"] if poster else None,
    }


class SignupBody(BaseModel):
    """席位制报名参数：pilot 需 callsign+aircraft，atc 需 positionId；
    空 payload 或 cancel=True 表示取消报名，兼容旧开关语义"""
    callsign: str = Field("", max_length=16)
    aircraft: str = Field("", max_length=16)
    role: str = Field("pilot", max_length=8)
    positionId: int | None = Field(None, ge=1)
    cancel: bool = False


@router.post("/{event_id}/cancel")
def cancel_signup(event_id: int, user: dict = Depends(require_auth)):
    """显式取消报名：删除当前用户的报名行，若占用管制席位则一并释放"""
    with get_conn() as conn:
        event = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "活动不存在")
        existing = conn.execute(
            "SELECT * FROM event_signups WHERE event_id = ? AND user_id = ?",
            (event_id, user["id"]),
        ).fetchone()
        if not existing:
            raise HTTPException(400, "你尚未报名该活动")
        conn.execute("DELETE FROM event_signups WHERE id = ?", (existing["id"],))
    return {"ok": True, "signed": False}


@router.post("/{event_id}/signup")
def signup(event_id: int, body: SignupBody | None = None, user: dict = Depends(require_auth)):
    """席位制报名，同一用户同一活动仅一条报名行：
    - 空 payload 或 cancel=True → 取消报名，释放席位
    - role=pilot → 必填呼号+机型，写入/更新报名行，换呼号/机型即更新
    - role=atc → 必填 positionId，校验席位归属与占用后绑定席位，换席位先释放旧的
    并发防双写：事务内用 BEGIN IMMEDIATE 加写锁后先查后写，
    且 event_signups 的 UNIQUE event_id, user_id 兜底拦截重复行。
    """
    payload = body or SignupBody()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")  # 立即取写锁，避免并发下「先查后写」竞态
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "活动不存在")
        if event["status"] not in ("upcoming", "ongoing"):
            raise HTTPException(400, "该活动当前不接受报名")

        existing = conn.execute(
            "SELECT * FROM event_signups WHERE event_id = ? AND user_id = ?",
            (event_id, user["id"]),
        ).fetchone()

        # 取消报名：显式 cancel 标记，或空 payload，旧客户端兼容
        if payload.cancel or (
            not payload.callsign.strip() and not payload.aircraft.strip()
            and payload.positionId is None
        ):
            if not existing:
                raise HTTPException(400, "你尚未报名该活动")
            conn.execute("DELETE FROM event_signups WHERE id = ?", (existing["id"],))
            return {"ok": True, "signed": False}

        role = "atc" if payload.role == "atc" else "pilot"

        if role == "pilot":
            # 飞行员：必填呼号 + 机型
            callsign = clean(payload.callsign, 16).upper()
            aircraft = clean(payload.aircraft, 16).upper()
            if not callsign:
                raise HTTPException(400, "请填写呼号")
            if not aircraft:
                raise HTTPException(400, "请填写机型")
            if existing:
                # 重复报名 = 更新，换呼号/机型场景
                conn.execute(
                    "UPDATE event_signups SET callsign = ?, aircraft = ?, role = 'pilot',"
                    " position_id = NULL WHERE id = ?",
                    (callsign, aircraft, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO event_signups (event_id, user_id, callsign, role, aircraft)"
                    " VALUES (?, ?, ?, 'pilot', ?)",
                    (event_id, user["id"], callsign, aircraft),
                )
            return {"ok": True, "signed": True, "role": "pilot",
                    "callsign": callsign, "aircraft": aircraft}

        # 管制员：必填席位 id，且席位属于本活动
        if payload.positionId is None:
            raise HTTPException(400, "请选择要报名的管制席位")
        # 管制资格鉴定：仅管制员可占席位，is_controller 且等级非「飞行员」。
        # SUP / ADM 属管理职务等级，视为当然合格；
        # 纯飞行员即使登录也不能抢管制席位。
        me = conn.execute(
            "SELECT is_controller, rating FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        if not me or (
            me["rating"] not in STAFF_RATINGS
            and (not me["is_controller"] or me["rating"] == PILOT_RATING)
        ):
            raise HTTPException(403, "仅管制员可报名管制席位，需先通过管制员申请")
        position = conn.execute(
            "SELECT * FROM event_atc_positions WHERE id = ? AND event_id = ?",
            (payload.positionId, event_id),
        ).fetchone()
        if not position:
            raise HTTPException(400, "席位不存在或不属于该活动")
        # 席位等级硬门槛：席位标注的等级是最低要求，等级不达标不能报
        required = (position["rating"] or "").strip()
        if required and rating_rank(me["rating"]) < rating_rank(required):
            raise HTTPException(
                403,
                f"你的管制等级，{me['rating']}不满足该席位要求，{required} 及以上",
            )
        # 席位占用校验，写锁内复查，防并发抢座：被他人占用则拒绝
        taken = conn.execute(
            "SELECT user_id FROM event_signups WHERE position_id = ?",
            (payload.positionId,),
        ).fetchone()
        if taken and taken["user_id"] != user["id"]:
            raise HTTPException(400, "该席位已被占用")
        # 同一用户换席位：先释放旧席位再绑新席位
        if existing:
            conn.execute(
                "UPDATE event_signups SET role = 'atc', position_id = ? WHERE id = ?",
                (payload.positionId, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO event_signups (event_id, user_id, callsign, role, position_id)"
                " VALUES (?, ?, ?, 'atc', ?)",
                (event_id, user["id"], user["cid"], payload.positionId),
            )
        return {"ok": True, "signed": True, "role": "atc", "positionId": payload.positionId}


class EventBody(BaseModel):
    title: str = Field("", max_length=120)
    description: str = Field("", max_length=2000)
    dep: str = Field("", max_length=8)
    arr: str = Field("", max_length=8)
    startTime: str = Field("", max_length=32)
    endTime: str = Field("", max_length=32)
    route: str = Field("", max_length=200)
    distanceNm: float | None = Field(None, ge=0)
    notams: str = Field("", max_length=500)


@router.post("")
def create_event(body: EventBody,
                       user: dict = Depends(require_capability("manage_events"))):
    # 能力校验，manage_events：与 admin.py 的活动管理端点同口径，不再仅看 role 字段
    title = clean(body.title, 100)
    if not title:
        raise HTTPException(400, "请填写活动标题")
    if not body.startTime or not body.endTime:
        raise HTTPException(400, "请选择活动起止时间")

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (title, description, dep, arr, start_time, end_time, status,"
            " created_by, route, distance_nm, notams)"
            " VALUES (?, ?, ?, ?, ?, ?, 'upcoming', ?, ?, ?, ?)",
            (title, clean(body.description, 2000), body.dep.upper(), body.arr.upper(),
             body.startTime, body.endTime, user["id"],
             clean(body.route, 200), body.distanceNm, clean(body.notams, 500)),
        )
    return {"ok": True, "id": cur.lastrowid}


class EventStatusBody(BaseModel):
    status: str = ""


@router.patch("/{event_id}")
def update_event(event_id: int, body: EventStatusBody, user: dict = Depends(require_auth)):
    if user["role"] != "admin":
        raise HTTPException(403, "仅管理员可修改活动")
    if body.status not in EVENT_STATUSES:
        raise HTTPException(400, "无效的活动状态")
    with get_conn() as conn:
        conn.execute("UPDATE events SET status = ? WHERE id = ?", (body.status, event_id))
    return {"ok": True}


@router.delete("/{event_id}")
def delete_event(event_id: int, request: Request, user: dict = Depends(require_auth)):
    if user["role"] != "admin":
        raise HTTPException(403, "仅管理员可删除活动")
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "活动不存在")
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        # 席位表无外键级联，见 admin.delete_event 同款注释，必须显式清理
        conn.execute("DELETE FROM event_atc_positions WHERE event_id = ?", (event_id,))
    # 删除活动是管理员级破坏性操作，必须在审计留痕，此前该端点完全不写审计
    log_event("content", "删除活动", actor=user, target_type="event", target_id=event_id,
              detail=row["title"], ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


# ==================== 活动简报 ====================
# 每场已结束活动一篇：管理员撰写标题与回顾正文，页面自动附带报名与呼号数据；
# 仅登录成员可见；截图复用工单附件的安全思路，magic bytes 嗅探、随机落盘名、鉴权读取。

import secrets

from fastapi import File, UploadFile

from ..config import ATTACH_DIR, MAX_ATTACH_BYTES
from ..ratelimit import enforce
from .uploads import sniff_image_ext

MAX_BRIEFING_IMAGES = 9


def _briefing_images(conn, briefing_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM event_briefing_images WHERE briefing_id = ? ORDER BY id",
        (briefing_id,),
    ).fetchall()
    return [
        {"id": r["id"], "name": r["orig_name"] or f"截图 {r['id']}",
         "contentType": r["content_type"], "size": r["size"]}
        for r in rows
    ]


@router.get("/{event_id}/briefing")
def get_briefing(event_id: int, user: dict = Depends(require_auth)):
    """简报详情：自动数据，报名/呼号+ 手写正文 + 截图；简报未发布时 briefing 为 null"""
    with get_conn() as conn:
        event = conn.execute(
            "SELECT e.*, u.username AS creator FROM events e"
            " LEFT JOIN users u ON u.id = e.created_by WHERE e.id = ?",
            (event_id,),
        ).fetchone()
        if not event:
            raise HTTPException(404, "活动不存在")
        signups = conn.execute(
            "SELECT s.callsign, s.role, u.username, u.cid FROM event_signups s"
            " JOIN users u ON u.id = s.user_id WHERE s.event_id = ? ORDER BY s.id",
            (event_id,),
        ).fetchall()
        b = conn.execute(
            "SELECT * FROM event_briefings WHERE event_id = ?", (event_id,)
        ).fetchone()
        images: list[dict] = _briefing_images(conn, b["id"]) if b else []
    return {
        "ok": True,
        "event": {
            "id": event["id"], "title": event["title"], "dep": event["dep"],
            "arr": event["arr"], "startTime": event["start_time"],
            "endTime": event["end_time"], "status": event["status"],
        },
        "auto": {
            "signupCount": len(signups),
            "pilotCount": sum(1 for s in signups if s["role"] != "atc"),
            "atcCount": sum(1 for s in signups if s["role"] == "atc"),
            "callsigns": [dict(s) for s in signups],
        },
        "briefing": ({
            "title": b["title"], "body": b["body"],
            "createdAt": b["created_at"], "updatedAt": b["updated_at"],
            "images": images,
        } if b else None),
    }


class BriefingBody(BaseModel):
    title: str = Field("", max_length=80)
    body: str = Field("", max_length=4000)


@router.post("/{event_id}/briefing")
def save_briefing(event_id: int, body: BriefingBody,
                        user: dict = Depends(require_capability("manage_events"))):
    """创建 / 更新简报，仅已结束的活动；重复提交即覆盖更新"""
    title = clean(body.title, 80)
    content = clean(body.body, 4000)
    if not title:
        raise HTTPException(400, "请填写简报标题")
    with get_conn() as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "活动不存在")
        if event["status"] != "ended":
            raise HTTPException(400, "只能为已结束的活动发布简报")
        conn.execute(
            "INSERT INTO event_briefings (event_id, title, body, created_by)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(event_id) DO UPDATE SET title = excluded.title,"
            " body = excluded.body, created_by = excluded.created_by,"
            " updated_at = datetime('now','localtime')",
            (event_id, title, content, user["id"]),
        )
    return {"ok": True, "message": "简报已保存"}


@router.post("/{event_id}/briefing/images")
async def upload_briefing_image(
    event_id: int, request: Request, file: UploadFile = File(...),
    user: dict = Depends(require_capability("manage_events")),
):
    """上传活动海报，能力 manage_events；2026-10-18 起与页面/其它活动管理接口同口径

    历史背景：海报原本在前台活动简报页、由站长指定「仅 admin 可上传」，当时这里用
    require_admin。后来上传入口收进管理后台「活动管理」，页面准入就是 manage_events，
    同一个页面里创建/编辑/删除活动都认能力，唯独上传海报还只认 role=admin ——
    有活动管理权限的人能进页面、能改能删，上传却拿到 403「看起来你没有权限访问这个页面」。
    现改为 require_capability，角色 admin 仍天然通过，权限模型与删除截图/删除简报一致。
    """
    enforce(request, "briefimg", 40, 3600)
    with get_conn() as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "活动不存在")
        b = conn.execute(
            "SELECT id FROM event_briefings WHERE event_id = ?", (event_id,)
        ).fetchone()
        if not b:
            # 无简报时自动创建空简报，海报上传不再要求先手写正文
            cur = conn.execute(
                "INSERT INTO event_briefings (event_id, title, body, created_by)"
                " VALUES (?, ?, '', ?)",
                (event_id, event["title"], user["id"]),
            )
            b = {"id": cur.lastrowid}
        count = conn.execute(
            "SELECT COUNT(*) c FROM event_briefing_images WHERE briefing_id = ?", (b["id"],)
        ).fetchone()["c"]
        if count >= MAX_BRIEFING_IMAGES:
            raise HTTPException(400, f"每篇简报最多 {MAX_BRIEFING_IMAGES} 张截图")

    head = await file.read(16)
    ext = sniff_image_ext(head)
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 图片，SVG 不支持")
    rest = await file.read(MAX_ATTACH_BYTES + 1)
    data = head + rest
    if len(data) > MAX_ATTACH_BYTES:
        raise HTTPException(400, f"图片不能超过 {MAX_ATTACH_BYTES // 1024 // 1024} MB")

    content_type = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}[ext]
    stored = f"briefing-{secrets.token_hex(12)}{ext}"
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    (ATTACH_DIR / stored).write_bytes(data)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO event_briefing_images (briefing_id, orig_name, stored_name, content_type, size)"
            " VALUES (?, ?, ?, ?, ?)",
            (b["id"], (file.filename or "")[:120], stored, content_type, len(data)),
        )
        img_id = cur.lastrowid
    log_event("content", "上传活动简报截图", actor=user, target_type="briefing_image",
              target_id=img_id, detail=f"event={event_id} · {len(data) // 1024}KB",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "image": {"id": img_id, "name": (file.filename or "")[:120],
                                  "contentType": content_type, "size": len(data)}}


briefing_router = APIRouter(prefix="/api/briefings", tags=["events"])


@briefing_router.get("/images/{image_id}")
def get_briefing_image(image_id: int, user: dict = Depends(require_auth)):
    """读取简报截图，登录成员均可；带 nosniff 与 CSP，杜绝内容伪装执行"""
    from fastapi.responses import FileResponse
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM event_briefing_images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, "图片不存在")
    path = ATTACH_DIR / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "图片文件已丢失，请联系管理员")
    return FileResponse(path, media_type=row["content_type"], headers={
        "Content-Disposition": f"inline; filename=\"briefing-{row['id']}\"",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=86400",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@briefing_router.delete("/images/{image_id}")
def delete_briefing_image(image_id: int, user: dict = Depends(require_capability("manage_events"))):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM event_briefing_images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "图片不存在")
        conn.execute("DELETE FROM event_briefing_images WHERE id = ?", (image_id,))
    try:
        (ATTACH_DIR / row["stored_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


@router.delete("/{event_id}/briefing")
def delete_briefing(event_id: int, user: dict = Depends(require_capability("manage_events"))):
    """整篇删除简报，含全部截图文件"""
    with get_conn() as conn:
        b = conn.execute(
            "SELECT * FROM event_briefings WHERE event_id = ?", (event_id,)
        ).fetchone()
        if not b:
            raise HTTPException(404, "简报不存在")
        files = [r["stored_name"] for r in conn.execute(
            "SELECT stored_name FROM event_briefing_images WHERE briefing_id = ?", (b["id"],)
        ).fetchall()]
        conn.execute("DELETE FROM event_briefings WHERE id = ?", (b["id"],))
    for name in files:
        try:
            (ATTACH_DIR / name).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True, "message": "简报已删除"}
