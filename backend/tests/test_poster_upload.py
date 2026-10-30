"""活动海报上传链路：中间件上限 + 统一 413 文案，2026-10-18 线上问题回归

线上现象：后台上传活动海报报「请求体过大」。排查结论是 **FastAPI 的
BodySizeLimitMiddleware 没给 `/api/events/` 配 path_limits**，于是落到默认
128KB —— 一张普通海报，几百 KB~几 MB 必然被拦，而 nginx，8m 和接口自身的
5MB 校验都还没轮到。

本文件锁两件事：
1. 2~3MB 的真实 PNG 能一路走到落库，中间件按 5.5MB 放行；
2. 超限时返回 413 + 可读 JSON，含「MB」字样，前端能直接展示原因。
"""
import random
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_user


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_attach_dir(tmp_path, monkeypatch):
    """把附件落盘目录指到临时目录

    为什么必须隔离：`ATTACH_DIR` 来自 config，backend/data/attachments，**不跟着
    测试库 DB_PATH 走**。不做这层隔离，上传用例会把真实文件写进仓库目录 ——
    2026-10-18 首次写本文件时就留下 4 个 2.88MB 的 PNG，还会让 deploy.ps1
    的「工作区脏检查」中止发布。
    """
    from app.routers import events as events_mod

    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr(events_mod, "ATTACH_DIR", target)
    return target


def auth(conn, user_id):
    from app.security import sign_token

    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"Authorization": f"Bearer {sign_token(row)}"}


def make_event(conn) -> int:
    cur = conn.execute(
        "INSERT INTO events (title, start_time, end_time, status)"
        " VALUES ('海报上传测试', datetime('now','localtime'),"
        " datetime('now','localtime','+2 hour'), 'upcoming')"
    )
    conn.commit()
    return cur.lastrowid


def png_noise(width: int = 1200, height: int = 800, seed: int = 7) -> bytes:
    """生成一张真实可解码的随机噪点 PNG，不用 Pillow，测试环境零额外依赖

    噪点图几乎不可压缩，1200x800 约 2.8MB —— 刚好覆盖「旧配置 128KB 必挂」
    与「新上限 5.5MB 可通过」之间那一段。
    """
    rnd = random.Random(seed)
    raw = bytearray()
    for _ in range(height):
        raw.append(0)                      # 每行的 filter type = 0，None
        raw.extend(rnd.randbytes(width * 3))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)   # 8bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def test_large_poster_upload_succeeds(client, conn):
    """一张约 2.8MB 的海报必须能上传成功，旧实现会在 128KB 处 413"""
    uid = make_user(conn, cid="9901", username="poster_admin", role="admin", rating="ADM")
    event_id = make_event(conn)
    data = png_noise()
    assert len(data) > 1024 * 1024, "测试图必须大于旧的 128KB 上限才有意义"

    r = client.post(
        f"/api/events/{event_id}/briefing/images",
        headers=auth(conn, uid),
        files={"file": ("poster.png", data, "image/png")},
    )
    assert r.status_code == 200, r.text
    img = r.json()["image"]
    row = conn.execute(
        "SELECT * FROM event_briefing_images WHERE id = ?", (img["id"],)
    ).fetchone()
    assert row is not None
    assert row["size"] == len(data)
    assert row["content_type"] == "image/png"


def test_oversize_upload_returns_friendly_413(client, conn):
    """超过中间件上限：413 + 明确文案，不是裸「请求体过大」、也不是 500"""
    uid = make_user(conn, cid="9902", username="poster_admin2", role="admin", rating="ADM")
    event_id = make_event(conn)
    data = b"\x89PNG\r\n\x1a\n" + b"x" * (6 * 1024 * 1024)

    r = client.post(
        f"/api/events/{event_id}/briefing/images",
        headers=auth(conn, uid),
        files={"file": ("big.png", data, "image/png")},
    )
    assert r.status_code == 413, r.text
    err = r.json()["error"]
    assert "MB" in err
    assert "图片" in err


# ---------- 权限口径：海报上传必须与页面/其它活动管理接口一致，2026-10-18 ----------

def _grant(conn, user_id: int, capability: str = "manage_events") -> None:
    conn.execute(
        "INSERT INTO user_permissions (user_id, capability, allowed) VALUES (?, ?, 1)",
        (user_id, capability),
    )
    conn.commit()


def test_capability_holder_can_upload_poster(client, conn):
    """有 manage_events 能力，非 admin 角色的人：能进活动管理页，就必须能传海报

    此前这里用 require_admin，导致「有活动管理权限」的人能创建/编辑/删除活动，
    唯独上传海报拿到 403「看起来你没有权限访问这个页面」。
    """
    uid = make_user(conn, cid="9911", username="event_manager")      # role=user
    _grant(conn, uid)
    event_id = make_event(conn)
    data = png_noise(800, 600, seed=3)                                # 约 1.4MB，旧 128KB 必挂

    r = client.post(
        f"/api/events/{event_id}/briefing/images",
        headers=auth(conn, uid),
        files={"file": ("poster.png", data, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["image"]["size"] == len(data)


def test_user_without_capability_is_rejected(client, conn):
    """没有任何活动管理能力：403，且不应该落任何文件/记录"""
    uid = make_user(conn, cid="9912", username="no_event_perm")
    event_id = make_event(conn)
    data = png_noise(200, 150, seed=5)

    r = client.post(
        f"/api/events/{event_id}/briefing/images",
        headers=auth(conn, uid),
        files={"file": ("poster.png", data, "image/png")},
    )
    assert r.status_code == 403, r.text
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM event_briefing_images"
    ).fetchone()["c"] == 0

