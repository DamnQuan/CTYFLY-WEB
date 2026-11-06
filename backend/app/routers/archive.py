"""飞圈事件检索：公开档案检索、登录投稿、纠错与管理员审核发布。

设计要点：
- 公开接口只返回已发布事件，投稿人信息与联系 QQ 永不出现在公开响应里。
- 投稿原文不可变；管理员编辑结果存在 draft 字段，只有审核通过才写入正式事件。
- 审核通过即自动发布，同时写 archive_revisions，便于追溯谁改了什么。
- 搜索先用 LIKE 覆盖标题、摘要、正文、标签与来源；数据量小，避免为 FTS5 引入额外分词依赖。
"""
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import optional_user, require_auth, require_capability
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


class CommentBody(BaseModel):
    content: str = Field("", max_length=500)
    parent_id: int | None = None


class ReportBody(BaseModel):
    reason: str = Field("", max_length=300)


class CommentStatusBody(BaseModel):
    status: str = Field("", max_length=12)


class FeaturedBody(BaseModel):
    featured: bool = False


class ResolveReportBody(BaseModel):
    action: str = Field("", max_length=12)
    note: str = Field("", max_length=300)


SORTS = {"latest", "hot", "featured"}
HOT_WINDOWS = {"day": "-1 day", "week": "-7 days", "month": "-30 days", "all": None}
COUNT_FIELDS = {"like_count", "favorite_count", "comment_count", "view_count"}


def _audit(request: Request, action: str, *, actor, target_id=None, detail: str = "") -> None:
    log_event("archive", action, actor=actor, target_type="archive", target_id=target_id or "",
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))


def _acis_anon_id(request: Request) -> str:
    """匿名访客标识：优先使用前端持久化的随机 ID，缺失时按 IP+UA 派生。"""
    raw = (request.headers.get("x-acis-anon") or "").strip()[:64]
    if raw and re.match(r"^[A-Za-z0-9_-]{8,64}$", raw):
        return raw
    derived = f"{client_ip_from_request(request)}|{user_agent(request)}".encode("utf-8", "ignore")
    return "ip-" + hashlib.sha256(derived).hexdigest()[:32]


def _guest_user(conn) -> dict:
    """ACIS 免登录投稿使用的内部访客账号，不能登录，仅用于外键与后台展示。"""
    row = conn.execute("SELECT * FROM users WHERE cid = 'ACIS'").fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        "INSERT INTO users (cid, username, email, password_hash, role, rating, status)"
        " VALUES ('ACIS', 'ACIS访客', 'acis-guest@local.invalid', '!', 'user', '飞行员', 'deleted')"
    )
    return {"id": int(cur.lastrowid), "cid": "ACIS", "username": "ACIS访客", "role": "user"}


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


def _count(row, name: str) -> int:
    return int(row[name] or 0) if name in row.keys() else 0


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
        "like_count": _count(row, "like_count"),
        "favorite_count": _count(row, "favorite_count"),
        "comment_count": _count(row, "comment_count"),
        "view_count": _count(row, "view_count"),
        "featured": bool(_count(row, "featured")),
    })
    return public


def _list_item(row, liked: bool = False, favorited: bool = False) -> dict:
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
        "like_count": _count(row, "like_count"),
        "favorite_count": _count(row, "favorite_count"),
        "comment_count": _count(row, "comment_count"),
        "view_count": _count(row, "view_count"),
        "featured": bool(_count(row, "featured")),
        "liked": liked,
        "favorited": favorited,
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


def _viewer_sets(conn, event_ids: list[int], user_id: int | None):
    if not event_ids or not user_id:
        return set(), set()
    marks = ",".join("?" for _ in event_ids)
    liked = {r["event_id"] for r in conn.execute(
        f"SELECT event_id FROM archive_likes WHERE user_id = ? AND event_id IN ({marks})",
        (user_id, *event_ids),
    )}
    favorited = {r["event_id"] for r in conn.execute(
        f"SELECT event_id FROM archive_favorites WHERE user_id = ? AND event_id IN ({marks})",
        (user_id, *event_ids),
    )}
    return liked, favorited


@router.get("")
def list_events(q: str = "", category: str = "", year: str = "", sort: str = "latest",
                window: str = "week", page: int = 1,
                user: dict | None = Depends(optional_user)):
    """公开检索：最新、最热、精选；只返回已发布事件。"""
    page = max(1, min(int(page or 1), 2000))
    offset = (page - 1) * PAGE_SIZE
    q = clean(q, 60)
    sort = sort if sort in SORTS else "latest"
    window = window if window in HOT_WINDOWS else "week"
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
    if sort == "featured":
        where.append("featured = 1")
    if sort == "hot" and HOT_WINDOWS[window]:
        where.append("published_at >= datetime('now','localtime', ?)")
        args.append(HOT_WINDOWS[window])
    where_sql = " AND ".join(where)
    if sort == "hot":
        order_sql = (" ORDER BY (like_count + comment_count * 3 + favorite_count * 4"
                     " + view_count * 0.1) DESC, published_at DESC, id DESC")
    elif sort == "featured":
        order_sql = " ORDER BY featured_at DESC, published_at DESC, id DESC"
    else:
        order_sql = " ORDER BY published_at DESC, id DESC"
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM archive_events WHERE {where_sql}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM archive_events WHERE {where_sql}{order_sql} LIMIT ? OFFSET ?",
            (*args, PAGE_SIZE, offset),
        ).fetchall()
        years = [
            row["y"] for row in conn.execute(
                "SELECT DISTINCT substr(occurred_at, 1, 4) y FROM archive_events"
                " WHERE status = 'published' ORDER BY y DESC"
            ) if row["y"]
        ]
        liked, favorited = _viewer_sets(conn, [row["id"] for row in rows], user["id"] if user else None)
    return {
        "items": [_list_item(row, row["id"] in liked, row["id"] in favorited) for row in rows],
        "total": total,
        "page": page,
        "pageSize": PAGE_SIZE,
        "sort": sort,
        "window": window,
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


def _visitor_key(request: Request, user: dict | None) -> str:
    if user:
        return f"u{user['id']}"
    raw = f"{client_ip_from_request(request)}|{user_agent(request)}".encode("utf-8", "ignore")
    return "a" + hashlib.sha256(raw).hexdigest()[:24]


def _related_events(conn, row, user_id: int | None) -> list[dict]:
    tags = set(_parse_json(row["tags"], []))
    candidates = conn.execute(
        "SELECT * FROM archive_events WHERE status = 'published' AND id != ?"
        " AND category = ? ORDER BY (like_count + comment_count * 3"
        " + favorite_count * 4) DESC, published_at DESC LIMIT 8",
        (row["id"], row["category"]),
    ).fetchall()
    ranked = []
    for candidate in candidates:
        overlap = len(tags & set(_parse_json(candidate["tags"], [])))
        ranked.append((overlap, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = [candidate for _, candidate in ranked[:4]]
    liked, favorited = _viewer_sets(conn, [item["id"] for item in chosen], user_id)
    return [_list_item(item, item["id"] in liked, item["id"] in favorited) for item in chosen]


@router.get("/mine/favorites")
def my_favorites(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.* FROM archive_favorites f JOIN archive_events e ON e.id = f.event_id"
            " WHERE f.user_id = ? AND e.status = 'published'"
            " ORDER BY f.created_at DESC LIMIT 200",
            (user["id"],),
        ).fetchall()
        liked, favorited = _viewer_sets(conn, [row["id"] for row in rows], user["id"])
    return {"items": [_list_item(row, row["id"] in liked, row["id"] in favorited) for row in rows]}


@router.get("/{event_id}")
def event_detail(event_id: int, request: Request, user: dict | None = Depends(optional_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_events WHERE id = ? AND status = 'published'", (event_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "事件不存在或已下线")
        viewed = conn.execute(
            "INSERT OR IGNORE INTO archive_views (event_id, visitor_key, viewed_on)"
            " VALUES (?, ?, date('now','localtime'))",
            (event_id, _visitor_key(request, user)),
        ).rowcount
        if viewed:
            conn.execute(
                "UPDATE archive_events SET view_count = view_count + 1 WHERE id = ?", (event_id,)
            )
            row = conn.execute("SELECT * FROM archive_events WHERE id = ?", (event_id,)).fetchone()
        liked, favorited = _viewer_sets(conn, [event_id], user["id"] if user else None)
        related = _related_events(conn, row, user["id"] if user else None)
    data = _event_public(row)
    data["liked"] = event_id in liked
    data["favorited"] = event_id in favorited
    data["related"] = related
    data["disclaimer"] = "本站事件资料来自公开渠道与社区整理，仅供参考，不构成事实认定或法律意见。"
    data["correction_notice"] = "发现事实或表述有误，可登录后提交纠错，管理员审核后更新。"
    return data


@router.post("/{event_id}/like")
def toggle_like(event_id: int, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "archive-like", 60, 600)
    with get_conn() as conn:
        _published_event(conn, event_id)
        exists = conn.execute(
            "SELECT 1 FROM archive_likes WHERE event_id = ? AND user_id = ?",
            (event_id, user["id"]),
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM archive_likes WHERE event_id = ? AND user_id = ?",
                (event_id, user["id"]),
            )
            conn.execute(
                "UPDATE archive_events SET like_count = MAX(0, like_count - 1) WHERE id = ?",
                (event_id,),
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO archive_likes (event_id, user_id) VALUES (?, ?)",
                (event_id, user["id"]),
            )
            conn.execute(
                "UPDATE archive_events SET like_count = like_count + 1 WHERE id = ?",
                (event_id,),
            )
            liked = True
        count = conn.execute(
            "SELECT like_count FROM archive_events WHERE id = ?", (event_id,)
        ).fetchone()["like_count"]
    return {"ok": True, "liked": liked, "count": count}


@router.post("/{event_id}/favorite")
def toggle_favorite(event_id: int, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "archive-favorite", 60, 600)
    with get_conn() as conn:
        _published_event(conn, event_id)
        exists = conn.execute(
            "SELECT 1 FROM archive_favorites WHERE event_id = ? AND user_id = ?",
            (event_id, user["id"]),
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM archive_favorites WHERE event_id = ? AND user_id = ?",
                (event_id, user["id"]),
            )
            conn.execute(
                "UPDATE archive_events SET favorite_count = MAX(0, favorite_count - 1)"
                " WHERE id = ?", (event_id,),
            )
            favorited = False
        else:
            conn.execute(
                "INSERT INTO archive_favorites (event_id, user_id) VALUES (?, ?)",
                (event_id, user["id"]),
            )
            conn.execute(
                "UPDATE archive_events SET favorite_count = favorite_count + 1 WHERE id = ?",
                (event_id,),
            )
            favorited = True
        count = conn.execute(
            "SELECT favorite_count FROM archive_events WHERE id = ?", (event_id,)
        ).fetchone()["favorite_count"]
    return {"ok": True, "favorited": favorited, "count": count}


def _published_event(conn, event_id: int):
    row = conn.execute(
        "SELECT * FROM archive_events WHERE id = ? AND status = 'published'", (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "事件不存在或已下线")
    return row


def _comment_public(row, viewer_id: int | None = None) -> dict:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "parent_id": row["parent_id"],
        "content": row["content"],
        "username": row["username"],
        "avatar_url": row["avatar_url"] or "",
        "created_at": row["created_at"],
        "is_mine": bool(viewer_id and row["user_id"] == viewer_id),
    }


def _comment_rows(conn, event_id: int):
    return conn.execute(
        "SELECT c.*, u.username, u.avatar_url FROM archive_comments c"
        " JOIN users u ON u.id = c.user_id"
        " WHERE c.event_id = ? AND c.status = 'published'"
        " ORDER BY c.id ASC LIMIT 300",
        (event_id,),
    ).fetchall()


@router.get("/{event_id}/comments")
def list_comments(event_id: int, user: dict | None = Depends(optional_user)):
    with get_conn() as conn:
        row = _published_event(conn, event_id)
        rows = _comment_rows(conn, event_id)
    viewer_id = user["id"] if user else None
    top = []
    replies = {}
    for item in rows:
        data = _comment_public(item, viewer_id)
        if item["parent_id"]:
            replies.setdefault(item["parent_id"], []).append(data)
        else:
            data["replies"] = []
            top.append(data)
    for item in top:
        item["replies"] = replies.get(item["id"], [])
    return {"items": top, "total": int(row["comment_count"] or 0)}


@router.post("/{event_id}/comments")
def create_comment(event_id: int, body: CommentBody, request: Request,
                   user: dict = Depends(require_auth)):
    enforce(request, "archive-comment", 8, 600)
    content = clean(body.content, 500)
    if len(content) < 2:
        raise HTTPException(400, "评论至少需要 2 个字")
    with get_conn() as conn:
        _published_event(conn, event_id)
        parent_id = None
        if body.parent_id:
            parent = conn.execute(
                "SELECT * FROM archive_comments WHERE id = ? AND event_id = ?"
                " AND status = 'published'", (body.parent_id, event_id),
            ).fetchone()
            if not parent:
                raise HTTPException(404, "回复的评论不存在")
            if parent["parent_id"]:
                raise HTTPException(400, "只支持回复一级评论")
            parent_id = int(parent["id"])
        cursor = conn.execute(
            "INSERT INTO archive_comments (event_id, user_id, parent_id, content)"
            " VALUES (?, ?, ?, ?)",
            (event_id, user["id"], parent_id, content),
        )
        comment_id = int(cursor.lastrowid)
        conn.execute(
            "UPDATE archive_events SET comment_count = comment_count + 1 WHERE id = ?",
            (event_id,),
        )
        row = conn.execute(
            "SELECT c.*, u.username, u.avatar_url FROM archive_comments c"
            " JOIN users u ON u.id = c.user_id WHERE c.id = ?", (comment_id,),
        ).fetchone()
    _audit(request, "发表事件评论", actor=user, target_id=event_id,
           detail=f"comment={comment_id}")
    return {"ok": True, "comment": _comment_public(row, user["id"])}


@router.delete("/comments/{comment_id}")
def delete_own_comment(comment_id: int, request: Request, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM archive_comments WHERE id = ?", (comment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "评论不存在")
        if row["user_id"] != user["id"]:
            raise HTTPException(403, "只能删除自己的评论")
        if row["status"] != "published":
            return {"ok": True}
        if row["parent_id"] is None:
            count = conn.execute(
                "SELECT COUNT(*) c FROM archive_comments WHERE parent_id = ? AND status = 'published'",
                (comment_id,),
            ).fetchone()["c"]
            total = 1 + int(count)
        else:
            total = 1
        conn.execute(
            "UPDATE archive_comments SET status = 'deleted' WHERE id = ?", (comment_id,)
        )
        if row["parent_id"] is None:
            conn.execute(
                "UPDATE archive_comments SET status = 'deleted'"
                " WHERE parent_id = ? AND status = 'published'", (comment_id,)
            )
        conn.execute(
            "UPDATE archive_events SET comment_count = MAX(0, comment_count - ?) WHERE id = ?",
            (total, row["event_id"]),
        )
    _audit(request, "删除自己的事件评论", actor=user, target_id=row["event_id"],
           detail=f"comment={comment_id}")
    return {"ok": True}


@router.post("/comments/{comment_id}/report")
def report_comment(comment_id: int, body: ReportBody, request: Request,
                   user: dict = Depends(require_auth)):
    enforce(request, "archive-report", 10, 3600)
    reason = clean(body.reason, 300)
    with get_conn() as conn:
        comment = conn.execute(
            "SELECT * FROM archive_comments WHERE id = ? AND status = 'published'", (comment_id,)
        ).fetchone()
        if not comment:
            raise HTTPException(404, "评论不存在")
        duplicate = conn.execute(
            "SELECT 1 FROM archive_comment_reports WHERE comment_id = ?"
            " AND user_id = ? AND status = 'pending'", (comment_id, user["id"]),
        ).fetchone()
        if duplicate:
            raise HTTPException(400, "你已经举报过这条评论，请等待处理")
        conn.execute(
            "INSERT INTO archive_comment_reports (comment_id, user_id, reason) VALUES (?, ?, ?)",
            (comment_id, user["id"], reason or "未填写原因"),
        )
    _audit(request, "举报事件评论", actor=user, target_id=comment["event_id"],
           detail=f"comment={comment_id}")
    return {"ok": True, "message": "举报已提交，管理员会尽快处理"}


@router.post("/submissions")
def submit_event(body: ArchivePayload, request: Request,
                 user: dict | None = Depends(optional_user)):
    enforce(request, "archive-submit", 3, 3600)
    payload = _normalise(body)
    anon_id = _acis_anon_id(request)
    with get_conn() as conn:
        guest = None if user else _guest_user(conn)
        owner_id = user["id"] if user else guest["id"]
        actor = user or guest
        if user:
            pending = conn.execute(
                "SELECT COUNT(*) c FROM archive_submissions WHERE user_id = ? AND status = 'pending'",
                (owner_id,),
            ).fetchone()["c"]
        else:
            pending = conn.execute(
                "SELECT COUNT(*) c FROM archive_submissions WHERE anon_id = ? AND status = 'pending'",
                (anon_id,),
            ).fetchone()["c"]
        if pending >= 1:
            raise HTTPException(400, "你还有一条投稿在审核中，请等待处理后再提交")
        if not payload["contact"] and user:
            payload["contact"] = user.get("qq") or user.get("email") or ""
        payload["personal_info_mode"] = "public"
        cursor = conn.execute(
            "INSERT INTO archive_submissions (user_id, anon_id, payload) VALUES (?, ?, ?)",
            (owner_id, anon_id, json.dumps(payload, ensure_ascii=False)),
        )
        submission_id = int(cursor.lastrowid)
    _audit(request, "提交事件投稿", actor=actor, target_id=submission_id,
           detail=payload["title"])
    return {"ok": True, "id": submission_id, "message": "投稿已提交，管理员审核通过后会自动发布"}


@router.post("/{event_id}/corrections")
def submit_correction(event_id: int, body: CorrectionBody, request: Request,
                      user: dict | None = Depends(optional_user)):
    enforce(request, "archive-correction", 5, 3600)
    field = body.field if body.field in ("title", "summary", "occurred_at", "category", "other") else "other"
    proposed = clean(body.proposed_value, 8000)
    reason = clean(body.reason, 500)
    source_url = body.source_url.strip()
    if len(proposed) < 2:
        raise HTTPException(400, "请填写需要更正的内容")
    if source_url and not (source_url.startswith("https://") or source_url.startswith("http://")):
        raise HTTPException(400, "来源链接格式不正确")
    anon_id = _acis_anon_id(request)
    with get_conn() as conn:
        event = conn.execute(
            "SELECT id, title, summary, occurred_at, category FROM archive_events"
            " WHERE id = ? AND status = 'published'", (event_id,)
        ).fetchone()
        if not event:
            raise HTTPException(404, "事件不存在或已下线")
        guest = None if user else _guest_user(conn)
        owner_id = user["id"] if user else guest["id"]
        actor = user or guest
        if user:
            pending = conn.execute(
                "SELECT 1 FROM archive_corrections WHERE event_id = ? AND user_id = ?"
                " AND status = 'pending'", (event_id, owner_id),
            ).fetchone()
        else:
            pending = conn.execute(
                "SELECT 1 FROM archive_corrections WHERE event_id = ? AND anon_id = ?"
                " AND status = 'pending'", (event_id, anon_id),
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
            "INSERT INTO archive_corrections (event_id, user_id, anon_id, field, current_value,"
            " proposed_value, reason, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, owner_id, anon_id, field, current, proposed, reason, source_url),
        )
        correction_id = int(cursor.lastrowid)
    _audit(request, "提交事件纠错", actor=actor, target_id=correction_id,
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


@admin_router.post("/events/{event_id}/featured")
def admin_set_featured(event_id: int, body: FeaturedBody, request: Request,
                       user: dict = Depends(require_capability("manage_archive"))):
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM archive_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "事件不存在")
        conn.execute(
            "UPDATE archive_events SET featured = ?,"
            " featured_at = CASE WHEN ? = 1 THEN datetime('now','localtime') ELSE NULL END"
            " WHERE id = ?",
            (1 if body.featured else 0, 1 if body.featured else 0, event_id),
        )
        _revision(conn, event_id, user["id"], "featured", {"featured": body.featured})
    _audit(request, "设置事件精选" if body.featured else "取消事件精选",
           actor=user, target_id=event_id, detail=row["title"])
    return {"ok": True, "featured": body.featured}


def _comment_status_change(conn, comment, status: str, admin_id: int) -> int:
    affected = [comment]
    if comment["parent_id"] is None:
        affected.extend(conn.execute(
            "SELECT * FROM archive_comments WHERE parent_id = ?", (comment["id"],)
        ).fetchall())
    before = sum(1 for item in affected if item["status"] == "published")
    ids = [item["id"] for item in affected]
    marks = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE archive_comments SET status = ?, hidden_by = ?,"
        f" hidden_at = datetime('now','localtime') WHERE id IN ({marks})",
        (status, admin_id, *ids),
    )
    after = sum(1 for _ in affected) if status == "published" else 0
    delta = after - before
    if delta:
        conn.execute(
            "UPDATE archive_events SET comment_count = MAX(0, comment_count + ?) WHERE id = ?",
            (delta, comment["event_id"]),
        )
    return len(affected)


@admin_router.get("/comments")
def admin_comments(status: str = "published",
                   user: dict = Depends(require_capability("manage_archive"))):
    if status not in ("published", "hidden", "deleted", "all"):
        status = "published"
    where = "1=1" if status == "all" else "c.status = ?"
    args = () if status == "all" else (status,)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT c.*, e.title AS event_title, u.username,"
            " (SELECT COUNT(*) FROM archive_comment_reports r"
            "  WHERE r.comment_id = c.id AND r.status = 'pending') AS report_count"
            " FROM archive_comments c JOIN archive_events e ON e.id = c.event_id"
            " JOIN users u ON u.id = c.user_id"
            f" WHERE {where} ORDER BY c.id DESC LIMIT 200", args,
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@admin_router.post("/comments/{comment_id}/status")
def admin_comment_status(comment_id: int, body: CommentStatusBody, request: Request,
                         user: dict = Depends(require_capability("manage_archive"))):
    if body.status not in ("published", "hidden", "deleted"):
        raise HTTPException(400, "无效的评论状态")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM archive_comments WHERE id = ?", (comment_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "评论不存在")
        affected = _comment_status_change(conn, row, body.status, user["id"])
    _audit(request, f"设置评论状态为 {body.status}", actor=user,
           target_id=row["event_id"], detail=f"comment={comment_id} affected={affected}")
    return {"ok": True, "affected": affected}


@admin_router.get("/reports")
def admin_reports(status: str = "pending",
                  user: dict = Depends(require_capability("manage_archive"))):
    if status not in ("pending", "resolved", "all"):
        status = "pending"
    where = "1=1" if status == "all" else "r.status = ?"
    args = () if status == "all" else (status,)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, c.content, c.status AS comment_status, c.event_id,"
            " e.title AS event_title, reporter.username AS reporter_name,"
            " author.username AS author_name"
            " FROM archive_comment_reports r"
            " JOIN archive_comments c ON c.id = r.comment_id"
            " JOIN archive_events e ON e.id = c.event_id"
            " JOIN users reporter ON reporter.id = r.user_id"
            " JOIN users author ON author.id = c.user_id"
            f" WHERE {where} ORDER BY r.id DESC LIMIT 200", args,
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@admin_router.post("/reports/{report_id}/resolve")
def resolve_report(report_id: int, body: ResolveReportBody, request: Request,
                   user: dict = Depends(require_capability("manage_archive"))):
    if body.action not in ("hide", "dismiss"):
        raise HTTPException(400, "无效操作")
    note = clean(body.note, 300)
    with get_conn() as conn:
        report = conn.execute(
            "SELECT * FROM archive_comment_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not report:
            raise HTTPException(404, "举报不存在")
        if report["status"] != "pending":
            raise HTTPException(400, "该举报已处理")
        comment = conn.execute(
            "SELECT * FROM archive_comments WHERE id = ?", (report["comment_id"],)
        ).fetchone()
        if not comment:
            raise HTTPException(404, "评论不存在")
        if body.action == "hide":
            _comment_status_change(conn, comment, "hidden", user["id"])
            conn.execute(
                "UPDATE archive_comment_reports SET status = 'resolved', resolution_note = ?,"
                " resolved_by = ?, resolved_at = datetime('now','localtime')"
                " WHERE comment_id = ? AND status = 'pending'",
                (note or "举报成立，评论已隐藏", user["id"], comment["id"]),
            )
        else:
            conn.execute(
                "UPDATE archive_comment_reports SET status = 'resolved', resolution_note = ?,"
                " resolved_by = ?, resolved_at = datetime('now','localtime') WHERE id = ?",
                (note or "举报不成立", user["id"], report_id),
            )
    _audit(request, "处理评论举报", actor=user, target_id=comment["event_id"],
           detail=f"report={report_id} action={body.action}")
    return {"ok": True}
