"""Ежедневные задания."""
from __future__ import annotations

import random

from ..data import balance as B
from ..data.quests import DAILY, DAILY_POOL
from ..utils.fmt import today
from . import players


def scale_reward(key: str, level: int) -> dict:
    base = DAILY[key]["reward"]
    k = 1 + level * 0.12
    out = {}
    for res, val in base.items():
        out[res] = int(val * k) if res in ("gold", "xp") else val
    return out


async def ensure_today(q, uid: int) -> list[dict]:
    day = today()
    rows = await q.all("SELECT * FROM daily_quests WHERE user_id=? AND day=? ORDER BY key", (uid, day))
    if not rows:
        rng = random.Random(uid * 100003 + day)
        for quest in rng.sample(DAILY_POOL, B.DAILY_QUESTS_PER_DAY):
            need = rng.randint(*quest["need"])
            await q.execute(
                "INSERT OR IGNORE INTO daily_quests(user_id, day, key, need) VALUES(?,?,?,?)",
                (uid, day, quest["key"], need),
            )
        rows = await q.all("SELECT * FROM daily_quests WHERE user_id=? AND day=? ORDER BY key", (uid, day))
    return rows


async def progress(q, uid: int, key: str, n: int = 1) -> None:
    await q.execute(
        "UPDATE daily_quests SET progress=MIN(need, progress+?) "
        "WHERE user_id=? AND day=? AND key=? AND claimed=0",
        (n, uid, today(), key),
    )


async def list_today(q, p: dict) -> list[dict]:
    rows = await ensure_today(q, p["user_id"])
    out = []
    for r in rows:
        meta = DAILY[r["key"]]
        out.append({**r, "text": meta["text"], "reward": scale_reward(r["key"], p["level"]),
                    "done": r["progress"] >= r["need"]})
    return out


async def claim(db, uid: int, key: str) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        row = await tx.one("SELECT * FROM daily_quests WHERE user_id=? AND day=? AND key=?", (uid, today(), key))
        if not row or row["claimed"] or row["progress"] < row["need"]:
            return {"ok": False}
        await tx.execute("UPDATE daily_quests SET claimed=1 WHERE user_id=? AND day=? AND key=?", (uid, today(), key))
        reward = scale_reward(key, p["level"])
        xp = reward.pop("xp", 0)
        await players.add(tx, uid, **reward)
        info = {"level": p["level"], "gained": 0, "inviter": None}
        if xp:
            info = await players.add_xp(tx, uid, xp)
        reward["xp"] = xp
        left = await tx.scalar("SELECT COUNT(*) FROM daily_quests WHERE user_id=? AND day=? AND claimed=0",
                               (uid, today()), 0)
        bonus = 0
        if left == 0:
            bonus = B.DAILY_QUESTS_BONUS_CRYSTALS
            await players.add(tx, uid, crystals=bonus)
        return {"ok": True, "reward": reward, "bonus": bonus, "levelup": info}
