"""Арена: рейтинговые бои между игроками (асинхронно — соперник сражается «призраком»)."""
from __future__ import annotations

import random

from ..data import balance as B
from ..utils.fmt import now, today
from . import combat, players, quests


def tries_used(p: dict) -> int:
    return p["arena_tries"] if p["arena_day"] == today() else 0


def tries_limit(p: dict) -> int:
    return B.ARENA_TRIES_PREMIUM if players.is_premium(p) else B.ARENA_TRIES


def tries_left(p: dict) -> int:
    return max(0, tries_limit(p) - tries_used(p))


def elo_delta(ra: int, rb: int, score: float, k: int = B.ARENA_K) -> int:
    expected = 1 / (1 + 10 ** ((rb - ra) / 400))
    return round(k * (score - expected))


def simulate(a: dict, b: dict, rng: random.Random = random, max_rounds: int = 40) -> dict:
    """a и b: {"hp","atk","def","crit"}. Возвращает {"winner": "a"|"b", "rounds", "hp_a", "hp_b"}."""
    ha, hb = a["hp"], b["hp"]
    rounds = 0
    first_a = a["atk"] + a["def"] >= b["atk"] + b["def"]
    while ha > 0 and hb > 0 and rounds < max_rounds:
        rounds += 1
        order = ("a", "b") if first_a else ("b", "a")
        for who in order:
            if ha <= 0 or hb <= 0:
                break
            att, dfn = (a, b) if who == "a" else (b, a)
            dmg = combat.hit(att["atk"], dfn["def"], rng, lvl=(att.get("lvl", 1) + dfn.get("lvl", 1)) / 2)
            if rng.random() < att.get("crit", 0.0) + B.BASE_CRIT:
                dmg = int(dmg * B.CRIT_MULT)
            if who == "a":
                hb -= dmg
            else:
                ha -= dmg
    if ha > 0 and hb <= 0:
        winner = "a"
    elif hb > 0 and ha <= 0:
        winner = "b"
    else:
        winner = "a" if ha / a["hp"] >= hb / b["hp"] else "b"
    return {"winner": winner, "rounds": rounds, "hp_a": max(0, ha), "hp_b": max(0, hb)}


async def find_opponent(q, p: dict, rng: random.Random = random) -> dict | None:
    rows = await q.all(
        "SELECT * FROM players WHERE user_id!=? AND banned=0 AND last_seen>? "
        "ORDER BY ABS(rating-?) ASC, RANDOM() LIMIT 8",
        (p["user_id"], now() - 30 * 86400, p["rating"]))
    return rng.choice(rows) if rows else None


async def fight(db, uid: int, rng: random.Random = random) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if tries_left(p) <= 0:
            return {"ok": False, "msg": "Попытки на сегодня закончились."}
        me = await players.derived(tx, p)
        me["lvl"] = p["level"]
        opp = await find_opponent(tx, p, rng)
        if opp:
            ost = await players.derived(tx, opp)
            ost["lvl"] = opp["level"]
            opp_info = {"id": opp["user_id"], "name": opp["name"], "cls": opp["cls"], "level": opp["level"],
                        "rating": opp["rating"], "npc": False}
        else:  # на арене пока никого — тень игрока
            k = rng.uniform(0.9, 1.1)
            ost = {s: int(me[s] * k) for s in ("hp", "atk", "def")}
            ost["crit"] = 0.0
            ost["lvl"] = p["level"]
            opp_info = {"id": None, "name": "Тень арены", "cls": p["cls"], "level": p["level"],
                        "rating": p["rating"], "npc": True}
        sim = simulate(me, ost, rng)
        win = sim["winner"] == "a"
        delta = elo_delta(p["rating"], opp_info["rating"], 1.0 if win else 0.0)
        new_rating = max(0, p["rating"] + delta)
        used = tries_used(p) + 1
        await tx.execute("UPDATE players SET rating=?, arena_tries=?, arena_day=? WHERE user_id=?",
                         (new_rating, used, today(), uid))
        if opp and not opp_info["npc"]:
            d_delta = -round(delta / 2)
            await tx.execute("UPDATE players SET rating=MAX(0, rating+?) WHERE user_id=?", (d_delta, opp["user_id"]))
        gold = (100 + p["level"] * 20) if win else 30
        await players.add(tx, uid, gold=gold)
        await quests.progress(tx, uid, "arena", 1)
        await tx.execute(
            "INSERT INTO arena_log(attacker, defender, winner, delta, created_at) VALUES(?,?,?,?,?)",
            (uid, opp_info["id"], uid if win else opp_info["id"], delta, now()))
        return {"ok": True, "win": win, "delta": delta, "rating": new_rating, "gold": gold,
                "opp": opp_info, "sim": sim, "me": me, "tries_left": tries_limit(p) - used}


async def add_try(q, uid: int) -> None:
    """Выдать дополнительную попытку (уменьшаем счётчик использованных)."""
    p = await players.get(q, uid)
    used = tries_used(p)
    await q.execute("UPDATE players SET arena_tries=?, arena_day=? WHERE user_id=?", (used - 1, today(), uid))


async def leaderboard(q, n: int = 10) -> list[dict]:
    return await q.all(
        "SELECT user_id, name, cls, level, rating, premium_until FROM players WHERE banned=0 "
        "ORDER BY rating DESC, level DESC LIMIT ?", (n,))


async def rank_of(q, p: dict) -> int:
    return 1 + await q.scalar("SELECT COUNT(*) FROM players WHERE rating>? AND banned=0", (p["rating"],), 0)
