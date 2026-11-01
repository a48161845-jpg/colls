"""Стенд для сквозных тестов: настоящий Dispatcher aiogram + поддельная сессия вместо сети Telegram.

Harness.say("/start", user=1)  — пользователь пишет сообщение
Harness.press("idle:tap")      — пользователь нажимает inline-кнопку на ПОСЛЕДНЕМ сообщении бота
Harness.text / .buttons        — текст и callback_data кнопок последнего ответа бота
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, AnswerPreCheckoutQuery, DeleteMessage, EditMessageCaption, EditMessageMedia,
                             CopyMessage, EditMessageText, GetMe, SendAnimation, SendInvoice, SendMessage, SendPhoto, SetMyCommands)
from aiogram.types import Message, MessageId, User

from bot.app import build_dispatcher
from bot.config import Settings

BOT_ID = 999


class _ErrorCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@dataclass
class Out:
    kind: str           # message / photo / edit_text / edit_media
    chat_id: int
    text: str
    buttons: list[str]  # callback_data (и url) всех кнопок
    labels: list[str]
    message_id: int


_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a", "tg-emoji",
                 "tg-spoiler", "blockquote", "span"}
_STRAY_LT = re.compile(r"<(?!/?(?:%s)[\s>])" % "|".join(re.escape(t) for t in _ALLOWED_TAGS))


class _HtmlCheck(HTMLParser):
    """Проверяет то, на что ругается Telegram: неизвестные/незакрытые теги."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_TAGS:
            self.problems.append(f"недопустимый тег <{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"сломана вложенность </{tag}>")
        else:
            self.stack.pop()


def html_problems(text: str) -> list[str]:
    p = _HtmlCheck()
    p.feed(text)
    p.close()
    out = list(p.problems)
    if p.stack:
        out.append(f"не закрыты теги: {p.stack}")
    if _STRAY_LT.search(text):
        out.append("«<» вне тега (нужно экранировать)")
    return out


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self.outs: list[Out] = []
        self.toasts: list[tuple[str, bool]] = []
        self.invoices: list[SendInvoice] = []
        self.reply_kbs: list = []
        self.copies: list[CopyMessage] = []
        self.animations: list = []
        self.precheckout: list[AnswerPreCheckoutQuery] = []
        self.deleted: list[tuple[int, int]] = []
        self.msgs: dict[tuple[int, int], dict] = {}
        self.last_msg: dict[int, dict] = {}
        self._mid = 1000

    async def close(self) -> None:
        pass

    async def stream_content(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError

    def _markup(self, method) -> tuple[list[str], list[str], dict | None]:
        rm = getattr(method, "reply_markup", None)
        if rm is None:
            return [], [], None
        if not hasattr(rm, "inline_keyboard"):  # reply-клавиатура или её удаление
            self.reply_kbs.append(rm)
            return [], [], None
        data, labels = [], []
        for row in rm.inline_keyboard:
            for b in row:
                data.append(b.callback_data or b.url or "")
                labels.append(b.text)
        return data, labels, rm.model_dump(exclude_none=True)

    def _validate(self, method, callback_data: list[str]) -> None:
        """Ограничения настоящего Telegram, которые легко нарушить."""
        name = type(method).__name__
        for cd in callback_data:
            if cd.startswith("http"):  # url-кнопка, у неё другой лимит
                continue
            if len(cd.encode()) > 64:
                self.violations.append(f"{name}: callback_data > 64 байт: {cd!r}")
        if isinstance(method, (SendMessage, EditMessageText)):
            text, limit = method.text or "", 4096
        elif isinstance(method, (SendPhoto, SendAnimation)):
            text, limit = method.caption or "", 1024
        elif isinstance(method, EditMessageCaption):
            text, limit = method.caption or "", 1024
        elif isinstance(method, EditMessageMedia):
            text, limit = getattr(method.media, "caption", "") or "", 1024
        else:
            return
        if len(text) > limit:
            self.violations.append(f"{name}: текст {len(text)} > {limit} символов")
        if not text.strip():
            self.violations.append(f"{name}: пустой текст")
        for prob in html_problems(text):
            self.violations.append(f"{name}: HTML: {prob} в {text[:80]!r}")

    def _store(self, bot: Bot, chat_id: int, mid: int, *, text=None, caption=None, photo=False, markup=None,
               animation=False) -> Message:
        d = {"message_id": mid, "date": int(time.time()), "chat": {"id": chat_id, "type": "private"},
             "from": {"id": BOT_ID, "is_bot": True, "first_name": "Bot", "username": "ashen_test_bot"}}
        if text is not None:
            d["text"] = text
        if caption is not None:
            d["caption"] = caption
        if photo:
            d["photo"] = [{"file_id": f"f{mid}", "file_unique_id": f"u{mid}", "width": 960, "height": 540}]
        if animation:
            d["animation"] = {"file_id": f"a{mid}", "file_unique_id": f"ua{mid}", "width": 800, "height": 450, "duration": 1}
            d["document"] = {"file_id": f"a{mid}", "file_unique_id": f"ua{mid}"}
        if markup:
            d["reply_markup"] = markup
        self.msgs[(chat_id, mid)] = d
        self.last_msg[chat_id] = d
        return Message.model_validate(d, context={"bot": bot})

    async def make_request(self, bot: Bot, method, timeout=None):  # type: ignore[override]
        if isinstance(method, GetMe):
            return User(id=BOT_ID, is_bot=True, first_name="Bot", username="ashen_test_bot")
        if isinstance(method, (SetMyCommands, DeleteMessage)):
            if isinstance(method, DeleteMessage):
                self.deleted.append((method.chat_id, method.message_id))
                self.msgs.pop((method.chat_id, method.message_id), None)
            return True
        if isinstance(method, AnswerCallbackQuery):
            self.toasts.append((method.text or "", bool(method.show_alert)))
            return True
        if isinstance(method, AnswerPreCheckoutQuery):
            self.precheckout.append(method)
            return True
        if isinstance(method, CopyMessage):
            self._mid += 1
            self.copies.append(method)
            for prob in html_problems(method.caption or ""):
                self.violations.append(f"CopyMessage: HTML: {prob}")
            return MessageId(message_id=self._mid)
        data, labels, markup = self._markup(method)
        self._validate(method, data)
        if isinstance(method, SendMessage):
            self._mid += 1
            self.outs.append(Out("message", method.chat_id, method.text, data, labels, self._mid))
            return self._store(bot, method.chat_id, self._mid, text=method.text, markup=markup)
        if isinstance(method, SendAnimation):
            self._mid += 1
            self.animations.append(method)
            self.outs.append(Out("animation", method.chat_id, method.caption or "", data, labels, self._mid))
            return self._store(bot, method.chat_id, self._mid, caption=method.caption, animation=True, markup=markup)
        if isinstance(method, SendPhoto):
            self._mid += 1
            self.outs.append(Out("photo", method.chat_id, method.caption or "", data, labels, self._mid))
            return self._store(bot, method.chat_id, self._mid, caption=method.caption, photo=True, markup=markup)
        if isinstance(method, SendInvoice):
            self._mid += 1
            self.invoices.append(method)
            self.outs.append(Out("invoice", method.chat_id, method.title, [], [], self._mid))
            return self._store(bot, method.chat_id, self._mid, text=method.title)
        if isinstance(method, EditMessageText):
            self.outs.append(Out("edit_text", method.chat_id, method.text, data, labels, method.message_id))
            return self._store(bot, method.chat_id, method.message_id, text=method.text, markup=markup)
        if isinstance(method, EditMessageMedia):
            cap = getattr(method.media, "caption", "") or ""
            anim = type(method.media).__name__ == "InputMediaAnimation"
            self.outs.append(Out("edit_media", method.chat_id, cap, data, labels, method.message_id))
            return self._store(bot, method.chat_id, method.message_id, caption=cap, photo=not anim, animation=anim, markup=markup)
        if isinstance(method, EditMessageCaption):
            old = self.msgs.get((method.chat_id, method.message_id), {})
            self.outs.append(Out("edit_caption", method.chat_id, method.caption or "", data, labels, method.message_id))
            return self._store(bot, method.chat_id, method.message_id, caption=method.caption, photo="photo" in old,
                               animation="animation" in old, markup=markup)
        raise NotImplementedError(f"FakeSession: {type(method).__name__} не поддержан в тестах")


@dataclass
class Harness:
    dp: Any
    bot: Bot
    session: FakeSession
    errors: _ErrorCatcher
    admin_id: int
    uid_seq: int = field(default=0)

    # ------------------------------------------------------------ ввод
    def _user(self, uid: int, name: str | None = None) -> dict:
        return {"id": uid, "is_bot": False, "first_name": name or f"Игрок{uid}", "username": f"user{uid}"}

    async def say(self, text: str, user: int = 1, entities: list[dict] | None = None, extra: dict | None = None) -> None:
        self.uid_seq += 1
        msg = {"message_id": 10_000 + self.uid_seq, "date": int(time.time()), "chat": {"id": user, "type": "private"},
               "from": self._user(user)}
        if extra and "photo" in extra:   # медиа: текст идёт как подпись
            msg["caption"] = text
            if entities:
                msg["caption_entities"] = entities
        else:
            msg["text"] = text
            if entities:
                msg["entities"] = entities
        if extra:
            msg.update(extra)
        await self.dp.feed_raw_update(self.bot, {"update_id": self.uid_seq, "message": msg})

    async def press(self, data: str, user: int = 1) -> None:
        self.uid_seq += 1
        last = self.session.last_msg.get(user)
        assert last is not None, "у пользователя нет сообщения бота, на которое можно нажать"
        cb = {"id": str(self.uid_seq), "from": self._user(user), "chat_instance": "ci", "message": last, "data": data}
        await self.dp.feed_raw_update(self.bot, {"update_id": self.uid_seq, "callback_query": cb})

    async def pay(self, payload: str, stars: int, charge: str, user: int = 1, skip_precheckout: bool = False) -> None:
        """Как в Telegram: pre_checkout -> если бот ответил ok, приходит successful_payment.
        skip_precheckout=True шлёт только successful_payment (проверка защитных веток)."""
        self.uid_seq += 1
        if not skip_precheckout:
            pq = {"id": f"pq{self.uid_seq}", "from": self._user(user), "currency": "XTR", "total_amount": stars,
                  "invoice_payload": payload}
            await self.dp.feed_raw_update(self.bot, {"update_id": self.uid_seq, "pre_checkout_query": pq})
            if not self.session.precheckout[-1].ok:
                return  # Telegram не проведёт платёж, если бот отказал
        self.uid_seq += 1
        msg = {"message_id": 20_000 + self.uid_seq, "date": int(time.time()), "chat": {"id": user, "type": "private"},
               "from": self._user(user),
               "successful_payment": {"currency": "XTR", "total_amount": stars, "invoice_payload": payload,
                                      "telegram_payment_charge_id": charge, "provider_payment_charge_id": charge}}
        await self.dp.feed_raw_update(self.bot, {"update_id": self.uid_seq, "message": msg})

    # ------------------------------------------------------------ вывод
    def last(self, user: int = 1) -> Out:
        outs = [o for o in self.session.outs if o.chat_id == user]
        assert outs, f"бот ничего не отправил пользователю {user}"
        return outs[-1]

    def text(self, user: int = 1) -> str:
        return self.last(user).text

    def buttons(self, user: int = 1) -> list[str]:
        return self.last(user).buttons

    def find_button(self, prefix: str, user: int = 1) -> str:
        for b in self.buttons(user):
            if b.startswith(prefix):
                return b
        raise AssertionError(f"нет кнопки {prefix!r}; есть: {self.buttons(user)}")

    def assert_no_errors(self) -> None:
        bad = [r for r in self.errors.records]
        assert not bad, "Ошибки в обработчиках:\n" + "\n".join(f"{r.name}: {r.getMessage()} {r.exc_info[1] if r.exc_info else ''}" for r in bad)
        for o in self.session.outs:
            assert "Что-то пошло не так" not in o.text, f"сработал обработчик ошибок: {o.text}"
        assert not self.session.violations, "Нарушения правил Telegram:\n" + "\n".join(self.session.violations)


async def make_harness(db, admin_ids=(777,), premium_emoji=True, animated=False) -> Harness:
    settings = Settings(token="123:TEST", admin_ids=frozenset(admin_ids), db_path="", database_url="", premium_emoji=premium_emoji, premium_buttons=False, animated_images=animated,
                        log_level="ERROR", support="@support")
    session = FakeSession()
    bot = Bot("123456:TESTTOKEN", session=session)
    # роутеры — модульные синглтоны; в одном процессе тестов их нужно отвязывать от прошлого Dispatcher
    from bot.handlers import get_routers
    for r in get_routers():
        r._parent_router = None
    dp = await build_dispatcher(settings, db, throttle_interval=0.0, tap_interval=0.0)
    catcher = _ErrorCatcher()
    logging.getLogger().addHandler(catcher)
    return Harness(dp, bot, session, catcher, next(iter(admin_ids)) if admin_ids else 0)
