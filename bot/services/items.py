"""Предметы: генерация, экипировка, продажа, усиление."""
from __future__ import annotations

import random

from ..data.items import (BASE_NAMES, ADJECTIVES, ENHANCE_CHANCE, MAX_PLUS, RARITIES, RARITY, RARITY_INDEX,
                          SLOT_ORDER, SUFFIXES)
from ..utils.fmt import now
from . import formulas, players


def roll_rarity(rng: random.Random = random, bonus: float = 0.0, min_index: int = 0,
                odds: dict[str, float] | None = None) -> str:
    """Выбор редкости. bonus повышает шансы старших редкостей."""
    if odds:
        keys = list(odds)
        return rng.choices(keys, weights=[odds[k] for k in keys])[0]
    weights = []
    for i, r in enumerate(RARITIES):
        w = r["weight"] * (1 + bonus * i) if i >= min_index else 0
        weights.append(w)
    return rng.choices([r["key"] for r in RARITIES], weights=weights)[0]


def roll_item(ilvl: int, rarity: str | None = None, slot: str | None = None,
              rng: random.Random = random, bonus: float = 0.0, min_index: int = 0) -> dict:
    ilvl = max(1, int(ilvl))
    rarity = rarity or roll_rarity(rng, bonus, min_index)
    slot = slot or rng.choice(SLOT_ORDER)
    m = RARITY[rarity]["mult"]
    var = lambda: rng.uniform(0.9, 1.1)  # noqa: E731
    atk = df = hp = idle = 0
    if slot == "weapon":
        atk = int((ilvl * 2.2 * m + 3) * var())
    elif slot == "armor":
        df = int((ilvl * 1.1 * m + 1) * var())
        hp = int(ilvl * 7 * m * var())
    elif slot == "ring":
        atk = int(ilvl * 1.0 * m * var())
        df = int(ilvl * 0.4 * m * var())
        hp = int(ilvl * 2 * m * var())
    else:  # amulet
        hp = int(ilvl * 5 * m * var())
        df = int(ilvl * 0.5 * m * var())
        idle = int(1 + RARITY_INDEX[rarity] * 2.5)
    name = f"{rng.choice(ADJECTIVES[rarity])} {rng.choice(BASE_NAMES[slot]).lower()}"
    if RARITY_INDEX[rarity] >= 3:
        name += f" {rng.choice(SUFFIXES)}"
    return {"name": name.capitalize(), "slot": slot, "rarity": rarity, "ilvl": ilvl,
            "atk": atk, "def": df, "hp": hp, "idle": idle}


async def create(q, uid: int, item: dict, equipped: int = 0) -> int:
    return await q.insert(
        "INSERT INTO items(owner_id, name, slot, rarity, ilvl, atk, def, hp, idle, equipped, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (uid, item["name"], item["slot"], item["rarity"], item["ilvl"], item["atk"], item["def"],
         item["hp"], item["idle"], equipped, now()),
    )


async def give_starter_kit(q, uid: int) -> None:
    for slot in ("weapon", "armor"):
        it = roll_item(1, rarity="common", slot=slot)
        it["name"] = "Рваный плащ" if slot == "armor" else "Ржавый меч"
        await create(q, uid, it, equipped=1)


async def get(q, uid: int, item_id: int) -> dict | None:
    return await q.one("SELECT * FROM items WHERE id=? AND owner_id=?", (item_id, uid))


async def list_inventory(q, uid: int, page: int = 0, per: int = 6) -> tuple[list[dict], int]:
    total = await q.scalar("SELECT COUNT(*) FROM items WHERE owner_id=?", (uid,), 0)
    rows = await q.all(
        "SELECT * FROM items WHERE owner_id=? ORDER BY equipped DESC, listed ASC, "
        "CASE rarity WHEN 'mythic' THEN 6 WHEN 'legendary' THEN 5 WHEN 'epic' THEN 4 WHEN 'rare' THEN 3 "
        "WHEN 'uncommon' THEN 2 ELSE 1 END DESC, ilvl DESC, id DESC LIMIT ? OFFSET ?",
        (uid, per, page * per),
    )
    return rows, total


async def equip(db, uid: int, item_id: int) -> tuple[bool, str]:
    async with db.transaction() as tx:
        it = await get(tx, uid, item_id)
        if not it:
            return False, "Предмет не найден."
        if it["listed"]:
            return False, "Предмет выставлен на рынок."
        await tx.execute("UPDATE items SET equipped=0 WHERE owner_id=? AND slot=? AND equipped=1", (uid, it["slot"]))
        await tx.execute("UPDATE items SET equipped=1 WHERE id=?", (item_id,))
    return True, "Надето."


async def unequip(db, uid: int, item_id: int) -> tuple[bool, str]:
    n = await db.execute("UPDATE items SET equipped=0 WHERE id=? AND owner_id=?", (item_id, uid))
    return (n == 1), ("Снято." if n else "Предмет не найден.")


async def sell(db, uid: int, item_id: int) -> tuple[bool, str, int]:
    async with db.transaction() as tx:
        it = await get(tx, uid, item_id)
        if not it:
            return False, "Предмет не найден.", 0
        if it["equipped"] or it["listed"]:
            return False, "Сначала сними предмет / сними с рынка.", 0
        price = formulas.sell_price(it)
        await tx.execute("DELETE FROM items WHERE id=?", (item_id,))
        await players.add(tx, uid, gold=price)
    return True, "Продано.", price


async def sell_junk(db, uid: int, max_rarity: str = "uncommon") -> tuple[int, int]:
    """Продать все неэкипированные предметы до указанной редкости включительно."""
    limit = RARITY_INDEX[max_rarity]
    async with db.transaction() as tx:
        rows = await tx.all("SELECT * FROM items WHERE owner_id=? AND equipped=0 AND listed=0", (uid,))
        junk = [r for r in rows if RARITY_INDEX[r["rarity"]] <= limit]
        total = sum(formulas.sell_price(r) for r in junk)
        for r in junk:
            await tx.execute("DELETE FROM items WHERE id=?", (r["id"],))
        await players.add(tx, uid, gold=total)
    return len(junk), total


async def enhance(db, uid: int, item_id: int, rng: random.Random = random) -> dict:
    async with db.transaction() as tx:
        it = await get(tx, uid, item_id)
        if not it:
            return {"ok": False, "msg": "Предмет не найден."}
        if it["plus"] >= MAX_PLUS:
            return {"ok": False, "msg": "Максимальное усиление."}
        gold, essence = formulas.enhance_cost(it)
        if not await players.spend(tx, uid, gold=gold, essence=essence):
            return {"ok": False, "msg": "Не хватает золота или эссенции.", "gold": gold, "essence": essence}
        chance = ENHANCE_CHANCE[it["plus"]]
        success = rng.random() < chance
        if success:
            await tx.execute("UPDATE items SET plus=plus+1 WHERE id=?", (item_id,))
        return {"ok": True, "success": success, "chance": chance, "plus": it["plus"] + (1 if success else 0),
                "gold": gold, "essence": essence}
