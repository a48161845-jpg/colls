"""Чистые формулы баланса (без БД) — легко тестировать и править."""
from __future__ import annotations

from ..data import balance as B
from ..data.buildings import BUILDINGS
from ..data.classes import CLASSES
from ..data.items import ENHANCE_STAT_BONUS, RARITY


def xp_needed(level: int) -> int:
    return int(60 * level ** 1.55)


def base_stats(cls: str, level: int, marks: int = 0) -> dict:
    c = CLASSES[cls]
    m = 1 + B.MARK_STAT_BONUS * marks
    return {
        "hp": int((90 + level * 17) * c["hp"] * m),
        "atk": int((7 + level * 2.6) * c["atk"] * m),
        "def": int((3 + level * 1.5) * c["def"] * m),
        "crit": c["crit"],
    }


def building_cost(key: str, level: int) -> int:
    """Цена улучшения здания с уровня `level` на level+1."""
    b = BUILDINGS[key]
    return int(b["base_cost"] * b["growth"] ** level)


def building_rate(key: str, level: int) -> float:
    """Доход здания в час (до множителей)."""
    b = BUILDINGS[key]
    if level <= 0 or not b["res"]:
        return 0.0
    return b["base_out"] * level * 1.05 ** level


def monster_stats(level: int, boss: bool = False) -> dict:
    """Статы монстра. ramp — мягкий старт: на 1 ур. враги слабее, к 10 ур. выходят на полную силу."""
    ramp = min(1.0, max(0.0, (level - 1) / 9))
    hp = 50 + level * 30
    atk = 8 + level * 3.0 * (1 + 2.0 * ramp)
    df = 2 + level * 1.2
    if boss:
        hp, atk, df = hp * (1.6 + 0.6 * ramp), atk * (1.05 + 0.05 * ramp), df * 1.2
    return {"hp": int(hp), "atk": int(atk), "def": int(df)}


def armor_reduction(df: float, level: float, pierce: float = 0.0) -> float:
    """Доля урона, поглощаемая защитой. Убывающая отдача: чем выше защита, тем меньше прирост,
    а константа растёт с уровнем — одинаковая броня на 50 ур. защищает слабее, чем на 5 ур."""
    eff = max(0.0, df * (1 - pierce))
    return eff / (eff + 8 * level + 20)


def item_mult(plus: int) -> float:
    return 1 + ENHANCE_STAT_BONUS * plus


def enhance_cost(item: dict) -> tuple[int, int]:
    n = item["plus"] + 1
    gold = int(80 * (item["ilvl"] + 5) * n ** 1.4)
    essence = 2 * n + item["ilvl"] // 10
    return gold, essence


def sell_price(item: dict) -> int:
    return max(1, int((5 + item["ilvl"] * 3) * RARITY[item["rarity"]]["sell"] * (1 + 0.25 * item["plus"])))


def tap_power(level: int, mine_level: int) -> int:
    return max(1, int((1 + level * 0.9) * (1 + 0.15 * mine_level)))


def rebirth_marks(level: int) -> int:
    return max(1, (level - 20) // 10)


def guild_xp_needed(level: int) -> int:
    return int(2000 * level ** 1.4)


def guild_boss_max(boss_level: int) -> int:
    return int(4000 * 1.45 ** (boss_level - 1))


def guild_max_members(level: int) -> int:
    return min(B.GUILD_MAX_MEMBERS, B.GUILD_BASE_MEMBERS + 2 * (level - 1))


def offline_cap_hours(library_level: int, premium: bool) -> float:
    return B.OFFLINE_CAP_H + B.OFFLINE_CAP_PER_LIBRARY * library_level + (B.PREMIUM_CAP_BONUS_H if premium else 0)


def power(stats: dict) -> int:
    return int(stats["atk"] * 3 + stats["def"] * 2 + stats["hp"] / 5)
