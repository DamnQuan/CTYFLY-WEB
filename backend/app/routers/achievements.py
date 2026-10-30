"""成就徽章：服务端统一结算 check_achievements user_id, event_type

为什么进度必须由服务端重算，而不是信任调用方传进来的数字：
签派、报告审核、竞标中标、二手成交这些事件在服务端都有确定的落库行，进度完全可以
由一条 SQL 数出来。若改成「客户端上报进度」，成就就退化成前端想给多少给多少的虚荣字段，
而解锁会真的发钱，reward 进钱包—— 那就成了可伪造的发钱入口。所以这里的唯一入参是
event_type，进度一律用 METRIC_SQL 白名单里的 SQL 重新计算。

三个必须守住的性质，每条都有对应的并发/幂等测试：
1. **只解锁一次**：UNIQUE user_id, achievement_id + `UPDATE ... WHERE unlocked_at IS NULL`
   的条件更新决定归属，rowcount=0 的那一方不重复发奖。
2. **失败不影响主流程**：调用方，签派/审核/成交已经提交完业务事务，成就结算即使异常
   也只写日志 —— 成就不能把一次真实的飞行报告审核搞成 500。
3. **必须在业务事务之外调用**：get_conn 是线程本地的，嵌套 with 会另开一条连接；
   SQLite 单写锁下，外层事务未提交时内层再写会等锁超时，10s 后抛错。
   本模块允许传 conn 是为了「同一事务内结算」的显式场景，路由里的钩子一律在
   with 块**结束之后**调用，见 dispatch.py / pirep.py / market.py 的注释。
"""
from fastapi import APIRouter, Depends, HTTPException
from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth
from ..mailer import notify_user

router = APIRouter(prefix="/api/achievements", tags=["achievements"])

# 进度取值口径白名单：key 与 achievement_defs.metric 一一对应。
# 全部是参数化查询，且只引用 user_id —— 没有任何字符串拼接进 SQL 的位置。
METRIC_SQL = {
    # 已通过审核的飞行报告数
    "flight_count": "SELECT COUNT(*) AS v FROM flight_reports WHERE user_id = ? AND status = 'approved'",
    # 累计飞行时长，wallets.total_hours 是审核通过时累加的权威口径
    "flight_hours": "SELECT CAST(COALESCE((SELECT total_hours FROM wallets WHERE user_id = ?), 0) AS INTEGER) AS v",
    # 签派单数
    "dispatch_count": "SELECT COUNT(*) AS v FROM dispatches WHERE user_id = ?",
    # 竞标中标数
    "bid_won_count": "SELECT COUNT(*) AS v FROM bid_offers WHERE user_id = ? AND status = 'won'",
    # 二手卖出数
    "market_sold_count": "SELECT COUNT(*) AS v FROM market_trades WHERE seller_id = ?",
    # 二手买入数
    "market_bought_count": "SELECT COUNT(*) AS v FROM market_trades WHERE buyer_id = ?",
    # 事故上报数，自己报的
    "incident_count": "SELECT COUNT(*) AS v FROM incidents WHERE user_id = ?",
}

# 前端展示用的事件文案，一次性说明「什么行为会推进这枚徽章」
EVENT_LABELS = {
    "flight_approved": "飞行报告通过审核",
    "dispatch_created": "签发签派单",
    "bid_won": "航线竞标中标",
    "market_sold": "二手市场卖出飞机",
    "market_bought": "二手市场买入飞机",
    "incident_reported": "上报飞行事故",
}

CATEGORY_LABELS = {
    "flight": "飞行",
    "airline": "航司运营",
    "economy": "经济",
    "safety": "安全",
}


def _defs(conn) -> list:
    return conn.execute(
        "SELECT * FROM achievement_defs WHERE active = 1 ORDER BY sort, id"
    ).fetchall()


def _metric_value(conn, metric: str, user_id: int) -> int:
    """按白名单口径算进度；metric 不认识时返回 0，不退化成 f-string 拼接"""
    sql = METRIC_SQL.get(metric)
    if not sql:
        return 0
    row = conn.execute(sql, (user_id,)).fetchone()
    return int(row["v"] or 0) if row else 0


def _pay_reward(conn, user_id: int, amount: int, ach_name: str) -> None:
    """成就奖金：与发薪同一条钱包链路，先原子加余额，再写流水"""
    if amount <= 0:
        return
    w = conn.execute("SELECT user_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if w:
        conn.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    else:
        conn.execute(
            "INSERT INTO wallets (user_id, balance, total_hours) VALUES (?, ?, 0)",
            (user_id, amount),
        )
    conn.execute(
        "INSERT INTO wallet_records (user_id, amount, type, note) VALUES (?, ?, 'achievement', ?)",
        (user_id, amount, f"成就解锁：{ach_name}"),
    )


def check_achievements(user_id: int, event_type: str, conn=None) -> list[dict]:
    """结算某用户的成就进度，返回**本次新解锁**的成就列表。

    - event_type 为空或不认识时直接返回 []，调用方无需特判。
    - conn 传入时复用调用方事务；不传则自开一条，钩子的常规用法。
    - 任何异常只打印、不抛出：成就结算失败不该让签派/审核/成交失败。
    """
    if not event_type:
        return []
    unlocked: list[dict] = []
    try:
        if conn is not None:
            unlocked = _settle(conn, user_id, event_type)
        else:
            with get_conn() as own:
                unlocked = _settle(own, user_id, event_type)
        # 通知与审计放在事务外：通知走邮件队列，可能慢，审计另开连接
        for a in unlocked:
            log_event("system", "成就解锁", actor={"id": user_id}, target_type="achievement",
                      target_id=a["id"], detail=f"{a['name']}，{a['code']}奖励 {a['reward']}")
            notify_user(
                user_id, f"成就解锁：{a['name']}",
                f"恭喜达成成就「{a['name']}」——{a['description']}。\n"
                f"奖励 {a['reward']} 游戏币已存入你的钱包。",
            )
    except Exception as exc:                      # noqa: BLE001 - 成就失败不影响主流程
        print(f"[achievements] 结算失败 uid={user_id} event={event_type}: {exc!r}")
        return []
    return unlocked


def _settle(conn, user_id: int, event_type: str) -> list[dict]:
    """同一事件下所有相关成就的进度更新 + 首次解锁发奖，调用方保证已提交/在事务内"""
    out = []
    for d in _defs(conn):
        if d["event_type"] != event_type:
            continue
        value = _metric_value(conn, d["metric"], user_id)
        # 进度只增不减：MAX progress, 新值 避免「删了报告导致进度回退」造成反复触达
        conn.execute(
            "INSERT INTO user_achievements (user_id, achievement_id, progress) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, achievement_id) DO UPDATE SET"
            " progress = MAX(user_achievements.progress, excluded.progress)",
            (user_id, d["id"], value),
        )
        if value < d["threshold"]:
            continue
        # 解锁条件更新：只有「第一次把 unlocked_at 从 NULL 改成非空」的那次才算解锁
        cur = conn.execute(
            "UPDATE user_achievements SET unlocked_at = datetime('now','localtime'),"
            " reward_paid = ?, notified = 1"
            " WHERE user_id = ? AND achievement_id = ? AND unlocked_at IS NULL",
            (d["reward"], user_id, d["id"]),
        )
        if cur.rowcount == 0:
            continue
        _pay_reward(conn, user_id, d["reward"], d["name"])
        out.append(dict(d))
    return out


@router.get("")
def list_achievements(user: dict = Depends(require_auth)):
    """全部成就 + 我的进度/解锁状态 + 汇总，页面一次请求拿全"""
    with get_conn() as conn:
        defs = _defs(conn)
        mine = {
            r["achievement_id"]: dict(r)
            for r in conn.execute(
                "SELECT achievement_id, progress, unlocked_at FROM user_achievements WHERE user_id = ?",
                (user["id"],),
            )
        }
    items = []
    for d in defs:
        st = mine.get(d["id"], {})
        progress = int(st.get("progress") or 0)
        items.append({
            **dict(d),
            "progress": progress,
            "percent": min(100, int(progress * 100 / d["threshold"])) if d["threshold"] > 0 else 100,
            "unlocked": bool(st.get("unlocked_at")),
            "unlockedAt": st.get("unlocked_at") or "",
            "eventLabel": EVENT_LABELS.get(d["event_type"], ""),
            "categoryLabel": CATEGORY_LABELS.get(d["category"], d["category"]),
        })
    total_unlocked = sum(1 for i in items if i["unlocked"])
    total_reward = sum(i["reward"] for i in items if i["unlocked"])
    return {
        "ok": True,
        "items": items,
        "stats": {
            "total": len(items),
            "unlocked": total_unlocked,
            "rewardEarned": total_reward,
            "categories": CATEGORY_LABELS,
        },
    }


@router.get("/{user_id}")
def list_user_achievements(user_id: int, user: dict = Depends(require_auth)):
    """查看任意用户的成就墙，个人信息页用；只暴露已解锁项，不泄露他人进度"""
    with get_conn() as conn:
        target = conn.execute("SELECT id, cid, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "用户不存在")
        rows = conn.execute(
            "SELECT d.id, d.code, d.name, d.description, d.icon, d.category, d.reward,"
            " d.threshold, d.sort, ua.unlocked_at"
            " FROM user_achievements ua JOIN achievement_defs d ON d.id = ua.achievement_id"
            " WHERE ua.user_id = ? AND ua.unlocked_at IS NOT NULL AND d.active = 1"
            " ORDER BY ua.unlocked_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return {
        "ok": True,
        "user": dict(target),
        "items": [
            {**dict(r), "categoryLabel": CATEGORY_LABELS.get(r["category"], r["category"])}
            for r in rows
        ],
    }
