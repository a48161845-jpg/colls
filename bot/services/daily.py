"""Ежедневная награда со стриком."""
from __future__ import annotations

from ..data import balance as B
from ..utils.fmt import today
from . import players


def reward_for(streak: int, premium: bool) -> dict:
    reward = dict(B.DAILY_REWARDS[(streak - 1) % len(B.DAILY_REWARDS)])
    if premium:
        reward["crystals"] = reward.get("crystals", 0) + 3
    return reward


async def status(q, p: dict) -> dict:
    day = today()
    claimed = p["last_daily"] == day
    streak = p["streak"] if p["last_daily"] >= day - 1 else 0
    next_streak = streak if claimed else streak + 1
    return {"claimed": claimed, "streak": streak, "next_streak": next_streak,
            "reward": reward_for(max(1, next_streak), players.is_premium(p)),
            "day_idx": (max(1, next_streak) - 1) % len(B.DAILY_REWARDS)}


async def claim(db, uid: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        day = today()
        if p["last_daily"] == day:
            return {"ok": False}
        streak = p["streak"] + 1 if p["last_daily"] == day - 1 else 1
        reward = reward_for(streak, players.is_premium(p))
        await players.add(tx, uid, **reward)
        await tx.execute("UPDATE players SET streak=?, last_daily=? WHERE user_id=?", (streak, day, uid))
        return {"ok": True, "streak": streak, "reward": reward}
