"""幂等迁移：只做加法式变更，由 database.init_db 在原位置顺序调用。

迁移函数只接受 conn，不 import 业务路由，方便独立测试。
"""
import sqlite3


def migrate_partner_logo(conn) -> None:
    """合作伙伴 Logo 从 dist 静态路径迁到持久化 uploads 目录。"""
    conn.execute(
        "UPDATE partners SET logo = '/uploads/partner-' || substr(logo, 11)"
        " WHERE logo LIKE '/partners/%'"
    )


def migrate_log_ua(conn) -> None:
    """日志表补 UA 解析列，并为历史行补算标记。"""
    from ..requestinfo import classify_ua

    for table in ("login_logs", "register_logs", "audit_logs"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "ua_label" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN ua_label TEXT NOT NULL DEFAULT ''")
        if "ua_bot" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN ua_bot INTEGER NOT NULL DEFAULT 0")
        rows = conn.execute(
            f"SELECT id, ua FROM {table} WHERE ua_label = '' AND ua != '' LIMIT 5000"
        ).fetchall()
        for r in rows:
            label, is_bot = classify_ua(r["ua"])
            conn.execute(
                f"UPDATE {table} SET ua_label = ?, ua_bot = ? WHERE id = ?",
                (label, 1 if is_bot else 0, r["id"]),
            )
        if rows:
            print(f"[db] {table} 已为 {len(rows)} 条历史日志补算 UA 标记")


def migrate_application_nickname(conn) -> None:
    """申请表 real_name 并入 nickname，旧列保留以支持回退。"""
    appcols = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
    if "nickname" not in appcols:
        conn.execute("ALTER TABLE applications ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
        print("[db] applications 已补 nickname 列")
    appcols = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
    if "real_name" in appcols:
        conn.execute(
            "UPDATE applications SET nickname = real_name"
            " WHERE nickname = '' AND real_name != ''"
        )


def migrate_badge_payload(conn) -> None:
    """早期徽章 payload 是英文单词，改为 SVG 图标标识。"""
    for old, new in (("star", "icon:star"), ("diamond", "icon:diamond")):
        conn.execute(
            "UPDATE shop_items SET payload = ? WHERE type = 'badge' AND payload = ?", (new, old)
        )


def migrate_archive_forum(conn) -> None:
    """飞圈事件检索论坛化：给既有 archive_events 补互动计数字段。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(archive_events)")}
    additions = (
        ("like_count", "INTEGER NOT NULL DEFAULT 0"),
        ("favorite_count", "INTEGER NOT NULL DEFAULT 0"),
        ("comment_count", "INTEGER NOT NULL DEFAULT 0"),
        ("view_count", "INTEGER NOT NULL DEFAULT 0"),
        ("featured", "INTEGER NOT NULL DEFAULT 0"),
        ("featured_at", "TEXT"),
    )
    for name, ddl in additions:
        if cols and name not in cols:
            conn.execute(f"ALTER TABLE archive_events ADD COLUMN {name} {ddl}")


def migrate_survey_anon(conn) -> None:
    """问卷一人一份：补匿名标识列与两个部分唯一索引。"""
    survey_cols = {r[1] for r in conn.execute("PRAGMA table_info(survey_responses)")}
    if survey_cols and "anon_id" not in survey_cols:
        conn.execute("ALTER TABLE survey_responses ADD COLUMN anon_id TEXT NOT NULL DEFAULT ''")
    for stmt in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_user_unique"
        " ON survey_responses(user_id) WHERE user_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_anon_unique"
        " ON survey_responses(anon_id) WHERE anon_id != ''",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.IntegrityError:
            print("[db] 问卷历史数据存在重复，跳过唯一索引；接口层仍会拦截重复提交")
