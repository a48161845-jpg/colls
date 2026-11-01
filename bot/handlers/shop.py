"""Магазин: Premium и кристаллы за Telegram Stars, траты кристаллов, обработка платежей."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ..bot_ctx import notify_inviter
from ..config import Settings
from ..data.shop import CHEST_ODDS, CRYSTAL_PACKS, CRYSTAL_SHOP, PREMIUM_PERKS, PREMIUM_PLANS, STARTER_PACK
from ..data.items import RARITY
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import payments, players, prices
from ..ui import notify, screen, toast
from ..utils.fmt import dur, now, num
from ..utils.texts import item_line, reward_line

log = logging.getLogger(__name__)
router = Router(name="shop")


# ---------------------------------------------------------------- витрина
async def show_shop(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    text = (f"{e('shop')} <b>Магазин</b>\n{e('crystal')} У тебя: <b>{num(p['crystals'])}</b> кристаллов\n\n"
            f"{e('premium')} <b>Premium</b> — +50% к доходу, +25% наград и другие бонусы\n"
            f"{e('stars')} <b>Кристаллы</b> за Telegram Stars\n"
            f"{e('chest')} <b>Траты кристаллов</b>: сундуки, энергия, скачки времени\n\n"
            f"<i>Вся игра проходима бесплатно — донат только ускоряет и украшает.</i>")
    if players.is_premium(p):
        text += f"\n\n{e('premium')} Premium активен ещё {dur(p['premium_until'] - now())}"
    if note:
        text += f"\n\n{note}"
    rows = [[(f"{plain('premium')} Premium", "shop:prem"), (f"{plain('stars')} Кристаллы", "shop:gems")]]
    if not p["starter_bought"]:
        rows.append([(f"🎁 Набор новичка — {prices.stars('starter', 'starter', STARTER_PACK['stars'])}{plain('stars')}", "shop:starter")])
    rows += [[(f"{plain('chest')} Купить за кристаллы", "shop:cr")], back()]
    await screen(event, text, kb(*rows), img=lambda: cards.banner("Магазин", "Premium, кристаллы, сундуки", "shop"), cache="b:shop")


@router.callback_query(F.data == "shop")
async def cb_shop(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_shop(cb, db)
    await toast(cb)


@router.message(Command("shop"))
async def cmd_shop(m: Message, db: Database, player: dict) -> None:
    await show_shop(m, db)


@router.callback_query(F.data == "shop:prem")
async def cb_prem(cb: CallbackQuery, db: Database, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    perks = "\n".join(f"• {x}" for x in PREMIUM_PERKS)
    text = f"{e('premium')} <b>Premium «Покровитель пепла»</b>\n\n{perks}"
    if players.is_premium(p):
        text += f"\n\n{e('ok')} Активен ещё {dur(p['premium_until'] - now())}. Покупка продлит срок."
    rows = [[(f"{d['title']} — {prices.stars('prem', k, d['stars'])}{plain('stars')}", f"shop:buy:prem:{k}")] for k, d in PREMIUM_PLANS.items()]
    await screen(cb, text, kb(*rows, [(f"{plain('shop')} Магазин", "shop")]),
                 img=lambda: cards.banner("Premium", "Покровитель пепла", "premium"), cache="b:premium")
    await toast(cb)


@router.callback_query(F.data == "shop:gems")
async def cb_gems(cb: CallbackQuery, db: Database, player: dict) -> None:
    lines = [f"{e('crystal')} <b>Кристаллы</b>\n\nОплата Telegram Stars ({e('stars')}). Кристаллы тратятся в магазине: "
             f"сундуки, энергия, скачки времени, попытки арены.\n"]
    for k, d in CRYSTAL_PACKS.items():
        lines.append(f"• {d['title']}: {e('crystal')} <b>{num(d['crystals'])}</b> {d['bonus']} — {prices.mark('pack:' + k, d['stars'], e('stars'))}")
    rows = [[(f"{plain('crystal')} {num(d['crystals'])} — {prices.stars('pack', k, d['stars'])}{plain('stars')} {d['bonus']}".strip(), f"shop:buy:pack:{k}")]
            for k, d in CRYSTAL_PACKS.items()]
    await screen(cb, "\n".join(lines), kb(*rows, [(f"{plain('shop')} Магазин", "shop")]),
                 img=lambda: cards.banner("Кристаллы", "Оплата Telegram Stars", "shop"), cache="b:shop")
    await toast(cb)


@router.callback_query(F.data == "shop:starter")
async def cb_starter(cb: CallbackQuery, db: Database, player: dict) -> None:
    d = STARTER_PACK
    cost = prices.stars("starter", "starter", d["stars"])
    text = (f"🎁 <b>{d['title']}</b> (один раз)\n\n"
            f"• {e('crystal')} {d['crystals']} кристаллов\n• {e('gold')} {num(d['gold'])} золота\n• {e('essence')} {d['essence']} эссенции\n"
            f"• {e('potion')} {d['potions']} зелий\n• {e('premium')} Premium на {d['premium_days']} дня\n"
            f"• {e('r_epic')} эпическое оружие\n\nЦена: <b>{prices.mark('starter:starter', d['stars'], e('stars'))}</b>")
    await screen(cb, text, kb([(f"Купить за {cost}{plain('stars')}", "shop:buy:starter:starter")], [(f"{plain('shop')} Магазин", "shop")]),
                 img=lambda: cards.banner("Набор новичка", "Лучший старт", "premium"), cache="b:starter")
    await toast(cb)


# ---------------------------------------------------------------- счёт в Stars
@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_buy(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    _, _, kind, key = cb.data.split(":")
    payload = payments.payload_for(kind, key)
    ok, why = await payments.can_buy(db, cb.from_user.id, payload)
    if not ok:
        await toast(cb, why, True)
        return
    info = payments.resolve(payload)
    await bot.send_invoice(
        chat_id=cb.from_user.id, title=info["title"][:32], description=info["desc"][:255], payload=payload,
        provider_token="", currency="XTR", prices=[LabeledPrice(label=info["title"][:32], amount=info["stars"])],
    )
    await toast(cb, "Счёт отправлен ниже ⬇️")


@router.pre_checkout_query()
async def on_pre_checkout(q: PreCheckoutQuery, db: Database) -> None:
    ok, why = (False, "Игрок не найден. Нажми /start.")
    if await players.get(db, q.from_user.id):
        ok, why = await payments.can_buy(db, q.from_user.id, q.invoice_payload)
    if ok and q.currency != "XTR":
        ok, why = False, "Неверная валюта."
    info = payments.resolve(q.invoice_payload)
    if ok and info and q.total_amount != info["stars"]:
        ok, why = False, "Цена изменилась, открой магазин заново."
    await q.answer(ok=ok, error_message=None if ok else why)


@router.message(F.successful_payment)
async def on_paid(m: Message, bot: Bot, db: Database, settings: Settings) -> None:
    sp = m.successful_payment
    res = await payments.grant(db, m.from_user.id, sp.invoice_payload, sp.telegram_payment_charge_id, sp.total_amount)
    if res.get("duplicate"):
        return
    if not res.get("ok"):
        log.error("paid but unknown payload %r charge=%s user=%s", sp.invoice_payload, sp.telegram_payment_charge_id, m.from_user.id)
        await m.answer("Платёж получен, но товар не найден. Напиши в поддержку — мы всё вернём. "
                       f"ID платежа: <code>{sp.telegram_payment_charge_id}</code>")
        return
    info = res["info"]
    lines = [f"{e('win')} <b>Спасибо за покупку!</b>", f"{info['title']}"]
    if res.get("crystals"):
        lines.append(f"{e('crystal')} +{num(res['crystals'])}")
    if res.get("gold"):
        lines.append(f"{e('gold')} +{num(res['gold'])}")
    if res.get("until"):
        lines.append(f"{e('premium')} Premium до {dur(res['until'] - now())} вперёд")
    if res.get("item"):
        lines.append(item_line(res["item"]))
    await m.answer("\n".join(lines), reply_markup=kb([(f"{plain('hero')} В меню", "menu"), (f"{plain('shop')} Магазин", "shop")]))
    for admin in settings.admin_ids:
        await notify(bot, admin, f"💰 Покупка: {info['title']} · {sp.total_amount}⭐ · user <code>{m.from_user.id}</code> · "
                                 f"charge <code>{sp.telegram_payment_charge_id}</code>")


# ---------------------------------------------------------------- траты кристаллов
@router.callback_query(F.data == "shop:cr")
async def cb_crystal_shop(cb: CallbackQuery, db: Database, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    lines = [f"{e('chest')} <b>Магазин за кристаллы</b> · {e('crystal')} {num(p['crystals'])}\n"]
    rows = []
    for k, d in CRYSTAL_SHOP.items():
        lines.append(f"• <b>{d['title']}</b> — {e('crystal')} {prices.mark('cr:' + k, d['cost'], '')}\n   <i>{d['desc']}</i>")
        rows.append([(f"{d['title']} — {prices.cost(k, d['cost'])}{plain('crystal')}", f"shop:crc:{k}")])
    await screen(cb, "\n".join(lines), kb(*rows, [(f"{plain('shop')} Магазин", "shop")]),
                 img=lambda: cards.banner("Лавка кристаллов", "Сундуки и ускорения", "shop"), cache="b:shop")
    await toast(cb)


@router.callback_query(F.data.startswith("shop:crc:"))
async def cb_crystal_confirm(cb: CallbackQuery, db: Database, player: dict) -> None:
    key = cb.data.split(":")[2]
    d = CRYSTAL_SHOP.get(key)
    if not d:
        await toast(cb)
        return
    p = await players.get(db, cb.from_user.id)
    price = prices.cost(key, d["cost"])
    text = f"<b>{d['title']}</b>\n{d['desc']}\n\nЦена: {e('crystal')} <b>{price}</b> · у тебя {num(p['crystals'])}"
    if key in CHEST_ODDS:
        odds = " · ".join(f"{RARITY[r]['name']} {w:g}%" for r, w in CHEST_ODDS[key].items())
        text += f"\n\n<b>Шансы:</b> {odds}"
    rows = [[(f"{plain('ok')} Купить", f"shop:crb:{key}")] if p["crystals"] >= price else
            [(f"{plain('lock')} Не хватает кристаллов", "shop:gems")],
            [(f"{plain('chest')} Назад", "shop:cr")]]
    await screen(cb, text, kb(*rows))
    await toast(cb)


@router.callback_query(F.data.startswith("shop:crb:"))
async def cb_crystal_buy(cb: CallbackQuery, db: Database, player: dict) -> None:
    key = cb.data.split(":")[2]
    res = await payments.spend_crystals(db, cb.from_user.id, key)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    lines = [f"{e('ok')} <b>{res['title']}</b> — куплено за {e('crystal')} {res['cost']}"]
    img = None
    if res.get("item"):
        lines.append(item_line(res["item"]))
        item = res["item"]
        img = lambda: cards.item_card(item, "Из сундука")  # noqa: E731
    if res.get("warp"):
        w = res["warp"]
        lines.append(reward_line(w))
        await notify_inviter(cb.bot, w.get("levelup"))
    rows = [[(f"{plain('chest')} Ещё", f"shop:crc:{key}")], [(f"{plain('bag')} Сумка", "inv:0"), (f"{plain('shop')} Магазин", "shop")]]
    await screen(cb, "\n".join(lines), kb(*rows), img=img)
    await toast(cb)
