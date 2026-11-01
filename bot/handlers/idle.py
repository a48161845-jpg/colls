"""Рудник: тапы, сбор добычи, постройки, перерождение."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..bot_ctx import notify_inviter
from ..data import balance as B
from ..data.buildings import BUILDINGS, BUILDING_ORDER
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb
from ..services import formulas, idle, players
from ..ui import screen, toast
from ..utils.fmt import bar, dur, num

router = Router(name="idle")

SCREEN_IMG = lambda: cards.banner("Пепельный рудник", "Копи золото, пока отдыхаешь", "idle")  # noqa: E731


async def _idle_text(db: Database, p: dict) -> tuple[str, dict, dict]:
    pend, ov = await idle.pending(db, p)
    r = ov["rates"]
    lines = [f"{e('idle')} <b>Пепельный рудник</b>",
             f"{e('gold')} {num(p['gold'])}   {e('essence')} {num(p['essence'])}\n",
             "<b>Доход в час</b> (с бонусами):",
             f"{e('gold')} {num(r['gold'])} · {e('xp')} {num(r['xp'])} · {e('essence')} {num(r['essence'])}",
             f"<i>Множитель ×{ov['mult']:.2f} (метки, амулет, гильдия, премиум)</i>\n",
             f"{e('chest')} <b>Накоплено за {dur(pend['hours'] * 3600)}</b> из {ov['cap_h']:.1f} ч"
             + (" — хранилище полно!" if pend["full"] else "") + ":",
             f"{e('gold')} <b>{num(pend['gold'])}</b> · {e('xp')} <b>{num(pend['xp'])}</b> · {e('essence')} <b>{num(pend['essence'])}</b>"]
    vein = _vein_line(p["user_id"])
    if vein:
        lines.append("\n" + vein)
    return "\n".join(lines), pend, ov


def _vein_line(uid: int, cool: float | None = None) -> str:
    st = idle.vein_state(uid)
    if st["broken"]:
        return f"{e('warn')} <b>Жила обрушилась!</b> Сама восстановится через {int(st['left'])} с."
    if st["heat"] >= 1:
        icon = "🔥" if st["warn"] else "⛏"
        return f"{icon} Нагрев жилы: {bar(st['heat'], st['max'], 10)} {int(st['heat'])}%" + (" — трещит!" if st["warn"] else "")
    return ""


def _idle_kb(pend: dict, uid: int = 0, level: int = 1):
    has = pend["gold"] or pend["xp"] or pend["essence"]
    broken = uid and idle.vein_state(uid)["broken"]
    tap_row = ([(f"{plain('gold')} Починить жилу ({num(idle.repair_cost(level))})", "idle:repair")] if broken
               else [(f"{plain('tap')} Ударить по жиле", "idle:tap")])
    return kb(
        tap_row,
        [(f"{plain('chest')} Забрать добычу" + (" ✓" if has else ""), "idle:collect")],
        [(f"{plain('forge')} Постройки", "idle:b"), (f"{plain('rebirth')} Перерождение", "idle:rb")],
        back(),
    )


async def show_idle(event, db: Database) -> None:
    p = await players.get(db, event.from_user.id)
    text, pend, _ = await _idle_text(db, p)
    await screen(event, text, _idle_kb(pend, p["user_id"], p["level"]), img=SCREEN_IMG, cache="b:idle")


@router.callback_query(F.data == "idle")
async def cb_idle(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_idle(cb, db)
    await toast(cb)


@router.message(Command("idle"))
async def cmd_idle(m: Message, db: Database, player: dict) -> None:
    await show_idle(m, db)


@router.callback_query(F.data == "idle:tap")
async def cb_tap(cb: CallbackQuery, db: Database, player: dict) -> None:
    r = await idle.tap(db, cb.from_user.id)
    if r["broken"]:
        if r["just_broken"]:
            await toast(cb, "💥 Жила не выдержала и обрушилась! Подожди или почини за золото.", True)
            await show_idle(cb, db)
        else:
            await toast(cb, f"Жила разрушена. Восстановится через {int(r['left'])} с.")
        return
    warn = "  🔥 Жила трещит, дай ей остыть!" if r["warn"] else ""
    await toast(cb, f"{'💥 КРИТ! ' if r['crit'] else ''}+{num(r['gain'])} 🪙  (всего {num(r['gold'])}){warn}")
    if r["taps"] % 15 == 0:  # экран обновляем изредка — Telegram ограничивает частоту правок
        await show_idle(cb, db)


@router.callback_query(F.data == "idle:repair")
async def cb_repair(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await idle.repair(db, cb.from_user.id)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        await show_idle(cb, db)
        return
    await toast(cb, f"Жила починена за {num(res['cost'])} золота.")
    await show_idle(cb, db)


@router.callback_query(F.data == "idle:collect")
async def cb_collect(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await idle.collect(db, cb.from_user.id)
    if not (res["gold"] or res["xp"] or res["essence"]):
        await toast(cb, "Пока нечего забирать — подожди немного.")
        return
    await toast(cb, f"Забрано: +{num(res['gold'])} золота, +{num(res['xp'])} опыта")
    await notify_inviter(cb.bot, res.get("levelup"))
    await show_idle(cb, db)


# ---------------------------------------------------------------- постройки
async def show_buildings(cb: CallbackQuery, db: Database, note: str = "") -> None:
    p = await players.get(db, cb.from_user.id)
    ov = await idle.overview(db, p)
    lines = [f"{e('forge')} <b>Постройки</b> · {e('gold')} {num(p['gold'])}"]
    if note:
        lines.append(note)
    rows = []
    for key in BUILDING_ORDER:
        meta, lvl = BUILDINGS[key], ov["blds"][key]
        if p["level"] < meta["unlock"]:
            lines.append(f"\n{e('lock')} <b>{meta['name']}</b> — откроется на {meta['unlock']} ур.")
            continue
        cost = formulas.building_cost(key, lvl)
        if meta["res"]:
            now_out = formulas.building_rate(key, lvl) * ov["mult"]
            nxt_out = formulas.building_rate(key, lvl + 1) * ov["mult"]
            gain = f"{e(meta['res'] if meta['res'] != 'xp' else 'xp')} {num(now_out)} → <b>{num(nxt_out)}</b>/ч"
        else:
            gain = meta["desc"]
        lines.append(f"\n{e(meta['emoji'])} <b>{meta['name']}</b> · ур. {lvl}\n   {gain}\n   Улучшить: {e('gold')} {num(cost)}")
        can = "✅" if p["gold"] >= cost else "🔒"
        rows.append([(f"{can} {plain(meta['emoji'])} {meta['name'].split(' «')[0]} → {lvl + 1} ({num(cost)})", f"idle:up:{key}")])
    await screen(cb, "\n".join(lines), kb(*rows, [(f"{plain('idle')} К руднику", "idle")], back()),
                 img=lambda: cards.banner("Постройки", "Развивай производство", "idle"), cache="b:build")


@router.callback_query(F.data == "idle:b")
async def cb_buildings(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_buildings(cb, db)
    await toast(cb)


@router.callback_query(F.data.startswith("idle:up:"))
async def cb_upgrade(cb: CallbackQuery, db: Database, player: dict) -> None:
    key = cb.data.split(":")[2]
    res = await idle.upgrade(db, cb.from_user.id, key)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    await toast(cb, f"{BUILDINGS[key]['name']} → ур. {res['level']}")
    await notify_inviter(cb.bot, res["collected"].get("levelup"))
    await show_buildings(cb, db, f"{e('ok')} <b>Улучшено до ур. {res['level']}</b> за {e('gold')} {num(res['cost'])}")


# ---------------------------------------------------------------- перерождение
@router.callback_query(F.data == "idle:rb")
async def cb_rebirth_info(cb: CallbackQuery, db: Database, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    info = idle.rebirth_info(p)
    text = (f"{e('rebirth')} <b>Перерождение</b>\n\n"
            f"Сбрось уровень, золото и постройки — и получи <b>метки пепла</b>. "
            f"Каждая метка навсегда даёт <b>+{int(B.MARK_IDLE_BONUS * 100)}%</b> к доходу рудника и "
            f"<b>+{int(B.MARK_STAT_BONUS * 100)}%</b> к характеристикам героя.\n\n"
            f"Сохраняются: предметы, кристаллы, эссенция, гильдия, сюжет, рейтинг.\n\n"
            f"Твои метки: {e('mark')} <b>{p['marks']}</b>\n")
    rows = []
    if info["can"]:
        text += f"Сейчас можно получить: {e('mark')} <b>+{info['marks']}</b>"
        rows.append([(f"{plain('rebirth')} Переродиться (+{info['marks']})", "idle:rb:yes")])
    else:
        text += f"{e('lock')} Доступно с <b>{info['need']}</b> уровня (у тебя {p['level']})."
    await screen(cb, text, kb(*rows, [(f"{plain('idle')} К руднику", "idle")]),
                 img=lambda: cards.banner("Перерождение", "Начни заново — сильнее", "rebirth"), cache="b:rebirth")
    await toast(cb)


@router.callback_query(F.data == "idle:rb:yes")
async def cb_rebirth(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await idle.rebirth(db, cb.from_user.id)
    if not res["ok"]:
        await toast(cb, f"Нужен {res['need']} уровень.", True)
        return
    text = (f"{e('rebirth')} <b>Ты переродился!</b>\n\nПолучено меток: {e('mark')} <b>+{res['marks']}</b> "
            f"(всего {res['total']}).\nДоход рудника ×{1 + B.MARK_IDLE_BONUS * res['total']:.2f}, "
            f"характеристики +{int(B.MARK_STAT_BONUS * res['total'] * 100)}%.")
    await screen(cb, text, kb([(f"{plain('idle')} В рудник", "idle")], back()),
                 img=lambda: cards.banner("Новое начало", "Метки пепла усиливают тебя", "rebirth"), cache="b:rebirth")
    await toast(cb)
