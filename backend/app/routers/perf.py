"""真实用户性能指标采集：Core Web Vitals 的轻量上报入口。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..database import get_conn
from ..ratelimit import enforce
from ..text import clean

router = APIRouter(prefix="/api/perf", tags=["perf"])


class PerfBody(BaseModel):
    path: str = Field("/", max_length=200)
    lcp: float = Field(0, ge=0, le=120000)
    inp: float = Field(0, ge=0, le=120000)
    cls: float = Field(0, ge=0, le=10)
    ttfb: float = Field(0, ge=0, le=120000)
    device: str = Field("", max_length=20)


@router.post("")
def report_perf(body: PerfBody, request: Request):
    enforce(request, "perf-report", 60, 3600)
    path = clean(body.path, 200) or "/"
    device = clean(body.device, 20)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO perf_metrics (path, lcp, inp, cls, ttfb, device)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (path, body.lcp, body.inp, body.cls, body.ttfb, device),
        )
    return {"ok": True}
