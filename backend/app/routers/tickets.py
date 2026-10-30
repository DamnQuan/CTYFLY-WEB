"""工单 API，含附件：图片 / PDF / Word

附件安全设计，防「图标越狱」类攻击：
- 类型只认**文件头 magic bytes**，客户端提供的扩展名 / Content-Type 一律不信任；
  SVG 明确不支持——SVG 可内嵌脚本，作为附件托管就是存储型 XSS。
- DOCX 额外校验 ZIP 结构必须包含 word/document.xml，防止任意文件改名混入。
- 落盘文件名服务端随机生成；原始文件名只存库用于展示，剥离路径与控制字符。
- 附件只能经 /api/attachments/{id} 带鉴权流式读取，仅工单主人与管理员可见，
  响应带 CSP sandbox 与 nosniff，即使内容被伪装也无法在页面上下文执行。
"""
import io
import secrets
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..audit import log_event
from ..config import ATTACH_DIR, MAX_ATTACH_BYTES, MAX_ATTACH_PER_TICKET
from ..database import get_conn
from ..mailer import notify_user
from ..deps import has_capability, require_auth
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent
from ..text import clean

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
attach_router = APIRouter(prefix="/api/attachments", tags=["tickets"])

CATEGORIES = ["连飞问题", "账号问题", "管制申请", "投诉建议", "其他"]


def _can_manage_tickets(user: dict) -> bool:
    """工单 staff 口径：具备 manage_tickets 能力即算，role=admin 天然全量；
    被授予该能力的 SUP/职員也能处理工单，与 admin.py 的 has_capability 用法一致。"""
    return has_capability(user, "manage_tickets")


# ---------- 附件：类型识别，只信文件头 ----------

def sniff_attachment(head: bytes, data: bytes) -> tuple[str, str, str] | None:
    """按文件头识别类型，返回 落盘扩展名, Content-Type, kind；不在白名单返回 None。

    Word 的两代格式都认：.docx，ZIP 容器，须含 word/document.xml、
    .doc，OLE2 复合文档 \xD0\xCF\x11\xE0。
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png", "image"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg", "image"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif", "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp", "image"
    if head.startswith(b"%PDF-"):
        return ".pdf", "application/pdf", "pdf"
    # OLE2：老版 .doc，Word 97-2003
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ".doc", "application/msword", "word"
    # ZIP 容器：.docx，必须真的是 Word 文档结构，防任意 ZIP/程序改名混入
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except Exception:
            return None
        if "word/document.xml" in names and "[Content_Types].xml" in names:
            return ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word"
    return None


def _safe_orig_name(name: str) -> str:
    """原始文件名只用于展示：剥离路径、控制字符，限长，空则给默认名"""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '\\"<>')
    name = name.strip().lstrip(".")
    return (name or "附件")[:120]


def _get_ticket_checked(conn, ticket_id: int, user: dict):
    t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not t:
        raise HTTPException(404, "工单不存在")
    if t["user_id"] != user["id"] and not _can_manage_tickets(user):
        raise HTTPException(403, "只能操作自己的工单附件")
    return t


def _attachment_meta(row) -> dict:
    return {
        "id": row["id"], "ticketId": row["ticket_id"], "replyId": row["reply_id"],
        "name": row["orig_name"], "kind": row["kind"],
        "contentType": row["content_type"], "size": row["size"],
        "createdAt": row["created_at"],
    }


@router.get("")
def list_tickets(scope: str = "", user: dict = Depends(require_auth)):
    show_all = _can_manage_tickets(user) and scope == "all"
    base = (
        "SELECT t.*, u.cid, u.username, u.avatar_url,"
        " (SELECT COUNT(*) FROM ticket_replies r WHERE r.ticket_id = t.id) AS reply_count"
        " FROM tickets t JOIN users u ON u.id = t.user_id"
    )
    with get_conn() as conn:
        if show_all:
            rows = conn.execute(f"{base} ORDER BY t.updated_at DESC LIMIT 200").fetchall()
        else:
            rows = conn.execute(
                f"{base} WHERE t.user_id = ? ORDER BY t.updated_at DESC LIMIT 200", (user["id"],)
            ).fetchall()
    return {"ok": True, "tickets": [dict(r) for r in rows], "categories": CATEGORIES}


class TicketBody(BaseModel):
    title: str = Field("", max_length=80)
    category: str = Field("其他", max_length=16)
    content: str = Field("", max_length=2000)


@router.post("")
def create_ticket(body: TicketBody, user: dict = Depends(require_auth)):
    title = clean(body.title, 60)
    content = clean(body.content, 2000)
    if not title:
        raise HTTPException(400, "标题需 1-60 字")
    if not content:
        raise HTTPException(400, "请描述您的问题")
    category = body.category if body.category in CATEGORIES else "其他"

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (user_id, title, category) VALUES (?, ?, ?)",
            (user["id"], title, category),
        )
        conn.execute(
            "INSERT INTO ticket_replies (ticket_id, user_id, is_staff, content) VALUES (?, ?, 0, ?)",
            (cur.lastrowid, user["id"], content),
        )
    return {"ok": True, "id": cur.lastrowid}


@router.get("/{ticket_id}")
def ticket_detail(ticket_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        ticket = conn.execute(
            "SELECT t.*, u.cid, u.username, u.avatar_url FROM tickets t"
            " JOIN users u ON u.id = t.user_id WHERE t.id = ?",
            (ticket_id,),
        ).fetchone()
        if not ticket:
            raise HTTPException(404, "工单不存在")
        if not _can_manage_tickets(user) and ticket["user_id"] != user["id"]:
            raise HTTPException(403, "无权限查看")
        replies = conn.execute(
            "SELECT r.*, u.username, u.cid, u.avatar_url, u.role FROM ticket_replies r"
            " JOIN users u ON u.id = r.user_id WHERE r.ticket_id = ? ORDER BY r.id",
            (ticket_id,),
        ).fetchall()
    return {"ok": True, "ticket": dict(ticket), "replies": [dict(r) for r in replies]}


class ReplyBody(BaseModel):
    content: str = Field("", max_length=2000)


@router.post("/{ticket_id}/reply")
def reply_ticket(ticket_id: int, body: ReplyBody, user: dict = Depends(require_auth)):
    content = clean(body.content, 2000)
    if not content:
        raise HTTPException(400, "回复内容不能为空")

    with get_conn() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not ticket:
            raise HTTPException(404, "工单不存在")
        if not _can_manage_tickets(user) and ticket["user_id"] != user["id"]:
            raise HTTPException(403, "无权限回复")
        if ticket["status"] == "closed":
            raise HTTPException(400, "工单已关闭")

        # staff 口径与工单管理页一致：具备 manage_tickets 能力且非工单本人的回复
        # 才算客服回复，触发状态机 replied 与邮件提醒
        is_staff = 1 if (_can_manage_tickets(user) and user["id"] != ticket["user_id"]) else 0
        cur = conn.execute(
            "INSERT INTO ticket_replies (ticket_id, user_id, is_staff, content) VALUES (?, ?, ?, ?)",
            (ticket_id, user["id"], is_staff, content),
        )
        next_status = "replied" if is_staff else ("open" if ticket["status"] == "replied" else ticket["status"])
        conn.execute(
            "UPDATE tickets SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (next_status, ticket_id),
        )
    # 管理员回复了用户的工单 → 邮件提醒工单主人，用户自己的回复不提醒，避免自己收到自己
    if is_staff:
        # 带上回复内容预览：用户不登录也能知道客服说了什么
        preview = content[:200] + ("…" if len(content) > 200 else "")
        notify_user(
            ticket["user_id"], "你的工单有新回复",
            f"工单「{ticket['title']}」有新的客服回复：\n"
            f"「{preview}」\n"
            f"登录即可查看完整对话并继续跟进。",
        )
    return {"ok": True, "id": cur.lastrowid}


class TicketStatusBody(BaseModel):
    status: str = ""


@router.patch("/{ticket_id}/status")
def set_ticket_status(ticket_id: int, body: TicketStatusBody, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not ticket:
            raise HTTPException(404, "工单不存在")

        is_owner = ticket["user_id"] == user["id"]
        # 与列表/详情同口径：具备 manage_tickets 能力即视作客服，可关/开任意工单
        is_staff = _can_manage_tickets(user)
        allowed = (body.status in ("closed", "open") and (is_staff or is_owner))
        if not allowed:
            raise HTTPException(403, "无权限执行该操作")

        conn.execute(
            "UPDATE tickets SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (body.status, ticket_id),
        )
    return {"ok": True}


# ==================== 附件 ====================

@router.get("/{ticket_id}/attachments")
def list_attachments(ticket_id: int, user: dict = Depends(require_auth)):
    """工单附件清单，工单主人与管理员可见"""
    with get_conn() as conn:
        _get_ticket_checked(conn, ticket_id, user)
        rows = conn.execute(
            "SELECT a.*, u.username AS uploader FROM ticket_attachments a"
            " JOIN users u ON u.id = a.user_id WHERE a.ticket_id = ? ORDER BY a.id",
            (ticket_id,),
        ).fetchall()
    return {"ok": True, "attachments": [_attachment_meta(r) | {"uploader": r["uploader"]} for r in rows]}


@router.post("/{ticket_id}/attachments")
async def upload_attachment(
    ticket_id: int,
    request: Request,
    file: UploadFile = File(...),
    reply_id: int = Form(0),
    user: dict = Depends(require_auth),
):
    """上传工单附件，一次一个文件；reply_id 可选，表示附属于某条回复"""
    enforce(request, "attach", 30, 3600)
    with get_conn() as conn:
        _get_ticket_checked(conn, ticket_id, user)
        if reply_id:
            r = conn.execute(
                "SELECT * FROM ticket_replies WHERE id = ? AND ticket_id = ?", (reply_id, ticket_id)
            ).fetchone()
            if not r or r["user_id"] != user["id"]:
                raise HTTPException(400, "回复不存在或无权限")
        count = conn.execute(
            "SELECT COUNT(*) c FROM ticket_attachments WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()["c"]
        if count >= MAX_ATTACH_PER_TICKET:
            raise HTTPException(400, f"每个工单最多 {MAX_ATTACH_PER_TICKET} 个附件")

    head = await file.read(16)
    rest = await file.read(MAX_ATTACH_BYTES + 1)
    data = head + rest
    if not data:
        raise HTTPException(400, "请选择要上传的文件")
    if len(data) > MAX_ATTACH_BYTES:
        raise HTTPException(400, f"单个文件不能超过 {MAX_ATTACH_BYTES // 1024 // 1024} MB")

    sniffed = sniff_attachment(head, data)
    if not sniffed:
        raise HTTPException(400, "仅支持图片，PNG/JPG/WebP/GIF、PDF、Word，doc/docx 文件")
    ext, content_type, kind = sniffed

    stored = f"att-{secrets.token_hex(16)}{ext}"
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    (ATTACH_DIR / stored).write_bytes(data)
    orig = _safe_orig_name(file.filename or "")

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO ticket_attachments (ticket_id, reply_id, user_id, orig_name, stored_name,"
            " content_type, kind, size) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, reply_id or None, user["id"], orig, stored, content_type, kind, len(data)),
        )
        att_id = cur.lastrowid
    log_event("content", "上传工单附件", actor=user, target_type="attachment", target_id=att_id,
              detail=f"ticket={ticket_id} · {len(data) // 1024}KB · {content_type}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "attachment": {
        "id": att_id, "ticketId": ticket_id, "replyId": reply_id or None,
        "name": orig, "kind": kind, "contentType": content_type, "size": len(data),
    }}


@attach_router.get("/{attachment_id}")
def download_attachment(attachment_id: int, user: dict = Depends(require_auth)):
    """读取附件：仅工单主人与管理员；带 CSP sandbox + nosniff 防内容伪装执行"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT a.*, t.user_id AS ticket_owner FROM ticket_attachments a"
            " JOIN tickets t ON t.id = a.ticket_id WHERE a.id = ?",
            (attachment_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "附件不存在")
    if row["ticket_owner"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权限访问该附件")

    path = ATTACH_DIR / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "附件文件已丢失，请联系管理员")
    disp = "inline" if row["kind"] in ("image", "pdf") else "attachment"
    return FileResponse(
        path,
        media_type=row["content_type"],
        headers={
            # 原始文件名可能含中文/特殊字符：ASCII 兜底 + RFC 5987 UTF-8
            "Content-Disposition": f"{disp}; filename=\"attachment-{row['id']}\"; filename*=UTF-8''{quote(row['orig_name'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
            # 即使附件内容被伪装成 HTML/脚本，也在沙箱里、且禁止加载任何子资源
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@attach_router.delete("/{attachment_id}")
def delete_attachment(attachment_id: int, user: dict = Depends(require_auth)):
    """删除附件：上传者本人或管理员，保护用户数据：自己传的随时可删"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ticket_attachments WHERE id = ?", (attachment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "附件不存在")
        if row["user_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "只能删除自己上传的附件")
        conn.execute("DELETE FROM ticket_attachments WHERE id = ?", (attachment_id,))
    try:
        (ATTACH_DIR / row["stored_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}
