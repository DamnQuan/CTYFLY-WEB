"""浏览器探测公网 IPv6 的上报接口，/api/auth/ip-probe

背景：站点目前只有 IPv4 入口，服务器无全局 IPv6、DNS 无 AAAA，连接层拿不到用户 IPv6；
前端用 WebRTC/STUN 探测后回传，见 frontend/src/ipv6Probe.js。本文件锁住后端契约：

1. 合法公网 IPv6 → 写入 users.last_ip_v6 / last_ip_v6_at；
2. 私网 / 链路本地 / 文档地址 / 非 IPv6，IPv4 一律 400，不污染溯源字段；
3. 未登录 401；`/api/auth/me` 回传探测开关与已记录地址，管理后台/个人中心可见。
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


def auth(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def test_public_ipv6_is_stored(client, conn):
    uid = make_user(conn, cid="9501", username="v6_reporter")
    r = client.post("/api/auth/ip-probe", headers=auth(conn, uid),
                    json={"ipv6": "2408:8207:1234:5678:abcd:ef01:2345:6789"})
    assert r.status_code == 200, r.text
    assert r.json()["ipv6"] == "2408:8207:1234:5678:abcd:ef01:2345:6789"

    row = conn.execute(
        "SELECT last_ip_v6, last_ip_v6_at FROM users WHERE id = ?", (uid,)
    ).fetchone()
    assert row["last_ip_v6"] == "2408:8207:1234:5678:abcd:ef01:2345:6789"
    assert row["last_ip_v6_at"]

    # /me 同时回传开关与已记录值，前端与管理后台据此展示
    me = client.get("/api/auth/me", headers=auth(conn, uid))
    assert me.status_code == 200
    assert me.json()["ipv6ProbeEnabled"] is True
    assert me.json()["user"]["last_ip_v6"] == "2408:8207:1234:5678:abcd:ef01:2345:6789"


def test_normalized_compressed_forms_are_accepted(client, conn):
    """压缩格式/方括号写法都应被规范化后再入库，与日志链路同一套 normalize_ip"""
    uid = make_user(conn, cid="9502", username="v6_format")
    r = client.post("/api/auth/ip-probe", headers=auth(conn, uid),
                    json={"ipv6": "[2408:8207::1]"})
    assert r.status_code == 200, r.text
    assert r.json()["ipv6"] == "2408:8207::1"


@pytest.mark.parametrize("idx, bad", list(enumerate([
    "fe80::1",                # 链路本地
    "::1",                    # 回环
    "fc00::1",                # ULA 私网
    "2001:db8::1",            # 文档地址，非全局
    "10.0.0.1",               # IPv4 不是 IPv6
    "1.2.3.4:5678",           # IPv4:port
    "not-an-ip",
    "",
])))
def test_private_or_malformed_values_are_rejected(client, conn, idx, bad):
    uid = make_user(conn, cid=f"95{idx:02d}", username=f"v6_bad_{idx}")
    r = client.post("/api/auth/ip-probe", headers=auth(conn, uid), json={"ipv6": bad})
    assert r.status_code == 400, r.text
    row = conn.execute("SELECT last_ip_v6 FROM users WHERE id = ?", (uid,)).fetchone()
    assert row["last_ip_v6"] == ""


def test_probe_requires_login(client, conn):
    uid = make_user(conn, cid="9503", username="v6_anon")
    r = client.post("/api/auth/ip-probe", json={"ipv6": "2408:8207::2"})
    assert r.status_code == 401
    # 未登录时不会写入任何账号
    row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE last_ip_v6 != ''").fetchone()
    assert row["c"] == 0
    assert uid
