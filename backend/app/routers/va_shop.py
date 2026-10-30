"""航司专属商城：CEO 自定义奖品/预设奖品/定价，上限 50 万，成员钱包兑换，货款进公司账上。"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_auth
from ..mailer import notify_user
from ..ratelimit import enforce
from ..text import clean

router = APIRouter(prefix="/api/airlines", tags=["va-shop"])

# 单件奖品定价上限，CEO 自定，防刷钱的天花板
AIRLINE_SHOP_MAX_PRICE = 500000

# 奖品预设：现实航司里程商城常见的奖励类型，CEO 可一键选用后改价
SHOP_PRIZE_PRESETS = [
    {"name": "限量机模，1:200", "description": "本公司涂装限量飞机模型，实物奖励"},
    {"name": "航空主题纪念徽章套装", "description": "飞行生涯纪念徽章一套"},
    {"name": "贵宾休息室体验券", "description": "合作贵宾休息室单次体验"},
    {"name": "优先排班权，一次", "description": "下次连飞活动优先选择航班"},
    {"name": "定制飞行日志本", "description": "烫金公司 Logo 精装飞行日志"},
    {"name": "机长体验日邀请函", "description": "全动模拟机体验一次"},
    {"name": "公司年度纪念套装", "description": "年度纪念品礼盒"},
    {"name": "专属航运保险箱", "description": "公司联名收藏摆件"},
]
# 预设建议价，游戏货币：按现实奖品价值量级给的参考，CEO 可自行改，≤ 上限
SHOP_PRIZE_PRESET_PRICES = {
    "限量机模，1:200": 300000,
    "航空主题纪念徽章套装": 80000,
    "贵宾休息室体验券": 150000,
    "优先排班权，一次": 50000,
    "定制飞行日志本": 60000,
    "机长体验日邀请函": 500000,
    "公司年度纪念套装": 45000,
    "专属航运保险箱": 200000,
}


def _active_member(conn, airline_id: int, user_id: int):
    return conn.execute(
        "SELECT * FROM airline_members WHERE airline_id = ? AND user_id = ? AND status = 'active'",
        (airline_id, user_id),
    ).fetchone()


def _require_ceo(conn, airline_id: int, user_id: int):
    m = _active_member(conn, airline_id, user_id)
    if not m or m["role"] != "ceo":
        raise HTTPException(403, "仅航司 CEO 可执行该操作")
    return m


@router.get("/{airline_id}/shop/presets")
def prize_presets(airline_id: int, user: dict = Depends(require_auth)):
    """奖品预设，CEO 选填后可改价"""
    with get_conn() as conn:
        if not _active_member(conn, airline_id, user["id"]):
            raise HTTPException(403, "仅航司成员可查看")
    presets = [
        {**p, "price": SHOP_PRIZE_PRESET_PRICES.get(p["name"], 100000)}
        for p in SHOP_PRIZE_PRESETS
    ]
    return {"ok": True, "presets": presets, "maxPrice": AIRLINE_SHOP_MAX_PRICE}


class ItemBody(BaseModel):
    name: str = Field("", max_length=40)
    description: str = Field("", max_length=200)
    price: int = Field(0, ge=0)
    stock: int = Field(-1, ge=-1, le=9999)


def _check_price(price: int):
    if price > AIRLINE_SHOP_MAX_PRICE:
        raise HTTPException(400, f"奖品价格最高 {AIRLINE_SHOP_MAX_PRICE}")


@router.post("/{airline_id}/shop/items")
def create_item(airline_id: int, body: ItemBody, request: Request,
                      user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        _check_price(body.price)
        name = clean(body.name, 40)
        if len(name) < 2:
            raise HTTPException(400, "奖品名称至少 2 个字")
        cur = conn.execute(
            "INSERT INTO airline_shop_items (airline_id, name, description, price, stock, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (airline_id, name, clean(body.description, 200), body.price, body.stock, user["id"]),
        )
    log_event("airline", "上架航司商城奖品", actor=user, target_type="va_shop_item",
              target_id=cur.lastrowid, detail=f"{name} · {body.price}")
    return {"ok": True, "id": cur.lastrowid, "message": "奖品已上架"}


@router.put("/{airline_id}/shop/items/{item_id}")
def update_item(airline_id: int, item_id: int, body: ItemBody,
                      user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        _check_price(body.price)
        item = conn.execute(
            "SELECT * FROM airline_shop_items WHERE id = ? AND airline_id = ?",
            (item_id, airline_id),
        ).fetchone()
        if not item:
            raise HTTPException(404, "奖品不存在")
        conn.execute(
            "UPDATE airline_shop_items SET name = ?, description = ?, price = ?, stock = ? WHERE id = ?",
            (clean(body.name, 40), clean(body.description, 200), body.price, body.stock, item_id),
        )
    return {"ok": True, "message": "奖品已更新"}


@router.delete("/{airline_id}/shop/items/{item_id}")
def delete_item(airline_id: int, item_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        conn.execute(
            "UPDATE airline_shop_items SET active = 0 WHERE id = ? AND airline_id = ?",
            (item_id, airline_id),
        )
    return {"ok": True, "message": "奖品已下架"}


@router.get("/{airline_id}/shop/items")
def list_items(airline_id: int, user: dict = Depends(require_auth)):
    """成员：可兑换奖品列表，含剩余限量与我的兑换状态"""
    with get_conn() as conn:
        if not _active_member(conn, airline_id, user["id"]):
            raise HTTPException(403, "仅航司成员可查看航司商城")
        items = conn.execute(
            "SELECT * FROM airline_shop_items WHERE airline_id = ? AND active = 1 ORDER BY price ASC, id",
            (airline_id,),
        ).fetchall()
        sold = {
            r["item_id"]: r["c"] for r in conn.execute(
                "SELECT item_id, COUNT(*) c FROM airline_shop_orders"
                " WHERE airline_id = ? AND status != 'cancelled' GROUP BY item_id",
                (airline_id,),
            ).fetchall()
        }
        mine = {
            r["item_id"] for r in conn.execute(
                "SELECT item_id FROM airline_shop_orders"
                " WHERE airline_id = ? AND user_id = ? AND status != 'cancelled'",
                (airline_id, user["id"]),
            ).fetchall()
        }
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
    out = []
    for it in items:
        d = dict(it)
        d["sold"] = sold.get(it["id"], 0)
        d["remaining"] = None if it["stock"] < 0 else max(0, it["stock"] - d["sold"])
        d["owned"] = it["id"] in mine
        out.append(d)
    return {"ok": True, "items": out, "balance": w["balance"] if w else 0,
            "maxPrice": AIRLINE_SHOP_MAX_PRICE}


@router.post("/{airline_id}/shop/buy/{item_id}")
def buy_item(airline_id: int, item_id: int, request: Request,
                   user: dict = Depends(require_auth)):
    enforce(request, "va-shop-buy", 10, 3600)
    with get_conn() as conn:
        if not _active_member(conn, airline_id, user["id"]):
            raise HTTPException(403, "仅航司成员可兑换")
        item = conn.execute(
            "SELECT * FROM airline_shop_items WHERE id = ? AND airline_id = ? AND active = 1",
            (item_id, airline_id),
        ).fetchone()
        if not item:
            raise HTTPException(404, "奖品不存在或已下架")

        mine = conn.execute(
            "SELECT 1 FROM airline_shop_orders WHERE item_id = ? AND user_id = ? AND status != 'cancelled'",
            (item_id, user["id"]),
        ).fetchone()
        if mine:
            raise HTTPException(400, "该奖品每人限兑一份")

        # 并发扣款防护：原子条件扣款，余额不足时 rowcount=0
        cur_w = conn.execute(
            "UPDATE wallets SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
            (item["price"], user["id"], item["price"]),
        )
        if cur_w.rowcount == 0:
            raise HTTPException(400, "余额不足")

        # 限量库存原子扣减，stock 为负数表示无限量，跳过该步
        if item["stock"] is not None and item["stock"] >= 0:
            cur_s = conn.execute(
                "UPDATE airline_shop_items SET stock = stock - 1 WHERE id = ? AND stock > 0",
                (item_id,),
            )
            if cur_s.rowcount == 0:
                raise HTTPException(400, "该奖品已售罄")

        # 钱包扣款 → 货款进公司账上，账本记收入 → 生成待发放订单
        conn.execute("UPDATE airlines SET balance = balance + ? WHERE id = ?", (item["price"], airline_id))
        conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note)"
            " VALUES (?, ?, 'revenue', ?)",
            (airline_id, item["price"], f"商城兑换：{item['name']}"),
        )
        conn.execute(
            "INSERT INTO wallet_records (user_id, amount, type, note)"
            " VALUES (?, ?, 'purchase', ?)",
            (user["id"], -item["price"], f"兑换 {item['name']}"),
        )
        # 重复兑换兜底：依赖 database.py 的 UNIQUE user_id, item_id 约束
        #前置的 mine 查询存在竞态窗口，并发双兑换由约束拦下
        try:
            cur = conn.execute(
                "INSERT INTO airline_shop_orders (airline_id, item_id, user_id, price)"
                " VALUES (?, ?, ?, ?)",
                (airline_id, item_id, user["id"], item["price"]),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "你已兑换过该奖品")
    log_event("airline", "兑换航司商城奖品", actor=user, target_type="va_shop_item",
              target_id=item_id, detail=f"{item['name']} · {item['price']}")
    return {"ok": True, "orderId": cur.lastrowid, "message": f"已兑换「{item['name']}」，等待公司发放"}


@router.get("/{airline_id}/shop/orders")
def list_orders(airline_id: int, scope: str = "mine", user: dict = Depends(require_auth)):
    with get_conn() as conn:
        m = _active_member(conn, airline_id, user["id"])
        is_ceo = bool(m) and m["role"] == "ceo"
        where, args = "o.airline_id = ?", [airline_id]
        if not (is_ceo and scope == "all"):
            where += " AND o.user_id = ?"
            args.append(user["id"])
        rows = conn.execute(
            f"SELECT o.*, i.name AS item_name, u.username, u.cid FROM airline_shop_orders o"
            f" JOIN airline_shop_items i ON i.id = o.item_id"
            f" JOIN users u ON u.id = o.user_id WHERE {where} ORDER BY o.id DESC LIMIT 200",
            args,
        ).fetchall()
    return {"ok": True, "orders": [dict(x) for x in rows]}


class OrderActionBody(BaseModel):
    action: str = Field("", max_length=12)


@router.post("/{airline_id}/shop/orders/{order_id}/handle")
def handle_order(airline_id: int, order_id: int, body: OrderActionBody,
                       request: Request, user: dict = Depends(require_auth)):
    """CEO 处理兑换订单：deliver=发放 / cancel=取消并退款"""
    if body.action not in ("deliver", "cancel"):
        raise HTTPException(400, "无效操作")
    with get_conn() as conn:
        _require_ceo(conn, airline_id, user["id"])
        o = conn.execute(
            "SELECT * FROM airline_shop_orders WHERE id = ? AND airline_id = ?",
            (order_id, airline_id),
        ).fetchone()
        if not o:
            raise HTTPException(404, "订单不存在")
        if o["status"] != "pending":
            raise HTTPException(400, "该订单已处理")

        # 奖品名与航司名：通知邮件要用
        item = conn.execute(
            "SELECT name FROM airline_shop_items WHERE id = ?", (o["item_id"],)
        ).fetchone()
        item_name = item["name"] if item else f"奖品#{o['item_id']}"
        al = conn.execute("SELECT name FROM airlines WHERE id = ?", (airline_id,)).fetchone()

        if body.action == "deliver":
            conn.execute(
                "UPDATE airline_shop_orders SET status = 'delivered',"
                " handled_by = ?, handled_at = datetime('now','localtime') WHERE id = ?",
                (user["id"], order_id),
            )
            log_event("airline", "发放航司商城奖品", actor=user, target_type="va_shop_order",
                      target_id=order_id, detail=f"订单 {order_id}")
            notify_user(
                o["user_id"], "商城奖品已发放",
                f"你在「{al['name']}」商城兑换的「{item_name}」已由公司发放，请注意查收。",
            )
            return {"ok": True, "message": "已标记发放"}

        # 取消：退款给成员，货款从公司账上退回
        conn.execute(
            "UPDATE airline_shop_orders SET status = 'cancelled',"
            " handled_by = ?, handled_at = datetime('now','localtime') WHERE id = ?",
            (user["id"], order_id),
        )
        conn.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (o["price"], o["user_id"]))
        # 退款流水：与兑换时的 purchase 流水对称，保证钱包明细可对账
        conn.execute(
            "INSERT INTO wallet_records (user_id, amount, type, note)"
            " VALUES (?, ?, 'refund', ?)",
            (o["user_id"], o["price"], f"商城兑换退款，订单 {order_id}"),
        )
        conn.execute("UPDATE airlines SET balance = balance - ? WHERE id = ?", (o["price"], airline_id))
        conn.execute(
            "INSERT INTO airline_ledger (airline_id, amount, type, note)"
            " VALUES (?, ?, 'expense', ?)",
            (airline_id, -o["price"], f"商城兑换取消退款，订单 {order_id}"),
        )
        log_event("airline", "取消航司商城兑换并退款", actor=user, target_type="va_shop_order",
                  target_id=order_id, detail=f"订单 {order_id} · 退 {o['price']}")
        notify_user(
            o["user_id"], "商城兑换已取消并退款",
            f"你在「{al['name']}」商城兑换的「{item_name}」已被公司取消，"
            f"{o['price']} 游戏币已退回你的钱包。",
        )
        return {"ok": True, "message": "已取消并退款"}
