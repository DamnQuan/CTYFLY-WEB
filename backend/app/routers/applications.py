"""申请 API：管制员申请 / 职员申请"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..database import get_conn
from ..deps import require_auth
from ..text import clean

router = APIRouter(prefix="/api/applications", tags=["applications"])


class ApplicationBody(BaseModel):
    type: str = Field("", max_length=16)
    nickname: str = Field("", max_length=32)
    hours: str = Field("", max_length=32)
    experience: str = Field("", max_length=200)
    motivation: str = Field("", max_length=1000)
    availableTime: str = Field("", max_length=100)


@router.get("/mine")
def my_applications(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC", (user["id"],)
        ).fetchall()
    return {"ok": True, "applications": [dict(r) for r in rows]}


@router.post("")
def create_application(body: ApplicationBody, user: dict = Depends(require_auth)):
    if body.type not in ("controller", "staff"):
        raise HTTPException(400, "无效的申请类型")

    with get_conn() as conn:
        pending = conn.execute(
            "SELECT 1 FROM applications WHERE user_id = ? AND type = ? AND status = 'pending'",
            (user["id"], body.type),
        ).fetchone()
        if pending:
            raise HTTPException(400, "您已有同类型申请正在审核中，请耐心等待")

    nickname = clean(body.nickname, 32)
    if not nickname:
        raise HTTPException(400, "请填写称呼")

    if body.type == "controller":
        if not body.hours.strip():
            raise HTTPException(400, "请填写累计连飞时长")
        if not body.experience.strip():
            raise HTTPException(400, "请填写管制经验")
    else:
        if not body.availableTime.strip():
            raise HTTPException(400, "请填写可参与工作时间")
        if not body.motivation.strip():
            raise HTTPException(400, "请填写申请理由")

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO applications (user_id, type, nickname, hours, experience, motivation, available_time)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], body.type, nickname, clean(body.hours, 32),
             clean(body.experience, 200), clean(body.motivation, 1000), clean(body.availableTime, 100)),
        )
    return {"ok": True, "id": cur.lastrowid}
