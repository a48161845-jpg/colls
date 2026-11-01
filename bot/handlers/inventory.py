"""Сумка: экипировка, усиление, продажа, выставление на рынок."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..data import balance as B
from ..data.items import MAX_PLUS, SLOT_ORDER, SLOTS
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb, pager
from ..services import formulas, items as items_svc, market, players
from ..ui import screen, toast
from ..utils.fmt import num
from ..utils.texts import item_line, plain_item

router = Router(name="inventory")
PER = 6


class SellState(StatesGroup):
    price = State()


# ---------------------------------------------------------------- список
async def show_inventory(event, db: Database, page: int = 0, note: str = "") -> None:
    uid = event.from_user.id
    p = await players.get(db, uid)
    eq = {it["slot"]: it for it in await players.equipped_items(db, uid)}
    st = await players.derived(db, p)
    rows_items, total = await items_svc.list_inventory(db, uid, page, PER)
    lines = [f"{e('bag')} <b>Сумка</b> · предметов: {total}"]
    if note:
        lines.append(note)
    lines.append(f"{e('hp')} {num(st['hp'])}  {e('atk')} {num(st['atk'])}  {e('def')} {num(st['def'])}  "
                 f"{e('power')} {num(st['power'])}\n")
    lines.append("<b>Надето:</b>")
    for slot in SLOT_ORDER:
        it = eq.get(slot)
        lines.append(f"{e(SLOTS[slot]['emoji'])} " + (item_line(it) if it else "<i>пусто</i>"))
    buttons = []
    for it in rows_items:
        tag = " ✔" if it["equipped"] else (" 🏷" if it["listed"] else "")
        buttons.append([(plain_item(it) + f" · {it['ilvl']}{tag}", f"inv:item:{it['id']}")])
    nav = pager("inv", page, total, PER)
    await screen(event, "\n".join(lines),
                 kb(*buttons, nav, [(f"{plain('gold')} Продать хлам", "inv:junk")], back()),
                 img=lambda: cards.banner("Сумка", "Экипировка и находки", "bag"), cache="b:bag")


@router.callback_query(F.data.regexp(r"^inv:\d+$"))
async def cb_inv_page(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_inventory(cb, db, int(cb.data.split(":")[1]))
    await toast(cb)


@router.message(Command("bag"))
async def cmd_bag(m: Message, db: Database, player: dict) -> None:
    await show_inventory(m, db)


# ---------------------------------------------------------------- карточка предмета
async def show_item(event, db: Database, item_id: int, note: str = "") -> None:
    uid = event.from_user.id
    it = await items_svc.get(db, uid, item_id)
    if not it:
        await toast(event, "Предмет не найден.", True) if isinstance(event, CallbackQuery) else None
        await show_inventory(event, db)
        return
    sell = formulas.sell_price(it)
    lines = [item_line(it)]
    if note:
        lines.append("\n" + note)
    rows = []
    if it["listed"]:
        lines.append("\n🏷 Выставлен на рынок. Сними лот в «Рынок → Мои лоты».")
    else:
        rows.append([(f"{plain('ok')} Снять" if it["equipped"] else f"{plain('up')} Надеть",
                      f"inv:{'un' if it['equipped'] else ''}equip:{item_id}")])
        if it["plus"] < MAX_PLUS:
            gold, ess = formulas.enhance_cost(it)
            from ..data.items import ENHANCE_CHANCE
            lines.append(f"\n{e('forge')} Усиление до +{it['plus'] + 1}: {e('gold')} {num(gold)} · {e('essence')} {num(ess)} "
                         f"(шанс {int(ENHANCE_CHANCE[it['plus']] * 100)}%)")
            rows.append([(f"{plain('forge')} Усилить (+{it['plus'] + 1})", f"inv:enh:{item_id}")])
        if not it["equipped"]:
            rows.append([(f"{plain('gold')} В лавку: {num(sell)}", f"inv:sell:{item_id}"),
                         (f"{plain('market')} На рынок", f"inv:list:{item_id}")])
    rows.append([(f"{plain('bag')} Сумка", "inv:0")])
    await screen(event, "\n".join(lines), kb(*rows), img=lambda: cards.item_card(it))


@router.callback_query(F.data.startswith("inv:item:"))
async def cb_item(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_item(cb, db, int(cb.data.split(":")[2]))
    await toast(cb)


@router.callback_query(F.data.startswith("inv:equip:"))
async def cb_equip(cb: CallbackQuery, db: Database, player: dict) -> None:
    iid = int(cb.data.split(":")[2])
    ok, msg = await items_svc.equip(db, cb.from_user.id, iid)
    await toast(cb, msg, not ok)
    await show_item(cb, db, iid, f"{e('ok')} Предмет надет." if ok else "")


@router.callback_query(F.data.startswith("inv:unequip:"))
async def cb_unequip(cb: CallbackQuery, db: Database, player: dict) -> None:
    iid = int(cb.data.split(":")[2])
    ok, msg = await items_svc.unequip(db, cb.from_user.id, iid)
    await toast(cb, msg, not ok)
    await show_item(cb, db, iid)


@router.callback_query(F.data.startswith("inv:enh:"))
async def cb_enhance(cb: CallbackQuery, db: Database, player: dict) -> None:
    iid = int(cb.data.split(":")[2])
    res = await items_svc.enhance(db, cb.from_user.id, iid)
    if not res["ok"]:
        extra = f" Нужно {num(res['gold'])} золота и {num(res['essence'])} эссенции." if "gold" in res else ""
        await toast(cb, res["msg"] + extra, True)
        return
    note = (f"{e('ok')} <b>Успех!</b> Теперь +{res['plus']}." if res["success"]
            else f"{e('no')} <b>Не удалось</b> (шанс был {int(res['chance'] * 100)}%). Ресурсы потрачены.")
    await show_item(cb, db, iid, note)
    await toast(cb)


@router.callback_query(F.data.startswith("inv:sell:"))
async def cb_sell(cb: CallbackQuery, db: Database, player: dict) -> None:
    iid = int(cb.data.split(":")[2])
    ok, msg, price = await items_svc.sell(db, cb.from_user.id, iid)
    if not ok:
        await toast(cb, msg, True)
        return
    await toast(cb, f"Продано за {num(price)} золота")
    await show_inventory(cb, db, 0, f"{e('gold')} Продано: +{num(price)}")


@router.callback_query(F.data == "inv:junk")
async def cb_junk_ask(cb: CallbackQuery, db: Database, player: dict) -> None:
    await screen(cb, f"{e('warn')} <b>Продать весь хлам?</b>\nБудут проданы все неэкипированные предметы "
                     f"<b>обычной и необычной</b> редкости (кроме выставленных на рынок).",
                 kb([(f"{plain('ok')} Да, продать", "inv:junk:yes")], [(f"{plain('no')} Отмена", "inv:0")]))
    await toast(cb)


@router.callback_query(F.data == "inv:junk:yes")
async def cb_junk(cb: CallbackQuery, db: Database, player: dict) -> None:
    n, total = await items_svc.sell_junk(db, cb.from_user.id)
    await toast(cb, f"Продано: {n} шт.")
    await show_inventory(cb, db, 0, f"{e('gold')} Продано {n} предметов: +{num(total)}")


# ---------------------------------------------------------------- выставить на рынок
@router.callback_query(F.data.startswith("inv:list:"))
async def cb_list_start(cb: CallbackQuery, db: Database, state: FSMContext, player: dict) -> None:
    iid = int(cb.data.split(":")[2])
    it = await items_svc.get(db, cb.from_user.id, iid)
    if not it or it["equipped"] or it["listed"]:
        await toast(cb, "Предмет недоступен для продажи.", True)
        return
    await state.set_state(SellState.price)
    await state.update_data(item_id=iid)
    rate = int(market.tax_rate(player) * 100)
    await screen(cb, f"{e('market')} <b>Выставить на рынок</b>\n{item_line(it)}\n\n"
                     f"Напиши цену в золоте одним числом (до {num(B.MARKET_MAX_PRICE)}).\n"
                     f"Комиссия рынка: <b>{rate}%</b> (с продавца). Ориентир — цена в лавке: {num(formulas.sell_price(it))}.",
                 kb([(f"{plain('no')} Отмена", f"inv:item:{iid}")]))
    await toast(cb)


@router.message(SellState.price, F.text)
async def msg_price(m: Message, db: Database, state: FSMContext, player: dict) -> None:
    raw = (m.text or "").replace(" ", "").replace(",", "").lower()
    mult = 1
    if raw.endswith("k"):
        raw, mult = raw[:-1], 1000
    elif raw.endswith("m"):
        raw, mult = raw[:-1], 1_000_000
    if not raw.isdigit():
        await m.answer("Нужно число, например <code>2500</code> или <code>5k</code>. Для отмены — /menu.")
        return
    data = await state.get_data()
    res = await market.list_item(db, m.from_user.id, data["item_id"], int(raw) * mult)
    if not res["ok"]:
        await m.answer(f"{e('no')} {res['msg']}")
        return
    await state.clear()
    await m.answer(f"{e('ok')} Выставлено за {e('gold')} <b>{num(int(raw) * mult)}</b>.",
                   reply_markup=kb([(f"{plain('market')} Мои лоты", "mk:mine")], [(f"{plain('bag')} Сумка", "inv:0")]))
