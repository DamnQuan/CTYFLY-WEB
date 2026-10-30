"""IP 黑名单 / 白名单语义回归测试

对应交接文档 §30 的反爬补强：自动封禁带到期，默认 90 天、过期自动清理、
白名单优先于黑名单、扣除/封禁的口径统一。这些规则如果被改坏，后果是
「真实用户被永久封禁」或「脚本畅通无阻」，两种都严重，必须有回归保护。
"""
import pytest

from tests.conftest import make_user


TEST_IP = "203.0.113.77"      # TEST-NET-3，文档保留地址
OTHER_IP = "203.0.113.88"


def test_auto_ban_has_expiry_and_blocks(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "脚本注册")
    assert _ip_banned(conn, TEST_IP) is True
    row = conn.execute("SELECT expires_at, source FROM banned_ips WHERE ip = ?", (TEST_IP,)).fetchone()
    assert row["expires_at"], "自动封禁必须带到期时间（否则动态 IP 会永久误伤）"
    assert row["source"] == "auto"


def test_expired_ban_is_ignored_and_cleaned(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "脚本注册")
    conn.execute(
        "UPDATE banned_ips SET expires_at = datetime('now','localtime','-1 day') WHERE ip = ?",
        (TEST_IP,),
    )
    assert _ip_banned(conn, TEST_IP) is False
    assert conn.execute("SELECT 1 FROM banned_ips WHERE ip = ?", (TEST_IP,)).fetchone() is None


def test_permanent_ban_when_days_zero(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "管理员手动封禁", days=0, source="manual")
    row = conn.execute("SELECT expires_at FROM banned_ips WHERE ip = ?", (TEST_IP,)).fetchone()
    assert row["expires_at"] is None
    assert _ip_banned(conn, TEST_IP) is True


def test_custom_days_expiry(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "手动封禁 1 天", days=1, source="manual")
    delta = conn.execute(
        "SELECT (julianday(expires_at) - julianday(datetime('now','localtime'))) AS d"
        " FROM banned_ips WHERE ip = ?",
        (TEST_IP,),
    ).fetchone()["d"]
    assert 0.9 < delta < 1.1
    assert _ip_banned(conn, TEST_IP) is True


def test_whitelist_beats_blacklist(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "脚本注册")
    conn.execute("INSERT INTO ip_whitelist (ip, note) VALUES (?, '误封兜底')", (TEST_IP,))
    assert _ip_banned(conn, TEST_IP) is False


def test_whitelist_does_not_affect_other_ips(conn):
    from app.routers.auth import _ban_ip, _ip_banned

    conn.execute("INSERT INTO ip_whitelist (ip, note) VALUES (?, '办公网')", (TEST_IP,))
    _ban_ip(conn, OTHER_IP, "脚本注册")
    assert _ip_banned(conn, OTHER_IP) is True


def test_reban_updates_reason_and_expiry(conn):
    """重复封禁同一 IP：更新原因/到期/来源，而不是插两行，ip 是主键"""
    from app.routers.auth import _ban_ip, _ip_banned

    _ban_ip(conn, TEST_IP, "第一次")
    _ban_ip(conn, TEST_IP, "第二次", days=0, source="manual")
    rows = conn.execute("SELECT reason, expires_at, source FROM banned_ips WHERE ip = ?",
                        (TEST_IP,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "第二次"
    assert rows[0]["source"] == "manual"
    assert rows[0]["expires_at"] is None
    assert _ip_banned(conn, TEST_IP) is True


def test_unknown_ip_not_banned(conn):
    from app.routers.auth import _ip_banned

    assert _ip_banned(conn, "198.51.100.9") is False


@pytest.mark.parametrize("ua,expect_bot", [
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/140.0 Safari/537.36", False),
    ("python-requests/2.31", True),
    ("curl/8.4.0", True),
    ("sqlmap/1.7", True),
    ("Googlebot/2.1", True),
    ("", True),
    # 未知客户端 ≠ 爬虫：QQ/微信 WebView 曾把真实用户误封，§6.8 已知边界
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) QQ/8.9", False),
])
def test_ua_classification(ua, expect_bot):
    from app.requestinfo import classify_ua

    _label, is_bot = classify_ua(ua)
    assert is_bot is expect_bot


def test_register_login_gate_sees_ban(conn):
    """被封 IP 在登录/注册入口会拿到 403，这里验证查询层，端到端由 antibot-check.js 覆盖"""
    from app.routers.auth import _ban_ip, _ip_banned

    make_user(conn, cid="8100", username="gateuser")
    _ban_ip(conn, TEST_IP, "脚本登录探测")
    assert _ip_banned(conn, TEST_IP) is True
