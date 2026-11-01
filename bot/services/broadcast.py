"""Рассылка. Берёт сообщение админа как есть: форматирование (жирный, курсив, ссылки, спойлеры, цитаты,
премиум-эмодзи), фото/видео/гифки с подписью, либо пересылает как копию ответное сообщение.

Источники текста (по приоритету):
  1. /broadcast в ОТВЕТ на любое сообщение — оно копируется целиком (с медиа и форматированием);
  2. /broadcast текст — форматирование из самого сообщения переводится в HTML;
  3. если форматирования в сообщении нет, а в тексте написаны HTML-теги вручную (<b>…</b>) — они применяются.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.types import Message

log = logging.getLogger(__name__)

_CMD = re.compile(r"^/broadcast(?:@\w+)?[ \t]*\n?", re.I)
_RAW_TAG = re.compile(r"</?(b|i|u|s|a|code|pre|tg-emoji|tg-spoiler|blockquote|strong|em|ins|del|strike)\b[^>]*>", re.I)
_FORMATTING = {"bold", "italic", "underline", "strikethrough", "spoiler", "code", "pre", "text_link", "text_mention",
               "custom_emoji", "blockquote", "expandable_blockquote"}
_MEDIA = ("photo", "video", "animation", "document", "audio", "voice", "video_note")


@dataclass
class Payload:
    kind: str               # "text" | "copy" | "media"
    html: str = ""          # текст/подпись в HTML
    from_chat: int = 0
    message_id: int = 0

    def describe(self) -> str:
        return {"text": "текст", "copy": "копия сообщения", "media": "медиа с подписью"}[self.kind]


def _body_html(m: Message) -> str:
    """Текст сообщения без команды, в HTML."""
    entities = (m.entities or []) if m.text is not None else (m.caption_entities or [])
    raw = m.text if m.text is not None else (m.caption or "")
    has_fmt = any(en.type in _FORMATTING for en in entities)
    if not has_fmt and _RAW_TAG.search(raw):
        html = raw                      # админ написал теги руками
    else:
        html = m.html_text              # форматирование Telegram -> HTML (включая <tg-emoji>)
    return _CMD.sub("", html, count=1).strip()


def build(m: Message) -> Payload | None:
    """None — слать нечего."""
    reply = m.reply_to_message
    if reply is not None:
        return Payload("copy", from_chat=reply.chat.id, message_id=reply.message_id)
    html = _body_html(m)
    if any(getattr(m, k, None) for k in _MEDIA):
        return Payload("media", html=html, from_chat=m.chat.id, message_id=m.message_id)
    return Payload("text", html=html) if html else None


async def send_one(bot: Bot, chat_id: int, pl: Payload) -> None:
    if pl.kind == "text":
        await bot.send_message(chat_id, pl.html)
    elif pl.kind == "copy":
        await bot.copy_message(chat_id, pl.from_chat, pl.message_id)
    else:
        await bot.copy_message(chat_id, pl.from_chat, pl.message_id, caption=pl.html or None, parse_mode="HTML")


async def deliver(bot: Bot, chat_id: int, pl: Payload) -> bool:
    """Одна доставка с ожиданием при лимитах Telegram. False — не доставлено (бот заблокирован и т.п.)."""
    for _ in range(3):
        try:
            await send_one(bot, chat_id, pl)
            return True
        except TelegramRetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 0.5)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:  # noqa: BLE001
            log.exception("broadcast to %s failed", chat_id)
            return False
    return False


async def run(bot: Bot, ids: list[int], pl: Payload, delay: float = 0.05) -> tuple[int, int]:
    sent = 0
    for uid in ids:
        if await deliver(bot, uid, pl):
            sent += 1
        await asyncio.sleep(delay)   # ~20 сообщений/сек — в рамках лимитов Telegram
    return sent, len(ids)
