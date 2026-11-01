"""Idle-часть: постройки, офлайн-доход, тапы, перерождение."""
from __future__ import annotations

import random

from ..data import balance as B
from ..data.buildings import BUILDINGS, BUILDING_ORDER
from ..utils.fmt import now
from . import formulas, players, quests

# кэш силы тапа: чтобы не ходить в БД на каждый клик
_tap_cache: dict[int, tuple[float, int]] = {}


async def get_buildings(q, uid: int) -> dict[str, int]:
    rows = await q.all("SELECT key, level FROM buildings WHERE user_id=?", (uid,))
    levels = {k: 0 for k in BUILDING_ORDER}
    levels.update({r["key"]: r["level"] for r in rows})
    return levels


async def _guild_level(q, p: dict) -> int:
    if not p["guild_id"]:
        return 0
    return await q.scalar("SELECT level FROM guilds WHERE id=?", (p["guild_id"],), 0)


def multiplier(p: dict, idle_pct: int, guild_level: int) -> float:
    m = 1 + B.MARK_IDLE_BONUS * p["marks"]
    m *= 1 + idle_pct / 100
    m *= 1 + B.GUILD_IDLE_PER_LEVEL * min(guild_level, 30)
    if players.is_premium(p):
        m *= B.PREMIUM_IDLE_MULT
    return m


async def overview(q, p: dict) -> dict:
    """Уровни зданий, ставки дохода в час (с множителями) и лимит накопления."""
    uid = p["user_id"]
    blds = await get_buildings(q, uid)
    equipped = await players.equipped_items(q, uid)
    idle_pct = sum(it["idle"] for it in equipped)
    glevel = await _guild_level(q, p)
    mult = multiplier(p, idle_pct, glevel)
    rates = {"gold": 0.0, "xp": 0.0, "essence": 0.0}
    for key, lvl in blds.items():
        res = BUILDINGS[key]["res"]
        if res:
            rates[res] += formulas.building_rate(key, lvl) * mult
    cap = formulas.offline_cap_hours(blds["library"], players.is_premium(p))
    return {"blds": blds, "rates": rates, "mult": mult, "cap_h": cap, "idle_pct": idle_pct, "guild_level": glevel}


def _pending_from(p: dict, ov: dict) -> dict:
    hours = min(max(0.0, (now() - p["last_collect"]) / 3600), ov["cap_h"])
    return {
        "hours": hours,
        "gold": int(ov["rates"]["gold"] * hours),
        "xp": int(ov["rates"]["xp"] * hours),
        "essence": int(ov["rates"]["essence"] * hours),
        "full": hours >= ov["cap_h"] - 1e-9,
    }


async def pending(q, p: dict) -> tuple[dict, dict]:
    ov = await overview(q, p)
    return _pending_from(p, ov), ov


async def _collect(tx, p: dict) -> dict:
    ov = await overview(tx, p)
    pend = _pending_from(p, ov)
    await tx.execute("UPDATE players SET last_collect=? WHERE user_id=?", (now(), p["user_id"]))
    await players.add(tx, p["user_id"], gold=pend["gold"], essence=pend["essence"])
    lvl = {"level": p["level"], "gained": 0, "inviter": None}
    if pend["xp"]:
        lvl = await players.add_xp(tx, p["user_id"], pend["xp"])
    pend["levelup"] = lvl
    return pend


async def collect(db, uid: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        pend = await _collect(tx, p)
        if pend["gold"] or pend["xp"] or pend["essence"]:
            await quests.progress(tx, uid, "collect", 1)
        return pend


async def upgrade(db, uid: int, key: str) -> dict:
    if key not in BUILDINGS:
        return {"ok": False, "msg": "Неизвестная постройка."}
    meta = BUILDINGS[key]
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if p["level"] < meta["unlock"]:
            return {"ok": False, "msg": f"Откроется на уровне {meta['unlock']}."}
        blds = await get_buildings(tx, uid)
        cur = blds[key]
        if cur >= B.MAX_BUILDING_LEVEL:
            return {"ok": False, "msg": "Максимальный уровень."}
        collected = await _collect(tx, p)  # чтобы новая ставка не применилась задним числом
        cost = formulas.building_cost(key, cur)
        if not await players.spend(tx, uid, gold=cost):
            return {"ok": False, "msg": "Не хватает золота.", "cost": cost}
        await tx.execute(
            "INSERT INTO buildings(user_id, key, level) VALUES(?,?,1) "
            "ON CONFLICT(user_id, key) DO UPDATE SET level=buildings.level+1", (uid, key))
        await quests.progress(tx, uid, "upgrade", 1)
        _tap_cache.pop(uid, None)
        return {"ok": True, "level": cur + 1, "cost": cost, "collected": collected}


# состояние жилы хранится в памяти процесса (оно короткоживущее: после перезапуска жила «остывает»)
_vein: dict[int, list[float]] = {}   # uid -> [нагрев, время последнего удара, сломана до]


def vein_state(uid: int, cool: float = B.VEIN_COOL_PER_SEC) -> dict:
    """Текущее состояние жилы с учётом остывания."""
    heat, ts, broken_until = _vein.get(uid, [0.0, 0.0, 0.0])
    t = now()
    if broken_until and t >= broken_until:       # жила восстановилась сама
        heat, broken_until = 0.0, 0.0
    elif not broken_until and heat > 0:
        heat = max(0.0, heat - (t - ts) * cool)
    _vein[uid] = [heat, t if not broken_until else ts, broken_until]
    left = max(0.0, broken_until - t)
    return {"heat": heat, "max": B.VEIN_HEAT_MAX, "broken": left > 0, "left": left,
            "warn": heat >= B.VEIN_WARN_AT and left <= 0}


def repair_cost(level: int) -> int:
    return max(100, level * B.VEIN_REPAIR_PER_LEVEL)


async def repair(db, uid: int) -> dict:
    """Мгновенная починка за золото (иначе жила восстановится сама через VEIN_BROKEN_SECONDS)."""
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        st = vein_state(uid)
        if not st["broken"]:
            return {"ok": False, "msg": "Жила цела."}
        cost = repair_cost(p["level"])
        if not await players.spend(tx, uid, gold=cost):
            return {"ok": False, "msg": f"Нужно {cost} золота или подожди {int(st['left'])} с."}
    _vein[uid] = [0.0, now(), 0.0]
    return {"ok": True, "cost": cost}


async def tap(db, uid: int, rng: random.Random = random) -> dict:
    cached = _tap_cache.get(uid)
    if not cached or cached[0] < now():
        p = await players.get(db, uid)
        mine = await db.scalar("SELECT level FROM buildings WHERE user_id=? AND key='mine'", (uid,), 1)
        power = formulas.tap_power(p["level"], mine)
        power = int(power * (1 + B.MARK_IDLE_BONUS * p["marks"]) * (B.PREMIUM_IDLE_MULT if players.is_premium(p) else 1))
        cool = B.VEIN_COOL_PER_SEC * (1 + B.VEIN_COOL_PER_MINE_LVL * mine) * (B.VEIN_PREMIUM_COOL if players.is_premium(p) else 1)
        cached = (now() + 20, max(1, power), cool)
        _tap_cache[uid] = cached
    st = vein_state(uid, cached[2])
    if st["broken"]:
        return {"broken": True, "left": st["left"], "just_broken": False, "gain": 0, "crit": False, "taps": 0, "gold": 0, "heat": st["heat"]}
    heat = st["heat"] + B.VEIN_HEAT_PER_TAP
    if heat >= B.VEIN_HEAT_MAX:     # перегрев: этот удар обрушивает жилу и ничего не приносит
        _vein[uid] = [B.VEIN_HEAT_MAX, now(), now() + B.VEIN_BROKEN_SECONDS]
        return {"broken": True, "just_broken": True, "left": B.VEIN_BROKEN_SECONDS, "gain": 0, "crit": False,
                "taps": 0, "gold": 0, "heat": B.VEIN_HEAT_MAX}
    _vein[uid] = [heat, now(), 0.0]
    crit = rng.random() < 0.10
    gain = cached[1] * (5 if crit else 1)
    row = await db.one(
        "UPDATE players SET gold=gold+?, gold_total=gold_total+?, taps=taps+1 WHERE user_id=? RETURNING taps, gold",
        (gain, gain, uid))
    await quests.progress(db, uid, "tap", 1)
    return {"broken": False, "just_broken": False, "gain": gain, "crit": crit, "taps": row["taps"], "gold": row["gold"],
            "heat": heat, "warn": heat >= B.VEIN_WARN_AT}


async def timewarp(tx, uid: int, hours: float) -> dict:
    p = await players.get(tx, uid)
    ov = await overview(tx, p)
    gold, xp, ess = (int(ov["rates"][k] * hours) for k in ("gold", "xp", "essence"))
    await players.add(tx, uid, gold=gold, essence=ess)
    lvl = await players.add_xp(tx, uid, xp) if xp else {"level": p["level"], "gained": 0, "inviter": None}
    return {"gold": gold, "xp": xp, "essence": ess, "levelup": lvl}


# ------------------------------------------------------------------ перерождение
def rebirth_info(p: dict) -> dict:
    return {
        "can": p["level"] >= B.REBIRTH_MIN_LEVEL,
        "need": B.REBIRTH_MIN_LEVEL,
        "marks": formulas.rebirth_marks(p["level"]) if p["level"] >= B.REBIRTH_MIN_LEVEL else 0,
    }


async def rebirth(db, uid: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        info = rebirth_info(p)
        if not info["can"]:
            return {"ok": False, "need": info["need"]}
        marks = info["marks"]
        t = now()
        await tx.execute(
            "UPDATE players SET level=1, xp=0, gold=150, marks=marks+?, last_collect=?, energy=?, energy_ts=? "
            "WHERE user_id=?", (marks, t, B.ENERGY_MAX, t, uid))
        await tx.execute("DELETE FROM buildings WHERE user_id=?", (uid,))
        await tx.execute("INSERT INTO buildings(user_id, key, level) VALUES(?, 'mine', 1)", (uid,))
        _tap_cache.pop(uid, None)
        return {"ok": True, "marks": marks, "total": p["marks"] + marks}
