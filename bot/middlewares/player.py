"""Загружает игрока в handler-ы (параметр `player`), блокирует забаненных."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..db.core import Database
from ..services import players
from ..utils.fmt import now


class PlayerMiddleware(BaseMiddleware):
    _ADMIN_PREFIXES = ("/admin", "/give", "/ban", "/unban", "/broadcast", "/refund", "/emojis", "/price", "/discount", "/setemoji",
                       "/delemoji", "/user")

    def __init__(self, db: Database, admin_ids: frozenset[int] = frozenset()) -> None:
        self.db = db
        self.admin_ids = admin_ids

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]], event: TelegramObject,
                       data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        player = await players.get(self.db, user.id)
        data["player"] = player

        if player is None:
            allowed = False
            is_admin = user.id in self.admin_ids
            if isinstance(event, Message):
                head = event.text or event.caption or ""
                allowed = bool(event.successful_payment) or head.startswith(("/start", "/help"))
                if is_admin:  # админ может управлять ботом и без своего героя
                    ents = (event.entities or []) + (event.caption_entities or [])
                    allowed = allowed or head.startswith(self._ADMIN_PREFIXES) or any(x.type == "custom_emoji" for x in ents)
            elif isinstance(event, CallbackQuery):
                allowed = (event.data or "").startswith(("start:", "help")) or (is_admin and (event.data or "").startswith(("bc:", "adm:")))
            if not allowed:
                text = "Сначала нажми /start, чтобы создать героя."
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(text)
                return None
            return await handler(event, data)

        if player["banned"]:
            if isinstance(event, CallbackQuery):
                await event.answer("Аккаунт заблокирован.", show_alert=True)
            return None

        # обновляем имя/last_seen не чаще раза в минуту
        full = (user.full_name or "Герой")[:24]
        if now() - player["last_seen"] > 60 or player["name"] != full or player["username"] != user.username:
            await players.touch(self.db, user.id, user.username, full)
            player["name"], player["username"] = full, user.username
        return await handler(event, data)
