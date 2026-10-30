"""平台发展问卷回归测试

锁住四件事：
1. 公开页取到的题目结构稳定，前端可以按题型渲染；
2. 非法答案被拒绝，合法答案归一化后落库；
3. 登录用户提交会带上身份快照，游客按匿名保存；
4. 后台列表与导出只对 view_surveys 能力开放。
"""
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user

VALID = {
    "frequency": "daily",
    "modules": ["weather", "events"],
    "satisfaction": 5,
    "priorities": ["atc", "tools"],
    "wishlist": "希望增加机组排班功能",
    "advice": "越做越好",
}


@pytest.fixture()
def client(db, monkeypatch):
    import app.captcha as captcha
    import app.ratelimit as ratelimit
    from app.main import app

    monkeypatch.setattr(captcha, "POW_CAPTCHA_ENABLED", False)
    monkeypatch.setattr(ratelimit, "RATE_LIMIT_ENABLED", False)
    return TestClient(app)


@pytest.fixture()
def admin_headers(conn):
    from app.security import sign_token

    uid = make_user(conn, cid="8101", username="survey_admin", role="admin")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


@pytest.fixture()
def user_headers(conn):
    from app.security import sign_token

    uid = make_user(conn, cid="8102", username="survey_user")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def test_schema_contains_all_question_types(client):
    data = client.get("/api/survey/schema").json()
    assert data["ok"] is True
    assert data["version"] == 1
    types = {q["type"] for q in data["questions"]}
    assert types == {"single", "multi", "rating", "text"}
    keys = {q["key"] for q in data["questions"]}
    assert {"frequency", "modules", "satisfaction", "priorities", "wishlist"} <= keys


def test_submit_anonymous_and_store_normalized(client, conn):
    resp = client.post("/api/survey", json={"answers": VALID, "contact": "qq 123456"})
    assert resp.status_code == 200, resp.text
    assert "感谢" in resp.json()["message"]
    row = conn.execute("SELECT * FROM survey_responses").fetchone()
    assert row["user_id"] is None
    assert row["contact"] == "qq 123456"
    assert row["anon_id"]
    answers = json.loads(row["answers"])
    assert answers["satisfaction"] == 5
    assert answers["priorities"] == ["atc", "tools"]


def test_anonymous_can_only_submit_once(client, conn):
    """同一浏览器匿名标识只能交一份，重复提交返回 409"""
    first = client.post("/api/survey", json={"answers": VALID})
    assert first.status_code == 200
    second = client.post("/api/survey", json={"answers": VALID})
    assert second.status_code == 409
    assert "已经提交过" in second.json()["error"]
    assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 1
    schema = client.get("/api/survey/schema").json()
    assert schema["submitted"] is True


def test_submit_with_invalid_token_still_anonymous(client, conn):
    """问卷不需要登录：带着过期或伪造令牌也必须能提交，身份按匿名处理"""
    resp = client.post(
        "/api/survey",
        json={"answers": VALID},
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert resp.status_code == 200
    row = conn.execute("SELECT * FROM survey_responses").fetchone()
    assert row["user_id"] is None
    assert row["username"] == ""


def test_submit_logged_in_keeps_identity(client, conn, user_headers):
    resp = client.post("/api/survey", json={"answers": VALID}, headers=user_headers)
    assert resp.status_code == 200
    row = conn.execute("SELECT * FROM survey_responses").fetchone()
    assert row["username"] == "survey_user"
    assert row["cid"] == "8102"


def test_logged_in_user_can_only_submit_once(client, conn, user_headers):
    """登录用户按账号去重，换个浏览器也不能再交"""
    first = client.post("/api/survey", json={"answers": VALID}, headers=user_headers)
    assert first.status_code == 200
    second = client.post("/api/survey", json={"answers": VALID}, headers=user_headers)
    assert second.status_code == 409
    assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 1


def test_different_accounts_can_submit(client, conn):
    """一人一份按账号算，不同用户可以各交一份"""
    from app.security import sign_token
    from tests.conftest import make_user

    for cid, name in (("8103", "survey_u1"), ("8104", "survey_u2")):
        uid = make_user(conn, cid=cid, username=name)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        headers = {"Authorization": f"Bearer {sign_token(row)}"}
        resp = client.post("/api/survey", json={"answers": VALID}, headers=headers)
        assert resp.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 2


def test_missing_required_answer_rejected(client):
    answers = dict(VALID)
    answers.pop("satisfaction")
    resp = client.post("/api/survey", json={"answers": answers})
    assert resp.status_code == 400
    assert "满意度" in resp.json()["error"]


def test_too_many_priorities_rejected(client):
    answers = dict(VALID)
    answers["priorities"] = ["atc", "tools", "training", "community"]
    resp = client.post("/api/survey", json={"answers": answers})
    assert resp.status_code == 400
    assert "最多选择" in resp.json()["error"]


def test_short_wishlist_rejected(client):
    answers = dict(VALID)
    answers["wishlist"] = "加"
    resp = client.post("/api/survey", json={"answers": answers})
    assert resp.status_code == 400
    assert "至少填写" in resp.json()["error"]


def test_admin_list_summary_and_items(client, conn, admin_headers):
    client.post("/api/survey", json={"answers": VALID})
    # 一人一份：第二份直接写库，模拟另一位用户的提交
    conn.execute(
        "INSERT INTO survey_responses (answers, anon_id) VALUES (?, ?)",
        (json.dumps(VALID, ensure_ascii=False), "another-browser-id-123456"),
    )
    conn.commit()
    data = client.get("/api/admin/surveys", headers=admin_headers).json()
    assert data["total"] == 2
    assert data["summary"]["total"] == 2
    assert data["summary"]["today"] == 2
    assert data["summary"]["averageSatisfaction"] == 5.0
    assert data["items"][0]["answers"][0]["title"] == "你使用本站的频率"
    assert data["items"][0]["answers"][0]["display"] == "几乎每天"


def test_admin_list_requires_capability(client, user_headers):
    resp = client.get("/api/admin/surveys", headers=user_headers)
    assert resp.status_code in (401, 403)


def test_page_size_is_server_controlled(client, conn, admin_headers):
    """每页条数由服务端固定，前端传多大的 limit 都不生效"""
    for _ in range(25):
        conn.execute("INSERT INTO survey_responses (answers) VALUES ('{}')")
    conn.commit()
    first = client.get("/api/admin/surveys?limit=1000", headers=admin_headers).json()
    assert first["limit"] == 20
    assert len(first["items"]) == 20
    second = client.get("/api/admin/surveys?offset=20&limit=1000", headers=admin_headers).json()
    assert second["limit"] == 20
    assert len(second["items"]) == 5


def test_export_escapes_formula_injection(client, admin_headers):
    """用户填的文本可能以 = + - @ 开头，导出前必须转义，避免 Excel 当公式执行"""
    answers = dict(VALID)
    answers["wishlist"] = "=1+1 请勿执行公式"
    answers["advice"] = "@SUM(A1:A2)"
    resp = client.post("/api/survey", json={
        "answers": answers,
        "nickname": "=nick",
        "contact": "+8613800000000",
    })
    assert resp.status_code == 200
    text = client.get("/api/admin/surveys/export", headers=admin_headers).content.decode("utf-8")
    assert "'=1+1" in text
    assert "'@SUM" in text
    assert "'=nick" in text
    assert "'+8613800000000" in text


def test_export_csv_requires_capability(client, admin_headers):
    client.post("/api/survey", json={"answers": VALID})
    resp = client.get("/api/admin/surveys/export", headers=admin_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.content.decode("utf-8")
    assert text.startswith("\ufeff")
    assert "提交时间" in text
    assert "希望增加机组排班功能" in text
    denied = client.get("/api/admin/surveys/export")
    assert denied.status_code == 401
