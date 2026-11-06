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


def test_submission_anonymous_allowed_and_one_pending(client, conn):
    headers = {"X-ACIS-Anon": "anon-test-requires"}
    first = client.post("/api/archive/submissions", json=payload(), headers=headers)
    assert first.status_code == 200
    second = client.post("/api/archive/submissions", json=payload(), headers=headers)
    assert second.status_code == 400
    assert "审核中" in second.json()["error"]


def test_anonymous_acis_submit_and_correction(client, conn):
    admin = make_user(conn, cid="8104", username="acis_admin", role="admin")
    ah = auth(conn, admin)
    headers = {"X-ACIS-Anon": "anon-test-0001"}
    data = payload(title="ACIS匿名投稿测试事件")
    r = client.post("/api/archive/submissions", json=data, headers=headers)
    assert r.status_code == 200, r.text
    submission_id = r.json()["id"]
    again = client.post("/api/archive/submissions", json=data, headers=headers)
    assert again.status_code == 400

    detail = client.get(f"/api/admin/archive/submissions/{submission_id}", headers=ah).json()
    assert detail["username"] == "ACIS访客"
    approved = client.post(f"/api/admin/archive/submissions/{submission_id}/approve",
                           json={"payload": data}, headers=ah)
    assert approved.status_code == 200
    event_id = approved.json()["event_id"]

    correction = client.post(f"/api/archive/{event_id}/corrections", json={
        "field": "title",
        "proposed_value": "ACIS匿名纠错后的标题",
        "reason": "匿名纠错测试",
    }, headers={"X-ACIS-Anon": "anon-test-0002"})
    assert correction.status_code == 200, correction.text
    duplicate = client.post(f"/api/archive/{event_id}/corrections", json={
        "field": "title",
        "proposed_value": "重复纠错",
    }, headers={"X-ACIS-Anon": "anon-test-0002"})
    assert duplicate.status_code == 400
    corrections = client.get("/api/admin/archive/corrections?status=pending", headers=ah).json()
    assert corrections["items"][0]["username"] == "ACIS访客"


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


def _create_event(client, headers, **over):
    data = payload(**over)
    r = client.post("/api/admin/archive/events", json=data, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["event_id"]


def test_like_favorite_views_and_hot(client, conn):
    author, admin = make_users(conn)
    ah = auth(conn, admin)
    uh = auth(conn, author)
    event_id = _create_event(client, ah, title="互动测试事件标题")

    like = client.post(f"/api/archive/{event_id}/like", headers=uh)
    assert like.status_code == 200 and like.json()["liked"] is True
    assert like.json()["count"] == 1
    assert client.post(f"/api/archive/{event_id}/like", headers=uh).json()["liked"] is False

    fav = client.post(f"/api/archive/{event_id}/favorite", headers=uh)
    assert fav.status_code == 200 and fav.json()["favorited"] is True
    assert fav.json()["count"] == 1

    detail = client.get(f"/api/archive/{event_id}", headers=uh).json()
    assert detail["liked"] is False
    assert detail["favorited"] is True
    assert detail["favorite_count"] == 1
    assert detail["view_count"] == 1
    assert client.get(f"/api/archive/{event_id}", headers=uh).json()["view_count"] == 1

    listing = client.get("/api/archive?sort=hot&window=all", headers=uh).json()
    assert listing["items"][0]["id"] == event_id
    assert listing["items"][0]["favorited"] is True

    mine = client.get("/api/archive/mine/favorites", headers=uh).json()
    assert [item["id"] for item in mine["items"]] == [event_id]

    featured = client.post(f"/api/admin/archive/events/{event_id}/featured",
                           json={"featured": True}, headers=ah)
    assert featured.status_code == 200
    featured_list = client.get("/api/archive?sort=featured").json()
    assert featured_list["items"][0]["id"] == event_id
    assert featured_list["items"][0]["featured"] is True


def test_comments_replies_reports_and_admin_hide(client, conn):
    author, admin = make_users(conn)
    reporter = make_user(conn, cid="8103", username="archive_reporter")
    ah = auth(conn, admin)
    uh = auth(conn, author)
    rh = auth(conn, reporter)
    event_id = _create_event(client, ah, title="评论测试事件标题")

    top = client.post(f"/api/archive/{event_id}/comments",
                      json={"content": "这是第一条评论"}, headers=uh)
    assert top.status_code == 200, top.text
    top_id = top.json()["comment"]["id"]
    reply = client.post(f"/api/archive/{event_id}/comments",
                        json={"content": "这是一条回复", "parent_id": top_id}, headers=rh)
    assert reply.status_code == 200, reply.text
    reply_id = reply.json()["comment"]["id"]

    second = client.post(f"/api/archive/{event_id}/comments",
                         json={"content": "二级回复", "parent_id": reply_id}, headers=rh)
    assert second.status_code == 400

    listing = client.get(f"/api/archive/{event_id}/comments", headers=uh).json()
    assert listing["total"] == 2
    assert listing["items"][0]["id"] == top_id
    assert listing["items"][0]["is_mine"] is True
    assert listing["items"][0]["replies"][0]["id"] == reply_id

    report = client.post(f"/api/archive/comments/{top_id}/report",
                         json={"reason": "测试举报"}, headers=rh)
    assert report.status_code == 200
    reports = client.get("/api/admin/archive/reports", headers=ah).json()["items"]
    assert reports[0]["comment_id"] == top_id

    hidden = client.post(f"/api/admin/archive/comments/{top_id}/status",
                         json={"status": "hidden"}, headers=ah)
    assert hidden.status_code == 200
    assert hidden.json()["affected"] == 2
    assert client.get(f"/api/archive/{event_id}/comments").json()["total"] == 0
    detail = client.get(f"/api/archive/{event_id}").json()
    assert detail["comment_count"] == 0

    resolved = client.post(f"/api/admin/archive/reports/{reports[0]['id']}/resolve",
                           json={"action": "dismiss", "note": "不成立"}, headers=ah)
    assert resolved.status_code == 200
