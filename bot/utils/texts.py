"""Сборка типовых кусков текста (с поддержкой премиум-эмодзи через e())."""
from __future__ import annotations

from ..data.items import RARITY, SLOTS
from ..emoji import e
from ..services.formulas import item_mult
from .fmt import esc, num


def wallet(p: dict) -> str:
    return (f"{e('gold')} <b>{num(p['gold'])}</b>   {e('crystal')} <b>{num(p['crystals'])}</b>   "
            f"{e('essence')} <b>{num(p['essence'])}</b>")


def item_stats(it: dict) -> str:
    m = item_mult(it.get("plus", 0))
    parts = []
    if it["atk"]:
        parts.append(f"{e('atk')}{num(int(it['atk'] * m))}")
    if it["def"]:
        parts.append(f"{e('def')}{num(int(it['def'] * m))}")
    if it["hp"]:
        parts.append(f"{e('hp')}{num(int(it['hp'] * m))}")
    if it["idle"]:
        parts.append(f"{e('idle')}+{it['idle']}%")
    return " ".join(parts)


def item_name(it: dict) -> str:
    return f"{e('r_' + it['rarity'])} <b>{esc(it['name'])}</b>" + (f" +{it['plus']}" if it.get("plus") else "")


def item_line(it: dict) -> str:
    return f"{item_name(it)} · ур.{it['ilvl']} · {item_stats(it)}"


def plain_item(it: dict) -> str:
    """Для подписей кнопок (без HTML)."""
    from ..emoji import p as plain
    return f"{plain('r_' + it['rarity'])} {it['name']}" + (f" +{it['plus']}" if it.get("plus") else "")


def rarity_name(key: str) -> str:
    return RARITY[key]["name"]


def slot_name(key: str) -> str:
    return SLOTS[key]["name"]


def reward_line(r: dict) -> str:
    parts = []
    for key, emo in (("gold", "gold"), ("xp", "xp"), ("essence", "essence"), ("crystals", "crystal"), ("potions", "potion")):
        v = r.get(key)
        if v:
            parts.append(f"{e(emo)} {'+' if v > 0 else ''}{num(v)}")
    return "  ".join(parts)


def levelup_line(info: dict | None) -> str:
    if info and info.get("gained"):
        return f"\n{e('level')} <b>Новый уровень: {info['level']}!</b>"
    return ""
