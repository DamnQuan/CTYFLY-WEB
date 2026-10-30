"""二手飞机市场：航司之间整机转让，含手续费与成交流水

一次成交必须在**同一个事务**里完成四件事，任何一步失败整体回滚：
    ① 抢下挂牌，条件更新 status='listed' → 'sold'，并发时只有一方成功
    ② 扣买家航司余额，原子条件 UPDATE，余额不足 rowcount=0
    ③ 飞机所有权转移，条件 UPDATE，必须仍是卖家的可用飞机
    ④ 加卖家航司余额，扣手续费并写双方账本 + market_trades 成交流水

为什么每一处都用「条件 UPDATE + rowcount 判定」而不是「先 SELECT 再 UPDATE」：
SQLite 的读是不阻塞写的，两个请求可能同时读到 status='listed'、都读到买家余额够，
然后各自扣款 —— 一个事务用条件更新把「判定」和「写入」压成一条语句，判据失效时
rowcount=0，业务层据此回滚，天然挡掉双花与重复售出。

为什么开头要 BEGIN IMMEDIATE：
默认事务是 DEFERRED，写锁要到第一条写语句才拿。本事务是「先读后写」，
DEFERRED 下两个事务可能都先拿到读锁、随后同时想升级写锁，SQLite 会让其中一个
直接返回 SQLITE_BUSY，不重试—— 表现为随机的 500。用 IMMEDIATE 在事务开始时
就排他拿写锁，冲突方在 timeout 10s 内等待，语义等价于串行的记账队列。

账本口径，与 wallet.py 一致：amount 带符号，收入为正、支出为负；
改 airlines.balance 的每一条都必须在同事务里写一条 airline_ledger，
否则启动自检 ledger invariant，main._check_ledger_invariant 会报警。
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth
from ..ratelimit import enforce
from ..requestinfo import client_ip_from_request, user_agent
from ..text import clean

from .achievements import check_achievements
from .airlines import FLEET_CATALOG, _require_ceo

router = APIRouter(prefix="/api/market", tags=["market"])

# 硬编码分页：页码只做钳制，分页大小永远由服务端决定，红线：无用户可控的分页参数
MARKET_PAGE_SIZE = 12
MARKET_MAX_PAGE = 2000

# 成交手续费，百分比：从卖家到账里扣，买家实付就是挂牌价 —— 手续费不额外加价
MARKET_FEE_RATE = 5

# 挂牌价相对目录价的区间，防 1 游戏币刷机、也防离谱高价当洗钱通道
PRICE_MIN_RATIO = 0.10
PRICE_MAX_RATIO = 1.50


def _begin_write(conn) -> None:
    """开一个「立即写」事务；拿不到写锁时给 409 而不是 500"""
    if conn.in_transaction:
        return
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise HTTPException(409, "市场当前繁忙，请稍后重试") from exc


def _audit(request: Request, action: str, *, actor, target_type: str, target_id,
           detail: str) -> None:
    log_event("airline", action, actor=actor, target_type=target_type, target_id=target_id,
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))


def _airline_row(conn, airline_id: int):
    row = conn.execute(
        "SELECT id, icao, name, balance, hub FROM airlines WHERE id = ?", (airline_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "虚拟航司不存在")
    return row


def _price_bounds(aircraft: str) -> tuple[int, int]:
    """挂牌价区间：按机型目录价折算，目录价锚点见 airlines.FLEET_CATALOG"""
    spec = FLEET_CATALOG.get(aircraft)
    if not spec:
        return 1000, 10000000
    base = spec["price"] * PRICE_MAX_RATIO
    return max(1000, int(spec["price"] * PRICE_MIN_RATIO)), int(base)


def _row_to_view(row) -> dict:
    d = dict(row)
    ok_price = FLEET_CATALOG.get(d.get("aircraft"))
    d["priceRatio"] = round(d["price"] / ok_price["price"], 3) if ok_price else None
    d["sellerReceived"] = d["price"] - d["fee"] if d.get("fee") else d["price"]
    return d


class ListingBody(BaseModel):
    airlineId: int = Field(..., ge=1)
    fleetId: int = Field(..., ge=1)
    price: int = Field(..., ge=0, le=100000000)
    conditionPct: int = Field(90, ge=10, le=100)
    description: str = Field("", max_length=200)


class BuyBody(BaseModel):
    airlineId: int = Field(..., ge=1)


@router.get("")
def list_market(page: int = 1, aircraft: str = "", sort: str = "new",
                user: dict = Depends(require_auth)):
    """在售挂牌列表，分页大小硬编码，page 只做钳制"""
    page = max(1, min(int(page or 1), MARKET_MAX_PAGE))
    offset = (page - 1) * MARKET_PAGE_SIZE

    where = ["m.status = 'listed'"]
    params: list = []
    if aircraft:
        where.append("m.aircraft = ?")
        params.append(aircraft.strip().upper())
    # 排序白名单：绝不把用户字符串拼进 ORDER BY
    order = {
        "new": "m.id DESC",
        "price_asc": "m.price ASC, m.id DESC",
        "price_desc": "m.price DESC, m.id DESC",
        "condition": "m.condition_pct DESC, m.id DESC",
    }.get(sort, "m.id DESC")
    where_sql = " AND ".join(where)

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM market_listings m WHERE {where_sql}", params
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT m.*, a.name AS seller_airline_name, a.icao AS seller_icao,"
            " u.username AS seller_name"
            " FROM market_listings m"
            " JOIN airlines a ON a.id = m.seller_airline_id"
            " JOIN users u ON u.id = m.seller_id"
            f" WHERE {where_sql} ORDER BY {order} LIMIT {MARKET_PAGE_SIZE} OFFSET ?",
            (*params, offset),
        ).fetchall()
        my_airlines = [
            dict(r)
            for r in conn.execute(
                "SELECT a.id, a.name, a.icao, a.balance, m.role FROM airline_members m"
                " JOIN airlines a ON a.id = m.airline_id"
                " WHERE m.user_id = ? AND m.status = 'active' ORDER BY a.id",
                (user["id"],),
            )
        ]
        counts = [
            {"aircraft": r["aircraft"], "count": r["c"]}
            for r in conn.execute(
                "SELECT aircraft, COUNT(*) AS c FROM market_listings WHERE status = 'listed'"
                " GROUP BY aircraft ORDER BY c DESC"
            )
        ]
    return {
        "ok": True,
        "total": total,
        "page": page,
        "pageSize": MARKET_PAGE_SIZE,
        "feeRate": MARKET_FEE_RATE,
        "items": [_row_to_view(r) for r in rows],
        "myAirlines": my_airlines,
        "aircraftCounts": counts,
    }


@router.get("/my")
def my_market(user: dict = Depends(require_auth)):
    """我所在航司的在售/已售挂牌 + 我的买入记录，页面右侧面板"""
    with get_conn() as conn:
        aids = [
            r["airline_id"]
            for r in conn.execute(
                "SELECT airline_id FROM airline_members WHERE user_id = ? AND status = 'active'",
                (user["id"],),
            )
        ]
        if not aids:
            return {"ok": True, "listings": [], "purchases": [], "fleet": []}
        marks = ",".join("?" * len(aids))
        listings = conn.execute(
            "SELECT m.*, a.name AS seller_airline_name, a.icao AS seller_icao"
            " FROM market_listings m JOIN airlines a ON a.id = m.seller_airline_id"
            f" WHERE m.seller_airline_id IN ({marks})"
            f" ORDER BY m.id DESC LIMIT {MARKET_PAGE_SIZE}",
            tuple(aids),
        ).fetchall()
        purchases = conn.execute(
            "SELECT t.*, a.name AS buyer_airline_name FROM market_trades t"
            " JOIN airlines a ON a.id = t.buyer_airline_id"
            " WHERE t.buyer_airline_id IN (" + marks + ")"
            f" ORDER BY t.id DESC LIMIT {MARKET_PAGE_SIZE}",
            tuple(aids),
        ).fetchall()
        # 可挂牌的飞机：本航司可用、且当前没有在售挂牌
        fleet = conn.execute(
            "SELECT f.* FROM airline_fleet f"
            f" WHERE f.airline_id IN ({marks}) AND f.status = 'available'"
            " AND NOT EXISTS (SELECT 1 FROM market_listings m"
            "                 WHERE m.fleet_id = f.id AND m.status = 'listed')"
            " ORDER BY f.id DESC LIMIT 200",
            tuple(aids),
        ).fetchall()
    return {
        "ok": True,
        "listings": [_row_to_view(r) for r in listings],
        "purchases": [dict(r) for r in purchases],
        "fleet": [dict(r) for r in fleet],
    }


@router.post("/list")
def create_listing(body: ListingBody, request: Request, user: dict = Depends(require_auth)):
    """CEO 把本航司一架可用飞机挂牌出售"""
    enforce(request, "market-list", 10, 3600)
    with get_conn() as conn:
        _begin_write(conn)
        _require_ceo(conn, body.airlineId, user["id"])
        al = _airline_row(conn, body.airlineId)
        f = conn.execute(
            "SELECT * FROM airline_fleet WHERE id = ? AND airline_id = ?",
            (body.fleetId, body.airlineId),
        ).fetchone()
        if not f:
            raise HTTPException(404, "飞机不在本航司机队")
        if f["status"] != "available":
            raise HTTPException(400, "该飞机正在签派任务中，不能挂牌")
        lo, hi = _price_bounds(f["aircraft"])
        price = int(body.price)
        if price < lo or price > hi:
            spec = FLEET_CATALOG.get(f["aircraft"], {})
            raise HTTPException(
                400,
                f"挂牌价需在 {lo} ~ {hi} 之间，{spec.get('name', f['aircraft'])} 目录价 {spec.get('price', '未知')}",
            )
        try:
            cur = conn.execute(
                "INSERT INTO market_listings (seller_id, seller_airline_id, fleet_id, aircraft,"
                " aircraft_name, reg, price, fee_rate, condition_pct, location, description)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user["id"], body.airlineId, f["id"], f["aircraft"],
                    FLEET_CATALOG.get(f["aircraft"], {}).get("name", f["aircraft"]),
                    f["reg"], price, MARKET_FEE_RATE, body.conditionPct,
                    f["location"] or al["hub"] or "", clean(body.description, 200),
                ),
            )
        except sqlite3.IntegrityError:
            # uq_market_listings_fleet：同一架飞机只允许一条在售
            raise HTTPException(400, "该飞机已在市场挂牌中")
        listing_id = cur.lastrowid
    _audit(request, "二手市场挂牌", actor=user, target_type="market_listing", target_id=listing_id,
           detail=f"{f['aircraft']} {f['reg']} · {price}")
    return {"ok": True, "id": listing_id, "message": f"已挂牌：{f['aircraft']} {f['reg']} · {price}"}


@router.post("/{listing_id}/cancel")
def cancel_listing(listing_id: int, request: Request, user: dict = Depends(require_auth)):
    """卖家 CEO 下架自己的在售挂牌，条件更新，成交中的挂牌不会被下架"""
    enforce(request, "market-cancel", 20, 3600)
    with get_conn() as conn:
        _begin_write(conn)
        row = conn.execute("SELECT * FROM market_listings WHERE id = ?", (listing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "挂牌不存在")
        if row["status"] != "listed":
            raise HTTPException(400, "该挂牌已结束")
        _require_ceo(conn, row["seller_airline_id"], user["id"])
        cur = conn.execute(
            "UPDATE market_listings SET status = 'cancelled' WHERE id = ? AND status = 'listed'",
            (listing_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "该挂牌已被买走，无法下架")
    _audit(request, "二手市场下架", actor=user, target_type="market_listing", target_id=listing_id,
           detail=f"{row['aircraft']} {row['reg']}")
    return {"ok": True, "message": "已下架"}


@router.post("/{listing_id}/buy")
def buy_listing(listing_id: int, body: BuyBody, request: Request,
                user: dict = Depends(require_auth)):
    """买入挂牌飞机：扣买家 → 转机队 → 加卖家，扣手续费→ 置 sold，全程一个事务"""
    enforce(request, "market-buy", 20, 3600)

    buyer_airline = body.airlineId
    trade_id = 0
    listing = None
    seller_airline = 0
    seller_user = 0
    with get_conn() as conn:
        _begin_write(conn)                      # ① 先拿写锁，DEFERRED 会随机 BUSY
        _require_ceo(conn, buyer_airline, user["id"])
        buyer = _airline_row(conn, buyer_airline)

        listing = conn.execute(
            "SELECT * FROM market_listings WHERE id = ?", (listing_id,)
        ).fetchone()
        if not listing:
            raise HTTPException(404, "挂牌不存在")
        if listing["status"] != "listed":
            raise HTTPException(400, "该飞机已售出或已下架")
        if listing["seller_airline_id"] == buyer_airline:
            raise HTTPException(400, "不能购买本航司自己的飞机")

        price = int(listing["price"])
        fee = price * int(listing["fee_rate"]) // 100
        seller_received = price - fee
        seller_airline = listing["seller_airline_id"]
        seller_user = listing["seller_id"]

        # ② 抢占挂牌：并发只有一方 rowcount=1；失败方不碰任何资金
        cur = conn.execute(
            "UPDATE market_listings SET status = 'sold', buyer_id = ?, buyer_airline_id = ?,"
            " sold_price = ?, fee = ?, sold_at = datetime('now','localtime')"
            " WHERE id = ? AND status = 'listed'",
            (user["id"], buyer_airline, price, fee, listing_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "手慢了，这架飞机已被买走")

        # ③ 扣买家：条件原子 UPDATE —— 余额不足时 rowcount=0，整个事务回滚
        cur_w = conn.execute(
            "UPDATE airlines SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (price, buyer_airline, price),
        )
        if cur_w.rowcount == 0:
            raise HTTPException(
                400, f"航司余额不足：需要 {price}，当前 {buyer['balance']}"
            )

        # ④ 飞机所有权转移：必须仍是卖家的、且仍可用，挂牌后被签派/下架都会失败
        cur_f = conn.execute(
            "UPDATE airline_fleet SET airline_id = ?, status = 'available', location = ?"
            " WHERE id = ? AND airline_id = ? AND status = 'available'",
            (buyer_airline, buyer["hub"] or listing["location"] or "", listing["fleet_id"],
             seller_airline),
        )
        if cur_f.rowcount == 0:
            raise HTTPException(409, "这架飞机已不可交易，可能正在签派或已被转移")

        # ⑤ 卖家入账 + 双方账本 + 成交流水
        conn.execute(
            "UPDATE airlines SET balance = balance + ? WHERE id = ?",
            (seller_received, seller_airline),
        )
        conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note)"
            " VALUES (?, ?, 'expense', ?)",
            (buyer_airline, -price, f"二手购入 {listing['aircraft']} {listing['reg']}，挂牌 #{listing_id}"),
        )
        conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note)"
            " VALUES (?, ?, 'revenue', ?)",
            (seller_airline, seller_received,
             f"二手售出 {listing['aircraft']} {listing['reg']}，挂牌 #{listing_id}，手续费 {fee}"),
        )
        cur_t = conn.execute(
            "INSERT INTO market_trades (listing_id, fleet_id, seller_id, seller_airline_id,"
            " buyer_id, buyer_airline_id, aircraft, reg, price, fee, seller_received)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (listing_id, listing["fleet_id"], seller_user, seller_airline,
             user["id"], buyer_airline, listing["aircraft"], listing["reg"],
             price, fee, seller_received),
        )
        trade_id = cur_t.lastrowid
    # —— 事务已提交，with 退出时 commit：以下动作都不允许回滚已成交的飞机 ——

    _audit(request, "二手市场成交", actor=user, target_type="market_trade", target_id=trade_id,
           detail=f"{listing['aircraft']} {listing['reg']} · 成交 {price} · 手续费 {fee}"
                  f" · 卖家到账 {seller_received}")
    # 成就钩子：必须在事务外调用，内部另开连接，事务内会等写锁超时
    check_achievements(user["id"], "market_bought")
    check_achievements(seller_user, "market_sold")
    return {
        "ok": True,
        "tradeId": trade_id,
        "price": price,
        "fee": fee,
        "message": f"已买入 {listing['aircraft']} {listing['reg']}，成交价 {price}，手续费 {fee} 由卖家承担",
    }
