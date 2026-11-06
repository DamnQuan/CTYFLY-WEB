"""真实用户性能指标上报：公开接口写入性能表。"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_conn
from app.main import app


@pytest.fixture()
def client(db):
    return TestClient(app)


def test_perf_report_accepts_anonymous(client):
    r = client.post("/api/perf", json={
        "path": "/acis",
        "lcp": 1200,
        "inp": 80,
        "cls": 0.01,
        "ttfb": 60,
        "device": "mobile",
    })
    assert r.status_code == 200, r.text
    with get_conn() as conn:
        row = conn.execute(
            "SELECT path, lcp, inp, cls, ttfb, device FROM perf_metrics ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["path"] == "/acis"
    assert row["device"] == "mobile"
    assert row["lcp"] == 1200
