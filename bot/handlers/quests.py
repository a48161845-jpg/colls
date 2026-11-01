"""Ежедневные задания."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..bot_ctx import notify_inviter
from ..data import balance as B
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import players, quests
from ..ui import screen, toast
from ..utils.fmt import bar
from ..utils.texts import levelup_line, reward_line

router = Router(name="quests")


async def show_quests(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    qs = await quests.list_today(db, p)
    lines = [f"{e('quest')} <b>Задания на сегодня</b>"]
    if note:
        lines.append(note)
    lines.append("")
    rows = []
    for q in qs:
        state = e("ok") if q["claimed"] else (e("chest") if q["done"] else "▫️")
        lines.append(f"{state} <b>{q['text']}</b>: {q['progress']}/{q['need']}\n   {bar(q['progress'], q['need'], 10)}  {reward_line(q['reward'])}")
        if q["done"] and not q["claimed"]:
            rows.append([(f"{plain('chest')} Забрать: {q['text']}", f"dq:claim:{q['key']}")])
    done = sum(1 for q in qs if q["claimed"])
    lines.append(f"\nВыполни все — бонус {e('crystal')} <b>{B.DAILY_QUESTS_BONUS_CRYSTALS}</b> ({done}/{len(qs)}).")
    lines.append("<i>Новые задания — каждый день в 00:00 UTC.</i>")
    await screen(event, "\n".join(lines), kb(*rows, back()),
                 img=lambda: cards.banner("Задания", "Три новых испытания в день", "quest"), cache="b:quest")


@router.callback_query(F.data == "dq")
async def cb_quests(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_quests(cb, db)
    await toast(cb)


@router.message(Command("quests"))
async def cmd_quests(m: Message, db: Database, player: dict) -> None:
    await show_quests(m, db)


@router.callback_query(F.data.startswith("dq:claim:"))
async def cb_claim(cb: CallbackQuery, db: Database, player: dict) -> None:
    key = cb.data.split(":")[2]
    res = await quests.claim(db, cb.from_user.id, key)
    if not res["ok"]:
        await toast(cb, "Награда недоступна.", True)
        return
    note = f"{e('win')} Получено: {reward_line(res['reward'])}"
    if res["bonus"]:
        note += f"\n{e('crystal')} Бонус за все задания: <b>+{res['bonus']}</b>"
    note += levelup_line(res.get("levelup"))
    await notify_inviter(cb.bot, res.get("levelup"))
    await show_quests(cb, db, note)
    await toast(cb)
