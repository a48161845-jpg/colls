"""Админ-инструменты: статистика, выдача валют, баны."""
from __future__ import annotations

from ..utils.fmt import now
from . import players


DAY = 86400
SPARK = "▁▂▃▄▅▆▇█"


def spark(values: list[int]) -> str:
    top = max(values) if values else 0
    if top <= 0:
        return "▁" * len(values)
    return "".join(SPARK[min(7, int(v / top * 7.999))] for v in values)


async def _per_day(q, table: str, col: str, days: int = 7, extra: str = "", agg: str = "COUNT(*)") -> list[int]:
    """Значения за каждый из последних `days` дней (старые -> новые)."""
    t = now()
    out = []
    for i in range(days - 1, -1, -1):
        lo, hi = t - (i + 1) * DAY, t - i * DAY
        out.append(int(await q.scalar(f"SELECT COALESCE({agg},0) FROM {table} WHERE {col}>? AND {col}<=? {extra}", (lo, hi), 0)))
    return out


async def stats(q) -> dict:
    """Короткая сводка (используется и тестами; подробности — в report())."""
    t = now()
    return {
        "players": await q.scalar("SELECT COUNT(*) FROM players", (), 0),
        "active_24h": await q.scalar("SELECT COUNT(*) FROM players WHERE last_seen>?", (t - DAY,), 0),
        "new_24h": await q.scalar("SELECT COUNT(*) FROM players WHERE created_at>?", (t - DAY,), 0),
        "premium": await q.scalar("SELECT COUNT(*) FROM players WHERE premium_until>?", (t,), 0),
        "guilds": await q.scalar("SELECT COUNT(*) FROM guilds", (), 0),
        "listings": await q.scalar("SELECT COUNT(*) FROM market", (), 0),
        "stars_total": await q.scalar("SELECT COALESCE(SUM(stars),0) FROM payments", (), 0),
        "stars_24h": await q.scalar("SELECT COALESCE(SUM(stars),0) FROM payments WHERE created_at>?", (t - DAY,), 0),
        "payments": await q.scalar("SELECT COUNT(*) FROM payments", (), 0),
    }


async def overview(q) -> dict:
    t = now()
    sc = lambda sql, *a: q.scalar(sql, a, 0)  # noqa: E731
    total = await sc("SELECT COUNT(*) FROM players")
    return {
        "total": total,
        "new": [await sc("SELECT COUNT(*) FROM players WHERE created_at>?", t - d * DAY) for d in (1, 7, 30)],
        "active": [await sc("SELECT COUNT(*) FROM players WHERE last_seen>?", t - d * DAY) for d in (1, 7, 30)],
        "new_spark": await _per_day(q, "players", "created_at"),
        "returned": await sc("SELECT COUNT(*) FROM players WHERE created_at<? AND created_at>? AND last_seen>?",
                             t - DAY, t - 8 * DAY, t - DAY),
        "cohort": await sc("SELECT COUNT(*) FROM players WHERE created_at<? AND created_at>?", t - DAY, t - 8 * DAY),
        "premium": await sc("SELECT COUNT(*) FROM players WHERE premium_until>?", t),
        "banned": await sc("SELECT COUNT(*) FROM players WHERE banned=1"),
        "guilds": await sc("SELECT COUNT(*) FROM guilds"),
        "in_guild": await sc("SELECT COUNT(*) FROM players WHERE guild_id IS NOT NULL"),
        "listings": await sc("SELECT COUNT(*) FROM market"),
        "invites": await sc("SELECT COUNT(*) FROM guild_invites"),
        "battles": await sc("SELECT COUNT(*) FROM battles"),
    }


async def money(q) -> dict:
    t = now()
    sc = lambda sql, *a: q.scalar(sql, a, 0)  # noqa: E731
    paying = await sc("SELECT COUNT(DISTINCT user_id) FROM payments")
    total = await sc("SELECT COALESCE(SUM(stars),0) FROM payments")
    return {
        "total": total, "count": await sc("SELECT COUNT(*) FROM payments"), "payers": paying,
        "periods": [await sc("SELECT COALESCE(SUM(stars),0) FROM payments WHERE created_at>?", t - d * DAY) for d in (1, 7, 30)],
        "spark": await _per_day(q, "payments", "created_at", 14, agg="SUM(stars)"),
        "players": await sc("SELECT COUNT(*) FROM players"),
        "arppu": (total / paying) if paying else 0,
        "by_product": await q.all("SELECT payload, COUNT(*) AS n, SUM(stars) AS stars FROM payments "
                                  "GROUP BY payload ORDER BY stars DESC LIMIT 6"),
        "top_payers": await q.all("SELECT p.user_id, COALESCE(pl.name,'—') AS name, SUM(p.stars) AS stars, COUNT(*) AS n "
                                  "FROM payments p LEFT JOIN players pl ON pl.user_id=p.user_id "
                                  "GROUP BY p.user_id, pl.name ORDER BY stars DESC LIMIT 5"),
        "last": await q.all("SELECT charge_id, user_id, payload, stars, created_at FROM payments ORDER BY created_at DESC LIMIT 5"),
    }


async def people(q) -> dict:
    return {
        "classes": await q.all("SELECT cls, COUNT(*) AS n FROM players GROUP BY cls ORDER BY n DESC"),
        "levels": await q.all("SELECT level/10 AS b, COUNT(*) AS n FROM players GROUP BY level/10 ORDER BY b"),
        "reborn": await q.scalar("SELECT COUNT(*) FROM players WHERE marks>0", (), 0),
        "top": await q.all("SELECT user_id, name, level, rating FROM players ORDER BY level DESC, xp DESC LIMIT 5"),
        "arena": await q.all("SELECT user_id, name, rating FROM players ORDER BY rating DESC LIMIT 3"),
        "referrals": await q.scalar("SELECT COUNT(*) FROM players WHERE ref_by IS NOT NULL", (), 0),
        "avg_level": await q.scalar("SELECT COALESCE(AVG(level),0) FROM players", (), 0),
    }


async def economy(q) -> dict:
    t = now()
    row = await q.one("SELECT COALESCE(SUM(gold),0) AS gold, COALESCE(SUM(crystals),0) AS crystals, "
                      "COALESCE(SUM(essence),0) AS essence, COALESCE(SUM(marks),0) AS marks, COUNT(*) AS n FROM players")
    return {
        **row,
        "richest": await q.all("SELECT user_id, name, gold FROM players ORDER BY gold DESC LIMIT 3"),
        "items": await q.all("SELECT rarity, COUNT(*) AS n FROM items GROUP BY rarity ORDER BY n DESC"),
        "market_n": await q.scalar("SELECT COUNT(*) FROM market", (), 0),
        "market_avg": await q.scalar("SELECT COALESCE(AVG(price),0) FROM market", (), 0),
        "arena_24h": await q.scalar("SELECT COUNT(*) FROM arena_log WHERE created_at>?", (t - DAY,), 0),
        "kills": await q.scalar("SELECT COALESCE(SUM(kills),0) FROM players", (), 0),
        "taps": await q.scalar("SELECT COALESCE(SUM(taps),0) FROM players", (), 0),
        "guild_top": await q.all("SELECT name, level FROM guilds ORDER BY level DESC, xp DESC LIMIT 3"),
    }


async def user_card(q, uid: int) -> dict | None:
    p = await players.get(q, uid)
    if not p:
        return None
    pays = await q.one("SELECT COALESCE(SUM(stars),0) AS stars, COUNT(*) AS n FROM payments WHERE user_id=?", (uid,))
    guild = await q.scalar("SELECT name FROM guilds WHERE id=?", (p["guild_id"],)) if p["guild_id"] else None
    refs = await q.scalar("SELECT COUNT(*) FROM players WHERE ref_by=?", (uid,), 0)
    return {"p": p, "stars": pays["stars"], "payments": pays["n"], "guild": guild, "refs": refs}


async def give(db, uid: int, kind: str, amount: int) -> bool:
    if kind not in players.CURRENCIES:
        return False
    async with db.transaction() as tx:
        if not await players.get(tx, uid):
            return False
        await players.add(tx, uid, **{kind: amount})
    return True


async def set_ban(q, uid: int, banned: bool) -> bool:
    return (await q.execute("UPDATE players SET banned=? WHERE user_id=?", (1 if banned else 0, uid))) == 1


async def all_user_ids(q) -> list[int]:
    return [r["user_id"] for r in await q.all("SELECT user_id FROM players WHERE banned=0")]


async def find_payment(q, charge_id: str) -> dict | None:
    return await q.one("SELECT * FROM payments WHERE charge_id=?", (charge_id,))
