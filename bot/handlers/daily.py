"""Ежедневная награда и топы."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..data import balance as B
from ..data.classes import CLASSES
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import arena, daily, guilds, players
from ..ui import screen, toast
from ..utils.fmt import esc, now, num
from ..utils.texts import reward_line

router = Router(name="daily")


# ---------------------------------------------------------------- ежедневка
async def show_daily(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    st = await daily.status(db, p)
    lines = [f"{e('daily')} <b>Ежедневная награда</b>"]
    if note:
        lines.append(note)
    lines.append(f"\nСерия: <b>{st['streak']}</b> дн. Пропустишь день — серия сбросится.\n")
    for i, rw in enumerate(B.DAILY_REWARDS):
        if st["claimed"]:
            mark = e("ok") if i <= (st["streak"] - 1) % 7 else "▫️"
        else:
            mark = "👉" if i == st["day_idx"] else (e("ok") if i < st["day_idx"] else "▫️")
        lines.append(f"{mark} День {i + 1}: {reward_line(rw)}")
    rows = []
    if st["claimed"]:
        lines.append("\nСегодня награда уже получена. Возвращайся завтра!")
    else:
        lines.append(f"\nСегодня: {reward_line(st['reward'])}")
        rows.append([(f"{plain('daily')} Забрать награду", "daily:claim")])
    await screen(event, "\n".join(lines), kb(*rows, back()),
                 img=lambda: cards.banner("Ежедневная награда", f"Серия: {st['streak']} дн.", "daily"))


@router.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_daily(cb, db)
    await toast(cb)


@router.message(Command("daily"))
async def cmd_daily(m: Message, db: Database, player: dict) -> None:
    await show_daily(m, db)


@router.callback_query(F.data == "daily:claim")
async def cb_claim(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await daily.claim(db, cb.from_user.id)
    if not res["ok"]:
        await toast(cb, "Сегодня уже получено.", True)
        return
    await toast(cb, "Награда получена!")
    await show_daily(cb, db, f"{e('win')} Получено: {reward_line(res['reward'])}")


# ---------------------------------------------------------------- топы
TOPS = {
    "level": ("Уровень", "level DESC, xp DESC", lambda r: f"ур. {r['level']}"),
    "arena": ("Арена", "rating DESC, level DESC", lambda r: f"{r['rating']} очк."),
    "rich": ("Богатство", "gold_total DESC", lambda r: f"{num(r['gold_total'])} золота"),
}
MEDALS = ["🥇", "🥈", "🥉"]


async def show_top(event, db: Database, kind: str) -> None:
    uid = event.from_user.id
    if kind == "guild":
        rows = await guilds.top(db, 10)
        lines = [f"{e('top')} <b>Топ гильдий</b>\n"]
        for i, g in enumerate(rows):
            lines.append(f"{MEDALS[i] if i < 3 else f'{i + 1}.'} <b>{esc(g['name'])}</b> · ур. {g['level']} · {g['members']} уч.")
        if not rows:
            lines.append("<i>Гильдий пока нет — создай первую!</i>")
    else:
        title, order, fmt = TOPS[kind]
        rows = await db.all(f"SELECT * FROM players WHERE banned=0 ORDER BY {order} LIMIT 10")
        lines = [f"{e('top')} <b>Топ: {title}</b>\n"]
        for i, r in enumerate(rows):
            crown = "👑 " if r["premium_until"] > now() else ""
            lines.append(f"{MEDALS[i] if i < 3 else f'{i + 1}.'} {crown}<b>{esc(r['name'])}</b> "
                         f"{e(CLASSES[r['cls']]['emoji'])} · {fmt(r)}")
        me = await players.get(db, uid)
        if kind == "arena":
            lines.append(f"\nТвоё место: <b>#{await arena.rank_of(db, me)}</b> ({me['rating']})")
    tabs = [("Уровень", "top:level"), ("Арена", "top:arena"), ("Золото", "top:rich"), ("Гильдии", "top:guild")]
    tabs = [((f"• {t}" if d == f"top:{kind}" else t), d) for t, d in tabs]
    await screen(event, "\n".join(lines), kb(tabs[:2], tabs[2:], back()),
                 img=lambda: cards.banner("Топы", "Лучшие герои королевства", "top"), cache="b:top")


@router.callback_query(F.data.startswith("top:"))
async def cb_top(cb: CallbackQuery, db: Database, player: dict) -> None:
    kind = cb.data.split(":")[1]
    if kind not in TOPS and kind != "guild":
        await toast(cb)
        return
    await show_top(cb, db, kind)
    await toast(cb)


@router.message(Command("top"))
async def cmd_top(m: Message, db: Database, player: dict) -> None:
    await show_top(m, db, "level")
