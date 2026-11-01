"""Помощники для inline-клавиатур. Кнопки: (текст, callback_data) или (текст, url, True)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..emoji import EMOJI, p

Row = list[tuple]


def _btn(spec: tuple) -> InlineKeyboardButton:
    text, icon = EMOJI.split_button(spec[0])
    extra = {"icon_custom_emoji_id": icon} if icon else {}  # поле Bot API 9.4; aiogram < 3.23 передаёт его как extra
    if len(spec) == 3 and spec[2] is True:
        return InlineKeyboardButton(text=text, url=spec[1], **extra)
    return InlineKeyboardButton(text=text, callback_data=spec[1], **extra)


def kb(*rows: Row) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(b) for b in row] for row in rows if row])


def back(to: str = "menu", label: str | None = None) -> Row:
    return [(label or f"{p('back')} Назад", to)]


def pager(prefix: str, page: int, total: int, per: int) -> Row:
    """Ряд «‹ 2/5 ›». prefix + ':' + номер страницы."""
    pages = max(1, -(-total // per))
    row: Row = []
    if page > 0:
        row.append(("‹", f"{prefix}:{page - 1}"))
    row.append((f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        row.append(("›", f"{prefix}:{page + 1}"))
    return row if pages > 1 else []
