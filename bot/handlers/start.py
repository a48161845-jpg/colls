"""Старт, выбор класса, главное меню, профиль, помощь, приглашения."""
from __future__ import annotations

from urllib.parse import urlencode

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..data import balance as B
from ..data.classes import CLASS_ORDER, CLASSES
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..keyboards.menu import hub_menu, main_menu, world_menu
from ..services import formulas, idle, items as items_svc, players
from ..ui import notify, screen, toast
from ..utils.fmt import bar, dur, esc, now, num
from ..utils.texts import reward_line, wallet

router = Router(name="start")


# ---------------------------------------------------------------- главное меню
async def menu_text(db: Database, p: dict) -> str:
    cur, mx, reg = await players.energy(db, p)
    pend, _ov = await idle.pending(db, p)
    xp_need = formulas.xp_needed(p["level"])
    lines = [
        f"{e('hero')} <b>{esc(players.display_name(p))}</b> · {esc(CLASSES[p['cls']]['name'])}",
        f"{e('level')} Ур. <b>{p['level']}</b> · {bar(p['xp'], xp_need, 10)} {num(p['xp'])}/{num(xp_need)}",
        wallet(p),
        f"{e('energy')} Энергия: <b>{int(cur)}/{mx}</b>" + (f" · +1 через {dur(reg * (1 - (cur % 1)))}" if cur < mx else ""),
    ]
    if pend["gold"] >= 1:
        lines.append(f"{e('idle')} В руднике ждёт: {e('gold')} <b>{num(pend['gold'])}</b>" + (" (хранилище полно!)" if pend["full"] else ""))
    if players.is_premium(p):
        lines.append(f"{e('premium')} Премиум ещё {dur(p['premium_until'] - now())}")
    return "\n".join(lines)


async def show_menu(target, db: Database, p: dict) -> None:
    await screen(target, await menu_text(db, p), main_menu(),
                 img=lambda: cards.banner("Пепельное королевство", "Выбери, чем заняться", "menu"), cache="b:menu")


@router.message(Command("menu"))
async def cmd_menu(m: Message, db: Database, player: dict, state: FSMContext) -> None:
    await state.clear()
    await show_menu(m, db, player)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, db: Database, player: dict, state: FSMContext) -> None:
    await state.clear()
    await show_menu(cb, db, await players.get(db, cb.from_user.id))
    await toast(cb)


@router.callback_query(F.data == "world")
async def cb_world(cb: CallbackQuery, player: dict) -> None:
    await screen(cb, f"{e('adventure')} <b>Мир</b>\n\nБои с монстрами, сюжетные главы и ежедневные задания.", world_menu(),
                 img=lambda: cards.banner("Мир", "Приключения, сюжет, задания", "adventure"), cache="b:world")
    await toast(cb)


@router.callback_query(F.data == "hub")
async def cb_hub(cb: CallbackQuery, player: dict) -> None:
    await screen(cb, f"{e('guild')} <b>Сообщество</b>\n\nГильдия, рынок, арена, рейтинги и приглашение друзей.", hub_menu(),
                 img=lambda: cards.banner("Сообщество", "Играй вместе с другими", "guild"), cache="b:hub")
    await toast(cb)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await toast(cb)


# ---------------------------------------------------------------- старт
def _class_screen_text() -> str:
    lines = [f"{e('fire')} <b>Пепельное королевство</b>\n",
             "Когда-то над этими землями горела Искра, осколок Первого Огня. Она берегла мир от тьмы. Однажды ночью "
             "пепельные сожгли Эмбервилль и украли огонёк, а ты очнулся среди углей. Теперь только ты можешь "
             "вернуть свет.\n",
             "<b>Выбери путь героя:</b>"]
    for key in CLASS_ORDER:
        c = CLASSES[key]
        lines.append(f"\n{e(c['emoji'])} <b>{c['name']}</b> — {c['desc']}\n<i>Умение «{c['skill_name']}»: {c['skill_desc']}</i>")
    return "\n".join(lines)


def _class_kb(ref: int = 0):
    suffix = f":{ref}" if ref else ""
    return kb(*[[(f"{plain(CLASSES[k]['emoji'])} {CLASSES[k]['name']}", f"start:cls:{k}{suffix}")] for k in CLASS_ORDER])


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, db: Database, player: dict | None, state: FSMContext) -> None:
    await state.clear()
    if player:
        await show_menu(m, db, player)
        return
    ref = 0
    arg = (command.args or "").strip()
    if arg.startswith("ref_") and arg[4:].isdigit():
        ref = int(arg[4:])
        if ref == m.from_user.id:
            ref = 0
    await screen(m, _class_screen_text(), _class_kb(ref),
                 img=lambda: cards.banner("Выбери свой путь", "Воин · Маг пепла · Теневой клинок", "menu"), cache="b:class")


@router.callback_query(F.data.startswith("start:cls:"))
async def cb_choose_class(cb: CallbackQuery, bot: Bot, db: Database, player: dict | None) -> None:
    if player:
        await toast(cb, "Герой уже создан.")
        await show_menu(cb, db, player)
        return
    parts = cb.data.split(":")
    cls = parts[2]
    if cls not in CLASSES:
        await toast(cb, "Неизвестный класс.", True)
        return
    ref = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    uid = cb.from_user.id
    inviter_ok = False
    async with db.transaction() as tx:
        if await players.get(tx, uid):  # двойной клик
            return
        if ref and not await players.get(tx, ref):
            ref = 0
        await players.create(tx, uid, cb.from_user.username, (cb.from_user.full_name or "Герой")[:24], cls, ref or None)
        await items_svc.give_starter_kit(tx, uid)
        if ref:
            await players.add(tx, uid, **B.REF_BONUS_NEW)
            inviter_ok = True
    text = (f"{e('win')} <b>Герой создан!</b> Ты — {e(CLASSES[cls]['emoji'])} {CLASSES[cls]['name']}.\n\n"
            "<b>С чего начать:</b>\n"
            f"1. {e('idle')} <b>Рудник</b> — тапай и копи золото, улучшай постройки.\n"
            f"2. {e('adventure')} <b>Приключения</b> — бои с монстрами и боссами, добыча.\n"
            f"3. {e('story')} <b>Сюжет</b> — первая глава ждёт.\n"
            f"4. {e('daily')} Заходи за <b>наградой</b> каждый день.\n")
    if inviter_ok:
        text += f"\n{e('ref')} Бонус за приглашение: {reward_line(B.REF_BONUS_NEW)}"
    await screen(cb, text, kb([(f"{plain('idle')} В рудник", "idle"), (f"{plain('story')} Начать сюжет", "story")],
                              [(f"{plain('hero')} В меню", "menu")]),
                 img=lambda: cards.banner("Добро пожаловать!", "Твоя история начинается", "win"), cache="b:welcome")
    if inviter_ok:
        await notify(bot, ref, f"{e('ref')} По твоей ссылке пришёл новый герой! Бонус придёт, когда он достигнет "
                               f"{B.REF_LEVEL_REQUIRED} уровня: {reward_line(B.REF_BONUS_INVITER)}")


# ---------------------------------------------------------------- профиль
@router.callback_query(F.data == "profile")
@router.message(Command("profile"))
async def show_profile(event: Message | CallbackQuery, db: Database, player: dict) -> None:
    uid = event.from_user.id
    p = await players.get(db, uid)
    st = await players.derived(db, p)
    guild_name = await db.scalar("SELECT name FROM guilds WHERE id=?", (p["guild_id"],)) if p["guild_id"] else None
    info = dict(name=p["name"], cls=p["cls"], level=p["level"], xp=p["xp"], xp_need=formulas.xp_needed(p["level"]),
                hp=st["hp"], atk=st["atk"], power=st["power"], premium=players.is_premium(p), guild=guild_name,
                marks=p["marks"], title=p["title"], rating=p["rating"])
    info["def"] = st["def"]
    eq = await players.equipped_items(db, uid)
    text = (f"{e('hero')} <b>{esc(players.display_name(p))}</b>\n{wallet(p)}\n"
            f"{e('potion')} Зелий: <b>{p['potions']}</b> · {e('boss')} Побед: <b>{num(p['kills'])}</b> · "
            f"{e('tap')} Тапов: <b>{num(p['taps'])}</b>\n")
    if st["idle_pct"]:
        text += f"{e('idle')} Бонус амулета к idle: <b>+{st['idle_pct']}%</b>\n"
    text += f"\n<i>Надето предметов: {len(eq)}/4 — управляй в «Сумке».</i>\nТвой ID: <code>{uid}</code> (для приглашений в гильдию)"
    markup = kb([(f"{plain('bag')} Сумка", "inv:0"), (f"{plain('help')} Помощь", "help")], back())
    await screen(event, text, markup, img=lambda: cards.hero_card(info))
    if isinstance(event, CallbackQuery):
        await toast(event)


# ---------------------------------------------------------------- помощь
HELP_TEXT = (
    "{help} <b>Как играть</b>\n\n"
    "{idle} <b>Рудник</b> — постройки копят золото, опыт и эссенцию, даже пока ты спишь (до лимита часов). "
    "Жми «Ударить» для золота прямо сейчас.\n"
    "{adventure} <b>Приключения</b> — пошаговые бои: атака, умение класса, зелье. За победу — опыт, золото, предметы.\n"
    "{story} <b>Сюжет</b> — 6 глав с выбором и бросками d20. Твои решения запоминаются, а финал зависит от пути.\n"
    "{quest} <b>Задания</b> — три новых задания каждый день.\n"
    "{bag} <b>Сумка</b> — экипировка в 4 слота, усиление до +10, продажа.\n"
    "{guild} <b>Гильдия</b> — общий босс, бонус к доходу рудника.\n"
    "{market} <b>Рынок</b> — торгуй предметами с другими игроками.\n"
    "{arena} <b>Арена</b> — рейтинговые бои, топ игроков.\n"
    "{rebirth} <b>Перерождение</b> с 30 уровня даёт навсегда +25% к idle и +5% к статам за метку.\n"
    "{shop} <b>Магазин</b> — Premium и кристаллы за Telegram Stars. Играть можно полностью бесплатно.\n\n"
    "Команды: /menu · /profile · /help"
)


@router.callback_query(F.data == "help")
@router.message(Command("help"))
async def show_help(event: Message | CallbackQuery, settings: Settings, player: dict | None) -> None:
    keys = {k: e(k) for k in ("help", "idle", "adventure", "story", "quest", "bag", "guild", "market", "arena", "rebirth", "shop")}
    text = HELP_TEXT.format(**keys)
    if settings.support:
        text += f"\nПоддержка: {esc(settings.support)}"
    markup = kb(back()) if player else None
    await screen(event, text, markup, img=lambda: cards.banner("Помощь", "Как устроена игра", "help"), cache="b:help")
    if isinstance(event, CallbackQuery):
        await toast(event)


# ---------------------------------------------------------------- приглашения
@router.callback_query(F.data == "ref")
@router.message(Command("ref"))
async def show_ref(event: Message | CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    uid = event.from_user.id
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    invited = await db.scalar("SELECT COUNT(*) FROM players WHERE ref_by=?", (uid,), 0)
    rewarded = await db.scalar("SELECT COUNT(*) FROM players WHERE ref_by=? AND ref_rewarded=1", (uid,), 0)
    text = (f"{e('ref')} <b>Приглашай друзей</b>\n\n"
            f"Друг получает: {reward_line(B.REF_BONUS_NEW)}\n"
            f"Ты получаешь, когда он дойдёт до {B.REF_LEVEL_REQUIRED} уровня: {reward_line(B.REF_BONUS_INVITER)}\n\n"
            f"Приглашено: <b>{invited}</b> · наград получено: <b>{rewarded}</b>\n\n"
            f"Твоя ссылка:\n<code>{link}</code>")
    share = "https://t.me/share/url?" + urlencode({"url": link, "text": "Присоединяйся к Пепельному королевству!"})
    await screen(event, text, kb([("Поделиться ссылкой", share, True)], back()),
                 img=lambda: cards.banner("Друзья", "Играть вместе веселее", "daily"), cache="b:ref")
    if isinstance(event, CallbackQuery):
        await toast(event)
