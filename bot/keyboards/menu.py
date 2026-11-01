"""Главное меню."""
from __future__ import annotations

from ..emoji import p
from .common import kb


def main_menu():
    """Главное меню: шесть кнопок, остальное спрятано в «Мир» и «Сообщество»."""
    return kb(
        [(f"{p('idle')} Рудник", "idle"), (f"{p('hero')} Герой", "profile")],
        [(f"{p('adventure')} Мир", "world"), (f"{p('guild')} Сообщество", "hub")],
        [(f"{p('daily')} Награда", "daily"), (f"{p('shop')} Магазин", "shop")],
    )


def world_menu():
    return kb(
        [(f"{p('adventure')} Приключения", "adv"), (f"{p('story')} Сюжет", "story")],
        [(f"{p('quest')} Задания", "dq")],
        [(f"{p('back')} Назад", "menu")],
    )


def hub_menu():
    return kb(
        [(f"{p('guild')} Гильдия", "g"), (f"{p('market')} Рынок", "mk")],
        [(f"{p('arena')} Арена", "ar"), (f"{p('top')} Топы", "top:level")],
        [(f"{p('ref')} Друзья", "ref")],
        [(f"{p('back')} Назад", "menu")],
    )
