"""Список роутеров. Порядок важен: админка — последняя, чтобы её «ловец премиум-эмодзи»
не перехватывал текстовый ввод (название гильдии, цена лота)."""
from aiogram import Router


def get_routers() -> list[Router]:
    from . import adventure, admin, arena, daily, guild, idle, inventory, market, quests, shop, start, story

    return [
        start.router, idle.router, adventure.router, story.router, quests.router, inventory.router,
        daily.router, guild.router, market.router, arena.router, shop.router, admin.router,
    ]
