"""请求体上限的路径匹配回归测试

锁定契约：`_limit_for path ` 取**最长匹配前缀**的上限，未命中用默认值。

为什么值得单独测：原实现把「上限值」和「前缀长度」混在一起比较，实际变成
「第一个匹配到的前缀」，见 middleware.py 里的修复说明。当前生产配置的两个前缀
互不重叠所以没暴露，但只要将来加一个 `/api/` 级别的通配，就会出现
「上传接口按默认 128KB 拦掉」或「普通接口按上传上限放行」——两种都很难现场定位。
"""
import pytest

from app.middleware import BodySizeLimitMiddleware

DEFAULT = 128 * 1024


@pytest.fixture()
def mw():
    return BodySizeLimitMiddleware(
        app=None,
        max_bytes=DEFAULT,
        path_limits={
            "/api/uploads/": 8 * 1024 * 1024,
            "/api/tickets/": 2 * 1024 * 1024,
        },
    )


def test_no_match_uses_default(mw):
    assert mw._limit_for("/api/airlines") == DEFAULT
    assert mw._limit_for("/") == DEFAULT


def test_exact_prefix_match(mw):
    assert mw._limit_for("/api/uploads/") == 8 * 1024 * 1024
    assert mw._limit_for("/api/uploads/avatar.png") == 8 * 1024 * 1024
    assert mw._limit_for("/api/tickets/12/attach") == 2 * 1024 * 1024


def test_prefix_is_case_sensitive_and_anchored(mw):
    """前缀必须从头匹配：/x/api/uploads/ 不算命中"""
    assert mw._limit_for("/x/api/uploads/a.png") == DEFAULT
    assert mw._limit_for("/api/Uploads/a.png") == DEFAULT


def test_longest_prefix_wins():
    """嵌套配置时取最长前缀 —— 这正是原实现的 bug 所在"""
    mw = BodySizeLimitMiddleware(
        app=None,
        max_bytes=DEFAULT,
        path_limits={
            "/api/": 1 * 1024 * 1024,
            "/api/uploads/": 8 * 1024 * 1024,
        },
    )
    assert mw._limit_for("/api/airlines") == 1 * 1024 * 1024
    assert mw._limit_for("/api/uploads/x.png") == 8 * 1024 * 1024


def test_longest_prefix_wins_regardless_of_insert_order():
    """顺序无关：先注册长的或先注册短的，结果都必须一样"""
    limits = {"/api/uploads/": 8 * 1024 * 1024, "/api/": 1 * 1024 * 1024}
    mw = BodySizeLimitMiddleware(app=None, max_bytes=DEFAULT, path_limits=limits)
    assert mw._limit_for("/api/uploads/x.png") == 8 * 1024 * 1024
    mw2 = BodySizeLimitMiddleware(
        app=None, max_bytes=DEFAULT,
        path_limits={"/api/": 1 * 1024 * 1024, "/api/uploads/": 8 * 1024 * 1024},
    )
    assert mw2._limit_for("/api/uploads/x.png") == 8 * 1024 * 1024


def test_stricter_child_prefix_can_tighten():
    """子路径可以比父路径更严，例如 /api/auth/ 只允许 4KB"""
    mw = BodySizeLimitMiddleware(
        app=None,
        max_bytes=DEFAULT,
        path_limits={"/api/": 1 * 1024 * 1024, "/api/auth/": 4096},
    )
    assert mw._limit_for("/api/auth/login") == 4096
    assert mw._limit_for("/api/airlines") == 1 * 1024 * 1024


def test_empty_path_limits_uses_default():
    mw = BodySizeLimitMiddleware(app=None, max_bytes=DEFAULT)
    assert mw._limit_for("/api/uploads/x.png") == DEFAULT


# ---------- 2026-10-18：上传上限 + 统一 413 文案 ----------

def test_rule_can_carry_custom_message():
    """path_limits 支持 上限, 文案 元组：长前缀规则连同文案一起生效"""
    mw = BodySizeLimitMiddleware(
        app=None,
        path_limits={
            "/api/events/": (5 * 1024 * 1024, "图片大小不能超过 5 MB，请压缩后再上传"),
            "/api/events/1/briefing/": (1 * 1024 * 1024, "单张简报截图不能超过 1 MB"),
        },
    )
    assert mw._limit_for("/api/events/1/briefing/images") == 1 * 1024 * 1024
    assert mw._rule_for("/api/events/1/briefing/images")[1] == "单张简报截图不能超过 1 MB"
    assert mw._limit_for("/api/events/2/briefing/images") == 5 * 1024 * 1024


def test_413_default_message_mentions_the_actual_limit():
    """没有自定义文案时，错误里必须写出上限，而不是笼统的「请求体过大」"""
    import json

    mw = BodySizeLimitMiddleware(app=None, max_bytes=128 * 1024)
    resp = mw._too_large(128 * 1024, "")
    assert resp.status_code == 413
    assert "128 KB" in json.loads(resp.body)["error"]


def test_413_uses_custom_message_when_configured():
    import json

    mw = BodySizeLimitMiddleware(app=None, max_bytes=DEFAULT)
    msg = "图片大小不能超过 5 MB，请压缩后再上传"
    resp = mw._too_large(5 * 1024 * 1024, msg)
    assert resp.status_code == 413
    assert json.loads(resp.body)["error"] == msg

