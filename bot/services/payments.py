"""Донат: выдача покупок за Telegram Stars и трата кристаллов."""
from __future__ import annotations

import random

from ..data.shop import CHEST_ODDS, CRYSTAL_PACKS, CRYSTAL_SHOP, PREMIUM_PLANS, STARTER_PACK
from ..utils.fmt import now
from . import prices, arena, idle, items as items_svc, players


def payload_for(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def resolve(payload: str) -> dict | None:
    """payload -> описание товара (title, stars) или None, если payload неизвестен."""
    kind, _, key = payload.partition(":")
    if kind == "pack" and key in CRYSTAL_PACKS:
        d = CRYSTAL_PACKS[key]
        return {"kind": kind, "key": key, "title": d["title"], "stars": prices.stars(kind, key, d["stars"]),
                "desc": f"{d['crystals']} кристаллов для игры"}
    if kind == "prem" and key in PREMIUM_PLANS:
        d = PREMIUM_PLANS[key]
        return {"kind": kind, "key": key, "title": d["title"], "stars": prices.stars(kind, key, d["stars"]),
                "desc": f"Премиум-бонусы на {d['days']} дней + {d['crystals']} кристаллов"}
    if kind == "starter" and key == STARTER_PACK["key"]:
        d = STARTER_PACK
        return {"kind": kind, "key": key, "title": d["title"], "stars": prices.stars(kind, key, d["stars"]),
                "desc": "Эпическая вещь, золото, кристаллы и 3 дня премиума (один раз)"}
    return None


async def can_buy(q, uid: int, payload: str) -> tuple[bool, str]:
    info = resolve(payload)
    if not info:
        return False, "Товар не найден."
    if info["kind"] == "starter":
        p = await players.get(q, uid)
        if p["starter_bought"]:
            return False, "Набор новичка уже куплен."
    return True, ""


async def grant(db, uid: int, payload: str, charge_id: str, stars: int) -> dict:
    """Выдать купленное. Идемпотентно по charge_id (повторная доставка не выдаст дважды)."""
    async with db.transaction() as tx:
        if await tx.one("SELECT 1 FROM payments WHERE charge_id=?", (charge_id,)):
            return {"ok": True, "duplicate": True}
        info = resolve(payload)
        await tx.execute("INSERT INTO payments(charge_id, user_id, payload, stars, created_at) VALUES(?,?,?,?,?)",
                         (charge_id, uid, payload, stars, now()))
        if not info:
            return {"ok": False, "msg": "unknown payload"}
        out: dict = {"ok": True, "info": info}
        if info["kind"] == "pack":
            d = CRYSTAL_PACKS[info["key"]]
            await players.add(tx, uid, crystals=d["crystals"])
            out["crystals"] = d["crystals"]
        elif info["kind"] == "prem":
            d = PREMIUM_PLANS[info["key"]]
            await players.add(tx, uid, crystals=d["crystals"])
            out["until"] = await players.extend_premium(tx, uid, d["days"])
            out["crystals"], out["days"] = d["crystals"], d["days"]
        elif info["kind"] == "starter":
            d = STARTER_PACK
            p = await players.get(tx, uid)
            await players.add(tx, uid, crystals=d["crystals"], gold=d["gold"], essence=d["essence"], potions=d["potions"])
            out["until"] = await players.extend_premium(tx, uid, d["premium_days"])
            item = items_svc.roll_item(max(5, p["level"]), rarity=d["item"], slot="weapon")
            await items_svc.create(tx, uid, item)
            await tx.execute("UPDATE players SET starter_bought=1 WHERE user_id=?", (uid,))
            out.update(crystals=d["crystals"], gold=d["gold"], item=item, days=d["premium_days"])
        return out


async def spend_crystals(db, uid: int, key: str, rng: random.Random = random) -> dict:
    meta = CRYSTAL_SHOP.get(key)
    if not meta:
        return {"ok": False, "msg": "Товар не найден."}
    price = prices.cost(key, meta["cost"])
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if key == "arena" and arena.tries_left(p) >= arena.tries_limit(p) + 10:
            return {"ok": False, "msg": "Слишком много попыток."}
        if not await players.spend(tx, uid, crystals=price):
            return {"ok": False, "msg": "Не хватает кристаллов.", "need": price}
        out: dict = {"ok": True, "title": meta["title"], "cost": price}
        if key == "energy":
            await players.fill_energy(tx, uid)
        elif key in ("warp4", "warp24"):
            out["warp"] = await idle.timewarp(tx, uid, 4 if key == "warp4" else 24)
        elif key == "arena":
            await arena.add_try(tx, uid)
        elif key == "potions":
            await players.add(tx, uid, potions=5)
        elif key in CHEST_ODDS:
            rarity = items_svc.roll_rarity(rng, odds=CHEST_ODDS[key])
            item = items_svc.roll_item(max(1, p["level"]), rarity=rarity, rng=rng)
            item["id"] = await items_svc.create(tx, uid, item)
            out["item"] = item
        return out
