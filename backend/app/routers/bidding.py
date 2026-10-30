"""航线竞标：平台放出航线招标，航司出价竞争，截止后一次性结算分配

资金模型，与 wallet / market 完全同一套账本口径：
- **出价即冻结**：从 airlines.balance 原子扣款，并写一条 airline_ledger 支出行。
  钱虽然离开了可用余额，但它对应一条 active 的 bid_offers 记录，随时可原路退回 ——
  所以「冻结」在这里是「已扣款 + 有据可退」，不需要额外的冻结字段，少一个状态就少一类不一致。
- **改价 = 先退旧的再冻新的**：同一航司同一招标只允许一笔在标出价，部分唯一索引兜底，
  改价时先把旧出价全额退回，再按新价冻结，两条账本行都留痕。
- **结算**：中标者的冻结款不退，航线归属，钱已作为支出入账，未中标者全额退回。
  因为退款与中标都只是「账本 + 余额」的成对操作，SUM ledger 恒等于 balance，
  启动自检，main._check_ledger_invariant 不会被这批数据破坏。

结算入口是幂等的：`UPDATE ... WHERE status='open' AND closes_at <= now` 先抢占状态，
只有 rowcount=1 的调用方进入结算流程，重复调用/并发调用都不会重复退款。
"""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_admin, require_auth
from ..mailer import notify_user
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent

from .achievements import check_achievements
from .airlines import _require_ceo

router = APIRouter(prefix="/api/bids", tags=["bidding"])

# 硬编码分页，红线：分页大小不由用户决定
BID_PAGE_SIZE = 20
BID_MAX_PAGE = 2000

# 单条航线招标的起拍价上限，防运营手滑填成天文数字
MAX_START_PRICE = 10_000_000

DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _begin_write(conn) -> None:
    if conn.in_transaction:
        return
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise HTTPException(409, "竞标通道繁忙，请稍后重试") from exc


def _now(conn) -> str:
    return conn.execute("SELECT datetime('now','localtime') AS t").fetchone()["t"]


def _audit(request: Request, action: str, *, actor, target_type: str, target_id,
           detail: str) -> None:
    log_event("airline", action, actor=actor, target_type=target_type, target_id=target_id,
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))


def _tender_or_404(conn, tender_id: int):
    row = conn.execute("SELECT * FROM bid_tenders WHERE id = ?", (tender_id,)).fetchone()
    if not row:
        raise HTTPException(404, "招标不存在")
    return row


def _refund_offer(conn, offer, note_prefix: str = "竞标退款") -> None:
    """退回一笔冻结资金：余额 +amount、账本记收入正数、出价置 refunded，幂等靠调用方条件更新"""
    conn.execute(
        "UPDATE airlines SET balance = balance + ? WHERE id = ?",
        (offer["amount"], offer["airline_id"]),
    )
    conn.execute(
        "INSERT INTO airline_ledger (airline_id, amount, type, note) VALUES (?, ?, 'revenue', ?)",
        (offer["airline_id"], offer["amount"],
         f"{note_prefix}：出价 #{offer['id']}，{offer['amount']}"),
    )
    conn.execute(
        "UPDATE bid_offers SET status = 'refunded', settled_at = datetime('now','localtime')"
        " WHERE id = ? AND status = 'active'",
        (offer["id"],),
    )


class TenderBody(BaseModel):
    dep: str = Field("", max_length=8)
    arr: str = Field("", max_length=8)
    flightNo: str = Field("", max_length=16)
    distanceNm: float = Field(0, ge=0, le=20000)
    startPrice: int = Field(0, ge=0, le=MAX_START_PRICE)
    minStep: int = Field(1000, ge=100, le=1000000)
    closesAt: str = Field(..., max_length=19)


class OfferBody(BaseModel):
    airlineId: int = Field(..., ge=1)
    amount: int = Field(..., ge=1, le=100000000)


@router.get("/tenders")
def list_tenders(page: int = 1, scope: str = "open", user: dict = Depends(require_auth)):
    """招标列表：open=在标 / settled=已结算；附带本航司在标出价与当前最高价"""
    page = max(1, min(int(page or 1), BID_MAX_PAGE))
    offset = (page - 1) * BID_PAGE_SIZE
    where = "status = 'open'" if scope != "settled" else "status = 'settled'"

    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM bid_tenders WHERE {where}").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM bid_tenders"
            f" WHERE {where} ORDER BY {'closes_at ASC' if scope != 'settled' else 'settled_at DESC, id DESC'}"
            f" LIMIT {BID_PAGE_SIZE} OFFSET ?",
            (offset,),
        ).fetchall()
        aids = [
            r["airline_id"]
            for r in conn.execute(
                "SELECT airline_id FROM airline_members WHERE user_id = ? AND status = 'active'",
                (user["id"],),
            )
        ]
        my_offers, top = {}, {}
        if rows:
            ids = [r["id"] for r in rows]
            marks = ",".join("?" * len(ids))
            for r in conn.execute(
                "SELECT bid_offers.*, a.name AS airline_name FROM bid_offers"
                " JOIN airlines a ON a.id = bid_offers.airline_id"
                f" WHERE tender_id IN ({marks}) AND bid_offers.status IN ('active','won')"
                " ORDER BY amount DESC",
                tuple(ids),
            ):
                top.setdefault(r["tender_id"], dict(r))
                if aids and r["airline_id"] in aids:
                    my_offers[r["tender_id"]] = dict(r)
            counts = {
                r["tender_id"]: r["c"]
                for r in conn.execute(
                    f"SELECT tender_id, COUNT(*) AS c FROM bid_offers"
                    f" WHERE tender_id IN ({marks}) AND status IN ('active','won')"
                    " GROUP BY tender_id",
                    tuple(ids),
                )
            }
        else:
            counts = {}
        balances: dict[int, int] = {}
        if aids:
            marks_a = ",".join("?" * len(aids))
            balances = {
                r["id"]: r["balance"]
                for r in conn.execute(
                    f"SELECT id, balance FROM airlines WHERE id IN ({marks_a})", tuple(aids)
                )
            }
        now = _now(conn)
    items = []
    for r in rows:
        d = dict(r)
        d["topOffer"] = top.get(r["id"])
        d["offerCount"] = counts.get(r["id"], 0)
        d["myOffer"] = my_offers.get(r["id"])
        d["canBid"] = d["status"] == "open" and d["closes_at"] > now
        items.append(d)
    return {
        "ok": True,
        "items": items,
        "total": total,
        "page": page,
        "pageSize": BID_PAGE_SIZE,
        "myAirlines": aids,
        "balances": balances,
        "serverNow": now,
    }


@router.post("/tenders")
def create_tender(body: TenderBody, request: Request, admin: dict = Depends(require_admin)):
    """管理员发布一条招标航线"""
    dep = body.dep.strip().upper()
    arr = body.arr.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,4}", dep) or not re.fullmatch(r"[A-Z0-9]{3,4}", arr):
        raise HTTPException(400, "起降机场需为 3~4 位 ICAO/IATA 代码")
    if dep == arr:
        raise HTTPException(400, "起降机场不能相同")
    if not DATETIME_RE.match(body.closesAt.strip()):
        raise HTTPException(400, "截止时间格式应为 YYYY-MM-DDTHH:mm")
    closes_at = body.closesAt.strip().replace("T", " ")
    # 统一成「秒级」时间串，避免 "10:00" 与 "10:00:00" 比较时被当成已过期
    if len(closes_at) == 16:
        closes_at += ":00"
    with get_conn() as conn:
        if closes_at <= _now(conn):
            raise HTTPException(400, "截止时间必须晚于当前时间")
        cur = conn.execute(
            "INSERT INTO bid_tenders (dep, arr, flight_no, distance_nm, start_price, min_step,"
            " closes_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (dep, arr, body.flightNo.strip().upper() or f"{dep}-{arr}", body.distanceNm,
             body.startPrice, body.minStep, closes_at, admin["id"]),
        )
        tender_id = cur.lastrowid
    _audit(request, "发布航线招标", actor=admin, target_type="bid_tender", target_id=tender_id,
           detail=f"{dep}-{arr} · 起拍 {body.startPrice}")
    return {"ok": True, "id": tender_id, "message": f"招标已发布：{dep}-{arr}"}


@router.post("/tenders/{tender_id}/offers")
def place_offer(tender_id: int, body: OfferBody, request: Request,
                user: dict = Depends(require_auth)):
    """CEO 出价：退旧冻结 → 原子扣新冻结 → 写入出价，同一事务"""
    enforce(request, "bid-offer", 30, 3600)
    amount = int(body.amount)
    with get_conn() as conn:
        _begin_write(conn)
        _require_ceo(conn, body.airlineId, user["id"])
        t = _tender_or_404(conn, tender_id)
        now = _now(conn)
        if t["status"] != "open" or t["closes_at"] <= now:
            raise HTTPException(400, "该招标已截止或已结算")

        highest = conn.execute(
            "SELECT * FROM bid_offers WHERE tender_id = ? AND status = 'active'"
            " ORDER BY amount DESC, id ASC LIMIT 1",
            (tender_id,),
        ).fetchone()
        floor = t["start_price"]
        if highest:
            floor = max(floor, highest["amount"] + t["min_step"])
        mine = conn.execute(
            "SELECT * FROM bid_offers WHERE tender_id = ? AND airline_id = ? AND status = 'active'",
            (tender_id, body.airlineId),
        ).fetchone()
        if mine and mine["amount"] == amount:
            raise HTTPException(400, "出价与当前一致，无需重复出价")
        if amount < floor:
            raise HTTPException(400, f"出价至少需要 {floor}，当前最高 {highest['amount'] if highest else 0}，最小加价 {t['min_step']}")

        # ① 先把本航司旧的在标出价全额退回，改价场景
        if mine:
            _refund_offer(conn, mine, "竞标改价退款")

        # ② 冻结新出价：条件原子扣款，余额不足则整个事务回滚，旧出价退款也一并撤销
        cur_w = conn.execute(
            "UPDATE airlines SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (amount, body.airlineId, amount),
        )
        if cur_w.rowcount == 0:
            bal = conn.execute(
                "SELECT balance FROM airlines WHERE id = ?", (body.airlineId,)
            ).fetchone()["balance"]
            raise HTTPException(400, f"航司余额不足：出价 {amount}，当前余额 {bal}")

        hold = conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note) VALUES (?, ?, 'expense', ?)",
            (body.airlineId, -amount, f"竞标冻结：{t['dep']}-{t['arr']}，招标 #{tender_id}"),
        )
        try:
            cur = conn.execute(
                "INSERT INTO bid_offers (tender_id, airline_id, user_id, amount, ledger_hold_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (tender_id, body.airlineId, user["id"], amount, hold.lastrowid),
            )
        except sqlite3.IntegrityError:
            # uq_bid_offers_active：并发双出价被约束拦下，唯一索引兜底
            raise HTTPException(409, "出价冲突，请刷新后重试")
        offer_id = cur.lastrowid
    _audit(request, "航线竞标出价", actor=user, target_type="bid_offer", target_id=offer_id,
           detail=f"{t['dep']}-{t['arr']} · 出价 {amount}，已冻结")
    return {
        "ok": True,
        "id": offer_id,
        "amount": amount,
        "message": f"出价成功 {amount}，资金已冻结；截止 {(t['closes_at'])}",
    }


@router.post("/offers/{offer_id}/withdraw")
def withdraw_offer(offer_id: int, request: Request, user: dict = Depends(require_auth)):
    """撤标：仅在招标未截止时允许，冻结资金原路退回"""
    enforce(request, "bid-withdraw", 30, 3600)
    with get_conn() as conn:
        _begin_write(conn)
        offer = conn.execute("SELECT * FROM bid_offers WHERE id = ?", (offer_id,)).fetchone()
        if not offer:
            raise HTTPException(404, "出价不存在")
        if offer["status"] != "active":
            raise HTTPException(400, "该出价已结算，无法撤回")
        _require_ceo(conn, offer["airline_id"], user["id"])
        t = _tender_or_404(conn, offer["tender_id"])
        if t["status"] != "open" or t["closes_at"] <= _now(conn):
            raise HTTPException(400, "招标已截止，无法撤标")
        # 状态与资金动作同一事务：撤标，withdrawn 与退款，余额 + 账本收入要么全成要么全败
        cur = conn.execute(
            "UPDATE bid_offers SET status = 'withdrawn', settled_at = datetime('now','localtime')"
            " WHERE id = ? AND status = 'active'",
            (offer_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "该出价已被处理")
        conn.execute(
            "UPDATE airlines SET balance = balance + ? WHERE id = ?",
            (offer["amount"], offer["airline_id"]),
        )
        conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note)"
            " VALUES (?, ?, 'revenue', ?)",
            (offer["airline_id"], offer["amount"],
             f"竞标撤标退款：出价 #{offer_id}，{offer['amount']}"),
        )
    _audit(request, "航线竞标撤标", actor=user, target_type="bid_offer", target_id=offer_id,
           detail=f"退回冻结 {offer['amount']}")
    return {"ok": True, "message": f"已撤标，{offer['amount']} 已退回航司余额"}


@router.post("/settle")
def settle_tenders(request: Request, user: dict = Depends(require_auth)):
    """结算所有已截止的招标，幂等；定时任务/任意登录用户/管理员都可以触发"""
    settled = []
    with get_conn() as conn:
        _begin_write(conn)
        now = _now(conn)
        due = conn.execute(
            "SELECT id FROM bid_tenders WHERE status = 'open' AND closes_at <= ? ORDER BY id",
            (now,),
        ).fetchall()
        for row in due:
            result = _settle_one(conn, row["id"], now)
            if result:
                settled.append(result)
    for s in settled:
        _audit(request, "航线竞标结算", actor=user, target_type="bid_tender",
               target_id=s["tenderId"], detail=f"{s['dep']}-{s['arr']} · 中标 {s['winnerName'] or '无'} · {s['price']}")
        if s["winnerUserId"]:
            notify_user(
                s["winnerUserId"], "航线竞标中标通知",
                f"你在 {s['dep']}-{s['arr']} 的竞标中以 {s['price']} 中标，"
                f"航线已加入「{s['winnerName']}」的航线网络，冻结资金已作为航线费用结算。",
            )
            # 成就钩子：事务外调用，内部另开连接
            check_achievements(s["winnerUserId"], "bid_won")
    return {"ok": True, "settled": settled, "count": len(settled), "serverNow": now,
            "message": f"已结算 {len(settled)} 条招标" if settled else "没有到期的招标"}


def _settle_one(conn, tender_id: int, now: str) -> dict | None:
    """结算单条招标，调用方已持有写事务；抢占状态失败返回 None"""
    cur = conn.execute(
        "UPDATE bid_tenders SET status = 'settled', settled_at = ?"
        " WHERE id = ? AND status = 'open' AND closes_at <= ?",
        (now, tender_id, now),
    )
    if cur.rowcount == 0:
        return None
    t = conn.execute("SELECT * FROM bid_tenders WHERE id = ?", (tender_id,)).fetchone()
    offers = conn.execute(
        "SELECT * FROM bid_offers WHERE tender_id = ? AND status = 'active'"
        " ORDER BY amount DESC, id ASC",
        (tender_id,),
    ).fetchall()
    winner = offers[0] if offers else None

    if winner:
        # 中标者的钱不再退回：冻结时已记支出，这里只把出价置为 won 并把航线入网
        conn.execute(
            "UPDATE bid_offers SET status = 'won', settled_at = ? WHERE id = ?",
            (now, winner["id"]),
        )
        conn.execute(
            "INSERT INTO airline_routes (airline_id, flight_no, dep, arr, distance_nm, base_salary)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (winner["airline_id"], t["flight_no"], t["dep"], t["arr"],
             t["distance_nm"], t["base_salary"]),
        )
        winner_name = conn.execute(
            "SELECT name FROM airlines WHERE id = ?", (winner["airline_id"],)
        ).fetchone()["name"]
        conn.execute(
            "UPDATE bid_tenders SET winner_airline_id = ?, winner_offer_id = ?, settle_price = ?"
            " WHERE id = ?",
            (winner["airline_id"], winner["id"], winner["amount"], tender_id),
        )
    else:
        winner_name = ""

    # 其余在标出价全额退回，含同一航司的其它历史在标记录，理论上只有一条
    for o in offers:
        if winner and o["id"] == winner["id"]:
            continue
        _refund_offer(conn, o, "竞标未中标退款")

    return {
        "tenderId": tender_id,
        "dep": t["dep"],
        "arr": t["arr"],
        "winnerName": winner_name,
        "winnerUserId": winner["user_id"] if winner else 0,
        "price": winner["amount"] if winner else 0,
        "refunded": len(offers) - (1 if winner else 0),
    }
