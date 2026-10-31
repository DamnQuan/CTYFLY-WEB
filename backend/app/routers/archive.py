"""飞圈事件检索：公开档案检索、登录投稿、纠错与管理员审核发布。

设计要点：
- 公开接口只返回已发布事件，投稿人信息与联系 QQ 永不出现在公开响应里。
- 投稿原文不可变；管理员编辑结果存在 draft 字段，只有审核通过才写入正式事件。
- 审核通过即自动发布，同时写 archive_revisions，便于追溯谁改了什么。
- 搜索先用 LIKE 覆盖标题、摘要、正文、标签与来源；数据量小，避免为 FTS5 引入额外分词依赖。
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth, require_capability
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent
from ..text import clean

router = APIRouter(prefix="/api/archive", tags=["archive"])
admin_router = APIRouter(prefix="/api/admin/archive", tags=["archive-admin"])

PAGE_SIZE = 12
CATEGORIES = ["事故与事件", "平台与规则", "社区与活动", "人物与账号", "其他"]
PERSONAL_MODES = {"public", "masked", "hidden"}
QQ_RE = re.compile(r"(?<!\d)([1-9]\d{4,11})(?!\d)")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class BlockBody(BaseModel):
    type: str = Field("text", max_length=16)
    text: str = Field("", max_length=8000)
    url: str = Field("", max_length=800)
    caption: str = Field("", max_length=200)


class SourceBody(BaseModel):
    title: str = Field("", max_length=120)
    url: str = Field("", max_length=800)
    publisher: str = Field("", max_length=80)
    published_at: str = Field("", max_length=20)


class ArchivePayload(BaseModel):
    title: str = Field("", max_length=120)
    occurred_at: str = Field("", max_length=10)
    category: str = Field("其他", max_length=30)
    summary: str = Field("", max_length=300)
    tags: list[str] = Field(default_factory=list)
    blocks: list[BlockBody] = Field(default_factory=list)
    sources: list[SourceBody] = Field(default_factory=list)
    contact: str = Field("", max_length=100)
    personal_info_mode: str = Field("public", max_length=10)


class CorrectionBody(BaseModel):
    field: str = Field("", max_length=20)
    proposed_value: str = Field("", max_length=8000)
    reason: str = Field("", max_length=500)
    source_url: str = Field("", max_length=800)


class ReviewBody(BaseModel):
    payload: ArchivePayload | None = None
    note: str = Field("", max_length=500)


def _audit(request: Request, action: str, *, actor, target_id=None, detail: str = "") -> None:
    log_event("archive", action, actor=actor, target_type="archive", target_id=target_id or "",
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))


def _parse_json(raw: str, fallback):
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _normalise(body: ArchivePayload) -> dict:
    title = clean(body.title, 120)
    if len(title) < 4:
        raise HTTPException(400, "标题至少需要 4 个字")
    occurred_at = clean(body.occurred_at, 10)
    # 历史数据与旧前端可能仍传完整日期，统一截断到月份；新数据只要求精确到月
    if re.match(r"^\d{4}-\d{2}-\d{2}$", occurred_at):
        occurred_at = occurred_at[:7]
    if not MONTH_RE.match(occurred_at):
        raise HTTPException(400, "发生时间请选择到月份，格式 YYYY-MM")
    category = body.category if body.category in CATEGORIES else "其他"
    summary = clean(body.summary, 300)
    tags = []
    for tag in body.tags[:10]:
        value = clean(tag, 20)
        if value and value not in tags:
            tags.append(value)
    blocks = []
    text_length = 0
    for block in body.blocks[:30]:
        if block.type == "image":
            url = block.url.strip()
            if not url.startswith("/uploads/"):
                raise HTTPException(400, "图片地址不合法，请重新上传")
            if ".." in url:
                raise HTTPException(400, "图片地址不合法")
            blocks.append({
                "type": "image",
                "url": url,
                "caption": clean(block.caption, 200),
            })
        else:
            text = clean(block.text, 8000)
            if not text:
                continue
            text_length += len(text)
            blocks.append({"type": "text", "text": text})
    if text_length < 10:
        raise HTTPException(400, "正文至少需要 10 个字")
    if text_length > 20000:
        raise HTTPException(400, "正文过长")
    sources = []
    for source in body.sources[:10]:
        title_s = clean(source.title, 120)
        url = source.url.strip()
        if not title_s or not url:
            continue
        if not (url.startswith("https://") or url.startswith("http://")):
            raise HTTPException(400, "资料来源链接必须以 http 或 https 开头")
        sources.append({
            "title": title_s,
            "url": url,
            "publisher": clean(source.publisher, 80),
            "published_at": clean(source.published_at, 20),
        })
    if not sources:
        raise HTTPException(400, "至少填写一个资料来源")
    mode = body.personal_info_mode if body.personal_info_mode in PERSONAL_MODES else "public"
    return {
        "title": title,
        "occurred_at": occurred_at,
        "category": category,
        "summary": summary,
        "tags": tags,
        "blocks": blocks,
        "sources": sources,
        "contact": clean(body.contact, 100),
        "personal_info_mode": mode,
    }


def _search_text(payload: dict) -> str:
    parts = [payload["title"], payload["summary"], payload["category"], " ".join(payload["tags"])]
    for block in payload["blocks"]:
        if block["type"] == "text":
            parts.append(block["text"])
        else:
            parts.append(block.get("caption", ""))
    parts.extend(source["title"] for source in payload["sources"])
    return " ".join(parts)[:60000]


def _redact(text: str, mode: str) -> str:
    if mode not in ("masked", "hidden"):
        return text
    if mode == "hidden":
        return QQ_RE.sub("[联系方式已隐藏]", text)

    def masked(match):
        value = match.group(1)
        return value[:3] + "***" + value[-2:]

    return QQ_RE.sub(masked, text)


def _public_payload(payload: dict) -> dict:
    mode = payload.get("personal_info_mode", "public")
    blocks = []
    for block in payload.get("blocks", []):
        if block.get("type") == "image":
            blocks.append({
                "type": "image",
                "url": block.get("url", ""),
                "caption": _redact(block.get("caption", ""), mode),
            })
        else:
            blocks.append({"type": "text", "text": _redact(block.get("text", ""), mode)})
    return {
        "title": payload.get("title", ""),
        "summary": _redact(payload.get("summary", ""), mode),
        "occurred_at": payload.get("occurred_at", ""),
        "category": payload.get("category", "其他"),
        "tags": payload.get("tags", []),
        "blocks": blocks,
        "sources": payload.get("sources", []),
        "personal_info_mode": mode,
    }


def _cover(payload: dict) -> str:
    for block in payload.get("blocks", []):
        if block.get("type") == "image":
            return block.get("url", "")
    return ""


def _event_public(row) -> dict:
    payload = {
        "title": row["title"],
        "summary": row["summary"],
        "occurred_at": row["occurred_at"],
        "category": row["category"],
        "tags": _parse_json(row["tags"], []),
        "blocks": _parse_json(row["blocks"], []),
        "sources": _parse_json(row["sources"], []),
        "personal_info_mode": row["personal_info_mode"],
    }
    public = _public_payload(payload)
    public.update({
        "id": row["id"],
        "cover_url": row["cover_url"],
        "source_count": len(_parse_json(row["sources"], [])),
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
    })
    return public


def _list_item(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": _redact(row["summary"], row["personal_info_mode"]),
        "occurred_at": row["occurred_at"],
        "category": row["category"],
        "tags": _parse_json(row["tags"], []),
        "cover_url": row["cover_url"],
        "source_count": len(_parse_json(row["sources"], [])),
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
    }


def _revision(conn, event_id: int, actor_id: int, action: str, changes: dict) -> None:
    conn.execute(
        "INSERT INTO archive_revisions (event_id, actor_id, action, changes) VALUES (?, ?, ?, ?)",
        (event_id, actor_id, action, json.dumps(changes, ensure_ascii=False)[:80000]),
    )


def _event_insert(conn, payload: dict, *, actor_id: int, submission_id: int | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO archive_events (title, summary, occurred_at, category, tags, blocks, sources,"
        " personal_info_mode, cover_url, search_text, status, created_by, reviewed_by,"
        " source_submission_id, published_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, datetime('now','localtime'),"
        " datetime('now','localtime'))",
        (
            payload["title"], payload["summary"], payload["occurred_at"], payload["category"],
            json.dumps(payload["tags"], ensure_ascii=False),
            json.dumps(payload["blocks"], ensure_ascii=False),
            json.dumps(payload["sources"], ensure_ascii=False),
            payload["personal_info_mode"], _cover(payload), _search_text(payload),
            actor_id, actor_id, submission_id,
        ),
    )
    return int(cursor.lastrowid)


@router.get("")
def list_events(q: str = "", category: str = "", year: str = "", page: int = 1):
    """公开检索：只返回已发布事件，关键词覆盖标题、摘要、正文、标签与来源。"""
    page = max(1, min(int(page or 1), 2000))
    offset = (page - 1) * PAGE_SIZE
    q = clean(q, 60)
    where = ["status = 'published'"]
    args = []
    if q:
        like = f"%{q}%"
        where.append("(title LIKE ? OR summary LIKE ? OR search_text LIKE ?)")
        args.extend([like, like, like])
    if category in CATEGORIES:
        where.append("category = ?")
        args.append(category)
    if re.match(r"^\d{4}$", year or ""):
        where.append("substr(occurred_at, 1, 4) = ?")
        args.append(year)
    where_sql = " AND ".join(where)
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM archive_events WHERE {where_sql}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM archive_events WHERE {where_sql}"
            " ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            (*args, PAGE_SIZE, offset),
        ).fetchall()
        years = [
            row["y"] for row in conn.execute(
                "SELECT DISTINCT substr(occurred_at, 1, 4) y FROM archive_events"
                " WHERE status = 'published' ORDER BY y DESC"
            ) if row["y"]
        ]
    return {
        "items": [_list_item(row) for row in rows],
        "total": total,
        "page": page,
        "pageSize": PAGE_SIZE,
        "categories": CATEGORIES,
        "years": years,
        "disclaimer": "本站事件资料来自公开渠道与社区整理，仅供参考，不构成事实认定或法律意见。",
    }


@router.get("/mine")
def my_submissions(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, payload, status, review_note, event_id, created_at, reviewed_at"
            " FROM archive_submissions WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
    items = []
    for row in rows:
        payload = _parse_json(row["payload"], {})
        items.append({
            "id": row["id"],
            "title": payload.get("title", ""),
            "status": row["status"],
            "review_note": row["review_note"],
            "event_id": row["event_id"],
            "created_at": row["created_at"],
            "reviewed_at": row["reviewed_at"],
        })
    return {"items": items}


@router.get("/{event_id}")
def event_detail(event_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_events WHERE id = ? AND status = 'published'", (event_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "事件不存在或已下线")
    data = _event_public(row)
    data["disclaimer"] = "本站事件资料来自公开渠道与社区整理，仅供参考，不构成事实认定或法律意见。"
    data["correction_notice"] = "发现事实或表述有误，可登录后提交纠错，管理员审核后更新。"
    return data


@router.post("/submissions")
def submit_event(body: ArchivePayload, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "archive-submit", 3, 3600)
    payload = _normalise(body)
    if not payload["contact"]:
        payload["contact"] = user.get("qq") or user.get("email") or ""
    payload["personal_info_mode"] = "public"
    with get_conn() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) c FROM archive_submissions WHERE user_id = ? AND status = 'pending'",
            (user["id"],),
        ).fetchone()["c"]
        if pending >= 1:
            raise HTTPException(400, "你还有一条投稿在审核中，请等待处理后再提交")
        cursor = conn.execute(
            "INSERT INTO archive_submissions (user_id, payload) VALUES (?, ?)",
            (user["id"], json.dumps(payload, ensure_ascii=False)),
        )
        submission_id = int(cursor.lastrowid)
    _audit(request, "提交事件投稿", actor=user, target_id=submission_id,
           detail=payload["title"])
    return {"ok": True, "id": submission_id, "message": "投稿已提交，管理员审核通过后会自动发布"}


@router.post("/{event_id}/corrections")
def submit_correction(event_id: int, body: CorrectionBody, request: Request,
                      user: dict = Depends(require_auth)):
    enforce(request, "archive-correction", 5, 3600)
    field = body.field if body.field in ("title", "summary", "occurred_at", "category", "other") else "other"
    proposed = clean(body.proposed_value, 8000)
    reason = clean(body.reason, 500)
    source_url = body.source_url.strip()
    if len(proposed) < 2:
        raise HTTPException(400, "请填写需要更正的内容")
    if source_url and not (source_url.startswith("https://") or source_url.startswith("http://")):
        raise HTTPException(400, "来源链接格式不正确")
    with get_conn() as conn:
        event = conn.execute(
            "SELECT id, title, summary, occurred_at, category FROM archive_events"
            " WHERE id = ? AND status = 'published'", (event_id,)
        ).fetchone()
        if not event:
            raise HTTPException(404, "事件不存在或已下线")
        pending = conn.execute(
            "SELECT 1 FROM archive_corrections WHERE event_id = ? AND user_id = ? AND status = 'pending'",
            (event_id, user["id"]),
        ).fetchone()
        if pending:
            raise HTTPException(400, "你已经提交过纠错，请等待管理员处理")
        current = {
            "title": event["title"],
            "summary": event["summary"],
            "occurred_at": event["occurred_at"],
            "category": event["category"],
            "other": "",
        }[field]
        cursor = conn.execute(
            "INSERT INTO archive_corrections (event_id, user_id, field, current_value, proposed_value,"
            " reason, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, user["id"], field, current, proposed, reason, source_url),
        )
        correction_id = int(cursor.lastrowid)
    _audit(request, "提交事件纠错", actor=user, target_id=correction_id,
           detail=f"event={event_id} field={field}")
    return {"ok": True, "id": correction_id, "message": "纠错已提交，管理员审核后更新"}


# ---------------- 管理端 ----------------

def _submission_view(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "cid": row["cid"],
        "username": row["username"],
        "status": row["status"],
        "payload": _parse_json(row["payload"], {}),
        "draft": _parse_json(row["draft"], {}) if row["draft"] else {},
        "review_note": row["review_note"],
        "event_id": row["event_id"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }


def _submission_query(where: str, args: tuple):
    with get_conn() as conn:
        return conn.execute(
            "SELECT s.*, u.cid, u.username FROM archive_submissions s"
            " JOIN users u ON u.id = s.user_id"
            f" WHERE {where} ORDER BY s.id DESC", args
        ).fetchall()


@admin_router.get("/submissions")
def admin_submissions(status: str = "pending", user: dict = Depends(require_capability("manage_archive"))):
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    where = "1=1" if status == "all" else "s.status = ?"
    args = () if status == "all" else (status,)
    rows = _submission_query(where, args)
    return {"items": [_submission_view(row) for row in rows]}


@admin_router.get("/submissions/{submission_id}")
def admin_submission_detail(submission_id: int,
                            user: dict = Depends(require_capability("manage_archive"))):
    rows = _submission_query("s.id = ?", (submission_id,))
    if not rows:
        raise HTTPException(404, "投稿不存在")
    return _submission_view(rows[0])


@admin_router.put("/submissions/{submission_id}/draft")
def save_review_draft(submission_id: int, body: ArchivePayload, request: Request,
                      user: dict = Depends(require_capability("manage_archive"))):
    payload = _normalise(body)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM archive_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "投稿不存在")
        if row["status"] != "pending":
            raise HTTPException(400, "该投稿已处理")
        conn.execute(
            "UPDATE archive_submissions SET draft = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), submission_id),
        )
    _audit(request, "保存审核草稿", actor=user, target_id=submission_id, detail=payload["title"])
    return {"ok": True, "draft": payload}


@admin_router.post("/submissions/{submission_id}/approve")
def approve_submission(submission_id: int, body: ReviewBody, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "投稿不存在")
        if row["status"] != "pending":
            raise HTTPException(400, "该投稿已处理")
        if body.payload is not None:
            payload = _normalise(body.payload)
        elif row["draft"]:
            payload = _parse_json(row["draft"], {})
        else:
            payload = _parse_json(row["payload"], {})
        event_id = _event_insert(conn, payload, actor_id=user["id"], submission_id=submission_id)
        conn.execute(
            "UPDATE archive_submissions SET status = 'approved', review_note = ?, event_id = ?,"
            " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
            (clean(body.note, 500), event_id, user["id"], submission_id),
        )
        _revision(conn, event_id, user["id"], "publish",
                  {"submission_id": submission_id, "payload": payload})
    _audit(request, "审核通过并发布事件", actor=user, target_id=event_id,
           detail=f"submission={submission_id}")
    return {"ok": True, "event_id": event_id}


@admin_router.post("/submissions/{submission_id}/reject")
def reject_submission(submission_id: int, body: ReviewBody, request: Request,
                      user: dict = Depends(require_capability("manage_archive"))):
    note = clean(body.note, 500)
    if len(note) < 2:
        raise HTTPException(400, "请填写驳回原因")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM archive_submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "投稿不存在")
        if row["status"] != "pending":
            raise HTTPException(400, "该投稿已处理")
        conn.execute(
            "UPDATE archive_submissions SET status = 'rejected', review_note = ?,"
            " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
            (note, user["id"], submission_id),
        )
    _audit(request, "驳回事件投稿", actor=user, target_id=submission_id, detail=note)
    return {"ok": True}


@admin_router.get("/events")
def admin_events(q: str = "", status: str = "all",
                 user: dict = Depends(require_capability("manage_archive"))):
    where = ["1=1"]
    args = []
    if status in ("published", "offline"):
        where.append("status = ?")
        args.append(status)
    q = clean(q, 60)
    if q:
        where.append("(title LIKE ? OR search_text LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM archive_events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 200",
            args,
        ).fetchall()
    return {"items": [_event_public(row) for row in rows]}


@admin_router.post("/events")
def admin_create_event(body: ArchivePayload, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    payload = _normalise(body)
    with get_conn() as conn:
        event_id = _event_insert(conn, payload, actor_id=user["id"])
        _revision(conn, event_id, user["id"], "create", {"payload": payload})
    _audit(request, "管理员创建事件", actor=user, target_id=event_id, detail=payload["title"])
    return {"ok": True, "event_id": event_id}


@admin_router.get("/events/{event_id}")
def admin_event_detail(event_id: int, user: dict = Depends(require_capability("manage_archive"))):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM archive_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "事件不存在")
        revisions = conn.execute(
            "SELECT id, actor_id, action, changes, created_at FROM archive_revisions"
            " WHERE event_id = ? ORDER BY id DESC LIMIT 50", (event_id,)
        ).fetchall()
    data = _event_public(row)
    data["status"] = row["status"]
    data["created_at"] = row["created_at"]
    data["revisions"] = [dict(r) for r in revisions]
    return data


@admin_router.put("/events/{event_id}")
def admin_update_event(event_id: int, body: ArchivePayload, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    payload = _normalise(body)
    with get_conn() as conn:
        old = conn.execute("SELECT title FROM archive_events WHERE id = ?", (event_id,)).fetchone()
        if not old:
            raise HTTPException(404, "事件不存在")
        conn.execute(
            "UPDATE archive_events SET title = ?, summary = ?, occurred_at = ?, category = ?,"
            " tags = ?, blocks = ?, sources = ?, personal_info_mode = ?, cover_url = ?,"
            " search_text = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (
                payload["title"], payload["summary"], payload["occurred_at"], payload["category"],
                json.dumps(payload["tags"], ensure_ascii=False),
                json.dumps(payload["blocks"], ensure_ascii=False),
                json.dumps(payload["sources"], ensure_ascii=False),
                payload["personal_info_mode"], _cover(payload), _search_text(payload), event_id,
            ),
        )
        _revision(conn, event_id, user["id"], "edit", {"title": old["title"], "payload": payload})
    _audit(request, "编辑事件", actor=user, target_id=event_id, detail=payload["title"])
    return {"ok": True}


@admin_router.post("/events/{event_id}/status")
def admin_event_status(event_id: int, body: dict, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    status = str(body.get("status", ""))
    if status not in ("published", "offline"):
        raise HTTPException(400, "无效状态")
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM archive_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "事件不存在")
        conn.execute(
            "UPDATE archive_events SET status = ?, updated_at = datetime('now','localtime')"
            " WHERE id = ?", (status, event_id),
        )
        _revision(conn, event_id, user["id"], "status", {"status": status})
    _audit(request, "变更事件状态", actor=user, target_id=event_id, detail=status)
    return {"ok": True}


@admin_router.get("/corrections")
def admin_corrections(status: str = "pending",
                      user: dict = Depends(require_capability("manage_archive"))):
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    where = "1=1" if status == "all" else "c.status = ?"
    args = () if status == "all" else (status,)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT c.*, u.cid, u.username, e.title AS event_title FROM archive_corrections c"
            " JOIN users u ON u.id = c.user_id JOIN archive_events e ON e.id = c.event_id"
            f" WHERE {where} ORDER BY c.id DESC", args,
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@admin_router.get("/corrections/{correction_id}")
def admin_correction_detail(correction_id: int,
                            user: dict = Depends(require_capability("manage_archive"))):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT c.*, u.cid, u.username, e.title AS event_title FROM archive_corrections c"
            " JOIN users u ON u.id = c.user_id JOIN archive_events e ON e.id = c.event_id"
            " WHERE c.id = ?", (correction_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "纠错不存在")
    return dict(row)


@admin_router.post("/corrections/{correction_id}/approve")
def approve_correction(correction_id: int, body: ReviewBody, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_corrections WHERE id = ?", (correction_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "纠错不存在")
        if row["status"] != "pending":
            raise HTTPException(400, "该纠错已处理")
        event = conn.execute(
            "SELECT * FROM archive_events WHERE id = ?", (row["event_id"],)
        ).fetchone()
        if not event:
            raise HTTPException(404, "事件不存在")
        field = row["field"]
        if field in ("title", "summary", "occurred_at", "category"):
            value = clean(row["proposed_value"], 8000)
            if field == "summary":
                value = value[:300]
            if field == "occurred_at":
                if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                    value = value[:7]
                if not MONTH_RE.match(value):
                    raise HTTPException(400, "发生时间请选择到月份，格式 YYYY-MM")
            conn.execute(
                f"UPDATE archive_events SET {field} = ?, updated_at = datetime('now','localtime')"
                " WHERE id = ?", (value, row["event_id"]),
            )
            # 同步重建搜索文本
            fresh = conn.execute("SELECT * FROM archive_events WHERE id = ?", (row["event_id"],)).fetchone()
            payload = {
                "title": fresh["title"], "summary": fresh["summary"],
                "occurred_at": fresh["occurred_at"], "category": fresh["category"],
                "tags": _parse_json(fresh["tags"], []),
                "blocks": _parse_json(fresh["blocks"], []),
                "sources": _parse_json(fresh["sources"], []),
            }
            conn.execute("UPDATE archive_events SET search_text = ? WHERE id = ?",
                         (_search_text(payload), row["event_id"]))
        conn.execute(
            "UPDATE archive_corrections SET status = 'approved', review_note = ?,"
            " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
            (clean(body.note, 500), user["id"], correction_id),
        )
        _revision(conn, row["event_id"], user["id"], "correction",
                  {"field": field, "proposed": row["proposed_value"]})
    _audit(request, "通过事件纠错", actor=user, target_id=row["event_id"],
           detail=f"correction={correction_id}")
    return {"ok": True}


@admin_router.post("/corrections/{correction_id}/reject")
def reject_correction(correction_id: int, body: ReviewBody, request: Request,
                      user: dict = Depends(require_capability("manage_archive"))):
    note = clean(body.note, 500)
    if len(note) < 2:
        raise HTTPException(400, "请填写驳回原因")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_corrections WHERE id = ?", (correction_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "纠错不存在")
        if row["status"] != "pending":
            raise HTTPException(400, "该纠错已处理")
        conn.execute(
            "UPDATE archive_corrections SET status = 'rejected', review_note = ?,"
            " reviewed_by = ?, reviewed_at = datetime('now','localtime') WHERE id = ?",
            (note, user["id"], correction_id),
        )
    _audit(request, "驳回事件纠错", actor=user, target_id=row["event_id"],
           detail=f"correction={correction_id}")
    return {"ok": True}
