"""Рынок игроков: выставить предмет, купить, снять с продажи."""
from __future__ import annotations

from ..data import balance as B
from ..utils.fmt import now
from . import players


def tax_rate(seller: dict) -> float:
    return B.MARKET_TAX_PREMIUM if players.is_premium(seller) else B.MARKET_TAX


async def list_item(db, uid: int, item_id: int, price: int) -> dict:
    if price < 1 or price > B.MARKET_MAX_PRICE:
        return {"ok": False, "msg": f"Цена: от 1 до {B.MARKET_MAX_PRICE}."}
    async with db.transaction() as tx:
        item = await tx.one("SELECT * FROM items WHERE id=? AND owner_id=?", (item_id, uid))
        if not item:
            return {"ok": False, "msg": "Предмет не найден."}
        if item["equipped"]:
            return {"ok": False, "msg": "Сначала сними предмет."}
        if item["listed"]:
            return {"ok": False, "msg": "Уже на рынке."}
        n = await tx.scalar("SELECT COUNT(*) FROM market WHERE seller_id=?", (uid,), 0)
        if n >= B.MARKET_MAX_LISTINGS:
            return {"ok": False, "msg": f"Максимум {B.MARKET_MAX_LISTINGS} лотов одновременно."}
        await tx.execute("UPDATE items SET listed=1 WHERE id=?", (item_id,))
        lid = await tx.insert("INSERT INTO market(seller_id, item_id, price, created_at) VALUES(?,?,?,?)",
                              (uid, item_id, price, now()))
        return {"ok": True, "id": lid, "item": item}


async def cancel(db, uid: int, listing_id: int) -> dict:
    async with db.transaction() as tx:
        row = await tx.one("SELECT * FROM market WHERE id=? AND seller_id=?", (listing_id, uid))
        if not row:
            return {"ok": False, "msg": "Лот не найден."}
        await tx.execute("DELETE FROM market WHERE id=?", (listing_id,))
        await tx.execute("UPDATE items SET listed=0 WHERE id=?", (row["item_id"],))
        return {"ok": True}


async def browse(q, slot: str | None = None, page: int = 0, per: int = 5, exclude: int | None = None):
    cond, params = "1=1", []
    if slot:
        cond += " AND i.slot=?"
        params.append(slot)
    if exclude:
        cond += " AND m.seller_id!=?"
        params.append(exclude)
    total = await q.scalar(f"SELECT COUNT(*) FROM market m JOIN items i ON i.id=m.item_id WHERE {cond}", params, 0)
    rows = await q.all(
        f"SELECT m.id AS lid, m.price, m.seller_id, i.* FROM market m JOIN items i ON i.id=m.item_id "
        f"WHERE {cond} ORDER BY m.price ASC, m.id DESC LIMIT ? OFFSET ?", params + [per, page * per])
    return rows, total


async def get_listing(q, listing_id: int) -> dict | None:
    return await q.one(
        "SELECT m.id AS lid, m.price, m.seller_id, i.* FROM market m JOIN items i ON i.id=m.item_id WHERE m.id=?",
        (listing_id,))


async def my_listings(q, uid: int) -> list[dict]:
    return await q.all(
        "SELECT m.id AS lid, m.price, m.seller_id, i.* FROM market m JOIN items i ON i.id=m.item_id "
        "WHERE m.seller_id=? ORDER BY m.id DESC", (uid,))


async def buy(db, uid: int, listing_id: int) -> dict:
    async with db.transaction() as tx:
        row = await get_listing(tx, listing_id)
        if not row:
            return {"ok": False, "msg": "Лот уже продан или снят."}
        if row["seller_id"] == uid:
            return {"ok": False, "msg": "Нельзя купить свой лот."}
        if not await players.spend(tx, uid, gold=row["price"]):
            return {"ok": False, "msg": "Не хватает золота."}
        seller = await players.get(tx, row["seller_id"])
        tax = int(row["price"] * tax_rate(seller)) if seller else 0
        if seller:
            await players.add(tx, row["seller_id"], gold=row["price"] - tax)
        await tx.execute("DELETE FROM market WHERE id=?", (listing_id,))
        await tx.execute("UPDATE items SET owner_id=?, listed=0, equipped=0 WHERE id=?", (uid, row["id"]))
        return {"ok": True, "item": row, "seller_id": row["seller_id"], "price": row["price"], "tax": tax}
