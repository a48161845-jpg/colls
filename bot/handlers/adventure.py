"""Приключения: выбор локации и пошаговые бои."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..bot_ctx import notify_inviter
from ..data import balance as B
from ..data.monsters import LOC, LOCATIONS
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import combat, players
from ..ui import screen, toast
from ..utils.fmt import esc, num
from ..utils.texts import item_line, levelup_line, reward_line

router = Router(name="adventure")


# ---------------------------------------------------------------- список локаций
async def show_locations(event, db: Database) -> None:
    p = await players.get(db, event.from_user.id)
    st = await combat.get_state(db, p["user_id"])
    if st:
        await show_battle(event, st)
        return
    cur, mx, _ = await players.energy(db, p)
    lines = [f"{e('adventure')} <b>Приключения</b>", f"{e('energy')} Энергия: <b>{int(cur)}/{mx}</b>\n"]
    rows = []
    for loc in LOCATIONS:
        hi = loc["max"] if loc["max"] < 900 else "∞"
        if p["level"] >= loc["min"]:
            lines.append(f"{loc['icon']} <b>{loc['name']}</b> · ур. {loc['min']}–{hi}")
            rows.append([(f"{loc['icon']} {loc['name']}", f"adv:loc:{loc['key']}")])
        else:
            lines.append(f"{e('lock')} <b>{loc['name']}</b> · откроется на {loc['min']} ур.")
    await screen(event, "\n".join(lines), kb(*rows, back()),
                 img=lambda: cards.banner("Приключения", "Куда отправимся?", "adventure"), cache="b:adv")


@router.callback_query(F.data == "adv")
async def cb_adv(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_locations(cb, db)
    await toast(cb)


@router.message(Command("adv"))
async def cmd_adv(m: Message, db: Database, player: dict) -> None:
    await show_locations(m, db)


@router.callback_query(F.data.startswith("adv:loc:"))
async def cb_location(cb: CallbackQuery, db: Database, player: dict) -> None:
    key = cb.data.split(":")[2]
    loc = LOC.get(key)
    p = await players.get(db, cb.from_user.id)
    if not loc or p["level"] < loc["min"]:
        await toast(cb, "Локация недоступна.", True)
        return
    cur, mx, _ = await players.energy(db, p)
    text = (f"{loc['icon']} <b>{loc['name']}</b>\n<i>{loc['desc']}</i>\n\n"
            f"Враги: {', '.join(m[0] for m in loc['monsters'])}\n"
            f"{e('boss')} Босс: <b>{loc['boss'][0]}</b>\n\n"
            f"{e('energy')} Энергия: <b>{int(cur)}/{mx}</b>")
    markup = kb([(f"{plain('atk')} Искать врага ({B.EXPEDITION_COST}{plain('energy')})", f"adv:go:{key}:0")],
                [(f"{plain('boss')} Вызвать босса ({B.BOSS_COST}{plain('energy')})", f"adv:go:{key}:1")],
                [(f"{plain('adventure')} Локации", "adv")], back())
    await screen(cb, text, markup, img=lambda: cards.location_card(key), cache=f"loc:{key}")
    await toast(cb)


# ---------------------------------------------------------------- бой
def _battle_kb(st: dict):
    left = st["potions_have"] - st["potions_used"]
    skill = f"{plain('skill')} Умение" + (f" ({st['cd']})" if st["cd"] else "")
    return kb([(f"{plain('atk')} Атака", "bt:attack"), (skill, "bt:skill")],
              [(f"{plain('potion')} Зелье ({left})", "bt:potion"), (f"{plain('flee')} Бежать", "bt:flee")])


def _battle_text(st: dict) -> str:
    M = st["m"]
    head = (f"{e('boss') if st['boss'] else '⚔️'} <b>{esc(M['name'])}</b> · ур. {M['lvl']}"
            if not st["done"] else "")
    log = "\n".join(st["log"]) if st["log"] else "Бой начался! Выбери действие."
    return f"{head}\n\n{log}" if head else log


async def show_battle(event, st: dict) -> None:
    await screen(event, _battle_text(st), _battle_kb(st), img=lambda: cards.battle_card(st))


async def show_result(cb: CallbackQuery, st: dict) -> None:
    res = st["result"]
    kind = res["kind"]
    loc = st["loc"]
    again = (f"{plain('atk')} Ещё раз", f"adv:go:{loc}:{1 if st['boss'] else 0}")
    nav = [[again], [(f"{plain('adventure')} Локации", "adv"), (f"{plain('hero')} Меню", "menu")]]
    log = "\n".join(st["log"])
    if kind == "win":
        text = f"{log}\n\n{e('win')} <b>Победа!</b>\n{reward_line(res)}{levelup_line(res.get('levelup'))}"
        item = res.get("item")
        if item:
            text += f"\n\n{e('chest')} Добыча: {item_line(item)}"
            nav.insert(0, [(f"{plain('bag')} Осмотреть добычу", f"inv:item:{item['id']}")])
            await screen(cb, text, kb(*nav), img=lambda: cards.item_card(item, "Новая находка!"))
        else:
            await screen(cb, text, kb(*nav), img=lambda: cards.banner("Победа!", st["m"]["name"] + " повержен", "win"), cache="b:win")
        await notify_inviter(cb.bot, res.get("levelup"))
    elif kind == "lose":
        text = f"{log}\n\n{e('lose')} <b>Поражение.</b> Потеряно {e('gold')} {num(res.get('gold_lost', 0))}.\nУсиль героя и возвращайся!"
        await screen(cb, text, kb(*nav), img=lambda: cards.banner("Поражение", "Ты отступил, чтобы вернуться", "lose"), cache="b:lose")
    else:
        text = f"{log}\n\n{e('flee')} Ты скрылся от врага. Энергия потрачена."
        await screen(cb, text, kb(*nav), img=lambda: cards.banner("Бегство", "Живой — значит победил", "adventure"), cache="b:flee")


@router.callback_query(F.data.startswith("adv:go:"))
async def cb_go(cb: CallbackQuery, db: Database, player: dict) -> None:
    _, _, key, boss = cb.data.split(":")
    res = await combat.start(db, cb.from_user.id, key, boss == "1")
    if not res["ok"]:
        msg = res["msg"]
        if "need" in res:
            msg += f" Нужно {res['need']}⚡."
        await toast(cb, msg, True)
        return
    await show_battle(cb, res["state"])
    await toast(cb, "Продолжаем бой!" if res.get("resumed") else "")


@router.callback_query(F.data.startswith("bt:"))
async def cb_battle(cb: CallbackQuery, db: Database, player: dict) -> None:
    action = cb.data.split(":")[1]
    if action not in ("attack", "skill", "potion", "flee"):
        await toast(cb)
        return
    before = await combat.get_state(db, cb.from_user.id)
    if not before:
        await toast(cb, "Бой уже закончился.", True)
        await show_locations(cb, db)
        return
    st = await combat.act(db, cb.from_user.id, action)
    if st["done"]:
        await show_result(cb, st)
        await toast(cb)
        return
    if st["log"] and st["log"][0].startswith(e("no")):  # действие не потратило ход
        await toast(cb, "Это сейчас недоступно.")
    await show_battle(cb, st)
    await toast(cb)
