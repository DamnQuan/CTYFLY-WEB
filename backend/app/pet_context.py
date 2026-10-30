"""小鲸灵 AI 的「全栈感知」上下文构造。

目的：让桌宠能回答站内问题，有多少航司/多少活动、AIRAC 是什么周期、报文去哪查、
     我是什么等级，而不是只会寒暄。

设计要点：
  - 静态「功能地图」每次都给，让模型知道每个模块的名字与用途，用户问「在哪查」时能指路；
  - 动态「实时快照」走 TTL 内存缓存，默认 300s：十几条 COUNT + 读一次 AIRAC nd.db3，
    既不每轮都查库，也不给模型塞重复内容；提示词里明确告诉它「不是秒级实时」，不许吹；
  - **任何一项失败只丢那一项**，整体 try/except，绝不让对话因为统计失败而挂掉；
  - 隐私红线：只给聚合数字与公开信息。用户自己的资料只给非敏感项
    等级/CID/所属航司/累计飞行小时/未关闭工单数/已报名活动，**不传钱包余额**——
    余额是财务信息，没必要交给第三方模型，模型可以说「去钱包页看」。
"""
import sqlite3
import threading
import time
from pathlib import Path

from .config import NAVDATA_DB, NAVDATA_SIDECAR_DIR
from .database import get_conn

# 快照缓存时长：300 秒。改小=更实时但更费库；改大=更省但数字更旧。
SNAPSHOT_TTL = 300

FEATURES = """【站点功能地图】（CTYFLY 虚拟航空社区，用来给用户指路）
- 首页 / 仪表盘：活动月历、飞行时长榜、最新公告
- 报文查询：METAR / TAF 实时报文
- 航路查询 / 飞行计划：基于 AIRAC 导航数据搜航路、算大圆距离、生成飞行计划
- 连飞活动：活动列表与报名、活动简报、管制席位
- 虚拟航司：申请或创建航司、成员与考核、机队、航司航线、航司内部商城、钱包与转账、航司动态（发帖/点赞/评论）
- 商城：用钱包余额购买涂装/服务等商品
- 工单中心：提交工单、追问与回复
- 个人资料：等级、CID、头像、隐私政策
- 管理后台（仅管理员）：用户与航司审核、公告、日志、数据概览
用户问「在哪查 / 怎么用」时，用上面这些名字指路；上面没有的不要编。"""

_snapshot_cache: dict = {"at": 0.0, "text": ""}
_snapshot_lock = threading.Lock()


def _airac_line() -> str:
    """读 AIRAC nd.db3 的 config 表，只读、失败返回一句兜底"""
    db = Path(NAVDATA_DB) if NAVDATA_DB else Path(NAVDATA_SIDECAR_DIR) / "Navdata" / "nd.db3"
    if not db.exists():
        return "- 导航数据：暂不可用"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cfg = dict(con.execute("SELECT key, val FROM config").fetchall())
        airports = con.execute("SELECT COUNT(*) FROM Airports").fetchone()[0]
        waypoints = con.execute("SELECT COUNT(*) FROM Waypoints").fetchone()[0]
        airways = con.execute("SELECT COUNT(*) FROM Airways").fetchone()[0]
    finally:
        con.close()
    name = cfg.get("CycleName", "?")
    start = cfg.get("CycleStartDate", "?")
    end = cfg.get("CycleEndDate", "?")
    return (f"- 导航数据 AIRAC {name}，{start} - {end}：机场 {airports} 个、"
            f"航路点 {waypoints} 个、航路 {airways} 条")


def site_snapshot() -> str:
    """站点实时快照，带 TTL 缓存。任何一项失败都不影响对话。"""
    now = time.time()
    with _snapshot_lock:
        if _snapshot_cache["text"] and now - _snapshot_cache["at"] < SNAPSHOT_TTL:
            return _snapshot_cache["text"]

    lines: list[str] = []
    try:
        with get_conn() as conn:
            def one(sql: str, *args):
                return conn.execute(sql, args).fetchone()

            total_users = one("SELECT COUNT(*) c FROM users")["c"]
            online = one(
                "SELECT COUNT(DISTINCT user_id) c FROM api_access_log"
                " WHERE user_id > 0 AND created_at >= datetime('now','localtime','-5 minutes')"
            )["c"]
            controllers = one("SELECT COUNT(*) c FROM users WHERE is_controller = 1")["c"]
            airlines = one("SELECT COUNT(*) c FROM airlines WHERE status = 'approved'")["c"]
            routes = one("SELECT COUNT(*) c FROM routes")["c"]
            hours = one("SELECT COALESCE(SUM(total_hours), 0) h FROM wallets")["h"]
            event_count = one(
                "SELECT COUNT(*) c FROM events WHERE status IN ('upcoming','ongoing')"
            )["c"]
            server_time = one("SELECT datetime('now','localtime') t")["t"]
            events = conn.execute(
                "SELECT title, dep, arr, start_time, status FROM events"
                " WHERE status IN ('upcoming','ongoing') ORDER BY start_time LIMIT 3"
            ).fetchall()
            notices = conn.execute(
                "SELECT title FROM notices ORDER BY pinned DESC, id DESC LIMIT 2"
            ).fetchall()

        lines.append(f"【站点实时快照】数据时间 {server_time}，缓存 {SNAPSHOT_TTL} 秒，"
                     "不要宣称秒级实时")
        lines.append(f"- 注册用户 {total_users} 人，近 5 分钟在线 {online} 人，管制员 {controllers} 人")
        lines.append(f"- 已通过虚拟航司 {airlines} 家；站内航线 {routes} 条；全站累计飞行 {round(hours)} 小时")
        if event_count:
            lines.append(f"- 进行中 / 即将开始的连飞活动 {event_count} 场：")
            for e in events:
                lines.append(f"    · {e['title']}，{e['dep']}→{e['arr']}，{e['start_time']}，{e['status']}")
        else:
            lines.append("- 目前没有进行中 / 即将开始的连飞活动")
        for n in notices:
            lines.append(f"- 最新公告：{n['title']}")
    except Exception:
        # 统计失败就少给一段，绝不能因此让宠物「哑掉」
        lines.append("【站点实时快照】暂时取不到，数据库查询失败。"
                     "这种情况直接说不知道，不要编数字。")

    try:
        lines.append(_airac_line())
    except Exception:
        lines.append("- 导航数据：暂时取不到")

    text = "\n".join(lines)
    with _snapshot_lock:
        _snapshot_cache["at"] = now
        _snapshot_cache["text"] = text
    return text


def user_context(user: dict) -> str:
    """这位用户自己的信息，只含非敏感项；不含钱包余额"""
    uid = user.get("id")
    name = user.get("username") or ""
    lines = [f"【你面前这位用户】用户名 {name}，CID {user.get('cid') or '未分配'}，"
             f"等级 {user.get('rating') or '学员'}"
             + (f"身份 {user.get('role')}" if user.get("role") else "")]
    if not uid:
        return "\n".join(lines)
    try:
        with get_conn() as conn:
            w = conn.execute(
                "SELECT total_hours FROM wallets WHERE user_id = ?", (uid,)
            ).fetchone()
            if w is not None:
                lines.append(f"- 累计飞行 {round(w['total_hours'] or 0)} 小时")
            t = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE user_id = ? AND status != 'closed'", (uid,)
            ).fetchone()["c"]
            if t:
                lines.append(f"- 未关闭工单 {t} 个")
            a = conn.execute(
                "SELECT COUNT(*) c FROM applications WHERE user_id = ? AND status = 'pending'",
                (uid,),
            ).fetchone()["c"]
            if a:
                lines.append(f"- 待审核申请 {a} 个")
            m = conn.execute(
                "SELECT al.name FROM airline_members m JOIN airlines al ON al.id = m.airline_id"
                " WHERE m.user_id = ? AND m.status = 'active' LIMIT 1",
                (uid,),
            ).fetchone()
            lines.append(f"- 所属虚拟航司：{m['name']}" if m else "- 暂未加入虚拟航司")
            s = conn.execute(
                "SELECT e.title, e.start_time FROM event_signups s JOIN events e ON e.id = s.event_id"
                " WHERE s.user_id = ? AND e.status IN ('upcoming','ongoing')"
                " ORDER BY e.start_time LIMIT 2",
                (uid,),
            ).fetchall()
            for row in s:
                lines.append(f"- 已报名活动：{row['title']}，{row['start_time']}")
    except Exception:
        pass
    return "\n".join(lines)


def build_context(user: dict) -> str:
    """拼成塞进 instructions 的完整上下文"""
    return "\n\n".join([FEATURES, site_snapshot(), user_context(user)])
