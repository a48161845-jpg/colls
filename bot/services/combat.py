"""Пошаговый бой с монстрами и боссами.

Состояние боя хранится в таблице battles как JSON — бой переживает перезапуск бота.
Движок (new_state / step / calc_rewards) не зависит от БД и тестируется отдельно.
"""
from __future__ import annotations

import json
import random

from ..data import balance as B
from ..data.monsters import LOC, tier
from ..emoji import e
from ..utils.fmt import now
from . import formulas, items as items_svc, players, quests


# ------------------------------------------------------------------ движок
HERO_HITS = ("Ты рубишь", "Ты обрушиваешь удар", "Твой клинок находит брешь", "Ты бьёшь без пощады",
             "Ты врываешься в атаку", "Ты наносишь удар")
MONSTER_HITS = ("{m} бросается на тебя", "{m} бьёт наотмашь", "{m} находит просвет в защите",
                "{m} атакует из тени", "{m} впивается в тебя")
BOSS_HITS = ("{m} обрушивает всю свою мощь", "{m} бьёт так, что дрожит земля", "{m} не знает пощады")


def hit(atk: float, df: float, rng: random.Random = random, var: float = 0.15, pierce: float = 0.0,
        lvl: float = 1) -> int:
    """Урон одного удара. lvl — уровень боя (монстра): от него зависит, насколько хорошо защита поглощает урон."""
    raw = atk * rng.uniform(1 - var, 1 + var) * (1 - formulas.armor_reduction(df, lvl, pierce))
    return max(1, int(raw))


def new_state(p: dict, stats: dict, loc_key: str, boss: bool, rng: random.Random = random) -> dict:
    loc = LOC[loc_key]
    plvl = p["level"]
    if boss:
        lvl = max(loc["min"], min(loc["max"], plvl + (2 if plvl >= 10 else 0)))  # новичкам босс не «выше уровнем»
        name, kind = loc["boss"]
    else:
        lvl = max(loc["min"], min(loc["max"], plvl + rng.randint(-1, 1)))
        name, kind = rng.choice(loc["monsters"])
    ms = formulas.monster_stats(lvl, boss)
    return {
        "loc": loc_key, "boss": boss, "round": 1, "cd": 0, "guard": False, "poison": 0,
        "potions_used": 0, "potions_have": p["potions"], "log": [], "done": None, "result": None,
        "m": {"name": name, "kind": kind, "lvl": lvl, "hp": ms["hp"], "max": ms["hp"], "atk": ms["atk"], "def": ms["def"]},
        "p": {"hp": stats["hp"], "max": stats["hp"], "atk": stats["atk"], "def": stats["def"],
              "crit": B.BASE_CRIT + stats.get("crit", 0.0), "cls": p["cls"]},
    }


def step(st: dict, action: str, rng: random.Random = random) -> bool:
    """Один ход. Возвращает False, если действие не потратило ход (нет зелий, кулдаун...)."""
    P, M = st["p"], st["m"]
    st["log"] = []
    log = st["log"].append

    if st["done"]:
        return False

    if action == "potion":
        if st["potions_have"] - st["potions_used"] <= 0:
            log(f"{e('no')} Зелий не осталось.")
            return False
        heal = int(P["max"] * B.POTION_HEAL)
        before = P["hp"]
        P["hp"] = min(P["max"], P["hp"] + heal)
        st["potions_used"] += 1
        log(f"{e('potion')} Зелье: +{P['hp'] - before} {e('hp')}")
    elif action == "flee":
        if st["boss"]:
            log(f"{e('no')} От босса не сбежать!")
            return False
        if rng.random() < B.FLEE_CHANCE:
            st["done"] = "fled"
            log(f"{e('flee')} Ты сбежал с поля боя.")
            return True
        log(f"{e('flee')} Сбежать не вышло — враг атакует!")
    elif action == "skill":
        if st["cd"] > 0:
            log(f"{e('no')} Умение перезаряжается ({st['cd']}).")
            return False
        st["cd"] = B.SKILL_COOLDOWN + 1
        crit = rng.random() < P["crit"]
        mult = B.CRIT_MULT if crit else 1.0
        cls = P["cls"]
        if cls == "warrior":
            dmg = int(hit(P["atk"] * 0.8, M["def"], rng, lvl=M["lvl"]) * mult)
            heal = int(P["max"] * 0.20)
            P["hp"] = min(P["max"], P["hp"] + heal)
            st["guard"] = True
            log(f"{e('skill')} Несокрушимость: {dmg} урона, +{heal} {e('hp')}, щит поднят.")
        elif cls == "mage":
            dmg = int(hit(P["atk"] * 2.4, M["def"], rng, pierce=0.5, lvl=M["lvl"]) * mult)
            log(f"{e('skill')} Пепельная буря: <b>{dmg}</b> урона!")
        else:
            dmg = int(hit(P["atk"], M["def"], rng, lvl=M["lvl"]) * mult)
            st["poison"] = 3
            log(f"{e('skill')} Ядовитый клинок: {dmg} урона и яд на 3 хода.")
        M["hp"] -= dmg
        if crit:
            log(f"{e('crit')} Критический удар!")
    else:  # attack
        crit = rng.random() < P["crit"]
        dmg = hit(P["atk"], M["def"], rng, lvl=M["lvl"])
        if crit:
            dmg = int(dmg * B.CRIT_MULT)
        M["hp"] -= dmg
        log(f"{e('atk')} {rng.choice(HERO_HITS)}: <b>{dmg}</b> урона" + (f" {e('crit')} крит!" if crit else "."))

    # яд
    if st["poison"] > 0 and M["hp"] > 0:
        pd = max(1, int(P["atk"] * 0.45))
        M["hp"] -= pd
        st["poison"] -= 1
        log(f"☠️ Яд: -{pd}")

    if M["hp"] <= 0:
        M["hp"] = 0
        st["done"] = "win"
        log(f"{e('win')} {M['name']} повержен, последний вздох стихает в тишине.")
        return True
    if st["done"] == "fled":
        return True

    # ответ монстра
    enrage = st["boss"] and st["round"] % 4 == 0
    dmg = hit(M["atk"] * (1.5 if enrage else 1.0), P["def"], rng, lvl=M["lvl"])
    if st["guard"]:
        dmg = max(1, dmg // 2)
        st["guard"] = False
        log("🛡 Щит смягчил удар.")
    P["hp"] -= dmg
    label = f"{e('fire')} ЯРОСТЬ! " if enrage else ""
    phrase = rng.choice(BOSS_HITS if st["boss"] else MONSTER_HITS).format(m=M["name"])
    log(f"{label}{e('boss') if st['boss'] else '👹'} {phrase}: <b>{dmg}</b>.")
    if P["hp"] <= 0:
        P["hp"] = 0
        st["done"] = "lose"
        log(f"{e('lose')} В глазах темнеет, и ты падаешь на холодную землю…")
        return True

    st["round"] += 1
    if st["cd"] > 0:
        st["cd"] -= 1
    return True


def calc_rewards(st: dict, premium: bool, rng: random.Random = random) -> dict:
    M = st["m"]
    lvl, boss = M["lvl"], st["boss"]
    mult = 4 if boss else 1
    pm = B.PREMIUM_REWARD_MULT if premium else 1.0
    out = {
        "xp": int((20 + lvl * 9) * mult * rng.uniform(0.9, 1.1) * pm),
        "gold": int((15 + lvl * 7) * mult * rng.uniform(0.8, 1.2) * pm),
        "essence": (3 + lvl // 5) if boss else (1 if rng.random() < 0.12 else 0),
        "item": None,
    }
    if boss or rng.random() < 0.18:
        bonus = tier(st["loc"]) * 0.15 + (0.6 if boss else 0.0)
        out["item"] = items_svc.roll_item(lvl, rng=rng, bonus=bonus, min_index=1 if boss else 0)
    return out


# ------------------------------------------------------------------ работа с БД
async def get_state(q, uid: int) -> dict | None:
    row = await q.one("SELECT state FROM battles WHERE user_id=?", (uid,))
    return json.loads(row["state"]) if row else None


async def start(db, uid: int, loc_key: str, boss: bool) -> dict:
    """Начать бой. Возвращает {"ok", "state"|"msg"}. Если бой уже идёт — продолжает его."""
    async with db.transaction() as tx:
        existing = await get_state(tx, uid)
        if existing:
            return {"ok": True, "state": existing, "resumed": True}
        p = await players.get(tx, uid)
        loc = LOC.get(loc_key)
        if not loc:
            return {"ok": False, "msg": "Такой локации нет."}
        if p["level"] < loc["min"]:
            return {"ok": False, "msg": f"Нужен {loc['min']} уровень."}
        cost = B.BOSS_COST if boss else B.EXPEDITION_COST
        if not await players.spend_energy(tx, p, cost):
            return {"ok": False, "msg": "Не хватает энергии.", "need": cost}
        stats = await players.derived(tx, p)
        st = new_state(p, stats, loc_key, boss)
        await tx.execute("INSERT INTO battles(user_id, state, updated) VALUES(?,?,?)",
                         (uid, json.dumps(st), now()))
        return {"ok": True, "state": st, "resumed": False}


async def _finish(tx, p: dict, st: dict) -> None:
    uid = p["user_id"]
    used = st["potions_used"]
    if used:
        await players.add(tx, uid, potions=-used)
    result = {"kind": st["done"], "levelup": None}
    if st["done"] == "win":
        rw = calc_rewards(st, players.is_premium(p))
        await players.add(tx, uid, gold=rw["gold"], essence=rw["essence"])
        result["levelup"] = await players.add_xp(tx, uid, rw["xp"])
        await tx.execute("UPDATE players SET kills=kills+1 WHERE user_id=?", (uid,))
        await quests.progress(tx, uid, "kill", 1)
        if st["boss"]:
            await quests.progress(tx, uid, "boss", 1)
        item = rw.pop("item")
        if item:
            item["id"] = await items_svc.create(tx, uid, item)
        result.update(rw)
        result["item"] = item
    elif st["done"] == "lose":
        loss = int(p["gold"] * B.DEFEAT_GOLD_LOSS)
        await players.add(tx, uid, gold=-loss)
        result["gold_lost"] = loss
    st["result"] = result
    await tx.execute("DELETE FROM battles WHERE user_id=?", (uid,))


async def act(db, uid: int, action: str) -> dict | None:
    """Выполнить действие игрока. Возвращает обновлённое состояние (None — боя нет)."""
    async with db.transaction() as tx:
        st = await get_state(tx, uid)
        if not st:
            return None
        p = await players.get(tx, uid)
        step(st, action)
        if st["done"]:
            await _finish(tx, p, st)
        else:
            await tx.execute("UPDATE battles SET state=?, updated=? WHERE user_id=?",
                             (json.dumps(st), now(), uid))
        return st


async def abandon(db, uid: int) -> None:
    await db.execute("DELETE FROM battles WHERE user_id=?", (uid,))
