"""Общие вспомогательные вещи для handler-ов, которым нужен Bot (уведомления)."""
from __future__ import annotations

from aiogram import Bot

from .data import balance as B
from .emoji import e
from .ui import notify
from .utils.texts import reward_line


async def notify_inviter(bot: Bot, levelup: dict | None) -> None:
    """Если повышение уровня выдало реферальный бонус пригласившему — сообщаем ему."""
    if levelup and levelup.get("inviter"):
        await notify(bot, levelup["inviter"],
                     f"{e('ref')} Приглашённый тобой герой достиг {B.REF_LEVEL_REQUIRED} уровня! "
                     f"Награда: {reward_line(B.REF_BONUS_INVITER)}")
