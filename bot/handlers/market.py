"""Рынок игроков."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..data import balance as B
from ..data.items import SLOT_ORDER, SLOTS
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb, pager
from ..services import market, players
from ..ui import notify, screen, toast
from ..utils.fmt import esc, num
from ..utils.texts import item_line, plain_item

router = Router(name="market")
PER = 5


async def show_market(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    total = await db.scalar("SELECT COUNT(*) FROM market", (), 0)
    rate = int(market.tax_rate(p) * 100)
    text = (f"{e('market')} <b>Рынок игроков</b>\n\nЛотов на продаже: <b>{total}</b>\n"
            f"Твоя комиссия при продаже: <b>{rate}%</b>" + (" (премиум)" if players.is_premium(p) else "") +
            f"\n{e('gold')} У тебя: {num(p['gold'])}\n\n<i>Выставить предмет можно из «Сумки».</i>")
    if note:
        text += f"\n\n{note}"
    rows = [[(f"{plain('market')} Все лоты", "mk:b:all:0")],
            [(f"{plain(SLOTS[s]['emoji'])} {SLOTS[s]['name']}", f"mk:b:{s}:0") for s in SLOT_ORDER[:2]],
            [(f"{plain(SLOTS[s]['emoji'])} {SLOTS[s]['name']}", f"mk:b:{s}:0") for s in SLOT_ORDER[2:]],
            [(f"{plain('bag')} Мои лоты", "mk:mine")], back()]
    await screen(event, text, kb(*rows), img=lambda: cards.banner("Рынок", "Торгуй с другими игроками", "market"), cache="b:market")


@router.callback_query(F.data == "mk")
async def cb_market(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_market(cb, db)
    await toast(cb)


@router.message(Command("market"))
async def cmd_market(m: Message, db: Database, player: dict) -> None:
    await show_market(m, db)


@router.callback_query(F.data.startswith("mk:b:"))
async def cb_browse(cb: CallbackQuery, db: Database, player: dict) -> None:
    _, _, slot, page = cb.data.split(":")
    page = int(page)
    flt = None if slot == "all" else slot
    rows, total = await market.browse(db, flt, page, PER, exclude=cb.from_user.id)
    title = "Все лоты" if not flt else SLOTS[flt]["name"]
    lines = [f"{e('market')} <b>{title}</b> · {total} шт. (от дешёвых к дорогим)\n"]
    buttons = []
    for r in rows:
        lines.append(f"{item_line(r)}\n   {e('gold')} <b>{num(r['price'])}</b>")
        buttons.append([(f"{plain_item(r)} · {num(r['price'])}{plain('gold')}", f"mk:v:{r['lid']}")])
    if not rows:
        lines.append("<i>Здесь пока пусто.</i>")
    nav = pager(f"mk:b:{slot}", page, total, PER)
    await screen(cb, "\n".join(lines), kb(*buttons, nav, [(f"{plain('market')} Рынок", "mk")]),
                 img=lambda: cards.banner(title, f"Лотов: {total}", "market"), cache=f"b:market:{slot}")
    await toast(cb)


@router.callback_query(F.data.startswith("mk:v:"))
async def cb_view(cb: CallbackQuery, db: Database, player: dict) -> None:
    lid = int(cb.data.split(":")[2])
    row = await market.get_listing(db, lid)
    if not row:
        await toast(cb, "Лот уже продан или снят.", True)
        await show_market(cb, db)
        return
    p = await players.get(db, cb.from_user.id)
    mine = row["seller_id"] == p["user_id"]
    seller = await players.get(db, row["seller_id"])
    text = (f"{item_line(row)}\n\nПродавец: <b>{esc(seller['name']) if seller else '—'}</b>\n"
            f"Цена: {e('gold')} <b>{num(row['price'])}</b> (у тебя {num(p['gold'])})")
    rows = []
    if mine:
        rows.append([(f"{plain('no')} Снять с продажи", f"mk:cancel:{lid}")])
    elif p["gold"] >= row["price"]:
        rows.append([(f"{plain('ok')} Купить за {num(row['price'])}", f"mk:buy:{lid}")])
    else:
        rows.append([(f"{plain('lock')} Не хватает золота", "noop")])
    rows.append([(f"{plain('market')} К лотам", "mk:b:all:0")])
    await screen(cb, text, kb(*rows), img=lambda: cards.item_card(row, f"Цена: {num(row['price'])}"))
    await toast(cb)


@router.callback_query(F.data.startswith("mk:buy:"))
async def cb_buy(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    res = await market.buy(db, cb.from_user.id, int(cb.data.split(":")[2]))
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        await show_market(cb, db)
        return
    it = res["item"]
    await notify(bot, res["seller_id"], f"{e('market')} Твой лот <b>{esc(it['name'])}</b> куплен за {e('gold')} {num(res['price'])}. "
                                        f"Комиссия: {num(res['tax'])}.")
    await toast(cb, "Покупка совершена!")
    await screen(cb, f"{e('ok')} <b>Куплено!</b>\n{item_line(it)}\n\nПредмет уже в твоей сумке.",
                 kb([(f"{plain('bag')} Осмотреть", f"inv:item:{it['id']}")], [(f"{plain('market')} Ещё лоты", "mk:b:all:0")]),
                 img=lambda: cards.item_card(it, "Покупка совершена"))


@router.callback_query(F.data == "mk:mine")
async def cb_mine(cb: CallbackQuery, db: Database, player: dict) -> None:
    rows = await market.my_listings(db, cb.from_user.id)
    lines = [f"{e('bag')} <b>Мои лоты</b> ({len(rows)}/{B.MARKET_MAX_LISTINGS})\n"]
    buttons = []
    for r in rows:
        lines.append(f"{item_line(r)}\n   {e('gold')} <b>{num(r['price'])}</b>")
        buttons.append([(f"{plain_item(r)} · {num(r['price'])}", f"mk:v:{r['lid']}")])
    if not rows:
        lines.append("<i>Ты ничего не продаёшь. Открой «Сумку» → предмет → «На рынок».</i>")
    await screen(cb, "\n".join(lines), kb(*buttons, [(f"{plain('market')} Рынок", "mk")]),
                 img=lambda: cards.banner("Мои лоты", f"{len(rows)} на продаже", "market"), cache="b:market:mine")
    await toast(cb)


@router.callback_query(F.data.startswith("mk:cancel:"))
async def cb_cancel(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await market.cancel(db, cb.from_user.id, int(cb.data.split(":")[2]))
    await toast(cb, "Лот снят." if res["ok"] else res["msg"], not res["ok"])
    await cb_mine(cb, db, player)
