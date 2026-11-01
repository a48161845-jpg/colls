"""Админ-команды (только для ADMIN_IDS из .env)."""
from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db.core import Database
from ..emoji import DEFAULTS, EMOJI, e
from ..keyboards.common import kb
from ..services import admin as admin_svc, broadcast, prices
from ..ui import notify, screen
from ..utils.fmt import dur, esc, now, num

log = logging.getLogger(__name__)
router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, event: Message, settings: Settings) -> bool:
        return bool(event.from_user and event.from_user.id in settings.admin_ids)


router.message.filter(IsAdmin())


def _ago(ts: float) -> str:
    return dur(max(0, now() - ts)) + " назад" if ts else "никогда"


def _pct(a: float, b: float) -> str:
    return f"{a / b * 100:.0f}%" if b else "0%"


ADMIN_TABS = [("ov", "Обзор"), ("mn", "Деньги"), ("pl", "Игроки"), ("ec", "Экономика")]


def _admin_kb(active: str):
    row = [((f"• {t}" if k == active else t), f"adm:{k}") for k, t in ADMIN_TABS]
    return kb(row[:2], row[2:], [("Команды", "adm:cmd"), ("Обновить", f"adm:{active}")])


async def _render(db: Database, tab: str) -> str:
    if tab == "mn":
        m = await admin_svc.money(db)
        prod = "\n".join(f"  {esc(r['payload'])}: {r['n']} шт. · {num(r['stars'])}⭐" for r in m["by_product"]) or "  пока нет"
        top = "\n".join(f"  <code>{r['user_id']}</code> {esc(r['name'])}: {num(r['stars'])}⭐ ({r['n']})" for r in m["top_payers"]) or "  пока нет"
        last = "\n".join(f"  {_ago(r['created_at'])} · {r['stars']}⭐ · <code>{esc(r['charge_id'][:18])}</code>" for r in m["last"]) or "  пока нет"
        return (f"{e('stars')} <b>Деньги</b>\n\nВсего: <b>{num(m['total'])}⭐</b> · платежей {num(m['count'])}\n"
                f"За 24ч: <b>{num(m['periods'][0])}⭐</b> · 7 дн: <b>{num(m['periods'][1])}⭐</b> · 30 дн: <b>{num(m['periods'][2])}⭐</b>\n"
                f"14 дней: <code>{admin_svc.spark(m['spark'])}</code>\n\n"
                f"Платящих: <b>{num(m['payers'])}</b> из {num(m['players'])} ({_pct(m['payers'], m['players'])})\n"
                f"Средний чек на плательщика: <b>{m['arppu']:.0f}⭐</b>\n\n<b>Товары</b>\n{prod}\n\n"
                f"<b>Топ плательщиков</b>\n{top}\n\n<b>Последние платежи</b>\n{last}")
    if tab == "pl":
        d = await admin_svc.people(db)
        names = {"warrior": "Воины", "mage": "Маги", "rogue": "Клинки"}
        total = sum(r["n"] for r in d["classes"]) or 1
        classes = "\n".join(f"  {names.get(r['cls'], r['cls'])}: {r['n']} ({_pct(r['n'], total)})" for r in d["classes"])
        levels = "\n".join(f"  {r['b'] * 10}–{r['b'] * 10 + 9}: {r['n']}" for r in d["levels"])
        top = "\n".join(f"  {i}. <code>{r['user_id']}</code> {esc(r['name'])} · ур. {r['level']}" for i, r in enumerate(d["top"], 1))
        return (f"{e('hero')} <b>Игроки</b>\n\nСредний уровень: <b>{d['avg_level']:.1f}</b> · перерождались: {d['reborn']} · "
                f"пришли по рефералке: {d['referrals']}\n\n<b>Классы</b>\n{classes}\n\n<b>Уровни</b>\n{levels}\n\n<b>Топ уровней</b>\n{top}")
    if tab == "ec":
        d = await admin_svc.economy(db)
        n = d["n"] or 1
        items = ", ".join(f"{r['rarity']}: {num(r['n'])}" for r in d["items"]) or "нет"
        rich = "\n".join(f"  <code>{r['user_id']}</code> {esc(r['name'])}: {num(r['gold'])}" for r in d["richest"])
        guilds = ", ".join(f"{esc(r['name'])} (ур. {r['level']})" for r in d["guild_top"]) or "нет"
        return (f"{e('gold')} <b>Экономика</b>\n\nЗолото в игре: <b>{num(d['gold'])}</b> (в среднем {num(d['gold'] // n)})\n"
                f"Кристаллы: <b>{num(d['crystals'])}</b> · эссенция: {num(d['essence'])} · метки: {num(d['marks'])}\n\n"
                f"Побед в боях: {num(d['kills'])} · ударов по жиле: {num(d['taps'])} · боёв арены за 24ч: {d['arena_24h']}\n"
                f"Рынок: {d['market_n']} лотов, средняя цена {num(int(d['market_avg']))}\n"
                f"Предметы: {items}\n\n<b>Самые богатые</b>\n{rich}\n\nТоп гильдий: {guilds}")
    if tab == "cmd":
        return ("<b>Команды</b>\n"
                "/user &lt;id&gt; — карточка игрока\n"
                "/give &lt;id&gt; &lt;gold|crystals|essence|marks|potions&gt; &lt;число&gt;\n"
                "/ban &lt;id&gt; · /unban &lt;id&gt;\n"
                "/broadcast — рассылка (текст с форматированием, медиа или ответом на сообщение)\n"
                "/refund &lt;charge_id&gt; — вернуть Stars\n"
                "/emojis · /setemoji &lt;имя&gt; [id] · /delemoji &lt;имя&gt;\n"
                "/price — список цен · /price &lt;ключ&gt; &lt;цена|reset&gt;\n"
                "/discount &lt;ключ|all|stars|packs|prem|cr&gt; &lt;процент&gt; [часы] · /discount off")
    o = await admin_svc.overview(db)
    ret = f"{_pct(o['returned'], o['cohort'])} ({o['returned']}/{o['cohort']})" if o["cohort"] else "нет данных"
    return (f"{e('top')} <b>Админ-панель · обзор</b>\n\n"
            f"Игроков: <b>{num(o['total'])}</b>\n"
            f"Новых: за 24ч <b>{o['new'][0]}</b> · 7 дн <b>{o['new'][1]}</b> · 30 дн <b>{o['new'][2]}</b>\n"
            f"7 дней: <code>{admin_svc.spark(o['new_spark'])}</code>\n"
            f"Активных: за 24ч <b>{o['active'][0]}</b> · 7 дн <b>{o['active'][1]}</b> · 30 дн <b>{o['active'][2]}</b>\n"
            f"Вернулись (пришли 1–7 дней назад и заходили за сутки): {ret}\n\n"
            f"{e('premium')} Premium: <b>{o['premium']}</b> ({_pct(o['premium'], o['total'])}) · заблокировано: {o['banned']}\n"
            f"{e('guild')} Гильдий: {o['guilds']} (в них {_pct(o['in_guild'], o['total'])} игроков) · приглашений: {o['invites']}\n"
            f"{e('market')} Лотов на рынке: {o['listings']} · идут бои: {o['battles']}")


@router.message(Command("admin"))
async def cmd_admin(m: Message, db: Database) -> None:
    await screen(m, await _render(db, "ov"), _admin_kb("ov"))


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(cb: CallbackQuery, db: Database, settings: Settings) -> None:
    if cb.from_user.id not in settings.admin_ids:
        await cb.answer()
        return
    tab = cb.data.split(":")[1]
    await screen(cb, await _render(db, tab), _admin_kb("ov" if tab == "cmd" else tab))
    await cb.answer()


@router.message(Command("user"))
async def cmd_user(m: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip().lstrip("#@")
    uid = int(arg) if arg.isdigit() else await db.scalar("SELECT user_id FROM players WHERE lower(username)=lower(?)", (arg,))
    card = await admin_svc.user_card(db, uid) if uid else None
    if not card:
        await m.answer("Формат: /user &lt;id или username&gt;. Игрок не найден.")
        return
    p = card["p"]
    await m.answer(
        f"{e('hero')} <b>{esc(p['name'])}</b> · <code>{p['user_id']}</code>" + (f" · @{esc(p['username'])}" if p["username"] else "") + "\n"
        f"Класс: {p['cls']} · ур. <b>{p['level']}</b> · рейтинг {p['rating']}" + (" · <b>ЗАБЛОКИРОВАН</b>" if p["banned"] else "") + "\n"
        f"{e('gold')} {num(p['gold'])} · {e('crystal')} {num(p['crystals'])} · {e('essence')} {num(p['essence'])} · метки {p['marks']}\n"
        f"Побед: {num(p['kills'])} · ударов: {num(p['taps'])} · серия входов: {p['streak']}\n"
        f"Гильдия: {esc(card['guild']) if card['guild'] else '—'} · приглашено друзей: {card['refs']}\n"
        f"Premium: {'до ' + dur(p['premium_until'] - now()) if p['premium_until'] > now() else 'нет'}\n"
        f"Донат: {num(card['stars'])}⭐ ({card['payments']} платежей)\n"
        f"Создан: {_ago(p['created_at'])} · был: {_ago(p['last_seen'])}")


@router.message(Command("give"))
async def cmd_give(m: Message, command: CommandObject, db: Database) -> None:
    parts = (command.args or "").split()
    if len(parts) != 3 or not parts[0].lstrip("-").isdigit() or not parts[2].lstrip("-").isdigit():
        await m.answer("Формат: /give &lt;id&gt; &lt;gold|crystals|essence|marks|potions&gt; &lt;число&gt;")
        return
    ok = await admin_svc.give(db, int(parts[0]), parts[1], int(parts[2]))
    await m.answer("Готово." if ok else "Не удалось: проверь id и тип валюты.")


@router.message(Command("ban", "unban"))
async def cmd_ban(m: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await m.answer("Формат: /ban &lt;id&gt;")
        return
    ok = await admin_svc.set_ban(db, int(arg), command.command == "ban")
    await m.answer("Готово." if ok else "Игрок не найден.")


_pending: dict[str, tuple[int, broadcast.Payload]] = {}   # токен -> (админ, рассылка), ждёт подтверждения
_tasks: set[asyncio.Task] = set()


@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message, bot: Bot, db: Database) -> None:
    pl = broadcast.build(m)
    if pl is None:
        await m.answer(
            "<b>Рассылка</b>\n"
            "• <code>/broadcast текст</code> — форматирование сохраняется (жирный, ссылки, спойлеры, премиум-эмодзи); "
            "можно и писать HTML-теги руками.\n"
            "• Фото/видео/гиф с подписью <code>/broadcast подпись</code> — уйдёт с медиа.\n"
            "• <code>/broadcast</code> ответом на любое сообщение — оно разошлётся как есть.\n"
            "Сначала придёт предпросмотр, потом подтверждение.")
        return
    try:                                   # предпросмотр — тем же способом, каким уйдёт игрокам
        await broadcast.send_one(bot, m.chat.id, pl)
    except Exception as ex:  # noqa: BLE001
        await m.answer(f"Telegram не принял это сообщение, проверь теги: {esc(ex)}")
        return
    ids = await admin_svc.all_user_ids(db)
    token = secrets.token_hex(4)
    _pending[token] = (m.from_user.id, pl)
    await m.answer(f"☝️ Так увидят игроки ({pl.describe()}). Получателей: <b>{len(ids)}</b>.",
                   reply_markup=kb([(f"Отправить {len(ids)}", f"bc:go:{token}"), ("Отмена", f"bc:no:{token}")]))


@router.callback_query(F.data.startswith("bc:"))
async def cb_broadcast(cb: CallbackQuery, bot: Bot, db: Database, settings: Settings) -> None:
    if cb.from_user.id not in settings.admin_ids:
        await cb.answer()
        return
    _, action, token = cb.data.split(":", 2)
    entry = _pending.pop(token, None)
    if entry is None or entry[0] != cb.from_user.id:
        await cb.answer("Рассылка уже отправлена или отменена.", show_alert=True)
        return
    if action == "no":
        await cb.message.edit_text("Рассылка отменена.")
        await cb.answer()
        return
    ids = await admin_svc.all_user_ids(db)
    await cb.message.edit_text(f"Рассылка пошла: {len(ids)} получателей…")
    await cb.answer()
    chat_id = cb.message.chat.id

    async def job() -> None:
        sent, total = await broadcast.run(bot, ids, entry[1])
        await notify(bot, chat_id, f"Рассылка завершена. Доставлено: <b>{sent}/{total}</b>")

    task = asyncio.create_task(job())      # не блокируем обработку остальных апдейтов
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.message(Command("refund"))
async def cmd_refund(m: Message, command: CommandObject, bot: Bot, db: Database) -> None:
    charge = (command.args or "").strip()
    pay = await admin_svc.find_payment(db, charge) if charge else None
    if not pay:
        await m.answer("Платёж не найден. Формат: /refund &lt;charge_id&gt;")
        return
    try:
        await bot.refund_star_payment(user_id=pay["user_id"], telegram_payment_charge_id=charge)
    except Exception as ex:  # noqa: BLE001
        await m.answer(f"Telegram отказал: {esc(ex)}")
        return
    await m.answer(f"Возврат {pay['stars']}⭐ выполнен. Выданные игроку награды не отзываются автоматически — "
                   "при необходимости спиши их через /give с минусом.")


# ---------------------------------------------------------------- премиум-эмодзи
def _custom_ids(m: Message) -> list[str]:
    ents = (m.entities or []) + (m.caption_entities or [])
    return [x.custom_emoji_id for x in ents if x.type == "custom_emoji" and x.custom_emoji_id]


@router.message(Command("emojis"))
async def cmd_emojis(m: Message) -> None:
    lines = ["<b>Имена эмодзи</b> (✅ — задан премиум-ID):"]
    for name, fb in DEFAULTS.items():
        lines.append(f"{'✅' if name in EMOJI.custom else '▫️'} <code>{name}</code> {fb}")
    lines.append("\nЗадать: <code>/setemoji gold 5368324170671202286</code>\n"
                 "или отправь <code>/setemoji gold</code> и вставь в это же сообщение премиум-эмодзи.\n"
                 "Любое сообщение с премиум-эмодзи без команды — бот вернёт их ID.")
    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await m.answer(text[i:i + 3800])


@router.message(Command("setemoji"))
async def cmd_setemoji(m: Message, command: CommandObject, db: Database) -> None:
    parts = (command.args or "").split()
    ids = _custom_ids(m)
    if not parts or parts[0] not in DEFAULTS:
        await m.answer("Формат: /setemoji &lt;имя&gt; &lt;id&gt; — имена смотри в /emojis")
        return
    name = parts[0]
    cid = parts[1] if len(parts) > 1 and parts[1].isdigit() else (ids[0] if ids else None)
    if not cid:
        await m.answer("Укажи ID цифрами или вставь премиум-эмодзи в сообщение.")
        return
    await EMOJI.set(db, name, cid)
    await m.answer(f"Готово: <code>{name}</code> → {EMOJI.render(name)} (id {cid})")


@router.message(Command("delemoji"))
async def cmd_delemoji(m: Message, command: CommandObject, db: Database) -> None:
    name = (command.args or "").strip()
    if name not in DEFAULTS:
        await m.answer("Неизвестное имя. Смотри /emojis")
        return
    await EMOJI.unset(db, name)
    await m.answer("Сброшено на обычный эмодзи.")


@router.message(~F.text.startswith("/"))
async def any_custom_emoji(m: Message) -> None:
    ids = _custom_ids(m)
    if ids:
        await m.answer("ID премиум-эмодзи:\n" + "\n".join(f"<code>{i}</code>" for i in ids))


# ---------------------------------------------------------------- цены и скидки
@router.message(Command("price"))
async def cmd_price(m: Message, command: CommandObject, db: Database) -> None:
    args = (command.args or "").split()
    if not args:
        await m.answer("<b>Цены</b> (Stars ⭐ / кристаллы 💎)\n\n" + prices.describe() +
                       "\n\n<code>/price pack:gems_s 20</code> — поставить цену\n"
                       "<code>/price pack:gems_s reset</code> — вернуть базовую\n"
                       "<code>/discount all 30 24</code> — скидка 30% на всё на 24 часа")
        return
    key = args[0]
    cat = prices.catalog()
    if key not in cat or len(args) != 2:
        await m.answer("Формат: /price &lt;ключ&gt; &lt;цена|reset&gt;. Ключи — в /price.")
        return
    if args[1].lower() == "reset":
        await prices.set_price(db, key, None)
        await m.answer(f"Цена <code>{key}</code> возвращена к базовой: {cat[key][1]}.")
        return
    if not args[1].isdigit() or not 1 <= int(args[1]) <= 100_000:
        await m.answer("Цена — целое число от 1 до 100000.")
        return
    await prices.set_price(db, key, int(args[1]))
    await m.answer(f"Готово: <code>{key}</code> теперь стоит <b>{prices.price(key, cat[key][1])}</b>. "
                   "Счета, уже выставленные игрокам по старой цене, оплатить не получится — они выставят новый.")


@router.message(Command("discount"))
async def cmd_discount(m: Message, command: CommandObject, db: Database) -> None:
    args = (command.args or "").split()
    groups = prices.groups()
    if args and args[0].lower() == "off":
        await prices.set_discount(db, groups["all"], 0)
        await m.answer("Все скидки сняты.")
        return
    if len(args) < 2 or not args[1].isdigit() or not 0 <= int(args[1]) <= 95:
        await m.answer("Формат: <code>/discount &lt;ключ|all|stars|packs|prem|cr&gt; &lt;процент 0–95&gt; [часы]</code>\n"
                       "Пример: <code>/discount packs 50 48</code> — −50% на кристаллы за Stars на двое суток.\n"
                       "<code>/discount off</code> — снять все скидки. Ключи — в /price.")
        return
    target = args[0]
    keys = groups.get(target) or ([target] if target in prices.catalog() else [])
    if not keys:
        await m.answer("Не знаю такой товар или группу. Список — в /price.")
        return
    hours = None
    if len(args) > 2:
        try:
            hours = float(args[2].replace(",", "."))
        except ValueError:
            hours = -1
        if hours <= 0:
            await m.answer("Срок — число часов, например 24.")
            return
    pct = int(args[1])
    await prices.set_discount(db, keys, pct, hours)
    when = f" на {args[2]} ч" if hours else " без срока"
    await m.answer(f"Скидка {pct}% на {len(keys)} поз.{when if pct else ''}." if pct else f"Скидка снята ({len(keys)} поз.).")
