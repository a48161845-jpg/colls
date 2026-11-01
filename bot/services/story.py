"""Движок сюжетных глав с выбором (данные — в data/story.py)."""
from __future__ import annotations

import json
import random

from ..data.story import CHAPTERS, CHAPTER_ORDER, CHECK_DIVISORS
from . import items as items_svc, players, quests


def load(p: dict) -> dict:
    try:
        st = json.loads(p.get("story") or "{}")
    except ValueError:
        st = {}
    st.setdefault("ch", 0)
    st.setdefault("node", "")
    st.setdefault("done", [])
    st.setdefault("flags", [])
    return st


def chapter_available(p: dict, ch: int) -> tuple[bool, str]:
    meta = CHAPTERS[ch]
    st = load(p)
    if p["level"] < meta["min_level"]:
        return False, f"нужен {meta['min_level']} уровень"
    if ch > CHAPTER_ORDER[0] and (ch - 1) not in st["done"]:
        return False, "сначала пройди предыдущую главу"
    return True, ""


def choice_visible(choice: dict, p: dict) -> bool:
    req = choice.get("req") or {}
    if "cls" in req and p["cls"] != req["cls"]:
        return False
    if "level" in req and p["level"] < req["level"]:
        return False
    if "flag" in req or "noflag" in req:
        flags = load(p)["flags"]
        if "flag" in req and req["flag"] not in flags:
            return False
        if "noflag" in req and req["noflag"] in flags:
            return False
    return True


def current(p: dict) -> tuple[int, str, dict] | None:
    st = load(p)
    if not st["ch"] or not st["node"]:
        return None
    return st["ch"], st["node"], CHAPTERS[st["ch"]]["nodes"][st["node"]]


async def _apply_fx(tx, p: dict, fx: dict, st: dict, rng: random.Random) -> dict:
    uid = p["user_id"]
    out = {"gold": 0, "xp": 0, "essence": 0, "crystals": 0, "potions": 0, "item": None, "levelup": None, "title": None}
    cur = {k: fx.get(k, 0) for k in ("gold", "essence", "crystals", "potions")}
    await players.add(tx, uid, **cur)
    for k, v in cur.items():
        out[k] = v
    if fx.get("xp"):
        out["xp"] = fx["xp"]
        out["levelup"] = await players.add_xp(tx, uid, fx["xp"])
    if fx.get("item"):
        item = items_svc.roll_item(max(1, p["level"]), rarity=fx["item"], rng=rng)
        item["id"] = await items_svc.create(tx, uid, item)
        out["item"] = item
    if fx.get("title"):
        out["title"] = fx["title"]
        await tx.execute("UPDATE players SET title=? WHERE user_id=?", (fx["title"], uid))
    if fx.get("flag") and fx["flag"] not in st["flags"]:
        st["flags"].append(fx["flag"])
    return out


async def start_chapter(db, uid: int, ch: int) -> dict:
    if ch not in CHAPTERS:
        return {"ok": False, "msg": "Такой главы нет."}
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        ok, why = chapter_available(p, ch)
        if not ok:
            return {"ok": False, "msg": why}
        st = load(p)
        st["ch"], st["node"] = ch, CHAPTERS[ch]["start"]
        await tx.execute("UPDATE players SET story=? WHERE user_id=?", (json.dumps(st), uid))
        return {"ok": True}


async def choose(db, uid: int, idx: int, rng: random.Random = random) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        cur = current(p)
        if not cur:
            return {"ok": False, "msg": "Сюжет не начат."}
        ch, node_id, node = cur
        choices = node.get("choices", [])
        if not (0 <= idx < len(choices)) or not choice_visible(choices[idx], p):
            return {"ok": False, "msg": "Недоступный вариант."}
        choice = choices[idx]
        st = load(p)
        res: dict = {"ok": True, "roll": None, "success": None, "fx": None}

        if "check" in choice:
            chk = choice["check"]
            stats = await players.derived(tx, p)
            value = p["level"] if chk["stat"] == "level" else stats[chk["stat"]]
            bonus = value // CHECK_DIVISORS[chk["stat"]]
            die = rng.randint(1, 20)
            res.update(roll=die, bonus=bonus, dc=chk["dc"], stat=chk["stat"])
            res["success"] = die + bonus >= chk["dc"]
            nxt = chk["win"] if res["success"] else chk["lose"]
        else:
            nxt = choice["goto"]

        if choice.get("fx"):
            res["fx"] = await _apply_fx(tx, p, choice["fx"], st, rng)

        new_node = CHAPTERS[ch]["nodes"][nxt]
        st["node"] = nxt
        res["node_id"], res["node"], res["chapter"] = nxt, new_node, ch

        if new_node.get("end"):
            first = ch not in st["done"]
            res["finished"] = True
            res["first_clear"] = first
            if first:
                st["done"].append(ch)
                res["reward"] = await _apply_fx(tx, p, new_node.get("reward", {}), st, rng)
            st["ch"], st["node"] = 0, ""
        await tx.execute("UPDATE players SET story=? WHERE user_id=?", (json.dumps(st), uid))
        await quests.progress(tx, uid, "story", 1)
        return res
