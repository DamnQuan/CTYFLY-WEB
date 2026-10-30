"""虚拟航司 · 资金账本与我的钱包 API，2026-10-11 从 routers/airlines.py 抽出，P3 第四刀

包含：GET /api/wallet，我的钱包 + 最近流水、GET /api/airlines/{id}/ledger，公司资金概览 +
账本分页，**只读**。

账本口径，见 airline_ledger_view 文档字符串：amount 带符号，收入为正、支出为负，
net = SUM amount 应恒等于 airlines.balance；`reconciled` 字段即账实自检。
本模块不提供任何变动资金的入口 —— 发钱只能走带经济上限的报告审核链路。

沿用同前缀多 router 的既有做法：router 只承载 /api/airlines 下的账本端点，
wallet_router 承载 /api/wallet。由 main.py 注册。
"""
from ..database import get_conn
from ..deps import require_auth
from fastapi import APIRouter, Depends

from .airlines import (LEDGER_PAGE_SIZE, _require_manager, rank_for)


router = APIRouter(prefix="/api/airlines", tags=["airlines"])
wallet_router = APIRouter(prefix="/api/wallet", tags=["wallet"])

def _wallet(conn, user_id: int) -> dict:
    row = conn.execute(
        "SELECT balance, total_hours FROM wallets WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row:
        return {"balance": row["balance"], "total_hours": row["total_hours"], "rank": rank_for(row["total_hours"])}
    return {"balance": 0, "total_hours": 0, "rank": "学员"}

@wallet_router.get("")
def my_wallet(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        wallet = _wallet(conn, user["id"])
        # 全站时长排名
        rank_row = conn.execute(
            "SELECT COUNT(*) + 1 AS r FROM wallets WHERE total_hours > ?", (wallet["total_hours"],)
        ).fetchone()
        records = conn.execute(
            "SELECT * FROM wallet_records WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
    wallet["siteRank"] = rank_row["r"]
    wallet["records"] = [dict(r) for r in records]
    return {"ok": True, "wallet": wallet}

@router.get("/{airline_id}/ledger")
def airline_ledger_view(airline_id: int, page: int = 1, type: str = "",
                              user: dict = Depends(require_auth)):
    """公司资金概览 + 账本流水分页，**只读**。

    为什么补这个端点：airline_ledger 此前是「只写不读」——全后端只有 8 处 INSERT
    报告结算 6 处 + 航司商城 2 处，却没有任何读接口，10-02 文档里列为功能的
    「公司账本」用户一直看不到。

    口径说明，与写入侧严格对齐：
    - amount 带符号，收入为正、支出为负；`type` 为 revenue | expense
    - 改 airlines.balance 的 4 处，报告净额 / CEO 人工审核 / 航司商城兑换 / 兑换退款
      都同步写了账本，因此 balance 应恒等于账本净额，`reconciled` 即账实自检
    - 本端点不提供任何变动资金的入口：发钱只能走带经济上限的报告审核那条路
    """
    page = max(1, min(int(page or 1), 10000))
    offset = (page - 1) * LEDGER_PAGE_SIZE
    kind = type if type in ("revenue", "expense") else ""

    with get_conn() as conn:
        _require_manager(conn, airline_id, user["id"])
        a = conn.execute("SELECT balance FROM airlines WHERE id = ?", (airline_id,)).fetchone()
        balance = (a["balance"] if a else 0) or 0

        totals = {"revenue": 0, "expense": 0}
        for r in conn.execute(
            "SELECT type, COALESCE(SUM(amount), 0) AS total FROM airline_ledger"
            " WHERE airline_id = ? GROUP BY type",
            (airline_id,),
        ):
            totals[r["type"]] = r["total"] or 0

        recent = {"revenue": 0, "expense": 0}
        for r in conn.execute(
            "SELECT type, COALESCE(SUM(amount), 0) AS total FROM airline_ledger"
            " WHERE airline_id = ? AND date(created_at) >= date('now','localtime','-30 days')"
            " GROUP BY type",
            (airline_id,),
        ):
            recent[r["type"]] = r["total"] or 0

        where = "airline_id = ?" + (" AND type = ?" if kind else "")
        params: tuple = (airline_id, kind) if kind else (airline_id,)
        total_rows = conn.execute(
            f"SELECT COUNT(*) AS c FROM airline_ledger WHERE {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT id, amount, type, note, report_id, created_at FROM airline_ledger"
            f" WHERE {where} ORDER BY id DESC LIMIT {LEDGER_PAGE_SIZE} OFFSET ?",
            (*params, offset),
        ).fetchall()

    net = totals["revenue"] + totals["expense"]
    return {
        "ok": True,
        "balance": balance,
        "income": totals["revenue"],
        "expense": totals["expense"],          # 负数，账本口径：支出记负
        "net": net,
        "recent30": {"income": recent["revenue"], "expense": recent["expense"]},
        "reconciled": net == balance,          # 账实自检：理论上恒为 True
        "total": total_rows,
        "page": page,
        "pageSize": LEDGER_PAGE_SIZE,
        "records": [dict(r) for r in rows],
    }
