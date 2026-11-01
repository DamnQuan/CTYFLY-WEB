"""SQLite 数据库：建库、种子数据、连接管理"""
import random
import secrets
import sqlite3
import threading
from contextlib import contextmanager

from .config import BACKEND_DIR, SEED_ADMIN, SEED_DEMO_DATA
from .migrations import (migrate_application_nickname, migrate_archive_forum,
                         migrate_badge_payload, migrate_log_ua, migrate_partner_logo,
                         migrate_survey_anon)
from .schema import SCHEMA
from .seed_data import ACHIEVEMENT_SEEDS, SAMPLE_ROUTES, seed_default_partner
from .security import hash_password

DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ctyfly.db"

# ---------------- 连接池，2026-10-11，P3 最后一项----------------
# 为什么：路由已改回同步 def，由 FastAPI 放进线程池执行，原来每个请求都新建 + 关闭连接，
# 而建连要打开文件、设 row_factory、跑 PRAGMA。改为**线程本地复用**后这些开销只付一次。
#
# 必须守住的三个语义，都有专门测试，见 tests/test_db_connection_pool.py：
#   1. 成功 commit / 异常 rollback —— 与改造前完全一致；
#   2. DB_PATH 变化必须拿到新连接 —— 测试会 monkeypatch DB_PATH，复用旧连接会串库；
#   3. 同线程内**嵌套**调用不得共用同一条连接 —— 否则内层 with 的 commit/rollback
#      会替外层结束事务。嵌套时临时新建一条，用完即关，不进池。
# 另外：复用前若发现残留事务，异常路径可能留下，先 rollback 清干净。
_local = threading.local()

def _pool() -> dict:
    pool = getattr(_local, "conns", None)
    if pool is None:
        pool = {}
        _local.conns = pool
    return pool

def _new_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def reset_connections() -> None:
    """关闭当前线程池中的连接，测试夹具 teardown 用；换库时也会自动清理其它路径的连接"""
    pool = _pool()
    for key, conn in list(pool.items()):
        try:
            conn.close()
        except Exception:                     # noqa: BLE001 - 已关闭/线程归属不符都忽略
            pass
        pool.pop(key, None)

@contextmanager
def get_conn():
    key = str(DB_PATH)
    pool = _pool()
    depth = getattr(_local, "depth", 0)

    # 换了库：把该线程上其它路径的旧连接关掉，测试逐个用例换 DB_PATH，不关会攒句柄
    for other in [k for k in pool if k != key]:
        try:
            pool.pop(other).close()
        except Exception:                     # noqa: BLE001
            pass

    fresh = False
    conn = pool.get(key)
    if conn is None:
        conn = _new_conn()
        pool[key] = conn
    elif depth > 0:                           # 嵌套：临时新建，避免内层替外层提交/回滚
        conn = _new_conn()
        fresh = True
    elif conn.in_transaction:                 # 复用前清掉可能的残留事务
        conn.rollback()

    _local.depth = depth + 1
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _local.depth -= 1
        if fresh:
            conn.close()



def _row_to_dict(row) -> dict | None:
    return dict(row) if row is not None else None

def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode = WAL;")
    conn.executescript(SCHEMA)

    # 迁移：旧库补 token_ver 列，令牌版本化，改密后旧会话失效
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "token_ver" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN token_ver INTEGER NOT NULL DEFAULT 0")
        print("[db] users 表已迁移：新增 token_ver 列")

    # 迁移：活动表补简报扩展列，航路 / 飞行距离 / NOTAMS，幂等可重复执行
    ecols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    for col, ddl in (
        ("route", "TEXT NOT NULL DEFAULT ''"),
        ("distance_nm", "REAL"),
        ("notams", "TEXT NOT NULL DEFAULT ''"),
    ):
        if col not in ecols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {ddl}")
            print(f"[db] events 表已迁移：新增 {col} 列")

    # 迁移：活动报名席位制，幂等可重复执行
    # a event_signups 补 aircraft，飞行员机型与 position_id，管制员占用席位
    # b 新表 event_atc_positions 由 SCHEMA 的 CREATE TABLE IF NOT EXISTS 保证
    scols = {r[1] for r in conn.execute("PRAGMA table_info(event_signups)")}
    for col, ddl in (
        ("aircraft", "TEXT NOT NULL DEFAULT ''"),
        ("position_id", "INTEGER"),
    ):
        if col not in scols:
            conn.execute(f"ALTER TABLE event_signups ADD COLUMN {col} {ddl}")
            print(f"[db] event_signups 表已迁移：新增 {col} 列")

    # 迁移：event_atc_positions 补 events 外键，2026-10-05
    # 为什么需要：旧表建表时漏了 REFERENCES events id，它是全库唯一不会随活动删除而
    # 清理的关联表，event_signups / event_briefings 都有 ON DELETE CASCADE，
    # 导致删活动后残留孤儿席位，生产 1 行、测试 4 行，均已手工清理。
    # 应用层两个删除端点也已显式清理，这里补表级约束做兜底。
    # SQLite 不支持 ADD CONSTRAINT，只能重建表；该表体量极小，且重建时用
    # WHERE event_id IN SELECT id FROM events 顺手丢弃历史孤儿。
    if not list(conn.execute("PRAGMA foreign_key_list(event_atc_positions)")):
        conn.commit()  # PRAGMA foreign_keys 在事务内无效，先退出事务
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE event_atc_positions RENAME TO event_atc_positions_old")
        conn.execute(
            "CREATE TABLE event_atc_positions ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,"
            " name TEXT NOT NULL,"
            " rating TEXT NOT NULL DEFAULT '',"
            " frequency TEXT NOT NULL DEFAULT '',"
            " sort INTEGER NOT NULL DEFAULT 0,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))"
            ")"
        )
        cur = conn.execute(
            "INSERT INTO event_atc_positions (id, event_id, name, rating, frequency, sort, created_at)"
            " SELECT id, event_id, name, rating, frequency, sort, created_at"
            " FROM event_atc_positions_old WHERE event_id IN (SELECT id FROM events)"
        )
        kept = cur.rowcount
        conn.execute("DROP TABLE event_atc_positions_old")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        print(f"[db] event_atc_positions 已重建：补 events 外键，保留 {kept} 行，丢弃历史孤儿席位")

    # 迁移：航司相关旧表补列
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airlines'").fetchone():
        acols = {r[1] for r in conn.execute("PRAGMA table_info(airlines)")}
        if "hourly_rate" not in acols:
            conn.execute("ALTER TABLE airlines ADD COLUMN hourly_rate INTEGER NOT NULL DEFAULT 100")
        if "distance_rate" not in acols:
            conn.execute("ALTER TABLE airlines ADD COLUMN distance_rate INTEGER NOT NULL DEFAULT 1")
        rcols = {r[1] for r in conn.execute("PRAGMA table_info(airline_routes)")}
        if "base_salary" not in rcols:
            conn.execute("ALTER TABLE airline_routes ADD COLUMN base_salary INTEGER NOT NULL DEFAULT 200")
        if "distance_nm" not in rcols:
            conn.execute("ALTER TABLE airline_routes ADD COLUMN distance_nm REAL")
        fcols = {r[1] for r in conn.execute("PRAGMA table_info(flight_reports)")}
        if "distance_nm" not in fcols:
            conn.execute("ALTER TABLE flight_reports ADD COLUMN distance_nm REAL")
        if "dispatch_id" not in fcols:
            conn.execute("ALTER TABLE flight_reports ADD COLUMN dispatch_id INTEGER")

    # 迁移：成员职位，现实飞行部门阶梯：教员/机长/副驾驶/二副/见习学员，空=未设置
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airline_members'").fetchone():
        mcols = {r[1] for r in conn.execute("PRAGMA table_info(airline_members)")}
        if "position" not in mcols:
            conn.execute("ALTER TABLE airline_members ADD COLUMN position TEXT NOT NULL DEFAULT ''")
        # 迁移：部长标记，CEO 任命的部门负责人，可代行航司管理职能
        if "minister" not in mcols:
            conn.execute("ALTER TABLE airline_members ADD COLUMN minister INTEGER NOT NULL DEFAULT 0")

    # 迁移：日志表加 PID，记录写入者进程实例 —— 跨重启/多进程时归因到具体进程，
    # 对应 APOC 报告「33 次崩溃重启」场景的取证粒度
    for table in ("audit_logs", "login_logs", "api_access_log"):
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            lcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "pid" not in lcols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN pid INTEGER NOT NULL DEFAULT 0")
                print(f"[db] {table} 已迁移：新增 pid 列")

    # 迁移：签派单扩展字段，机队关联 + 详细放行信息
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dispatches'").fetchone():
        dcols = {r[1] for r in conn.execute("PRAGMA table_info(dispatches)")}
        for col, ddl in (
            ("fleet_id", "INTEGER"),
            ("captain", "TEXT NOT NULL DEFAULT ''"),
            ("callsign", "TEXT NOT NULL DEFAULT ''"),
            ("sched_dep", "TEXT NOT NULL DEFAULT ''"),
            ("pax", "INTEGER NOT NULL DEFAULT 0"),
            ("cargo", "INTEGER NOT NULL DEFAULT 0"),
            ("network", "TEXT NOT NULL DEFAULT ''"),
            ("copilot", "TEXT NOT NULL DEFAULT ''"),
            ("ci", "INTEGER NOT NULL DEFAULT 0"),
            ("dep_rwy", "TEXT NOT NULL DEFAULT ''"),
            ("arr_rwy", "TEXT NOT NULL DEFAULT ''"),
            ("flight_token", "TEXT NOT NULL DEFAULT ''"),
            ("flight_state", "TEXT NOT NULL DEFAULT 'issued'"),
            ("route_string", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in dcols:
                conn.execute(f"ALTER TABLE dispatches ADD COLUMN {col} {ddl}")
        # 存量未完成签派单回填飞行令牌，老签派单也能走 ACARS 上报流程
        conn.execute(
            "UPDATE dispatches SET flight_token = lower(hex(randomblob(16)))"
            " WHERE flight_token = '' AND status = 'open'"
        )

    # 合作伙伴：首页展示位，管理后台维护，logo 为同源相对地址
    conn.execute(
        """CREATE TABLE IF NOT EXISTS partners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  logo TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
)"""
    )
    # 迁移：合作伙伴简介列，存量表补列
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(partners)")}
    if "description" not in pcols:
        conn.execute("ALTER TABLE partners ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    seed_default_partner(conn)
    migrate_partner_logo(conn)

    # 迁移执行登记表：一次性数据迁移/约束加固只跑一次，避免每次启动重复执行
    #历史问题：无机队航司每次重启都被补赠 2 架 A320、位置回填覆盖 CEO 的调机结果
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
    )

    def _migration_done(name: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (name,)).fetchone())

    def _mark_migration(name: str) -> None:
        conn.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (name,))

    # 迁移：主基地与飞机所在机场，转场/包机体系的地基+ 签派单类型与距离
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airlines'").fetchone():
        acols = {r[1] for r in conn.execute("PRAGMA table_info(airlines)")}
        if "hub" not in acols:
            conn.execute("ALTER TABLE airlines ADD COLUMN hub TEXT NOT NULL DEFAULT ''")
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airline_fleet'").fetchone():
        flcols = {r[1] for r in conn.execute("PRAGMA table_info(airline_fleet)")}
        if "location" not in flcols:
            conn.execute("ALTER TABLE airline_fleet ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        # 存量飞机回填到主基地，无主基地的留空，CEO 设定后可再回填
        # 只跑一次：否则每次启动都会把 CEO 清空调机位置的结果重新写回主基地
        if not _migration_done("backfill_fleet_location_v1"):
            conn.execute(
                "UPDATE airline_fleet SET location = (SELECT hub FROM airlines WHERE airlines.id = airline_fleet.airline_id)"
                " WHERE location = ''"
            )
            _mark_migration("backfill_fleet_location_v1")
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dispatches'").fetchone():
        dcols = {r[1] for r in conn.execute("PRAGMA table_info(dispatches)")}
        if "kind" not in dcols:
            conn.execute("ALTER TABLE dispatches ADD COLUMN kind TEXT NOT NULL DEFAULT 'line'")  # line | ferry | charter
        if "distance_nm" not in dcols:
            conn.execute("ALTER TABLE dispatches ADD COLUMN distance_nm REAL")
        # 存量航线签派回填距离，取自航线表
        conn.execute(
            "UPDATE dispatches SET distance_nm = (SELECT distance_nm FROM airline_routes WHERE airline_routes.id = dispatches.route_id)"
            " WHERE distance_nm IS NULL AND kind = 'line'"
        )

    # 迁移：航线类型，国内 / 国际——影响油量备用油规章
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airline_routes'").fetchone():
        rcols = {r[1] for r in conn.execute("PRAGMA table_info(airline_routes)")}
        if "intl" not in rcols:
            conn.execute("ALTER TABLE airline_routes ADD COLUMN intl INTEGER NOT NULL DEFAULT 0")

    # 迁移：飞行报告核验结果列，平台 ACARS 评分引擎
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flight_reports'").fetchone():
        frcols = {r[1] for r in conn.execute("PRAGMA table_info(flight_reports)")}
        for col, ddl in (
            ("verify_score", "INTEGER NOT NULL DEFAULT -1"),
            ("verify_status", "TEXT NOT NULL DEFAULT ''"),   # auto_pass | needs_review | auto_rejected
            ("verify_detail", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in frcols:
                conn.execute(f"ALTER TABLE flight_reports ADD COLUMN {col} {ddl}")

    # 迁移：给已批准但还没有机队的航司补初始机队，2 架 A320
    # 只跑一次：否则 CEO 合法清空机队后，每次重启都白得 2 架
    #新航司的初始机队由批准流程 airlines.py 的 _seed_fleet 发放，不依赖本迁移
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='airline_fleet'").fetchone():
        if not _migration_done("seed_fleet_v1"):
            approved = conn.execute(
                "SELECT id FROM airlines WHERE status = 'approved'"
                " AND id NOT IN (SELECT DISTINCT airline_id FROM airline_fleet)"
            ).fetchall()
            for a in approved:
                for _ in range(2):
                    conn.execute(
                        "INSERT INTO airline_fleet (airline_id, aircraft, reg) VALUES (?, 'A320', ?)",
                        (a["id"], f"B-{random.randint(1000, 9999)}"),
                    )
            _mark_migration("seed_fleet_v1")
            if approved:
                print(f"[db] 已为 {len(approved)} 家存量航司补初始机队，各 2 架 A320")

    # 迁移：airlines 表补对外主页自定义字段
    acols = {r[1] for r in conn.execute("PRAGMA table_info(airlines)")}
    for col, ddl in (
        ("public_slogan", "TEXT NOT NULL DEFAULT ''"),
        ("public_welcome", "TEXT NOT NULL DEFAULT ''"),
        ("show_members", "INTEGER NOT NULL DEFAULT 1"),
        ("show_routes", "INTEGER NOT NULL DEFAULT 1"),
        ("show_fleet", "INTEGER NOT NULL DEFAULT 1"),
        ("show_stats", "INTEGER NOT NULL DEFAULT 1"),
        ("balance", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in acols:
            conn.execute(f"ALTER TABLE airlines ADD COLUMN {col} {ddl}")

    # 迁移：users 表补注册/登录元信息字段
    ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for col, ddl in (
        ("reg_ip", "TEXT NOT NULL DEFAULT ''"),
        ("reg_geo", "TEXT NOT NULL DEFAULT ''"),
        ("reg_fingerprint", "TEXT NOT NULL DEFAULT ''"),
        ("reg_ua", "TEXT NOT NULL DEFAULT ''"),
        ("last_login_ip", "TEXT NOT NULL DEFAULT ''"),
        ("last_login_geo", "TEXT NOT NULL DEFAULT ''"),
        ("last_login_fingerprint", "TEXT NOT NULL DEFAULT ''"),
        ("last_login_at", "TEXT"),
        ("equipped_title", "TEXT NOT NULL DEFAULT ''"),
        ("equipped_badge", "TEXT NOT NULL DEFAULT ''"),
        # 浏览器主动探测到的公网 IPv6，站点当前是 IPv4 入口，连接层拿不到 v6 —— 见
        # 交接文档 §42/§43；由 /api/auth/ip-probe 写入，空字符串=从未探测到
        ("last_ip_v6", "TEXT NOT NULL DEFAULT ''"),
        ("last_ip_v6_at", "TEXT"),
    ):
        if col not in ucols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

    # 迁移：管制等级归一化到 VATSIM 阶梯，飞行员/OBS/S1..I3/SUP/ADM
    # 旧数据里的 P0~P5 等占位值按角色与管制员标记折算，幂等可重复执行
    from .permissions import PILOT_RATING, RATINGS

    placeholders = ",".join("?" * len(RATINGS))
    legacy = conn.execute(
        f"SELECT id, role, rating, is_controller FROM users WHERE rating NOT IN ({placeholders})",
        RATINGS,
    ).fetchall()
    for u in legacy:
        if u["role"] == "admin":
            new_rating = "ADM"
        elif u["role"] == "sup":
            new_rating = "SUP"
        elif u["is_controller"]:
            new_rating = "OBS"
        else:
            new_rating = PILOT_RATING
        conn.execute("UPDATE users SET rating = ? WHERE id = ?", (new_rating, u["id"]))
    if legacy:
        print(f"[db] 已将 {len(legacy)} 个用户的管制等级归一化到新阶梯")

    # 种子：角色能力矩阵
    if conn.execute("SELECT COUNT(*) c FROM role_permissions").fetchone()["c"] == 0:
        from .permissions import CAPABILITIES, DEFAULT_MATRIX

        for role, caps in DEFAULT_MATRIX.items():
            for cap, _label in CAPABILITIES:
                conn.execute(
                    "INSERT INTO role_permissions (role, capability, allowed) VALUES (?, ?, ?)",
                    (role, cap, 1 if cap in caps else 0),
                )

    # 种子：管制等级，rating 能力矩阵 —— 默认只有 SUP / ADM 全开，其余等级为空
    if conn.execute("SELECT COUNT(*) c FROM rating_permissions").fetchone()["c"] == 0:
        from .permissions import CAPABILITIES, DEFAULT_RATING_MATRIX

        for rating, caps in DEFAULT_RATING_MATRIX.items():
            for cap, _label in CAPABILITIES:
                conn.execute(
                    "INSERT INTO rating_permissions (rating, capability, allowed) VALUES (?, ?, ?)",
                    (rating, cap, 1 if cap in caps else 0),
                )
        print("[db] 已初始化 rating 权限矩阵，默认仅 SUP / ADM 全权限")

    # 迁移：新加的能力项给既有矩阵补行，老库不会重新播种，缺行会被当成「不允许」
    from .permissions import CAPABILITIES as _CAPS
    from .permissions import DEFAULT_MATRIX as _DM
    from .permissions import DEFAULT_RATING_MATRIX as _DRM

    for table, key, defaults in (
        ("role_permissions", "role", _DM),
        ("rating_permissions", "rating", _DRM),
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not cols:
            continue
        have = {(r[0], r[1]) for r in conn.execute(f"SELECT {key}, capability FROM {table}")}
        for owner, caps in defaults.items():
            for cap, _label in _CAPS:
                if (owner, cap) in have:
                    continue
                conn.execute(
                    f"INSERT INTO {table} ({key}, capability, allowed) VALUES (?, ?, ?)",
                    (owner, cap, 1 if cap in caps else 0),
                )

    migrate_log_ua(conn)

    migrate_application_nickname(conn)

    # 迁移：IP 黑名单补「到期/来源/备注」列，并新建白名单表，2026-10-10，加法式幂等
    # 旧的自动封禁是永久的，动态 IP 复用会永久误伤 → 现在自动封禁默认带到期时间；
    # 老数据 expires_at 保持 NULL，永久，由管理员在后台按需处理。
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='banned_ips'"
    ).fetchone():
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(banned_ips)")}
        if "expires_at" not in bcols:
            conn.execute("ALTER TABLE banned_ips ADD COLUMN expires_at TEXT")
            print("[db] banned_ips 已补 expires_at 列，NULL=永久")
        if "source" not in bcols:
            conn.execute("ALTER TABLE banned_ips ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'")
            print("[db] banned_ips 已补 source 列")
        if "note" not in bcols:
            conn.execute("ALTER TABLE banned_ips ADD COLUMN note TEXT NOT NULL DEFAULT ''")
            print("[db] banned_ips 已补 note 列")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ip_whitelist ("
        " ip TEXT PRIMARY KEY,"
        " note TEXT NOT NULL DEFAULT '',"
        " created_by TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
    )

    # 迁移：申请表补面试流程字段，2026-10-05，加法式幂等
    # 职员申请要先安排面试、面试完成后才能给通过/驳回结论，see admin.review_application 门禁
    appcols = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
    for col, ddl in (
        ("interview_status", "TEXT NOT NULL DEFAULT ''"),
        ("interview_at1", "TEXT NOT NULL DEFAULT ''"),
        ("interview_at2", "TEXT NOT NULL DEFAULT ''"),
        ("interview_sent_at", "TEXT"),
        ("interview_done_at", "TEXT"),
        ("interview_by", "INTEGER REFERENCES users(id)"),
    ):
        if col not in appcols:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {ddl}")
            print(f"[db] applications 已补 {col} 列")

    # 约束加固：唯一索引，先清理历史脏数据，防止建索引失败导致启动崩溃
    # a 公共商城：同一用户同一商品只允许一条有效订单，并发双购由约束拦下
    conn.execute(
        "DELETE FROM shop_orders WHERE id NOT IN"
        " (SELECT MIN(id) FROM shop_orders GROUP BY user_id, item_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_orders_user_item"
        " ON shop_orders(user_id, item_id)"
    )
    # b 航司商城：每人限兑一份；已取消，已退款的订单不占名额 → 部分唯一索引
    conn.execute(
        "DELETE FROM airline_shop_orders WHERE status != 'cancelled' AND id NOT IN"
        " (SELECT MIN(id) FROM airline_shop_orders WHERE status != 'cancelled'"
        "  GROUP BY user_id, item_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_va_shop_orders_user_item"
        " ON airline_shop_orders(user_id, item_id) WHERE status != 'cancelled'"
    )
    # c 飞机注册号唯一：历史重复号不删数据，可能被签派单引用，改为加后缀让位
    reg_dups = conn.execute(
        "SELECT f.id, f.reg FROM airline_fleet f WHERE f.reg != '' AND EXISTS"
        " (SELECT 1 FROM airline_fleet g WHERE g.reg = f.reg AND g.id < f.id)"
    ).fetchall()
    for r in reg_dups:
        conn.execute(
            "UPDATE airline_fleet SET reg = ? WHERE id = ?",
            (f"{r['reg']}-D{r['id']}", r["id"]),
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_airline_fleet_reg"
        " ON airline_fleet(reg) WHERE reg != ''"
    )
    if reg_dups:
        print(f"[db] 已为 {len(reg_dups)} 架重复注册号的飞机改号，原号保留给最早一架")

    # 种子：管理员
    admin = conn.execute("SELECT id FROM users WHERE cid = ?", (SEED_ADMIN["cid"],)).fetchone()
    if not admin:
        # 用与注册/登录完全相同的迭代强度，避免种子账号的哈希成本低于全局配置
        admin_password = SEED_ADMIN["password"]
        if not admin_password:
            admin_password = secrets.token_urlsafe(18)
            print(f"[seed] 未设置 ADMIN_PASSWORD，已生成随机管理员密码：{admin_password}")
        password_hash = hash_password(admin_password)
        conn.execute(
            "INSERT INTO users (cid, username, email, password_hash, role, rating, pilot_rank)"
            " VALUES (?, ?, ?, ?, 'admin', 'ADM', '教员')",
            (SEED_ADMIN["cid"], SEED_ADMIN["username"], SEED_ADMIN["email"], password_hash),
        )
        print(f"[seed] 已创建管理员账号 CID={SEED_ADMIN['cid']}，请立即登录并修改密码")

    # 以下全部是演示内容：仅当 SEED_DEMO_DATA=true 时写入。
    # 生产环境保持默认 false —— 只建库、只创建管理员和系统权限表，不带任何示例数据。
    if SEED_DEMO_DATA:
        # 种子：航路
        if conn.execute("SELECT COUNT(*) c FROM routes").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO routes (dep, arr, level, route_text, distance, created_by)"
                " VALUES (?, ?, ?, ?, ?, 1)",
                SAMPLE_ROUTES,
            )

        # 种子：示例活动
        if conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 0:
            admin_id = conn.execute("SELECT id FROM users WHERE cid = ?", (SEED_ADMIN["cid"],)).fetchone()["id"]
            conn.execute(
                "INSERT INTO events (title, description, dep, arr, start_time, end_time, status, created_by)"
                " VALUES (?, ?, ?, ?,"
                " datetime('now','+2 day','localtime'), datetime('now','+2 day','+3 hour','localtime'), 'upcoming', ?)",
                ("CTY 周五之夜 · 北京首都黄金连线",
                 "本周五晚黄金时段，欢迎各位飞行员连飞 ZBAA - ZSPD 主干线，管制服务全程开放，新手友好。",
                 "ZBAA", "ZSPD", admin_id),
            )

        # 种子：公告
        if conn.execute("SELECT COUNT(*) c FROM notices").fetchone()["c"] == 0:
            conn.execute("INSERT INTO notices (title, content, pinned) VALUES (?, ?, 1)",
                         ("欢迎来到 CTYFLY", "CTY Flight Control Community 官网上线，注册账号即可参与连飞活动与管制员招募。"))
            conn.execute("INSERT INTO notices (title, content, pinned) VALUES (?, ?, 0)",
                         ("邮件验证码说明", "注册与找回密码均需邮箱验证码，请确保邮箱填写正确；未收到请检查垃圾箱或 60 秒后重发。"))

        # 种子：虚拟商城商品，title=称号文字；badge 的 payload 用 icon:名称 渲染 SVG 图标
        if conn.execute("SELECT COUNT(*) c FROM shop_items").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO shop_items (name, description, price, type, payload) VALUES (?, ?, ?, ?, ?)",
                [
                    ("元老称号", "授予早期加入 CTYFLY的飞行员", 500, "title", "元老"),
                    ("VIP 称号", "社区支持者专属标识", 800, "title", "VIP"),
                    ("金牌机长", "累计飞行时长领先的机长", 1200, "title", "金牌机长"),
                    ("星星徽章", "佩戴后用户名前显示星形徽章", 300, "badge", "icon:star"),
                    ("钻石徽章", "佩戴后用户名前显示钻石徽章", 1000, "badge", "icon:diamond"),
                ],
            )

    migrate_badge_payload(conn)

    # 种子：成就徽章定义，**始终写入**，与权限矩阵同理 —— 生产环境也需要这批「产品内容」
    # 用 INSERT OR IGNORE + code 唯一键：重复启动不会重复插入，也不会覆盖运营手改的文案。
    # metric 的取值口径写在 routers/achievements.py 的 METRIC_SQL 里，白名单，不拼用户输入。
    for i, row in enumerate(ACHIEVEMENT_SEEDS):
        conn.execute(
            "INSERT OR IGNORE INTO achievement_defs"
            " (code, name, description, category, icon, event_type, metric, threshold, reward, badge, sort)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*row, (i + 1) * 10),
        )

    # 种子：示例招标航线，仅演示模式；生产由管理员通过 /api/bids/tenders 发布
    if SEED_DEMO_DATA:
        if conn.execute("SELECT COUNT(*) c FROM bid_tenders").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO bid_tenders (dep, arr, flight_no, distance_nm, intl, start_price,"
                " min_step, closes_at)"
                " VALUES (?, ?, ?, ?, 0, ?, ?, datetime('now', ?, 'localtime'))",
                [
                    ("ZSPD", "RJAA", "CTY101", 1120.0, 60000, 5000, "+3 day"),
                    ("ZBAA", "VHHH", "CTY205", 1080.0, 80000, 5000, "+5 day"),
                    ("ZGGG", "WSSS", "CTY320", 1440.0, 120000, 8000, "+7 day"),
                ],
            )

    migrate_archive_forum(conn)
    migrate_survey_anon(conn)

    conn.commit()
    conn.close()
    print(f"[db] SQLite 就绪: {DB_PATH}")
