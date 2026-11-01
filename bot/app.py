"""Сборка бота: Bot, Dispatcher, middleware, роутеры. Отдельно от main — чтобы можно было тестировать."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BotCommand, ErrorEvent

from .config import Settings
from .db.core import Database
from .emoji import EMOJI
from .services import prices
from .handlers import get_routers
from .middlewares.player import PlayerMiddleware
from .middlewares.throttle import ThrottleMiddleware

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="profile", description="Профиль героя"),
    BotCommand(command="idle", description="Рудник"),
    BotCommand(command="adv", description="Приключения"),
    BotCommand(command="story", description="Сюжет"),
    BotCommand(command="quests", description="Задания"),
    BotCommand(command="bag", description="Сумка"),
    BotCommand(command="guild", description="Гильдия"),
    BotCommand(command="market", description="Рынок"),
    BotCommand(command="arena", description="Арена"),
    BotCommand(command="daily", description="Ежедневная награда"),
    BotCommand(command="shop", description="Магазин"),
    BotCommand(command="help", description="Помощь"),
]


def build_bot(settings: Settings) -> Bot:
    return Bot(settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))


async def build_dispatcher(settings: Settings, db: Database, *, throttle_interval: float = 0.35,
                           tap_interval: float = 0.12) -> Dispatcher:
    EMOJI.enabled = settings.premium_emoji
    EMOJI.button_icons = settings.premium_buttons
    from .images import theme
    theme.ANIMATE = settings.animated_images
    EMOJI.load_file()
    await EMOJI.load_db(db)
    await prices.load(db)

    dp = Dispatcher(storage=MemoryStorage(), db=db, settings=settings)
    throttle = ThrottleMiddleware(throttle_interval, tap_interval)
    player_mw = PlayerMiddleware(db, settings.admin_ids)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(throttle)
        observer.outer_middleware(player_mw)
    dp.include_routers(*get_routers())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        exc = event.exception
        if isinstance(exc, TelegramBadRequest) and "emoji" in str(exc).lower() and EMOJI.button_icons:
            # Telegram не принял премиум-иконки на кнопках (например, у владельца бота нет Premium)
            EMOJI.button_icons = False
            log.warning("Telegram отклонил премиум-иконки на кнопках — отключаю PREMIUM_BUTTONS до перезапуска: %s", exc)
        elif isinstance(exc, TelegramRetryAfter):
            log.warning("Telegram просит подождать %s с: %s", exc.retry_after, exc.method)
            try:
                if event.update.callback_query:
                    await event.update.callback_query.answer(f"Слишком часто, подожди {min(exc.retry_after, 60)} с.")
            except Exception:  # noqa: BLE001
                pass
            return True
        else:
            log.exception("Unhandled error", exc_info=exc)
        upd = event.update
        try:
            if upd.callback_query:
                await upd.callback_query.answer("Что-то пошло не так. Попробуй ещё раз.", show_alert=True)
            elif upd.message:
                await upd.message.answer("Что-то пошло не так. Попробуй ещё раз или /menu.")
        except Exception:  # noqa: BLE001
            pass
        return True

    return dp
