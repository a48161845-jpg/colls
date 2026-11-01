"""Защита от спама кнопками: слишком частые нажатия молча отбрасываются."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

FAST = ("idle:tap",)  # тапы можно чаще


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, interval: float = 0.35, tap_interval: float = 0.12) -> None:
        self.interval = interval
        self.tap_interval = tap_interval
        self._last: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]], event: TelegramObject,
                       data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)
        is_tap = isinstance(event, CallbackQuery) and (event.data or "") in FAST
        gap = self.tap_interval if is_tap else self.interval
        t = time.monotonic()
        key = user.id * 2 + (1 if is_tap else 0)
        if t - self._last.get(key, 0.0) < gap:
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None
        self._last[key] = t
        if len(self._last) > 50_000:  # не даём словарю расти бесконечно
            cutoff = t - 60
            self._last = {k: v for k, v in self._last.items() if v > cutoff}
        return await handler(event, data)
