"""pytest 公共夹具与测试数据工厂

隔离方式：把 app.database 的模块级 DB_PATH 指向 pytest 的临时目录，
每个测试一个全新库，含全部迁移与种子。这样测试绝不会碰到 backend/data/ctyfly.db。

为什么要这套东西：项目此前零自动化测试，只有 D:\\audit-tools 下手写的 Playwright 脚本，
而经济系统，工资结算 / ACARS 评分 / 航司余额恰恰是最需要回归保护的部分，见交接文档 §34。
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# **必须在任何 app.* 导入之前**设置：CI 与新克隆的机器上没有 backend/.env
#.env 含密钥、不入库，而 app/config.py 出于安全考虑会在导入期校验 JWT_SECRET，
# 缺失或仍是示例默认值就直接拒绝启动 —— 于是「本地有 .env 全绿、CI 无 .env 全红」。
# 这里用 setdefault 补一个**测试专用**密钥：只存在于测试进程环境变量，不写任何文件，
# 也不会削弱生产校验，真实环境仍要求显式配置；本地有 .env 时以 .env 为准。
# 教训来自 2026-10-16：CI 从建立到第 21 次运行一直红着，本地却全绿 —— 见交接文档 §34.22。
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-for-production-9f3c1a7e5b2d48c6")

# **测试进程绝不发真实邮件**，2026-10-18 事故：
# app/config.py 会读 backend/.env，本地有生产 SMTP 凭据时，用例里的 notify_user
# 会真的用 noreply@ccflysim.cn 给 money_member@test.local 这类夹具地址发通知，
# QQ 企业邮箱全部退信，发件账号里堆满垃圾联系人。
# .env 的加载用 os.environ.setdefault，所以这里显式置空即可把它压住；
# 必须写在任何 app.* 导入之前。
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASS"] = ""
os.environ["SMTP_FROM"] = ""

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """把数据库指向临时文件并建表；返回 database 模块

    注意：database 现在有**线程本地连接池**，2026-10-11 起。
    get_conn 内部会按 DB_PATH 分桶，换库时自动关掉旧路径的连接，
    所以逐个用例换临时库不会串数据；这里再显式 reset 一次，及时释放文件句柄
    Windows 上句柄不释放会影响临时目录清理。
    """
    import app.database as database

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db", raising=True)
    monkeypatch.setattr(database, "DATA_DIR", tmp_path, raising=True)
    database.reset_connections()
    database.init_db()
    try:
        yield database
    finally:
        database.reset_connections()


@pytest.fixture()
def conn(db):
    with db.get_conn() as c:
        yield c


# ---------- 数据工厂 ----------

def make_user(conn, *, cid: str = "9001", username: str = "tester",
              role: str = "user", rating: str = "飞行员", status: str = "active") -> int:
    cur = conn.execute(
        "INSERT INTO users (cid, username, email, password_hash, rating, role, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, username, f"{username}@test.local", "x", rating, role, status),
    )
    # 必须提交：端到端用例的 HTTP 请求走另一条连接，未提交的数据它看不见
    #曾因此拿到 401「账号不存在」—— SQLite 连接间有隔离
    conn.commit()
    return cur.lastrowid


def make_airline(conn, *, name: str = "测试航空", owner_id: int, balance: int = 0,
                 status: str = "approved", hourly_rate: int = 100, distance_rate: int = 1,
                 icao: str | None = None) -> int:
    """建航司；icao 必填，无默认，未指定时按序号生成，避免测试之间撞唯一约束"""
    if icao is None:
        n = conn.execute("SELECT COALESCE(MAX(id), 0) FROM airlines").fetchone()[0] + 1
        icao = f"T{n:03d}"[:4]
    cur = conn.execute(
        "INSERT INTO airlines (icao, name, owner_id, status, balance, hourly_rate, distance_rate)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (icao, name, owner_id, status, balance, hourly_rate, distance_rate),
    )
    # 必须提交：端到端用例的 HTTP 请求走另一条连接，未提交的数据它看不见
    #曾因此拿到 401「账号不存在」—— SQLite 连接间有隔离
    conn.commit()
    return cur.lastrowid


def make_route(conn, *, airline_id: int, dep: str = "ZBAA", arr: str = "ZSPD",
               distance_nm: float = 860.0) -> int:
    """建一条航司航线，dispatches.route_id / flight_reports.route_id 是外键，需要真实行"""
    cur = conn.execute(
        "INSERT INTO airline_routes (airline_id, dep, arr, distance_nm) VALUES (?, ?, ?, ?)",
        (airline_id, dep, arr, distance_nm),
    )
    # 必须提交：端到端用例的 HTTP 请求走另一条连接，未提交的数据它看不见
    #曾因此拿到 401「账号不存在」—— SQLite 连接间有隔离
    conn.commit()
    return cur.lastrowid


def make_dispatch(conn, *, airline_id: int, kind: str = "line", route_id: int | None = None,
                  distance_nm: float | None = None, sched_dep: str = "",
                  user_id: int | None = None):
    """建一张签派单并返回该行，读法与业务代码一致：dispatch["kind"] 等

    user_id 必填且必须真实存在，外键 + get_conn 开了 PRAGMA foreign_keys=ON，未指定时自动建用户。
    route_id 传 0/None 表示「无航线」，转场、包机，落库为 NULL —— 传 0 会违反外键。
    """
    if user_id is None:
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] + 1
        user_id = make_user(conn, cid=f"6{n:03d}", username=f"dispatchuser{n}")
    cur = conn.execute(
        "INSERT INTO dispatches (airline_id, user_id, kind, route_id, distance_nm, sched_dep,"
        " dep, arr, status)"
        " VALUES (?, ?, ?, ?, ?, ?, 'ZBAA', 'ZSPD', 'open')",
        (airline_id, user_id, kind, route_id or None, distance_nm, sched_dep),
    )
    conn.commit()   # 同上：端到端用例要用另一条连接读这张签派单
    return conn.execute("SELECT * FROM dispatches WHERE id = ?", (cur.lastrowid,)).fetchone()


def add_event(conn, *, dispatch_id: int, airline_id: int, user_id: int,
              event_type: str, server_time: str) -> None:
    conn.execute(
        "INSERT INTO flight_events (dispatch_id, airline_id, user_id, event_type, server_time)"
        " VALUES (?, ?, ?, ?, ?)",
        (dispatch_id, airline_id, user_id, event_type, server_time),
    )
    conn.commit()


def add_report(conn, *, airline_id: int, user_id: int, hours: float = 2.0,
               created_at: str | None = None) -> int:
    """插入一条飞行报告，用于「24 小时内报告过多」这类频率判定"""
    if created_at:
        cur = conn.execute(
            "INSERT INTO flight_reports (airline_id, user_id, hours, created_at)"
            " VALUES (?, ?, ?, ?)",
            (airline_id, user_id, hours, created_at),
        )
    else:
        cur = conn.execute(
            "INSERT INTO flight_reports (airline_id, user_id, hours) VALUES (?, ?, ?)",
            (airline_id, user_id, hours),
        )
    # 必须提交：端到端用例的 HTTP 请求走另一条连接，未提交的数据它看不见
    #曾因此拿到 401「账号不存在」—— SQLite 连接间有隔离
    conn.commit()
    return cur.lastrowid
