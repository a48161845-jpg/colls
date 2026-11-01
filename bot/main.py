"""Точка входа:  python -m bot"""
from __future__ import annotations

import asyncio
import logging

from .app import COMMANDS, build_bot, build_dispatcher
from .config import load_settings
from .db.core import open_database


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("bot")

    db = await open_database(settings)
    bot = build_bot(settings)
    dp = await build_dispatcher(settings, db)
    try:
        me = await bot.me()
        log.info("Запущен @%s (id %s), БД: %s", me.username, me.id, db.describe())
        if not settings.admin_ids:
            log.warning("ADMIN_IDS пуст — админ-команды недоступны")
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "pre_checkout_query"])
    finally:
        await bot.session.close()
        await db.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
