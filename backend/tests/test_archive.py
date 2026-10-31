"""飞圈事件检索：公开检索、投稿审核、编辑后发布、纠错与隐私脱敏。"""
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


def payload(**over):
    data = {
        "title": "测试飞圈事件标题",
        "occurred_at": "2026-01",
        "category": "社区与活动",
        "summary": "这是一条用于测试的事件摘要",
        "tags": ["测试", "连飞"],
        "blocks": [
            {"type": "text", "text": "事件正文内容，足够十个字以上。"},
            {"type": "image", "url": "/uploads/archive-test.png", "caption": "现场图片"},
        ],
        "contact": "123456789",
    }
    data.update(over)
    return data


def make_users(conn):
    author = make_user(conn, cid="8101", username="archive_author")
    admin = make_user(conn, cid="8102", username="archive_admin", role="admin")
    return author, admin


def submit(client, headers, data=None):
    return client.post("/api/archive/submissions", json=data or payload(), headers=headers)


def test_public_list_and_detail(client, conn):
    author, admin = make_users(conn)
    h = auth(conn, author)
    r = submit(client, h)
    assert r.status_code == 200, r.text
    submission_id = r.json()["id"]

    # 未审核不进入公开检索
    assert client.get("/api/archive").json()["total"] == 0

    ah = auth(conn, admin)
    r = client.post(f"/api/admin/archive/submissions/{submission_id}/approve",
                    json={"payload": payload(), "note": "通过"}, headers=ah)
    assert r.status_code == 200, r.text
    event_id = r.json()["event_id"]

    listing = client.get("/api/archive", params={"q": "测试"}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == event_id

    detail = client.get(f"/api/archive/{event_id}").json()
    assert detail["title"] == "测试飞圈事件标题"
    assert detail["occurred_at"] == "2026-01"
    assert detail["blocks"][1]["url"] == "/uploads/archive-test.png"
    assert "disclaimer" in detail
    assert "contact" not in detail


def test_submission_requires_login_and_one_pending(client, conn):
    author, _ = make_users(conn)
    assert client.post("/api/archive/submissions", json=payload()).status_code == 401
    h = auth(conn, author)
    assert submit(client, h).status_code == 200
    second = submit(client, h)
    assert second.status_code == 400
    assert "审核中" in second.json()["error"]


def test_admin_edit_before_publish(client, conn):
    author, admin = make_users(conn)
    h = auth(conn, author)
    sid = submit(client, h).json()["id"]
    ah = auth(conn, admin)

    edited = payload(title="管理员修改后的标题", summary="管理员改写的摘要")
    r = client.put(f"/api/admin/archive/submissions/{sid}/draft", json=edited, headers=ah)
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/admin/archive/submissions/{sid}", headers=ah).json()
    assert detail["draft"]["title"] == "管理员修改后的标题"

    r = client.post(f"/api/admin/archive/submissions/{sid}/approve",
                    json={"payload": edited, "note": "编辑后发布"}, headers=ah)
    assert r.status_code == 200, r.text
    event_id = r.json()["event_id"]
    assert client.get(f"/api/archive/{event_id}").json()["title"] == "管理员修改后的标题"

    with conn:
        revisions = conn.execute(
            "SELECT action FROM archive_revisions WHERE event_id = ?", (event_id,)
        ).fetchall()
    assert any(row["action"] == "publish" for row in revisions)


def test_personal_info_hidden_on_public_detail(client, conn):
    author, admin = make_users(conn)
    h = auth(conn, author)
    data = payload(
        summary="联系人 QQ 123456789",
        blocks=[{"type": "text", "text": "请联系 QQ 123456789 处理后续。"}],
    )
    sid = submit(client, h, data).json()["id"]
    ah = auth(conn, admin)
    hidden = payload(
        summary="联系人 QQ 123456789",
        blocks=[{"type": "text", "text": "请联系 QQ 123456789 处理后续。"}],
        personal_info_mode="hidden",
    )
    r = client.post(f"/api/admin/archive/submissions/{sid}/approve",
                    json={"payload": hidden}, headers=ah)
    event_id = r.json()["event_id"]
    detail = client.get(f"/api/archive/{event_id}").json()
    assert "123456789" not in detail["summary"]
    assert "123456789" not in detail["blocks"][0]["text"]
    assert "联系方式已隐藏" in detail["summary"]


def test_admin_reject_keeps_submission(client, conn):
    author, admin = make_users(conn)
    sid = submit(client, auth(conn, author)).json()["id"]
    r = client.post(f"/api/admin/archive/submissions/{sid}/reject",
                    json={"note": "来源不足"}, headers=auth(conn, admin))
    assert r.status_code == 200
    detail = client.get(f"/api/admin/archive/submissions/{sid}", headers=auth(conn, admin)).json()
    assert detail["status"] == "rejected"
    assert detail["review_note"] == "来源不足"


def test_correction_approve_updates_event(client, conn):
    author, admin = make_users(conn)
    sid = submit(client, auth(conn, author)).json()["id"]
    ah = auth(conn, admin)
    event_id = client.post(f"/api/admin/archive/submissions/{sid}/approve",
                           json={"payload": payload()}, headers=ah).json()["event_id"]
    r = client.post(f"/api/archive/{event_id}/corrections", json={
        "field": "title",
        "proposed_value": "纠错后的标题",
        "reason": "原标题有误",
        "source_url": "https://example.com/right",
    }, headers=auth(conn, author))
    assert r.status_code == 200, r.text
    correction_id = r.json()["id"]
    items = client.get("/api/admin/archive/corrections", headers=ah).json()["items"]
    assert len(items) == 1
    assert items[0]["event_title"] == "测试飞圈事件标题"
    r = client.post(f"/api/admin/archive/corrections/{correction_id}/approve",
                    json={"note": "确认"}, headers=ah)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/archive/{event_id}").json()["title"] == "纠错后的标题"


def test_non_admin_cannot_review(client, conn):
    author, _ = make_users(conn)
    submit(client, auth(conn, author))
    r = client.get("/api/admin/archive/submissions", headers=auth(conn, author))
    assert r.status_code == 403
