"""Игрок: создание, валюты, энергия, уровень, характеристики."""
from __future__ import annotations

from ..data import balance as B
from ..utils.fmt import now
from . import formulas

CURRENCIES = {"gold", "crystals", "essence", "marks", "potions"}


async def get(q, uid: int) -> dict | None:
    return await q.one("SELECT * FROM players WHERE user_id=?", (uid,))


async def create(q, user_id: int, username: str | None, name: str, cls: str, ref_by: int | None = None) -> dict:
    t = now()
    await q.execute(
        "INSERT INTO players(user_id, username, name, cls, energy, energy_ts, last_collect, ref_by, "
        "rating, created_at, last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, username, name, cls, B.ENERGY_MAX, t, t, ref_by, B.ARENA_START_RATING, t, t),
    )
    await q.execute("INSERT OR IGNORE INTO buildings(user_id, key, level) VALUES(?, 'mine', 1)", (user_id,))
    return await get(q, user_id)


async def touch(q, uid: int, username: str | None, name: str) -> None:
    await q.execute("UPDATE players SET username=?, name=?, last_seen=? WHERE user_id=?",
                    (username, name, now(), uid))


async def add(q, uid: int, **delta: int) -> None:
    """Начислить/списать валюту без проверки (баланс не уйдёт ниже нуля)."""
    sets, params = [], []
    for key, val in delta.items():
        if key not in CURRENCIES or not val:
            continue
        sets.append(f"{key}=MAX(0,{key}+?)")
        params.append(int(val))
        if key == "gold" and val > 0:
            sets.append("gold_total=gold_total+?")
            params.append(int(val))
    if not sets:
        return
    params.append(uid)
    await q.execute(f"UPDATE players SET {', '.join(sets)} WHERE user_id=?", params)


async def spend(q, uid: int, **cost: int) -> bool:
    """Атомарно списать валюту, если хватает. Вызывать внутри транзакции."""
    conds, sets, params = [], [], []
    for key, val in cost.items():
        if key not in CURRENCIES or val <= 0:
            continue
        sets.append(f"{key}={key}-?")
        conds.append(f"{key}>=?")
        params.append(int(val))
    if not sets:
        return True
    where_params = [int(v) for k, v in cost.items() if k in CURRENCIES and v > 0]
    n = await q.execute(
        f"UPDATE players SET {', '.join(sets)} WHERE user_id=? AND {' AND '.join(conds)}",
        params + [uid] + where_params,
    )
    return n == 1


# ---------------------------------------------------------------- премиум
def is_premium(p: dict) -> bool:
    return p["premium_until"] > now()


async def extend_premium(q, uid: int, days: int) -> float:
    row = await q.one("SELECT premium_until FROM players WHERE user_id=?", (uid,))
    start = max(now(), row["premium_until"]) if row else now()
    until = start + days * 86400
    await q.execute("UPDATE players SET premium_until=? WHERE user_id=?", (until, uid))
    return until


# ---------------------------------------------------------------- энергия
async def tavern_level(q, uid: int) -> int:
    return await q.scalar("SELECT level FROM buildings WHERE user_id=? AND key='tavern'", (uid,), 0)


def energy_max_for(tavern: int) -> int:
    return B.ENERGY_MAX + B.ENERGY_PER_TAVERN * tavern


def regen_seconds(tavern: int) -> float:
    return B.ENERGY_REGEN_SEC * (1 - min(0.6, B.ENERGY_REGEN_PER_TAVERN * tavern))


async def energy(q, p: dict) -> tuple[float, int, float]:
    """(текущая, максимум, секунд на 1 энергию)."""
    tav = await tavern_level(q, p["user_id"])
    mx, reg = energy_max_for(tav), regen_seconds(tav)
    cur = min(mx, p["energy"] + (now() - p["energy_ts"]) / reg) if p["energy"] < mx else p["energy"]
    return cur, mx, reg


async def spend_energy(tx, p: dict, cost: int) -> bool:
    cur, _mx, _reg = await energy(tx, p)
    if cur + 1e-9 < cost:
        return False
    await tx.execute("UPDATE players SET energy=?, energy_ts=? WHERE user_id=?", (cur - cost, now(), p["user_id"]))
    return True


async def fill_energy(q, uid: int) -> None:
    tav = await tavern_level(q, uid)
    await q.execute("UPDATE players SET energy=?, energy_ts=? WHERE user_id=?",
                    (energy_max_for(tav), now(), uid))


# ---------------------------------------------------------------- характеристики
async def equipped_items(q, uid: int) -> list[dict]:
    return await q.all("SELECT * FROM items WHERE owner_id=? AND equipped=1", (uid,))


async def derived(q, p: dict, items: list[dict] | None = None) -> dict:
    """Итоговые характеристики героя с учётом экипировки."""
    if items is None:
        items = await equipped_items(q, p["user_id"])
    st = formulas.base_stats(p["cls"], p["level"], p["marks"])
    idle_pct = 0
    for it in items:
        m = formulas.item_mult(it["plus"])
        st["atk"] += int(it["atk"] * m)
        st["def"] += int(it["def"] * m)
        st["hp"] += int(it["hp"] * m)
        idle_pct += it["idle"]
    st["idle_pct"] = idle_pct
    st["power"] = formulas.power(st)
    return st


# ---------------------------------------------------------------- уровень
async def add_xp(tx, uid: int, amount: int) -> dict:
    """Начислить опыт, обработать повышения уровня и реферальную награду.

    Возвращает {"level", "gained", "inviter"} — inviter = id пригласившего,
    если ему только что выдан бонус (нужно уведомить).
    """
    row = await tx.one("SELECT level, xp, ref_by, ref_rewarded FROM players WHERE user_id=?", (uid,))
    level, xp = row["level"], row["xp"] + max(0, int(amount))
    start_level = level
    while xp >= formulas.xp_needed(level):
        xp -= formulas.xp_needed(level)
        level += 1
    await tx.execute("UPDATE players SET level=?, xp=? WHERE user_id=?", (level, xp, uid))
    inviter = None
    if level >= B.REF_LEVEL_REQUIRED and row["ref_by"] and not row["ref_rewarded"]:
        await tx.execute("UPDATE players SET ref_rewarded=1 WHERE user_id=?", (uid,))
        if await get(tx, row["ref_by"]):
            await add(tx, row["ref_by"], **B.REF_BONUS_INVITER)
            inviter = row["ref_by"]
    return {"level": level, "gained": level - start_level, "inviter": inviter}


def display_name(p: dict) -> str:
    name = p.get("name") or "Герой"
    return ("👑 " if is_premium(p) else "") + name
