"""虚拟商城：商品浏览、购买、装备、我的订单"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import log_event
from ..database import get_conn
from ..deps import require_admin, require_auth
from ..text import clean

router = APIRouter(prefix="/api/shop", tags=["shop"])


def _require_airline_member(conn, user_id: int):
    """公共商城仅限已加入航司的成员，航司另有专属商城"""
    m = conn.execute(
        "SELECT 1 FROM airline_members WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchone()
    if not m:
        raise HTTPException(403, "公共商城仅限已加入航司的成员使用，可在虚拟航司页加入")


@router.get("/items")
def list_items(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_airline_member(conn, user["id"])
        rows = conn.execute(
            "SELECT * FROM shop_items WHERE active = 1 ORDER BY price ASC, id"
        ).fetchall()
        owned = {
            r["item_id"] for r in conn.execute(
                "SELECT item_id FROM shop_orders WHERE user_id = ?", (user["id"],)
            ).fetchall()
        }
        me = conn.execute(
            "SELECT equipped_title, equipped_badge FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    return {
        "ok": True,
        "items": [dict(r) for r in rows],
        "ownedIds": list(owned),
        "equippedTitle": me["equipped_title"] if me else "",
        "equippedBadge": me["equipped_badge"] if me else "",
    }


@router.post("/buy/{item_id}")
def buy_item(item_id: int, user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_airline_member(conn, user["id"])
        item = conn.execute(
            "SELECT * FROM shop_items WHERE id = ? AND active = 1", (item_id,)
        ).fetchone()
        if not item:
            raise HTTPException(404, "商品不存在或已下架")

        owned = conn.execute(
            "SELECT 1 FROM shop_orders WHERE user_id = ? AND item_id = ?",
            (user["id"], item_id),
        ).fetchone()
        if owned:
            raise HTTPException(400, "你已拥有该商品")

        # 原子扣费：条件更新防并发双花，先查后扣存在竞态窗口
        cur = conn.execute(
            "UPDATE wallets SET balance = balance - ?"
            " WHERE user_id = ? AND balance >= ?",
            (item["price"], user["id"], item["price"]),
        )
        if cur.rowcount == 0:
            w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
            raise HTTPException(400, f"余额不足，需要 {item['price']}，当前 {w['balance'] if w else 0}")
        # 扣款后回查真实余额，修复返回值恒为 0 的 bug
        w = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
        balance = w["balance"] if w else 0
        # 称号与徽章购买后自动装备，同类型旧装备自动卸下，可在商城手动切换
        is_title = item["type"] == "title"
        conn.execute(
            "UPDATE shop_orders SET equipped = 0 WHERE user_id = ? AND equipped = 1"
            " AND item_id IN (SELECT id FROM shop_items WHERE type = ?)",
            (user["id"], item["type"]),
        )
        # 重复购买兜底：依赖 database.py 的 UNIQUE user_id, item_id 约束
        #前置的 owned 查询存在竞态窗口，并发双购由约束拦下
        try:
            cur = conn.execute(
                "INSERT INTO shop_orders (user_id, item_id, price, equipped) VALUES (?, ?, ?, 1)",
                (user["id"], item_id, item["price"]),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "已拥有该商品")
        conn.execute(
            f"UPDATE users SET {'equipped_title' if is_title else 'equipped_badge'} = ? WHERE id = ?",
            (item["payload"], user["id"]),
        )
        conn.execute(
            "INSERT INTO wallet_records (user_id, amount, type, note)"
            " VALUES (?, ?, 'purchase', ?)",
            (user["id"], -item["price"], f"购买 {item['name']}"),
        )

    log_event("airline", "商城购买", actor=user, target_type="shop_item", target_id=item_id,
              detail=f"{item['name']} · {item['price']}")
    return {"ok": True, "message": f"已购买「{item['name']}」", "balance": balance}


@router.get("/orders")
def my_orders(user: dict = Depends(require_auth)):
    with get_conn() as conn:
        _require_airline_member(conn, user["id"])
        rows = conn.execute(
            "SELECT o.*, i.name AS item_name, i.type AS item_type, i.payload AS item_payload"
            " FROM shop_orders o JOIN shop_items i ON i.id = o.item_id"
            " WHERE o.user_id = ? ORDER BY o.id DESC",
            (user["id"],),
        ).fetchall()
        w = conn.execute("SELECT balance, total_hours FROM wallets WHERE user_id = ?", (user["id"],)).fetchone()
        me = conn.execute(
            "SELECT equipped_title, equipped_badge FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    return {
        "ok": True,
        "orders": [dict(r) for r in rows],
        "balance": w["balance"] if w else 0,
        "equippedTitle": me["equipped_title"] if me else "",
        "equippedBadge": me["equipped_badge"] if me else "",
    }


class EquipBody(BaseModel):
    order_id: int = Field(0, ge=0)


# 商品类型 -> 可装备的 users 表字段
EQUIP_FIELD = {"title": "equipped_title", "badge": "equipped_badge"}


@router.post("/equip")
def equip_item(body: EquipBody, user: dict = Depends(require_auth)):
    """装备/卸下称号或徽章，同一类型同时只能装备一件"""
    with get_conn() as conn:
        _require_airline_member(conn, user["id"])
        o = conn.execute(
            "SELECT o.*, i.type, i.payload, i.name FROM shop_orders o"
            " JOIN shop_items i ON i.id = o.item_id"
            " WHERE o.id = ? AND o.user_id = ?",
            (body.order_id, user["id"]),
        ).fetchone()
        if not o:
            raise HTTPException(404, "订单不存在")
        if o["type"] not in EQUIP_FIELD:
            raise HTTPException(400, "该商品类型不支持装备")
        field = EQUIP_FIELD[o["type"]]

        # 先卸下同类型当前装备
        conn.execute(
            "UPDATE shop_orders SET equipped = 0 WHERE user_id = ? AND equipped = 1"
            " AND item_id IN (SELECT id FROM shop_items WHERE type = ?)",
            (user["id"], o["type"]),
        )
        if o["equipped"]:
            conn.execute("UPDATE shop_orders SET equipped = 0 WHERE id = ?", (o["id"],))
            conn.execute(f"UPDATE users SET {field} = '' WHERE id = ?", (user["id"],))
            return {"ok": True, "message": f"已卸下「{o['name']}」"}
        conn.execute("UPDATE shop_orders SET equipped = 1 WHERE id = ?", (o["id"],))
        conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (o["payload"], user["id"]))
    return {"ok": True, "message": f"已装备「{o['name']}」"}


# ---------- 管理员：商品 CRUD ----------

shop_admin_router = APIRouter(prefix="/api/admin/shop", tags=["shop-admin"])


class ShopItemBody(BaseModel):
    name: str = Field("", max_length=60)
    description: str = Field("", max_length=200)
    price: int = Field(0, ge=0, le=1000000)
    type: str = Field("title", max_length=16)
    payload: str = Field("", max_length=100)
    active: bool = True


@shop_admin_router.get("/items")
def admin_list_items(_: dict = Depends(require_admin)):
    from ..database import get_conn as gc

    with gc() as conn:
        rows = conn.execute("SELECT * FROM shop_items ORDER BY id").fetchall()
    return {"ok": True, "items": [dict(r) for r in rows]}


@shop_admin_router.post("/items")
def admin_create_item(body: ShopItemBody, user: dict = Depends(require_admin)):
    name = clean(body.name, 60)
    if not name:
        raise HTTPException(400, "请填写商品名称")
    if body.type not in ("title", "badge"):
        raise HTTPException(400, "无效的商品类型")
    from ..database import get_conn as gc

    with gc() as conn:
        cur = conn.execute(
            "INSERT INTO shop_items (name, description, price, type, payload, active)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, clean(body.description, 200), body.price, body.type,
             clean(body.payload, 100), 1 if body.active else 0),
        )
    return {"ok": True, "id": cur.lastrowid}


@shop_admin_router.put("/items/{item_id}")
def admin_update_item(item_id: int, body: ShopItemBody, user: dict = Depends(require_admin)):
    from ..database import get_conn as gc

    with gc() as conn:
        if not conn.execute("SELECT 1 FROM shop_items WHERE id = ?", (item_id,)).fetchone():
            raise HTTPException(404, "商品不存在")
        conn.execute(
            "UPDATE shop_items SET name = ?, description = ?, price = ?, type = ?, payload = ?, active = ?"
            " WHERE id = ?",
            (clean(body.name, 60), clean(body.description, 200), body.price, body.type,
             clean(body.payload, 100), 1 if body.active else 0, item_id),
        )
    return {"ok": True}


@shop_admin_router.delete("/items/{item_id}")
def admin_delete_item(item_id: int, user: dict = Depends(require_admin)):
    from ..database import get_conn as gc

    with gc() as conn:
        conn.execute("UPDATE shop_items SET active = 0 WHERE id = ?", (item_id,))
    return {"ok": True, "message": "商品已下架"}
