"""平台发展问卷：公开提交与后台查看

公开接口只负责发题与收卷，后台接口按 view_surveys 能力控制可见性。
"""
import csv
import io
import json
import re
import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..audit import log_event
from ..captcha import require_pow_verification
from ..database import get_conn
from ..deps import optional_user, require_capability
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent
from ..survey import (QUESTIONS, describe_answers, parse_answers,
                      priority_counts, public_schema, validate_answers)
from ..text import csv_safe

router = APIRouter(tags=["survey"])

# 后端分页固定每页 20 条，只允许前端传 offset：不给用户可控的 LIMIT，保持与后台其它列表一致
_PAGE_SIZE = 20
# 匿名浏览器标识：服务端下发 HttpOnly Cookie，用来保证未登录用户也只能交一份
_ANON_COOKIE = "ctyfly_survey_uid"
_ANON_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_ALREADY_MESSAGE = "你已经提交过问卷了，感谢支持"


class SubmitBody(BaseModel):
    answers: dict = Field(default_factory=dict)
    nickname: str = Field("", max_length=40)
    contact: str = Field("", max_length=120)


def _identity(row) -> dict | None:
    if not row["user_id"] and not row["username"]:
        return None
    return {
        "userId": row["user_id"],
        "cid": row["cid"],
        "username": row["username"],
    }


def _ensure_anon_id(request: Request, response: Response) -> str:
    """读取或下发匿名浏览器标识；服务端保存，前端无需也不允许读取"""
    value = request.cookies.get(_ANON_COOKIE, "")
    if not _ANON_RE.match(value or ""):
        value = secrets.token_urlsafe(24)
    secure = request.url.scheme == "https" or request.headers.get(
        "x-forwarded-proto", ""
    ).lower().startswith("https")
    response.set_cookie(
        _ANON_COOKIE, value, max_age=365 * 24 * 3600, path="/",
        httponly=True, samesite="lax", secure=secure,
    )
    return value


def _already_submitted(conn, user: dict | None, anon_id: str) -> bool:
    if user:
        return conn.execute(
            "SELECT 1 FROM survey_responses WHERE user_id = ?", (user["id"],)
        ).fetchone() is not None
    return conn.execute(
        "SELECT 1 FROM survey_responses WHERE anon_id = ? AND anon_id != ''",
        (anon_id,),
    ).fetchone() is not None


@router.get("/api/survey/schema")
def survey_schema(request: Request, response: Response,
                  user: dict | None = Depends(optional_user)):
    """公开页取题：同时告诉前端当前身份是否已经交过，避免重复填写"""
    anon_id = _ensure_anon_id(request, response)
    with get_conn() as conn:
        submitted = _already_submitted(conn, user, anon_id)
    return {"ok": True, "submitted": submitted, **public_schema()}


@router.post("/api/survey")
def submit_survey(body: SubmitBody, request: Request, response: Response,
                  user: dict | None = Depends(optional_user),
                  _pow: None = Depends(require_pow_verification)):
    """提交问卷；登录用户自动带上身份，游客可留昵称与联系方式；每人限一份"""
    enforce(request, "survey", 5, 3600)
    try:
        answers = validate_answers(body.answers)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    nickname = (body.nickname or "").strip()
    contact = (body.contact or "").strip()
    ip = client_ip_from_request(request)
    anon_id = _ensure_anon_id(request, response)
    with get_conn() as conn:
        if _already_submitted(conn, user, anon_id):
            raise HTTPException(409, _ALREADY_MESSAGE)
        try:
            cur = conn.execute(
                "INSERT INTO survey_responses"
                " (user_id, cid, username, nickname, contact, answers, ip, ua, anon_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user["id"] if user else None,
                    user["cid"] if user else "",
                    user["username"] if user else "",
                    nickname,
                    contact,
                    json.dumps(answers, ensure_ascii=False),
                    ip,
                    user_agent(request),
                    # 登录用户按账号去重，不再占匿名标识，避免同浏览器多账号互相顶掉
                    anon_id if not user else "",
                ),
            )
        except sqlite3.IntegrityError:
            # 唯一索引兜底：并发提交时由数据库保证只有一份
            raise HTTPException(409, _ALREADY_MESSAGE)
        row_id = cur.lastrowid
    log_event("content", "提交平台发展问卷", actor=user, target_type="survey",
              target_id=row_id, ip=ip, ua=user_agent(request))
    return {"ok": True, "id": row_id, "message": "感谢反馈，我们会认真阅读每一条建议"}


@router.get("/api/admin/surveys")
def list_surveys(offset: int = 0,
                 user: dict = Depends(require_capability("view_surveys"))):
    """问卷列表与概览；按提交时间倒序，支持翻页，每页条数由服务端固定"""
    offset = max(0, int(offset))
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM survey_responses"
            " WHERE date(created_at) = date('now','localtime')"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM survey_responses ORDER BY id DESC LIMIT ? OFFSET ?",
            (_PAGE_SIZE, offset),
        ).fetchall()
        all_answers = [
            parse_answers(r["answers"])
            for r in conn.execute("SELECT answers FROM survey_responses")
        ]
    scores = [a["satisfaction"] for a in all_answers if isinstance(a.get("satisfaction"), int)]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    items = []
    for row in rows:
        answers = parse_answers(row["answers"])
        items.append({
            "id": row["id"],
            "createdAt": row["created_at"],
            "identity": _identity(row),
            "nickname": row["nickname"],
            "contact": row["contact"],
            "answers": describe_answers(answers),
        })
    return {
        "ok": True,
        "total": total,
        "limit": _PAGE_SIZE,
        "offset": offset,
        "summary": {
            "total": total,
            "today": today,
            "averageSatisfaction": avg_score,
            "priorities": priority_counts(all_answers),
        },
        "items": items,
    }


@router.get("/api/admin/surveys/export")
def export_surveys(request: Request,
                   user: dict = Depends(require_capability("view_surveys"))):
    """导出全部问卷为 CSV，Excel 直接打开不乱码"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM survey_responses ORDER BY id DESC"
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    title_by_key = {q["key"]: q["title"] for q in QUESTIONS}
    writer.writerow(
        ["编号", "提交时间", "CID", "用户名", "昵称", "联系方式"]
        + [title_by_key[q["key"]] for q in QUESTIONS]
    )
    for row in rows:
        answers = parse_answers(row["answers"])
        display = {d["key"]: d["display"] for d in describe_answers(answers)}
        writer.writerow(
            [csv_safe(row["id"]), csv_safe(row["created_at"]), csv_safe(row["cid"]),
             csv_safe(row["username"]), csv_safe(row["nickname"]), csv_safe(row["contact"])]
            + [csv_safe(display.get(q["key"], "")) for q in QUESTIONS]
        )
    content = "\ufeff" + buf.getvalue()
    log_event("content", "导出平台发展问卷", actor=user, target_type="survey",
              detail=f"共 {len(rows)} 份", ip=client_ip_from_request(request),
              ua=user_agent(request))
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="survey-export.csv"'},
    )
