"""IPv6 采集链路：规范化 + XFF 解析 + 真实落库

背景，2026-10-18：站长问「会不会采集用户 IPv6」。现状是**采集代码本身支持 IPv6**，
但站点只有 IPv4，服务器无全局 IPv6、DNS 无 AAAA，所以线上永远看不到 IPv6 客户端。
本文件锁住「一旦 IPv6 流量进来，地址必须被正确解析并原样入库」这一段：

1. `normalize_ip` 覆盖 nginx/代理头可能出现的各种写法；
2. `xff_last_ip` 对 IPv6，含方括号/端口/映射地址取最后一段，畸形值不被当成 IP；
3. 事故上报这类会落库的接口，把 IPv6 原样写进 `incidents.ip`，TEXT 列，45 字符以内。
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user


# ---------- 1. 规范化 ----------

@pytest.mark.parametrize("raw, expected", [
    ("1.2.3.4", "1.2.3.4"),
    (" 1.2.3.4 ", "1.2.3.4"),
    ("2001:db8::1", "2001:db8::1"),
    ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),   # 压缩规范形式
    ("[2001:db8::1]", "2001:db8::1"),                              # 方括号
    ("[2001:db8::1]:443", "2001:db8::1"),                          # 方括号 + 端口
    ("2001:db8::1%eth0", "2001:db8::1"),                           # zone id
    ("::ffff:203.0.113.10", "203.0.113.10"),                         # IPv4 映射地址折回 v4
    ("203.0.113.10:5678", "203.0.113.10"),                           # IPv4:port 兜底
    ("", ""),
    ("unknown", ""),
    ("[broken", ""),
    ("999.1.1.1", ""),
])
def test_normalize_ip(raw, expected):
    from app.requestinfo import normalize_ip

    assert normalize_ip(raw) == expected


# ---------- 2. XFF 解析，生产 TRUST_PROXY=true ----------

@pytest.fixture()
def trust_proxy(monkeypatch):
    import app.requestinfo as ri

    monkeypatch.setattr(ri, "TRUST_PROXY", True)


def test_xff_ipv6_is_used(trust_proxy):
    from app.requestinfo import xff_last_ip

    assert xff_last_ip("2001:db8::1", "127.0.0.1") == "2001:db8::1"
    # 多级代理：只认最后一段，nginx 追加的真实地址
    assert xff_last_ip("9.9.9.9, 2001:db8::2", "127.0.0.1") == "2001:db8::2"
    # 方括号/端口写法也能取到
    assert xff_last_ip("[2001:db8::3]:8443", "127.0.0.1") == "2001:db8::3"
    # 畸形段：回退直连地址，绝不把垃圾串当 IP
    assert xff_last_ip("not-an-ip", "127.0.0.1") == "127.0.0.1"


def test_client_ip_from_request_ipv6(trust_proxy):
    from starlette.requests import Request

    from app.requestinfo import client_ip_from_request

    scope = {
        "type": "http", "method": "GET", "path": "/api/x", "query_string": b"",
        "headers": [(b"x-forwarded-for", b"2001:db8::4")],
        "client": ("127.0.0.1", 1234), "server": ("test", 80), "scheme": "https",
    }
    assert client_ip_from_request(Request(scope)) == "2001:db8::4"


# ---------- 3. 真实落库：IPv6 原样存进 incidents.ip ----------

def test_incident_stores_ipv6_address(db, monkeypatch):
    import app.requestinfo as ri

    monkeypatch.setattr(ri, "TRUST_PROXY", True)
    from app.main import app
    from app.security import sign_token

    client = TestClient(app)
    with db.get_conn() as conn:
        uid = make_user(conn, cid="9601", username="v6_pilot")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    headers = {
        "Authorization": f"Bearer {sign_token(row)}",
        # IPv6 里最常见的大小写混写 + 压缩形式，入库前应保持可解析
        "X-Forwarded-For": "2408:8207:1234:5678:abcd:ef01:2345:6789",
    }
    r = client.post(
        "/api/incidents", headers=headers,
        json={"summary": "IPv6 溯源写入验证", "severity": "incident"},
    )
    assert r.status_code == 200, r.text

    with db.get_conn() as conn:
        incident = conn.execute(
            "SELECT ip, ua_label FROM incidents WHERE id = ?", (r.json()["id"],)
        ).fetchone()
    assert incident["ip"] == "2408:8207:1234:5678:abcd:ef01:2345:6789"
    # 溯源分类字段同样正常写入，不因 IPv6 影响
    assert incident["ua_label"]
