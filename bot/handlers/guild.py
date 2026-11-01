"""Гильдии."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..data import balance as B
from ..db.core import Database
from ..emoji import e, p as plain
from ..images import cards
from ..keyboards.common import back, kb, pager
from ..services import formulas, guilds, players
from ..ui import notify, screen, toast
from ..utils.fmt import bar, esc, num

router = Router(name="guild")
PER = 6


class GuildState(StatesGroup):
    name = State()
    invite = State()


# ---------------------------------------------------------------- главный экран
async def show_guild(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    if not p["guild_id"]:
        text = (f"{e('guild')} <b>Гильдии</b>\n\nОбъединяйся с другими героями: общий босс, "
                f"бонус <b>+{int(B.GUILD_IDLE_PER_LEVEL * 100)}%</b> к доходу рудника за каждый уровень гильдии.\n\n"
                f"Создание стоит {e('gold')} <b>{num(B.GUILD_CREATE_COST)}</b>.")
        if note:
            text += f"\n\n{note}"
        invites = await guilds.my_invites(db, event.from_user.id)
        rows = [[(f"{plain('guild')} Найти гильдию", "g:list:0")], [(f"{plain('up')} Создать гильдию", "g:create")]]
        if invites:
            rows.insert(0, [(f"{plain('ref')} Приглашения ({len(invites)})", "g:invs")])
            text += f"\n\n{e('ref')} Тебя приглашают в гильдии: <b>{len(invites)}</b>."
        await screen(event, text, kb(*rows, back()),
                     img=lambda: cards.banner("Гильдии", "Вместе сильнее", "guild"), cache="b:guild")
        return
    g = await guilds.get(db, p["guild_id"])
    is_leader = p["guild_role"] == "leader"
    need = formulas.guild_xp_needed(g["level"])
    text = (f"{e('guild')} <b>{esc(g['name'])}</b> · ур. {g['level']}\n"
            f"{bar(g['xp'], need, 12)} {num(g['xp'])}/{num(need)}\n"
            f"Участников: <b>{g['members']}/{formulas.guild_max_members(g['level'])}</b> · "
            f"бонус к idle: <b>+{int(B.GUILD_IDLE_PER_LEVEL * g['level'] * 100)}%</b>\n"
            f"{e('boss')} Босс: ур. <b>{g['boss_level']}</b> — {num(g['boss_hp'])}/{num(g['boss_max'])}\n"
            f"Твоя роль: <b>{'глава' if is_leader else 'участник'}</b>")
    if note:
        text += f"\n\n{note}"
    rows = [[(f"{plain('boss')} Босс гильдии", "g:boss"), (f"{plain('gold')} Вклад", "g:don")],
            [(f"{plain('hero')} Участники", "g:mem"), (f"{plain('top')} Топ гильдий", "top:guild")],
            [(f"{plain('flee')} Покинуть", "g:leave")], back()]
    if is_leader:
        rows.insert(2, [(f"{plain('ref')} Пригласить по ID", "g:inv")])
    await screen(event, text, kb(*rows), img=lambda: cards.guild_card(g))


@router.callback_query(F.data == "g")
async def cb_guild(cb: CallbackQuery, db: Database, state: FSMContext, player: dict) -> None:
    await state.clear()
    await show_guild(cb, db)
    await toast(cb)


@router.message(Command("guild"))
async def cmd_guild(m: Message, db: Database, player: dict) -> None:
    await show_guild(m, db)


# ---------------------------------------------------------------- список / вступление
@router.callback_query(F.data.startswith("g:list:"))
async def cb_list(cb: CallbackQuery, db: Database, player: dict) -> None:
    page = int(cb.data.split(":")[2])
    rows, total = await guilds.list_guilds(db, page, PER)
    lines = [f"{e('guild')} <b>Гильдии</b> · всего {total}\n"]
    buttons = []
    for g in rows:
        cap = formulas.guild_max_members(g["level"])
        lines.append(f"• <b>{esc(g['name'])}</b> · ур. {g['level']} · {g['members']}/{cap}")
        if g["members"] < cap:
            buttons.append([(f"{g['name']} · ур.{g['level']} ({g['members']}/{cap})", f"g:join:{g['id']}")])
    if not rows:
        lines.append("<i>Пока ни одной гильдии. Создай первую!</i>")
    await screen(cb, "\n".join(lines), kb(*buttons, pager("g:list", page, total, PER), [(f"{plain('guild')} Назад", "g")]),
                 img=lambda: cards.banner("Список гильдий", "Выбери свой отряд", "guild"), cache="b:guild")
    await toast(cb)


@router.callback_query(F.data.startswith("g:join:"))
async def cb_join(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await guilds.join(db, cb.from_user.id, int(cb.data.split(":")[2]))
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    await toast(cb, f"Ты в гильдии «{res['name']}»!")
    await show_guild(cb, db, f"{e('win')} Добро пожаловать в гильдию!")


# ---------------------------------------------------------------- создание
@router.callback_query(F.data == "g:create")
async def cb_create(cb: CallbackQuery, db: Database, state: FSMContext, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    if p["gold"] < B.GUILD_CREATE_COST:
        await toast(cb, f"Нужно {num(B.GUILD_CREATE_COST)} золота (у тебя {num(p['gold'])}).", True)
        return
    await state.set_state(GuildState.name)
    await screen(cb, f"{e('guild')} <b>Создание гильдии</b>\n\nНапиши название ({B.GUILD_NAME_MIN}–{B.GUILD_NAME_MAX} символов: "
                     f"буквы, цифры, пробел, дефис). Спишется {e('gold')} {num(B.GUILD_CREATE_COST)}.",
                 kb([(f"{plain('no')} Отмена", "g")]))
    await toast(cb)


@router.message(GuildState.name, F.text)
async def msg_name(m: Message, db: Database, state: FSMContext, player: dict) -> None:
    res = await guilds.create(db, m.from_user.id, m.text or "")
    if not res["ok"]:
        await m.answer(f"{e('no')} {res['msg']}")
        return
    await state.clear()
    await m.answer(f"{e('win')} Гильдия создана! Ты — её глава.", reply_markup=kb([(f"{plain('guild')} Открыть гильдию", "g")]))


# ---------------------------------------------------------------- выход / участники
@router.callback_query(F.data == "g:leave")
async def cb_leave_ask(cb: CallbackQuery, db: Database, player: dict) -> None:
    await screen(cb, f"{e('warn')} Покинуть гильдию? Если ты глава, лидерство перейдёт сильнейшему участнику "
                     f"(а пустая гильдия будет распущена).",
                 kb([(f"{plain('ok')} Да, уйти", "g:leave:yes")], [(f"{plain('no')} Отмена", "g")]))
    await toast(cb)


@router.callback_query(F.data == "g:leave:yes")
async def cb_leave(cb: CallbackQuery, db: Database, player: dict) -> None:
    res = await guilds.leave(db, cb.from_user.id)
    await toast(cb, "Ты покинул гильдию." if res["ok"] else res["msg"], not res["ok"])
    await show_guild(cb, db)


@router.callback_query(F.data == "g:mem")
async def cb_members(cb: CallbackQuery, db: Database, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    if not p["guild_id"]:
        await toast(cb, "Ты не в гильдии.", True)
        return
    rows = await guilds.members(db, p["guild_id"])
    is_leader = p["guild_role"] == "leader"
    lines = [f"{e('hero')} <b>Участники</b> ({len(rows)})\n"]
    buttons = []
    for r in rows:
        crown = "👑 " if r["guild_role"] == "leader" else ""
        lines.append(f"{crown}<b>{esc(r['name'])}</b> · ур. {r['level']}" + (f" · урон боссу {num(r['dmg'])}" if r["dmg"] else ""))
        if is_leader and r["user_id"] != p["user_id"]:
            buttons.append([(f"Исключить {r['name']}", f"g:kick:{r['user_id']}")])
    await screen(cb, "\n".join(lines), kb(*buttons[:8], [(f"{plain('guild')} Назад", "g")]))
    await toast(cb)


@router.callback_query(F.data.startswith("g:kick:"))
async def cb_kick(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    target = int(cb.data.split(":")[2])
    res = await guilds.kick(db, cb.from_user.id, target)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    await notify(bot, target, f"{e('warn')} Тебя исключили из гильдии.")
    await toast(cb, f"{res['name']} исключён.")
    await cb_members(cb, db, player)


# ---------------------------------------------------------------- вклад
@router.callback_query(F.data == "g:don")
async def cb_donate_menu(cb: CallbackQuery, db: Database, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    amounts = [1000, 10_000, 100_000]
    rows = [[(f"{plain('gold')} {num(a)}", f"g:don:{a}") for a in amounts if p["gold"] >= a] or [("Мало золота", "noop")]]
    if p["gold"] >= 100:
        rows.append([(f"{plain('gold')} Всё золото ({num(p['gold'])})", f"g:don:{p['gold']}")])
    await screen(cb, f"{e('gold')} <b>Вклад в гильдию</b>\n\nЗолото превращается в опыт гильдии 1:1. Уровни гильдии усиливают "
                     f"доход рудника у всех участников.\n\nУ тебя: {e('gold')} {num(p['gold'])}",
                 kb(*rows, [(f"{plain('guild')} Назад", "g")]))
    await toast(cb)


@router.callback_query(F.data.startswith("g:don:"))
async def cb_donate(cb: CallbackQuery, db: Database, player: dict) -> None:
    amount = int(cb.data.split(":")[2])
    res = await guilds.donate(db, cb.from_user.id, amount)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    note = f"{e('ok')} Вклад {num(amount)} принят!" + (f"\n{e('level')} Гильдия достигла <b>{res['level']}</b> уровня!" if res["gained"] else "")
    await show_guild(cb, db, note)
    await toast(cb)


# ---------------------------------------------------------------- босс гильдии
async def show_boss(event, db: Database, note: str = "") -> None:
    p = await players.get(db, event.from_user.id)
    if not p["guild_id"]:
        await show_guild(event, db)
        return
    g = await guilds.get(db, p["guild_id"])
    cur, mx, _ = await players.energy(db, p)
    mem = await guilds.members(db, p["guild_id"])
    top = sorted((m for m in mem if m["dmg"]), key=lambda m: -m["dmg"])[:5]
    lines = [f"{e('boss')} <b>Босс гильдии «{esc(g['name'])}»</b> · ур. {g['boss_level']}",
             f"{bar(g['boss_hp'], g['boss_max'], 12)} {num(g['boss_hp'])}/{num(g['boss_max'])}",
             f"{e('energy')} Энергия: <b>{int(cur)}/{mx}</b> · удар стоит {B.GUILD_BOSS_COST}{e('energy')}"]
    if top:
        lines.append("\n<b>Лучшие в этом бою:</b>")
        for i, m in enumerate(top):
            lines.append(f"{i + 1}. {esc(m['name'])} — {num(m['dmg'])}")
    lines.append("\n<i>Когда босс падает, награду получают все, кто бил. Лучший получает кристаллы и эпический предмет.</i>")
    if note:
        lines.append("\n" + note)
    await screen(event, "\n".join(lines),
                 kb([(f"{plain('atk')} Ударить ({B.GUILD_BOSS_COST}{plain('energy')})", "g:hit")], [(f"{plain('guild')} Назад", "g")]),
                 img=lambda: cards.guild_boss_card(g))


@router.callback_query(F.data == "g:boss")
async def cb_boss(cb: CallbackQuery, db: Database, player: dict) -> None:
    await show_boss(cb, db)
    await toast(cb)


@router.callback_query(F.data == "g:hit")
async def cb_hit(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    res = await guilds.boss_hit(db, cb.from_user.id)
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        return
    note = f"{e('atk')} Ты нанёс <b>{num(res['dmg'])}</b> урона" + (f" {e('crit')} крит!" if res["crit"] else ".")
    if res["killed"]:
        note = f"{e('win')} <b>Босс повержен!</b> Твой финальный удар: {num(res['dmg'])}.\nНаграды розданы, появился босс ур. {res['boss_level'] + 1}."
        for rw in res["rewards"]:
            if rw["user_id"] == cb.from_user.id:
                continue
            extra = f" и {e('crystal')} {rw['crystals']} + эпический предмет" if rw["top"] else ""
            await notify(bot, rw["user_id"], f"{e('boss')} Гильдия победила босса! Твоя награда: {e('gold')} {num(rw['gold'])}, "
                                             f"{e('essence')} {rw['essence']}{extra}.")
        mine = next((r for r in res["rewards"] if r["user_id"] == cb.from_user.id), None)
        if mine:
            note += f"\nТвоя награда: {e('gold')} {num(mine['gold'])}, {e('essence')} {mine['essence']}" + (
                f", {e('crystal')} {mine['crystals']} и эпический предмет!" if mine["top"] else ".")
    await show_boss(cb, db, note)
    await toast(cb)


# ---------------------------------------------------------------- приглашения
INVITE_HELP = ("Пришли Telegram ID игрока (число). Узнать его можно у бота @userinfobot, а ещё игрок видит свой ID "
               "в нашем боте в /profile. Он должен уже запускать этого бота.")


async def _send_invite(bot: Bot, db: Database, uid: int, target: int) -> str:
    res = await guilds.invite(db, uid, target)
    if not res["ok"]:
        return f"{e('no')} {esc(res['msg'])}"
    delivered = await notify(
        bot, target, f"{e('guild')} <b>{esc(res['inviter'])}</b> приглашает тебя в гильдию «<b>{esc(res['guild'])}</b>».\n"
                     f"Приглашение действует 3 дня.",
        kb([(f"{plain('ok')} Принять", f"g:inv:yes:{res['guild_id']}"), (f"{plain('no')} Отклонить", f"g:inv:no:{res['guild_id']}")]))
    if not delivered:
        await db.execute("DELETE FROM guild_invites WHERE guild_id=? AND user_id=?", (res["guild_id"], target))
        return f"{e('warn')} Не удалось отправить: игрок заблокировал бота."
    return f"{e('ok')} Приглашение отправлено игроку <b>{esc(res['target_name'])}</b>."


@router.callback_query(F.data == "g:inv")
async def cb_invite_ask(cb: CallbackQuery, db: Database, state: FSMContext, player: dict) -> None:
    p = await players.get(db, cb.from_user.id)
    if p["guild_role"] != "leader":
        await toast(cb, "Приглашать может только глава гильдии.", True)
        return
    await state.set_state(GuildState.invite)
    await screen(cb, f"{e('ref')} <b>Приглашение в гильдию</b>\n\n{INVITE_HELP}", kb([("Отмена", "g")]))
    await toast(cb)


@router.message(GuildState.invite, F.text)
async def msg_invite(m: Message, bot: Bot, db: Database, state: FSMContext, player: dict) -> None:
    raw = (m.text or "").strip().lstrip("#")
    if not raw.isdigit():
        await m.answer("ID — это число, например <code>123456789</code>. Пришли ещё раз или нажми «Отмена».")
        return
    await state.clear()
    note = await _send_invite(bot, db, m.from_user.id, int(raw))
    await show_guild(m, db, note)


@router.message(Command("invite"))
async def cmd_invite(m: Message, command: CommandObject, bot: Bot, db: Database, player: dict) -> None:
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        await m.answer("Формат: <code>/invite ID</code>, например <code>/invite 123456789</code>.")
        return
    await m.answer(await _send_invite(bot, db, m.from_user.id, int(arg)))


@router.callback_query(F.data == "g:invs")
async def cb_invites(cb: CallbackQuery, db: Database, player: dict) -> None:
    invites = await guilds.my_invites(db, cb.from_user.id)
    if not invites:
        await toast(cb, "Приглашений нет.", True)
        await show_guild(cb, db)
        return
    lines = [f"{e('ref')} <b>Приглашения в гильдии</b>\n"]
    rows = []
    for i in invites:
        lines.append(f"• <b>{esc(i['guild'])}</b> · ур. {i['level']} · участников {i['members']}")
        rows.append([(f"{plain('ok')} {i['guild'][:18]}", f"g:inv:yes:{i['guild_id']}"), (f"{plain('no')}", f"g:inv:no:{i['guild_id']}")])
    await screen(cb, "\n".join(lines), kb(*rows, [(f"{plain('guild')} Назад", "g")]))
    await toast(cb)


@router.callback_query(F.data.startswith("g:inv:yes:"))
async def cb_invite_yes(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    res = await guilds.accept_invite(db, cb.from_user.id, int(cb.data.split(":")[3]))
    if not res["ok"]:
        await toast(cb, res["msg"], True)
        if cb.message:
            await show_guild(cb, db)
        return
    await toast(cb, f"Ты в гильдии «{res['name']}»!")
    await notify(bot, res["leader_id"], f"{e('win')} <b>{esc(res['player'])}</b> принял приглашение и вступил в гильдию.")
    await show_guild(cb, db, f"{e('win')} Добро пожаловать в гильдию!")


@router.callback_query(F.data.startswith("g:inv:no:"))
async def cb_invite_no(cb: CallbackQuery, bot: Bot, db: Database, player: dict) -> None:
    res = await guilds.decline_invite(db, cb.from_user.id, int(cb.data.split(":")[3]))
    await toast(cb, "Приглашение отклонено.")
    if res["ok"] and res["inviter_id"]:
        await notify(bot, res["inviter_id"], f"{e('no')} {esc(player['name'])} отклонил приглашение в «{esc(res['guild'])}».")
    await show_guild(cb, db)
