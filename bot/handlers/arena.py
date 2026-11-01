"""Арена."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..data.shop import CRYSTAL_SHOP
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import arena, payments, players, prices
from ..ui import screen, toast
from ..utils.fmt import esc, num

router = Router(name="arena")


async def show_arena(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    left = arena.tries_left(p)
    rank = await arena.rank_of(db, p)
    text = (f"{e('arena')} <b>Арена</b>\n\nРейтинг: <b>{p['rating']}</b> · место <b>#{rank}</b>\n"
            f"Попыток сегодня: <b>{left}/{arena.tries_limit(p)}</b>\n\n"
            "Ты сражаешься с «призраком» другого игрока (его статы и экипировка) — он может быть оффлайн. "
            "Победа даёт рейтинг и золото. Если на арене пусто — выйдет Тень арены.")
    if note:
        text += f"\n\n{note}"
    rows = [[(f"{plain('atk')} В бой ({left})", "ar:fight")] if left > 0 else
            [(f"{plain('crystal')} +1 попытка ({prices.cost('arena', CRYSTAL_SHOP['arena']['cost'])}{plain('crystal')})", "ar:buy")],
            [(f"{plain('top')} Топ арены", "top:arena")], back()]
    await screen(event, text, kb(*rows), img=lambda: cards.banner("Арена", f"Рейтинг {p['rating']}", "arena"))


@router.callback_query(F.data == "ar")
async def cb_arena(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_arena(cb, db)
    await toast(cb)


@router.message(Command("arena"))
async def cmd_arena(m: Message, db: Database, player: dict) -> None:
    await show_arena(m, db)


@router.callback_query(F.data == "ar:fight")
async def cb_fight(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await arena.fight(db, cb.from_user.id)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        await show_arena(cb, db)
        return
    p = await players.get(db, cb.from_user.id)
    opp = res["opp"]
    sim = res["sim"]
    sign = "+" if res["delta"] >= 0 else ""
    text = (f"{e('win') if res['win'] else e('lose')} <b>{'Победа!' if res['win'] else 'Поражение'}</b> "
            f"над <b>{esc(opp['name'])}</b> (ур. {opp['level']}) за {sim['rounds']} раундов.\n"
            f"Рейтинг: <b>{res['rating']}</b> ({sign}{res['delta']}) · {e('gold')} +{num(res['gold'])}\n"
            f"Попыток осталось: <b>{res['tries_left']}</b>")
    me = {"name": p["name"], "cls": p["cls"], "level": p["level"]}
    markup = kb([(f"{plain('atk')} Ещё бой", "ar:fight")] if res["tries_left"] > 0 else [], [(f"{plain('arena')} Арена", "ar")], back())
    await screen(cb, text, markup, img=lambda: cards.arena_card(me, opp, res["win"], res["delta"], res["rating"]))
    await toast(cb)


@router.callback_query(F.data == "ar:buy")
async def cb_buy_try(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await payments.spend_crystals(db, cb.from_user.id, "arena")
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    await toast(cb, "Попытка добавлена!")
    await show_arena(cb, db, f"{e('ok')} Куплена дополнительная попытка.")
