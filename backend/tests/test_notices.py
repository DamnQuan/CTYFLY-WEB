"""社区公告回归测试：新公告默认置顶，并排在仪表盘公告首位"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def admin_headers(conn):
    from app.security import sign_token

    uid = make_user(conn, cid="8201", username="notice_admin", role="admin")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def test_new_notice_defaults_to_pinned(client, admin_headers):
    """发布时没有显式传 pinned，后端也按置顶处理"""
    resp = client.post("/api/admin/notices",
                       json={"title": "平台发展问卷上线", "content": "欢迎填写"},
                       headers=admin_headers)
    assert resp.status_code == 200
    notices = client.get("/api/admin/notices", headers=admin_headers).json()["notices"]
    assert notices[0]["title"] == "平台发展问卷上线"
    assert notices[0]["pinned"] == 1


def test_new_notice_ranks_above_old_pinned(client, admin_headers):
    """老公告已置顶时，新发的公告仍要排在仪表盘最上面"""
    client.post("/api/admin/notices", json={"title": "旧公告", "content": "旧"},
                headers=admin_headers)
    client.post("/api/admin/notices", json={"title": "新公告", "content": "新"},
                headers=admin_headers)
    data = client.get("/api/dashboard", headers=admin_headers).json()
    assert data["notices"][0]["title"] == "新公告"
    assert data["notices"][1]["title"] == "旧公告"


def test_notice_can_still_be_unpinned(client, admin_headers):
    resp = client.post("/api/admin/notices",
                       json={"title": "普通公告", "content": "不需要置顶", "pinned": False},
                       headers=admin_headers)
    assert resp.status_code == 200
    notices = client.get("/api/admin/notices", headers=admin_headers).json()["notices"]
    row = next(n for n in notices if n["title"] == "普通公告")
    assert row["pinned"] == 0
