"""Показ «экранов»: картинка + подпись + кнопки, с редактированием одного сообщения.

screen(target, text, markup, img=..., cache="ключ")
  target — Message (команда) или CallbackQuery (нажатие кнопки);
  img    — bytes или функция без аргументов, возвращающая bytes (рисуется в потоке);
  cache  — ключ для статичных картинок: после первой отправки используется file_id,
           картинка не рисуется и не загружается повторно.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Union

from aiogram import Bot
import time

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InputMediaAnimation, InputMediaPhoto,
                           Message)

from .emoji import EMOJI

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
_file_ids: dict[str, tuple[str, bool]] = {}   # ключ кэша -> (file_id, это анимация)

_shown: dict[tuple[int, int], str] = {}   # (чат, сообщение) -> ключ кэша показанной картинки
_flood_until: dict[int, float] = {}       # чат -> до какого момента Telegram просит не менять картинки
_SHOWN_MAX = 20000

ImgSource = Union[bytes, Callable[[], bytes], None]


async def _media(img: ImgSource, cache: str | None):
    """-> (медиа, из_кэша, анимация). Карточка-GIF (байты начинаются с GIF8) уходит как анимация."""
    if cache and cache in _file_ids:
        fid, animated = _file_ids[cache]
        return fid, True, animated
    data = bytes(img if isinstance(img, (bytes, bytearray)) else await asyncio.to_thread(img))
    animated = data[:4] == b"GIF8"
    return BufferedInputFile(data, filename="card.gif" if animated else "card.jpg"), False, animated


def _remember(cache: str | None, res) -> None:
    if not (cache and isinstance(res, Message)):
        return
    if res.animation:
        _file_ids[cache] = (res.animation.file_id, True)
    elif res.photo:
        _file_ids[cache] = (res.photo[-1].file_id, False)


def _mark(old: Message, res, cache: str | None) -> None:
    if len(_shown) > _SHOWN_MAX:
        _shown.clear()
    new = res if isinstance(res, Message) else old
    if cache:
        _shown[(new.chat.id, new.message_id)] = cache
    else:
        _shown.pop((new.chat.id, new.message_id), None)


def _has_media(msg: Message) -> bool:
    return bool(msg.photo or msg.animation)


async def _send(msg: Message, media, animated: bool, text: str, markup):
    if animated:
        return await msg.answer_animation(media, caption=text, reply_markup=markup)
    return await msg.answer_photo(media, caption=text, reply_markup=markup)


def _input_media(media, animated: bool, text: str):
    cls = InputMediaAnimation if animated else InputMediaPhoto
    return cls(media=media, caption=text, parse_mode="HTML")


async def _delete(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


async def screen(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None, *,
                 img: ImgSource = None, cache: str | None = None) -> Message | None:
    cb = target if isinstance(target, CallbackQuery) else None
    msg: Message = cb.message if cb else target  # type: ignore[assignment]
    if msg is None:
        return None
    text = EMOJI.strip(text)
    if img is not None and len(text) > CAPTION_LIMIT:
        log.warning("caption too long (%s), falling back to text-only", len(text))
        img = None

    # Картинка уже та же (или Telegram ограничил смену картинок в этом чате) — меняем только подпись,
    # это не упирается в лимит EditMessageMedia.
    if img is not None and cb and _has_media(msg):
        same = cache is not None and _shown.get((msg.chat.id, msg.message_id)) == cache
        if same or _flood_until.get(msg.chat.id, 0) > time.time():
            try:
                res = await msg.edit_caption(caption=text, reply_markup=markup)
                return res if isinstance(res, Message) else msg
            except TelegramBadRequest as ex:
                if "not modified" in str(ex):
                    return msg
            except TelegramRetryAfter as ex:
                _flood_until[msg.chat.id] = time.time() + ex.retry_after
                return msg

    if img is not None:
        for _attempt in (0, 1):
            media, from_cache, animated = await _media(img, cache)
            try:
                if cb and _has_media(msg):
                    res = await msg.edit_media(_input_media(media, animated, text), reply_markup=markup)
                    _remember(cache, res)
                    _mark(msg, res, cache)
                    return res if isinstance(res, Message) else msg
                if cb:
                    await _delete(msg)
                res = await _send(msg, media, animated, text, markup)
                _remember(cache, res)
                _mark(msg, res, cache)
                return res
            except TelegramRetryAfter as ex:
                # лимит Telegram на смену картинок: оставляем старую картинку, обновляем только текст и кнопки
                _flood_until[msg.chat.id] = time.time() + ex.retry_after
                log.warning("flood control в чате %s на %s с — меняю только подпись", msg.chat.id, ex.retry_after)
                try:
                    res = await msg.edit_caption(caption=text, reply_markup=markup)
                    return res if isinstance(res, Message) else msg
                except (TelegramBadRequest, TelegramRetryAfter):
                    return msg
            except TelegramBadRequest as ex:
                if "not modified" in str(ex):
                    return msg
                if from_cache and cache:  # протухший file_id — перерисуем
                    _file_ids.pop(cache, None)
                    continue
                if cb and _has_media(msg):  # не вышло отредактировать — шлём заново
                    await _delete(msg)
                    res = await _send(msg, media, animated, text, markup)
                    _remember(cache, res)
                    return res
                raise
        return None

    # без картинки
    try:
        if cb and not _has_media(msg):
            res = await msg.edit_text(text, reply_markup=markup)
            return res if isinstance(res, Message) else msg
    except TelegramBadRequest as ex:
        if "not modified" in str(ex):
            return msg
    if cb:
        await _delete(msg)
    return await msg.answer(text, reply_markup=markup)


async def toast(cb: CallbackQuery, text: str = "", alert: bool = False) -> None:
    try:
        await cb.answer(EMOJI.strip(text), show_alert=alert)
    except TelegramBadRequest:
        pass


async def notify(bot: Bot, user_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
    """Сообщение игроку вне диалога (уведомления). Не падает, если бот заблокирован."""
    try:
        await bot.send_message(user_id, EMOJI.strip(text), reply_markup=markup)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False
    except Exception:  # noqa: BLE001
        log.exception("notify failed for %s", user_id)
        return False
