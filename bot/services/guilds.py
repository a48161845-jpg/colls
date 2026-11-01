"""Гильдии: создание, вступление, вклад, гильдийный босс."""
from __future__ import annotations

import random
import re

from ..data import balance as B
from ..utils.fmt import now
from . import formulas, items as items_svc, players

NAME_RE = re.compile(r"^[\w \-’'.А-Яа-яЁё]+$", re.UNICODE)


def valid_name(name: str) -> bool:
    return B.GUILD_NAME_MIN <= len(name) <= B.GUILD_NAME_MAX and bool(NAME_RE.match(name))


async def get(q, gid: int) -> dict | None:
    return await q.one(
        "SELECT g.*, (SELECT COUNT(*) FROM players WHERE guild_id=g.id) AS members FROM guilds g WHERE g.id=?",
        (gid,))


async def create(db, uid: int, name: str) -> dict:
    name = " ".join(name.split())
    if not valid_name(name):
        return {"ok": False, "msg": f"Название: {B.GUILD_NAME_MIN}–{B.GUILD_NAME_MAX} символов, буквы/цифры/пробел/дефис."}
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if p["guild_id"]:
            return {"ok": False, "msg": "Ты уже состоишь в гильдии."}
        if await tx.one("SELECT 1 FROM guilds WHERE lower(name)=lower(?)", (name,)):
            return {"ok": False, "msg": "Такое название уже занято."}
        if not await players.spend(tx, uid, gold=B.GUILD_CREATE_COST):
            return {"ok": False, "msg": f"Нужно {B.GUILD_CREATE_COST} золота."}
        bmax = formulas.guild_boss_max(1)
        gid = await tx.insert(
            "INSERT INTO guilds(name, leader_id, boss_hp, boss_max, created_at) VALUES(?,?,?,?,?)",
            (name, uid, bmax, bmax, now()))
        await tx.execute("UPDATE players SET guild_id=?, guild_role='leader' WHERE user_id=?", (gid, uid))
        return {"ok": True, "id": gid}


async def join(db, uid: int, gid: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if p["guild_id"]:
            return {"ok": False, "msg": "Ты уже состоишь в гильдии."}
        g = await get(tx, gid)
        if not g:
            return {"ok": False, "msg": "Гильдия не найдена."}
        if g["members"] >= formulas.guild_max_members(g["level"]):
            return {"ok": False, "msg": "В гильдии нет мест."}
        await tx.execute("UPDATE players SET guild_id=?, guild_role='member' WHERE user_id=?", (gid, uid))
        return {"ok": True, "name": g["name"]}


async def invite(db, uid: int, target: int) -> dict:
    """Глава гильдии приглашает игрока по его Telegram ID. Игрок должен был хотя бы раз запустить бота."""
    async with db.transaction() as tx:
        me = await players.get(tx, uid)
        if not me["guild_id"] or me["guild_role"] != "leader":
            return {"ok": False, "msg": "Приглашать может только глава гильдии."}
        if target == uid:
            return {"ok": False, "msg": "Себя приглашать не нужно."}
        t = await players.get(tx, target)
        if not t:
            return {"ok": False, "msg": "Игрок с таким ID не найден. Он должен сначала запустить бота (/start)."}
        if t["banned"]:
            return {"ok": False, "msg": "Этого игрока приглашать нельзя."}
        if t["guild_id"]:
            return {"ok": False, "msg": "Игрок уже состоит в гильдии."}
        g = await get(tx, me["guild_id"])
        if g["members"] >= formulas.guild_max_members(g["level"]):
            return {"ok": False, "msg": "В гильдии нет мест."}
        await tx.execute("DELETE FROM guild_invites WHERE created_at<?", (now() - B.GUILD_INVITE_TTL,))
        if await tx.scalar("SELECT COUNT(*) FROM guild_invites WHERE guild_id=?", (g["id"],), 0) >= B.GUILD_INVITES_MAX:
            return {"ok": False, "msg": f"Слишком много ожидающих приглашений (максимум {B.GUILD_INVITES_MAX})."}
        if await tx.one("SELECT 1 FROM guild_invites WHERE guild_id=? AND user_id=?", (g["id"], target)):
            return {"ok": False, "msg": "Приглашение этому игроку уже отправлено."}
        await tx.execute("INSERT INTO guild_invites(guild_id, user_id, inviter_id, created_at) VALUES(?,?,?,?)",
                         (g["id"], target, uid, now()))
        return {"ok": True, "guild_id": g["id"], "guild": g["name"], "target_name": t["name"], "inviter": me["name"]}


async def my_invites(q, uid: int) -> list[dict]:
    return await q.all(
        "SELECT i.guild_id, i.inviter_id, g.name AS guild, g.level, "
        "(SELECT COUNT(*) FROM players WHERE guild_id=g.id) AS members "
        "FROM guild_invites i JOIN guilds g ON g.id=i.guild_id WHERE i.user_id=? AND i.created_at>=? "
        "ORDER BY i.created_at DESC LIMIT 10", (uid, now() - B.GUILD_INVITE_TTL))


async def accept_invite(db, uid: int, gid: int) -> dict:
    async with db.transaction() as tx:
        inv = await tx.one("SELECT * FROM guild_invites WHERE guild_id=? AND user_id=?", (gid, uid))
        if not inv or inv["created_at"] < now() - B.GUILD_INVITE_TTL:
            await tx.execute("DELETE FROM guild_invites WHERE guild_id=? AND user_id=?", (gid, uid))
            return {"ok": False, "msg": "Приглашение устарело или отозвано."}
        res = None
        p = await players.get(tx, uid)
        g = await get(tx, gid)
        if p["guild_id"]:
            res = {"ok": False, "msg": "Ты уже состоишь в гильдии."}
        elif not g:
            res = {"ok": False, "msg": "Гильдия больше не существует."}
        elif g["members"] >= formulas.guild_max_members(g["level"]):
            res = {"ok": False, "msg": "В гильдии нет мест."}
        if res:
            return res
        await tx.execute("UPDATE players SET guild_id=?, guild_role='member' WHERE user_id=?", (gid, uid))
        await tx.execute("DELETE FROM guild_invites WHERE user_id=?", (uid,))  # остальные приглашения больше не нужны
        return {"ok": True, "name": g["name"], "leader_id": g["leader_id"], "player": p["name"]}


async def decline_invite(db, uid: int, gid: int) -> dict:
    async with db.transaction() as tx:
        inv = await tx.one("SELECT inviter_id FROM guild_invites WHERE guild_id=? AND user_id=?", (gid, uid))
        await tx.execute("DELETE FROM guild_invites WHERE guild_id=? AND user_id=?", (gid, uid))
        g = await get(tx, gid)
        return {"ok": bool(inv), "inviter_id": inv["inviter_id"] if inv else None, "guild": g["name"] if g else ""}


async def leave(db, uid: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        gid = p["guild_id"]
        if not gid:
            return {"ok": False, "msg": "Ты не в гильдии."}
        await tx.execute("UPDATE players SET guild_id=NULL, guild_role=NULL WHERE user_id=?", (uid,))
        g = await tx.one("SELECT * FROM guilds WHERE id=?", (gid,))
        if g and g["leader_id"] == uid:
            heir = await tx.one("SELECT user_id FROM players WHERE guild_id=? ORDER BY level DESC LIMIT 1", (gid,))
            if heir:
                await tx.execute("UPDATE guilds SET leader_id=? WHERE id=?", (heir["user_id"], gid))
                await tx.execute("UPDATE players SET guild_role='leader' WHERE user_id=?", (heir["user_id"],))
            else:
                await tx.execute("DELETE FROM guilds WHERE id=?", (gid,))
                await tx.execute("DELETE FROM guild_damage WHERE guild_id=?", (gid,))
                await tx.execute("DELETE FROM guild_invites WHERE guild_id=?", (gid,))
        return {"ok": True}


async def kick(db, uid: int, target: int) -> dict:
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        t = await players.get(tx, target)
        if not p["guild_id"] or p["guild_role"] != "leader":
            return {"ok": False, "msg": "Только глава может исключать."}
        if not t or t["guild_id"] != p["guild_id"] or target == uid:
            return {"ok": False, "msg": "Игрок не найден в твоей гильдии."}
        await tx.execute("UPDATE players SET guild_id=NULL, guild_role=NULL WHERE user_id=?", (target,))
        return {"ok": True, "name": t["name"]}


async def donate(db, uid: int, amount: int) -> dict:
    if amount <= 0:
        return {"ok": False, "msg": "Некорректная сумма."}
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if not p["guild_id"]:
            return {"ok": False, "msg": "Ты не в гильдии."}
        if not await players.spend(tx, uid, gold=amount):
            return {"ok": False, "msg": "Не хватает золота."}
        g = await tx.one("SELECT * FROM guilds WHERE id=?", (p["guild_id"],))
        level, xp = g["level"], g["xp"] + amount
        while xp >= formulas.guild_xp_needed(level):
            xp -= formulas.guild_xp_needed(level)
            level += 1
        await tx.execute("UPDATE guilds SET level=?, xp=? WHERE id=?", (level, xp, g["id"]))
        return {"ok": True, "level": level, "gained": level - g["level"], "xp": xp}


async def list_guilds(q, page: int = 0, per: int = 6) -> tuple[list[dict], int]:
    total = await q.scalar("SELECT COUNT(*) FROM guilds", (), 0)
    rows = await q.all(
        "SELECT g.*, (SELECT COUNT(*) FROM players WHERE guild_id=g.id) AS members FROM guilds g "
        "ORDER BY level DESC, xp DESC LIMIT ? OFFSET ?", (per, page * per))
    return rows, total


async def members(q, gid: int) -> list[dict]:
    return await q.all(
        "SELECT p.user_id, p.name, p.level, p.guild_role, p.premium_until, "
        "COALESCE((SELECT dmg FROM guild_damage d WHERE d.guild_id=p.guild_id AND d.user_id=p.user_id "
        "AND d.cycle=(SELECT boss_cycle FROM guilds WHERE id=p.guild_id)),0) AS dmg "
        "FROM players p WHERE p.guild_id=? ORDER BY (p.guild_role='leader') DESC, p.level DESC", (gid,))


async def top(q, n: int = 10) -> list[dict]:
    return await q.all(
        "SELECT g.*, (SELECT COUNT(*) FROM players WHERE guild_id=g.id) AS members FROM guilds g "
        "ORDER BY level DESC, xp DESC LIMIT ?", (n,))


async def boss_hit(db, uid: int, rng: random.Random = random) -> dict:
    """Удар по гильдийному боссу. Если босс убит — награды всем участникам боя."""
    async with db.transaction() as tx:
        p = await players.get(tx, uid)
        if not p["guild_id"]:
            return {"ok": False, "msg": "Ты не в гильдии."}
        g = await tx.one("SELECT * FROM guilds WHERE id=?", (p["guild_id"],))
        if not await players.spend_energy(tx, p, B.GUILD_BOSS_COST):
            return {"ok": False, "msg": "Не хватает энергии.", "need": B.GUILD_BOSS_COST}
        stats = await players.derived(tx, p)
        dmg = int(stats["atk"] * rng.uniform(8, 12))
        crit = rng.random() < 0.1 + stats.get("crit", 0)
        if crit:
            dmg = int(dmg * 1.5)
        dmg = min(dmg, g["boss_hp"])
        hp_left = g["boss_hp"] - dmg
        await tx.execute(
            "INSERT INTO guild_damage(guild_id, cycle, user_id, dmg) VALUES(?,?,?,?) "
            "ON CONFLICT(guild_id, cycle, user_id) DO UPDATE SET dmg=guild_damage.dmg+excluded.dmg",
            (g["id"], g["boss_cycle"], uid, dmg))
        res = {"ok": True, "dmg": dmg, "crit": crit, "hp": hp_left, "max": g["boss_max"],
               "killed": False, "rewards": [], "boss_level": g["boss_level"]}
        if hp_left > 0:
            await tx.execute("UPDATE guilds SET boss_hp=? WHERE id=?", (hp_left, g["id"]))
            return res

        # босс убит: награды участникам, следующий босс
        rows = await tx.all("SELECT user_id, dmg FROM guild_damage WHERE guild_id=? AND cycle=? ORDER BY dmg DESC",
                            (g["id"], g["boss_cycle"]))
        total = sum(r["dmg"] for r in rows) or 1
        L = g["boss_level"]
        for i, r in enumerate(rows):
            share = r["dmg"] / total
            gold = int(300 * L * (0.5 + share))
            ess = 5 * L
            crystals = 5 if i == 0 else 0
            await players.add(tx, r["user_id"], gold=gold, essence=ess, crystals=crystals)
            res["rewards"].append({"user_id": r["user_id"], "gold": gold, "essence": ess, "crystals": crystals,
                                   "dmg": r["dmg"], "top": i == 0})
        if rows:
            top_p = await players.get(tx, rows[0]["user_id"])
            await items_svc.create(tx, rows[0]["user_id"], items_svc.roll_item(top_p["level"], rarity="epic"))
        # гильдия получает опыт, спавнится новый босс
        glevel, gxp = g["level"], g["xp"] + 500 * L
        while gxp >= formulas.guild_xp_needed(glevel):
            gxp -= formulas.guild_xp_needed(glevel)
            glevel += 1
        nb = formulas.guild_boss_max(L + 1)
        await tx.execute(
            "UPDATE guilds SET boss_level=?, boss_hp=?, boss_max=?, boss_cycle=boss_cycle+1, level=?, xp=? WHERE id=?",
            (L + 1, nb, nb, glevel, gxp, g["id"]))
        res.update(killed=True, hp=0)
        return res
