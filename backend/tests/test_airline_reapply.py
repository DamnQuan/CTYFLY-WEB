"""航司建司申请：被驳回后可复用原记录重新提交，不被 400 拦截。"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limit():
    from app import ratelimit

    ratelimit._buckets.clear()
    yield
    ratelimit._buckets.clear()


def auth(conn, user_id: int) -> dict:
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def test_rejected_airline_can_reapply(client, conn):
    author = make_user(conn, cid="8301", username="va_reapply")
    admin = make_user(conn, cid="8302", username="va_admin", role="admin")
    user_h = auth(conn, author)
    admin_h = auth(conn, admin)

    body = {
        "icao": "TST1",
        "name": "测试重审航空",
        "description": "第一次提交",
        "logoUrl": "",
    }
    first = client.post("/api/airlines", json=body, headers=user_h)
    assert first.status_code == 200, first.text
    airline_id = first.json()["id"]

    pending = client.get("/api/airlines", headers=user_h).json()["myApplication"]
    assert pending["status"] == "pending"

    rejected = client.post(
        f"/api/airlines/admin/{airline_id}/review",
        json={"action": "reject", "note": "资料不足，请补充简介"},
        headers=admin_h,
    )
    assert rejected.status_code == 200, rejected.text

    state = client.get("/api/airlines", headers=user_h).json()["myApplication"]
    assert state["status"] == "rejected"
    assert state["review_note"] == "资料不足，请补充简介"

    # 沿用原代码和名称重新提交：不应被「已创建过航司」或唯一性检查拦截
    again = client.post(
        "/api/airlines",
        json={**body, "description": "已补充的简介"},
        headers=user_h,
    )
    assert again.status_code == 200, again.text
    data = again.json()
    assert data["id"] == airline_id
    assert data["reapply"] is True
    assert data["previous_note"] == "资料不足，请补充简介"

    state = client.get("/api/airlines", headers=user_h).json()["myApplication"]
    assert state["status"] == "pending"
    assert state["description"] == "已补充的简介"
    assert state["review_note"] == "资料不足，请补充简介"

    # 待审核期间不能重复提交
    blocked = client.post("/api/airlines", json=body, headers=user_h)
    assert blocked.status_code == 400
    assert "审核中" in blocked.json()["error"]


def test_reapply_can_change_icao_and_name(client, conn):
    author = make_user(conn, cid="8311", username="va_reapply_rename")
    admin = make_user(conn, cid="8312", username="va_admin2", role="admin")
    user_h = auth(conn, author)
    admin_h = auth(conn, admin)

    first = client.post("/api/airlines", json={
        "icao": "TST2", "name": "测试重审航空二号", "description": "", "logoUrl": "",
    }, headers=user_h)
    assert first.status_code == 200, first.text
    airline_id = first.json()["id"]
    assert client.post(
        f"/api/airlines/admin/{airline_id}/review",
        json={"action": "reject", "note": "换一个代码再试"},
        headers=admin_h,
    ).status_code == 200

    again = client.post("/api/airlines", json={
        "icao": "TST3", "name": "测试重审航空三号", "description": "", "logoUrl": "",
    }, headers=user_h)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == airline_id
    state = client.get("/api/airlines", headers=user_h).json()["myApplication"]
    assert state["icao"] == "TST3"
    assert state["name"] == "测试重审航空三号"
