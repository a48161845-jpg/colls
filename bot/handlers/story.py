"""Сюжетные главы с выбором."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..bot_ctx import notify_inviter
from ..data.story import CHAPTERS, CHAPTER_ORDER
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import players, story as story_svc
from ..ui import screen, toast
from ..utils.texts import item_line, levelup_line, reward_line

router = Router(name="story")


async def show_chapters(event, db: Database) -> None:
    p = await players.get(db, event.from_user.id)
    st = story_svc.load(p)
    cur = story_svc.current(p)
    lines = [f"{e('story')} <b>Сюжет</b>\n"]
    rows = []
    for ch in CHAPTER_ORDER:
        meta = CHAPTERS[ch]
        ok, why = story_svc.chapter_available(p, ch)
        done = ch in st["done"]
        mark = e("ok") if done else (e("lock") if not ok else "▫️")
        lines.append(f"{mark} <b>Глава {ch}. {meta['title']}</b>" + ("" if ok else f" — {why}"))
        if ok:
            label = ("Продолжить" if cur and cur[0] == ch else "Перечитать" if done else "Начать")
            rows.append([(f"{plain('story')} Гл. {ch}: {label}", f"story:ch:{ch}")])
    lines.append("\n<i>Твои решения запоминаются и влияют на следующие главы.</i>")
    await screen(event, "\n".join(lines), kb(*rows, back()),
                 img=lambda: cards.banner("Сюжет", "Истории Пепельного королевства", "story"), cache="b:story")


@router.callback_query(F.data == "story")
async def cb_story(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_chapters(cb, db)
    await toast(cb)


@router.message(Command("story"))
async def cmd_story(m: Message, db: Database, player: dict) -> None:
    await show_chapters(m, db)


def _node_view(p: dict, ch: int, node: dict, prefix: str = ""):
    title = CHAPTERS[ch]["title"]
    text = f"{e('story')} <b>{title}</b>\n\n{prefix}{node['text']}"
    rows = []
    for idx, c in enumerate(node.get("choices", [])):
        if story_svc.choice_visible(c, p):
            tag = "🎲 " if "check" in c else ""
            rows.append([(f"{tag}{c['text']}", f"story:c:{idx}")])
    rows.append([(f"{plain('story')} К главам", "story")])
    return text, kb(*rows)


async def show_node(event, db: Database, prefix: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    cur = story_svc.current(p)
    if not cur:
        await show_chapters(event, db)
        return
    ch, _nid, node = cur
    text, markup = _node_view(p, ch, node, prefix)
    theme = CHAPTERS[ch]["theme"]
    await screen(event, text, markup, img=lambda: cards.location_card(theme, CHAPTERS[ch]["title"]), cache=f"story:{ch}")


@router.callback_query(F.data.startswith("story:ch:"))
async def cb_chapter(cb: CallbackQuery, db: Database, player: dict) -> None:
    ch = int(cb.data.split(":")[2])
    p = await players.get(db, cb.from_user.id)
    cur = story_svc.current(p)
    if not (cur and cur[0] == ch):
        res = await story_svc.start_chapter(db, cb.from_user.id, ch)
        if not res["ok"]:
            await toast(cb, res["msg"].capitalize(), True)
            return
    await show_node(cb, db)
    await toast(cb)


@router.callback_query(F.data.startswith("story:c:"))
async def cb_choice(cb: CallbackQuery, db: Database, player: dict) -> None:
    idx = int(cb.data.split(":")[2])
    res = await story_svc.choose(db, cb.from_user.id, idx)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        await show_node(cb, db)
        return

    prefix = ""
    if res.get("roll") is not None:
        total = res["roll"] + res["bonus"]
        verdict = f"{e('ok')} <b>Успех!</b>" if res["success"] else f"{e('no')} <b>Неудача.</b>"
        prefix = f"🎲 d20: {res['roll']} + {res['bonus']} = <b>{total}</b> против {res['dc']} — {verdict}\n\n"
    fx = res.get("fx")
    if fx:
        got = reward_line(fx)
        if fx.get("item"):
            got += f"\n{e('chest')} {item_line(fx['item'])}"
        if got.strip():
            prefix += f"<i>Получено: {got}</i>\n\n"
        await notify_inviter(cb.bot, fx.get("levelup"))

    node = res["node"]
    ch = res["chapter"]
    if res.get("finished"):
        text = f"{e('story')} <b>{CHAPTERS[ch]['title']}</b>\n\n{prefix}{node['text']}"
        if res.get("first_clear") and res.get("reward"):
            rw = res["reward"]
            text += f"\n\n{e('win')} <b>Награда за главу:</b> {reward_line(rw)}"
            if rw.get("item"):
                text += f"\n{e('chest')} {item_line(rw['item'])}"
            if rw.get("title"):
                text += f"\n{e('top')} Новый титул: <b>«{rw['title']}»</b>"
            text += levelup_line(rw.get("levelup"))
            await notify_inviter(cb.bot, rw.get("levelup"))
        markup = kb([(f"{plain('story')} К главам", "story")], [(f"{plain('bag')} Сумка", "inv:0")], back())
        await screen(cb, text, markup, img=lambda: cards.banner("Глава пройдена", CHAPTERS[ch]["title"], "win"), cache="b:win")
    else:
        await show_node(cb, db, prefix)
    await toast(cb)
