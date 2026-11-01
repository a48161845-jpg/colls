"""Тесты игровой логики на реальной SQLite."""
import random

from bot.data import balance as B
from bot.data.shop import CRYSTAL_PACKS, PREMIUM_PLANS, STARTER_PACK
from bot.services import (arena, combat, daily, formulas, guilds, idle, items as items_svc, market, payments,
                          players, quests, story)
from bot.utils.fmt import now

from .conftest import make_player, run


# ----------------------------------------------------------------- ядро / валюты
def test_spend_is_atomic_and_never_negative(db):
    async def go():
        await make_player(db, 1, gold=100)
        assert not await players.spend(db, 1, gold=101)
        assert (await players.get(db, 1))["gold"] == 100
        assert await players.spend(db, 1, gold=100)
        assert (await players.get(db, 1))["gold"] == 0
        await players.add(db, 1, gold=-50)  # не уходит в минус
        assert (await players.get(db, 1))["gold"] == 0
    run(go())


def test_transaction_rolls_back_on_error(db):
    async def go():
        await make_player(db, 1, gold=500)
        try:
            async with db.transaction() as tx:
                await players.spend(tx, 1, gold=400)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert (await players.get(db, 1))["gold"] == 500
    run(go())


def test_level_up_and_referral_reward(db):
    async def go():
        await make_player(db, 1, name="Пригласивший")
        await make_player(db, 2, name="Новичок", ref_by=1)
        before = (await players.get(db, 1))["crystals"]
        async with db.transaction() as tx:
            info = await players.add_xp(tx, 2, 10_000)
        assert info["level"] > B.REF_LEVEL_REQUIRED and info["inviter"] == 1
        assert (await players.get(db, 1))["crystals"] == before + B.REF_BONUS_INVITER["crystals"]
        async with db.transaction() as tx:  # второй раз награды нет
            info2 = await players.add_xp(tx, 2, 10_000)
        assert info2["inviter"] is None
    run(go())


def test_energy_spend_and_regen(db):
    async def go():
        p = await make_player(db, 1)
        async with db.transaction() as tx:
            assert await players.spend_energy(tx, p, 60)
        p = await players.get(db, 1)
        cur, mx, _ = await players.energy(db, p)
        assert 39 < cur < 41 and mx == B.ENERGY_MAX
        async with db.transaction() as tx:
            assert not await players.spend_energy(tx, p, 99)
        await db.execute("UPDATE players SET energy_ts=? WHERE user_id=1", (now() - 3600,))
        cur, _, _ = await players.energy(db, await players.get(db, 1))
        assert cur > 55
    run(go())


# ----------------------------------------------------------------- idle
def test_idle_collect_upgrade_and_cap(db):
    async def go():
        await make_player(db, 1, gold=100_000, level=10, last_collect=now() - 100 * 3600)
        p = await players.get(db, 1)
        pend, ov = await idle.pending(db, p)
        assert pend["full"] and pend["hours"] == ov["cap_h"]  # упёрлись в лимит офлайна
        res = await idle.collect(db, 1)
        assert res["gold"] > 0
        p = await players.get(db, 1)
        assert p["gold"] >= 100_000 + res["gold"]
        up = await idle.upgrade(db, 1, "mine")
        assert up["ok"] and up["level"] == 2
        bad = await idle.upgrade(db, 1, "library")  # откроется на 12 уровне
        assert not bad["ok"]
    run(go())


def test_tap_updates_gold_and_crit(db):
    async def go():
        await make_player(db, 1, gold=0)
        total = 0
        idle._vein.clear()
        for _ in range(15):
            r = await idle.tap(db, 1, random.Random(7))
            total += r["gain"]
        p = await players.get(db, 1)
        assert p["gold"] == total and p["taps"] == 15
    run(go())


def test_vein_breaks_when_spammed_then_repairs_or_recovers(db):
    from bot.data import balance as B
    from bot.utils import fmt

    async def go():
        await make_player(db, 1, gold=0, level=10)
        idle._vein.clear()
        res = [await idle.tap(db, 1) for _ in range(40)]       # без пауз: жила рушится
        broke = next(i for i, r in enumerate(res) if r["broken"])
        assert res[broke]["just_broken"] and 15 <= broke <= 25
        assert all(r["broken"] and r["gain"] == 0 for r in res[broke:])
        gold = (await players.get(db, 1))["gold"]
        assert (await players.get(db, 1))["taps"] == broke                   # удары по сломанной жиле не считаются
        # починка за золото: без золота нельзя
        assert not (await idle.repair(db, 1))["ok"]
        await db.execute("UPDATE players SET gold=? WHERE user_id=1", (gold + 5000,))
        r = await idle.repair(db, 1)
        assert r["ok"] and r["cost"] == idle.repair_cost(10)
        assert not (await idle.tap(db, 1))["broken"]
        # самовосстановление по времени
        idle._vein[1] = [B.VEIN_HEAT_MAX, fmt.now(), fmt.now() + 5]
        assert idle.vein_state(1)["broken"]
        idle._vein[1][2] = fmt.now() - 1
        assert not idle.vein_state(1)["broken"] and idle.vein_state(1)["heat"] == 0
        # медленный ритм жилу не ломает
        idle._vein.clear()
        for _ in range(30):
            idle._vein[1] = [max(0.0, idle._vein.get(1, [0, 0, 0])[0]), fmt.now() - 2, 0.0]
            assert not (await idle.tap(db, 1))["broken"]

    run(go())


def test_rebirth(db):
    async def go():
        await make_player(db, 1, level=35, gold=999)
        r = await idle.rebirth(db, 1)
        assert r["ok"] and r["marks"] == 1
        p = await players.get(db, 1)
        assert p["level"] == 1 and p["marks"] == 1
        assert (await idle.get_buildings(db, 1))["mine"] == 1
        assert not (await idle.rebirth(db, 1))["ok"]
    run(go())


# ----------------------------------------------------------------- бой
def test_full_battle_flow_win(db):
    async def go():
        await make_player(db, 1, level=5)
        r = await combat.start(db, 1, "forest", False)
        assert r["ok"]
        assert (await combat.start(db, 1, "forest", False))["resumed"]  # повторный старт = продолжение
        st = None
        for _ in range(60):
            st = await combat.act(db, 1, "attack")
            if st["done"]:
                break
        assert st["done"] in ("win", "lose")
        assert await combat.get_state(db, 1) is None
        if st["done"] == "win":
            assert st["result"]["xp"] > 0
            assert (await players.get(db, 1))["kills"] == 1
    run(go())


def test_battle_needs_energy_and_level(db):
    async def go():
        await make_player(db, 1, level=1, energy=0)
        assert not (await combat.start(db, 1, "forest", False))["ok"]
        await players.fill_energy(db, 1)
        assert not (await combat.start(db, 1, "crypt", False))["ok"]  # нужен 10 уровень
    run(go())


def test_combat_engine_skills_and_potions():
    rng = random.Random(1)
    base = {"user_id": 1, "level": 10, "cls": "mage", "potions": 1}
    st = combat.new_state(base, {"hp": 500, "atk": 80, "def": 30, "crit": 0.0}, "crypt", False, rng)
    assert combat.step(st, "skill", rng) and st["cd"] > 0
    assert not combat.step(st, "skill", rng)  # кулдаун
    st["p"]["hp"] = 100
    assert combat.step(st, "potion", rng) and st["potions_used"] == 1
    st["m"]["hp"] = 10**6
    assert not combat.step(st, "potion", rng)  # зелья кончились
    boss = combat.new_state(base, {"hp": 500, "atk": 80, "def": 30, "crit": 0.0}, "crypt", True, rng)
    assert not combat.step(boss, "flee", rng)  # от босса не сбежать


def test_rogue_poison_ticks():
    rng = random.Random(3)
    st = combat.new_state({"user_id": 1, "level": 10, "cls": "rogue", "potions": 0},
                          {"hp": 5000, "atk": 100, "def": 80, "crit": 0.1}, "crypt", False, rng)
    st["m"]["hp"] = st["m"]["max"] = 10**7
    combat.step(st, "skill", rng)
    assert st["poison"] == 2  # 3 минус тик этого же хода


# ----------------------------------------------------------------- предметы / рынок
def test_item_equip_enhance_sell(db):
    async def go():
        await make_player(db, 1, gold=10**7, essence=10**4)
        async with db.transaction() as tx:
            iid = await items_svc.create(tx, 1, items_svc.roll_item(10, rarity="rare", slot="weapon"))
        ok, _ = await items_svc.equip(db, 1, iid)
        assert ok
        old = [i for i in await players.equipped_items(db, 1) if i["slot"] == "weapon"]
        assert len(old) == 1 and old[0]["id"] == iid  # старое оружие снято автоматически
        res = await items_svc.enhance(db, 1, iid, random.Random(0))
        assert res["ok"] and res["success"]
        assert not (await items_svc.sell(db, 1, iid))[0]  # надетое не продать
        await items_svc.unequip(db, 1, iid)
        ok, _, price = await items_svc.sell(db, 1, iid)
        assert ok and price > 0
    run(go())


def test_market_buy_tax_and_ownership(db):
    async def go():
        await make_player(db, 1, name="Продавец", gold=0)
        await make_player(db, 2, name="Покупатель", gold=5000)
        async with db.transaction() as tx:
            iid = await items_svc.create(tx, 1, items_svc.roll_item(5, rarity="epic"))
        r = await market.list_item(db, 1, iid, 1000)
        assert r["ok"]
        assert not (await market.buy(db, 1, r["id"]))["ok"]  # свой лот
        b = await market.buy(db, 2, r["id"])
        assert b["ok"] and b["tax"] == int(1000 * B.MARKET_TAX)
        assert (await players.get(db, 1))["gold"] == 1000 - b["tax"]
        assert (await players.get(db, 2))["gold"] == 4000
        assert (await items_svc.get(db, 2, iid)) is not None
        assert not (await market.buy(db, 2, r["id"]))["ok"]  # лот уже продан
    run(go())


def test_market_rejects_equipped_and_bad_price(db):
    async def go():
        await make_player(db, 1)
        eq = (await players.equipped_items(db, 1))[0]["id"]
        assert not (await market.list_item(db, 1, eq, 100))["ok"]
        async with db.transaction() as tx:
            iid = await items_svc.create(tx, 1, items_svc.roll_item(3))
        assert not (await market.list_item(db, 1, iid, 0))["ok"]
        ok = await market.list_item(db, 1, iid, 50)
        assert ok["ok"]
        assert not (await items_svc.sell(db, 1, iid))[0]  # выставленное не продать в лавку
        assert (await market.cancel(db, 1, ok["id"]))["ok"]
    run(go())


# ----------------------------------------------------------------- гильдии
def test_guild_lifecycle_and_boss(db):
    async def go():
        await make_player(db, 1, name="Глава", gold=B.GUILD_CREATE_COST + 10, level=30)
        await make_player(db, 2, name="Участник", level=30)
        g = await guilds.create(db, 1, "Пепельный Орден")
        assert g["ok"]
        assert not (await guilds.create(db, 2, "Пепельный орден"))["ok"]  # дубль без учёта регистра
        assert (await guilds.join(db, 2, g["id"]))["ok"]
        # босс: бьём, пока не умрёт
        killed = None
        for _ in range(400):
            await players.fill_energy(db, 1)
            await players.fill_energy(db, 2)
            r = await guilds.boss_hit(db, 1 if _ % 2 else 2, random.Random(_))
            assert r["ok"]
            if r["killed"]:
                killed = r
                break
        assert killed and killed["rewards"] and any(x["top"] for x in killed["rewards"])
        info = await guilds.get(db, g["id"])
        assert info["boss_level"] == 2 and info["boss_hp"] == info["boss_max"]
        # глава уходит — лидерство переходит
        assert (await guilds.leave(db, 1))["ok"]
        assert (await players.get(db, 2))["guild_role"] == "leader"
    run(go())


def test_guild_donate_levels_up(db):
    async def go():
        await make_player(db, 1, gold=B.GUILD_CREATE_COST + 50_000)
        g = await guilds.create(db, 1, "Тест")
        r = await guilds.donate(db, 1, 50_000)
        assert r["ok"] and r["gained"] >= 1
        assert not (await guilds.donate(db, 1, 10**9))["ok"]
    run(go())


# ----------------------------------------------------------------- арена
def test_arena_vs_npc_and_vs_player(db):
    async def go():
        await make_player(db, 1, level=10)
        r = await arena.fight(db, 1, random.Random(5))
        assert r["ok"] and r["opp"]["npc"]
        await make_player(db, 2, level=10, name="Соперник")
        r2 = await arena.fight(db, 1, random.Random(5))
        assert r2["ok"] and not r2["opp"]["npc"]
        # лимит попыток
        left = arena.tries_left(await players.get(db, 1))
        for _ in range(left):
            await arena.fight(db, 1, random.Random(1))
        assert not (await arena.fight(db, 1))["ok"]
        await arena.add_try(db, 1)
        assert (await arena.fight(db, 1))["ok"]
    run(go())


def test_elo_symmetry():
    assert arena.elo_delta(1000, 1000, 1.0) == 16
    assert arena.elo_delta(1000, 1000, 0.0) == -16
    assert arena.elo_delta(1400, 1000, 1.0) < 16 < arena.elo_delta(1000, 1400, 1.0)


# ----------------------------------------------------------------- квесты / сюжет / ежедневка
def test_daily_quests_progress_and_claim(db):
    async def go():
        p = await make_player(db, 1, level=5)
        qs = await quests.list_today(db, p)
        assert len(qs) == B.DAILY_QUESTS_PER_DAY
        for q in qs:
            await quests.progress(db, 1, q["key"], 10_000)
        total_bonus = 0
        for q in await quests.list_today(db, await players.get(db, 1)):
            assert q["done"]
            r = await quests.claim(db, 1, q["key"])
            assert r["ok"]
            total_bonus += r["bonus"]
            assert not (await quests.claim(db, 1, q["key"]))["ok"]  # повторно нельзя
        assert total_bonus == B.DAILY_QUESTS_BONUS_CRYSTALS
    run(go())


def test_story_chapter_playthrough(db):
    async def go():
        await make_player(db, 1, level=12)
        assert (await story.start_chapter(db, 1, 1))["ok"]
        assert not (await story.start_chapter(db, 1, 2))["ok"]  # сначала глава 1
        rng = random.Random(2)
        for _ in range(40):
            p = await players.get(db, 1)
            cur = story.current(p)
            if not cur:
                break
            _, _, node = cur
            idx = next(i for i, c in enumerate(node["choices"]) if story.choice_visible(c, p))
            res = await story.choose(db, 1, idx, rng)
            assert res["ok"]
        p = await players.get(db, 1)
        assert 1 in story.load(p)["done"]
        assert (await story.start_chapter(db, 1, 2))["ok"]
    run(go())


def test_story_hides_class_choices(db):
    async def go():
        await make_player(db, 1, cls="mage", level=3)
        await story.start_chapter(db, 1, 1)
        await db.execute("UPDATE players SET story=? WHERE user_id=1", ('{"ch":1,"node":"forest","done":[],"flags":[]}',))
        p = await players.get(db, 1)
        node = story.current(p)[2]
        visible = [c["text"] for c in node["choices"] if story.choice_visible(c, p)]
        assert any("заклинанием" in t for t in visible) and not any("плечом" in t for t in visible)
        warrior_idx = next(i for i, c in enumerate(node["choices"]) if "плечом" in c["text"])
        assert not (await story.choose(db, 1, warrior_idx))["ok"]
    run(go())


def test_daily_bonus_streak(db):
    async def go():
        await make_player(db, 1)
        r1 = await daily.claim(db, 1)
        assert r1["ok"] and r1["streak"] == 1
        assert not (await daily.claim(db, 1))["ok"]
        await db.execute("UPDATE players SET last_daily=last_daily-1 WHERE user_id=1")
        assert (await daily.claim(db, 1))["streak"] == 2
        await db.execute("UPDATE players SET last_daily=last_daily-5 WHERE user_id=1")  # стрик сорван
        assert (await daily.claim(db, 1))["streak"] == 1
    run(go())


# ----------------------------------------------------------------- донат
def test_payment_pack_is_idempotent(db):
    async def go():
        await make_player(db, 1)
        r = await payments.grant(db, 1, "pack:gems_m", "charge-1", 250)
        assert r["ok"] and r["crystals"] == CRYSTAL_PACKS["gems_m"]["crystals"]
        dup = await payments.grant(db, 1, "pack:gems_m", "charge-1", 250)
        assert dup["duplicate"]
        assert (await players.get(db, 1))["crystals"] == CRYSTAL_PACKS["gems_m"]["crystals"]
    run(go())


def test_payment_premium_and_starter_once(db):
    async def go():
        await make_player(db, 1)
        r = await payments.grant(db, 1, "prem:prem_30", "c2", 300)
        assert r["until"] > now() + 29 * 86400
        p = await players.get(db, 1)
        assert players.is_premium(p) and p["crystals"] == PREMIUM_PLANS["prem_30"]["crystals"]
        await payments.grant(db, 1, "prem:prem_30", "c3", 300)  # продлевается, а не перезаписывается
        assert (await players.get(db, 1))["premium_until"] > now() + 59 * 86400
        ok, _ = await payments.can_buy(db, 1, "starter:starter")
        assert ok
        await payments.grant(db, 1, "starter:starter", "c4", STARTER_PACK["stars"])
        ok, why = await payments.can_buy(db, 1, "starter:starter")
        assert not ok
    run(go())


def test_unknown_payload_rejected(db):
    assert payments.resolve("pack:nope") is None
    assert payments.resolve("hack:gems_s") is None
    assert payments.resolve("pack:gems_s")["stars"] == CRYSTAL_PACKS["gems_s"]["stars"]


def test_crystal_shop(db):
    async def go():
        await make_player(db, 1, crystals=500, level=20)
        for key in ("energy", "warp4", "arena", "potions", "chest_s", "chest_g"):
            r = await payments.spend_crystals(db, 1, key, random.Random(1))
            assert r["ok"], key
        gold_chest = await payments.spend_crystals(db, 1, "chest_g", random.Random(2))
        assert gold_chest["item"]["rarity"] in ("epic", "legendary", "mythic")
        await db.execute("UPDATE players SET crystals=0 WHERE user_id=1")
        assert not (await payments.spend_crystals(db, 1, "energy"))["ok"]
    run(go())


def test_chest_odds_sum_sane():
    from bot.data.shop import CHEST_ODDS
    for odds in CHEST_ODDS.values():
        assert abs(sum(odds.values()) - 100) < 0.01


# ----------------------------------------------------------------- баланс
def test_balance_curves_monotonic():
    prev = 0
    for lvl in range(1, 100):
        need = formulas.xp_needed(lvl)
        assert need > prev
        prev = need
    assert formulas.building_cost("mine", 10) > formulas.building_cost("mine", 9)
    assert formulas.sell_price({"ilvl": 10, "rarity": "epic", "plus": 0}) > formulas.sell_price(
        {"ilvl": 10, "rarity": "rare", "plus": 0})


# ----------------------------------------------------------------- гонки (одновременные действия)
def test_concurrent_market_buy_only_one_wins(db):
    import asyncio

    async def go():
        await make_player(db, 1, name="Продавец", gold=0)
        for uid in range(2, 12):
            await make_player(db, uid, gold=1000)
        async with db.transaction() as tx:
            iid = await items_svc.create(tx, 1, items_svc.roll_item(5, rarity="epic"))
        lot = await market.list_item(db, 1, iid, 700)
        results = await asyncio.gather(*(market.buy(db, uid, lot["id"]) for uid in range(2, 12)))
        assert sum(1 for r in results if r["ok"]) == 1
        owners = await db.scalar("SELECT owner_id FROM items WHERE id=?", (iid,))
        assert owners in range(2, 12)
        total_gold = await db.scalar("SELECT SUM(gold) FROM players", (), 0)
        taxes = int(700 * B.MARKET_TAX)
        assert total_gold == 10 * 1000 - taxes  # золото не создано и не потеряно, кроме комиссии
    run(go())


def test_concurrent_spend_never_goes_negative(db):
    import asyncio

    async def go():
        await make_player(db, 1, gold=1000)

        async def buy():
            async with db.transaction() as tx:
                return await players.spend(tx, 1, gold=300)

        results = await asyncio.gather(*(buy() for _ in range(10)))
        assert sum(results) == 3
        assert (await players.get(db, 1))["gold"] == 100
    run(go())


def test_concurrent_duplicate_payment_grants_once(db):
    import asyncio

    async def go():
        await make_player(db, 1)
        results = await asyncio.gather(*(payments.grant(db, 1, "pack:gems_s", "same-charge", 50) for _ in range(8)))
        assert sum(1 for r in results if not r.get("duplicate")) == 1
        assert (await players.get(db, 1))["crystals"] == CRYSTAL_PACKS["gems_s"]["crystals"]
    run(go())


def test_concurrent_daily_claim_once(db):
    import asyncio

    async def go():
        await make_player(db, 1)
        results = await asyncio.gather(*(daily.claim(db, 1) for _ in range(6)))
        assert sum(1 for r in results if r["ok"]) == 1
    run(go())


def test_concurrent_quest_claim_once(db):
    import asyncio

    async def go():
        p = await make_player(db, 1, level=5)
        q = (await quests.list_today(db, p))[0]
        await quests.progress(db, 1, q["key"], 9999)
        before = (await players.get(db, 1))["gold"] + (await players.get(db, 1))["essence"]
        results = await asyncio.gather(*(quests.claim(db, 1, q["key"]) for _ in range(6)))
        assert sum(1 for r in results if r["ok"]) == 1
    run(go())


def test_button_icons_markers():
    from bot.emoji import EMOJI, p
    old = (EMOJI.enabled, EMOJI.button_icons, dict(EMOJI.custom))
    try:
        EMOJI.enabled, EMOJI.button_icons, EMOJI.custom = True, True, {"gold": "555"}
        assert EMOJI.split_button(f"{p('gold')} Рудник") == ("Рудник", "555")
        assert EMOJI.split_button(f"Рудник {p('gold')}")[1] is None
        EMOJI.button_icons = False
        text, icon = EMOJI.split_button(f"{p('gold')} Рудник")
        assert icon is None and "" not in text
    finally:
        EMOJI.enabled, EMOJI.button_icons, EMOJI.custom = old


def test_custom_sprites_are_used(tmp_path, monkeypatch):
    from PIL import Image
    from bot.images import art, cards
    (tmp_path / "monsters").mkdir()
    Image.new("RGBA", (64, 128), (255, 0, 255, 255)).save(tmp_path / "monsters" / "beast.png")
    monkeypatch.setattr(art, "SPRITE_DIR", tmp_path)
    art._load_sprite.cache_clear()
    try:
        img = Image.new("RGBA", (960, 540), (0, 0, 0, 255))
        art.draw_monster(img, "beast", 600, 300, 120, (255, 150, 70))
        assert (255, 0, 255, 255) in {img.getpixel((600, y)) for y in range(250, 420, 5)}
        assert cards.banner("x", "y", "menu")  # обычные карточки рисуются
    finally:
        art._load_sprite.cache_clear()


def test_image_text_keeps_characters_and_falls_back_to_other_fonts():
    from PIL import Image, ImageDraw
    from bot.images import cards
    from bot.images.theme import clean, font, measure, text

    assert clean("𝓗𝓮𝓵𝓵𝓸 ｗｏｒｌｄ") == "Hello world"            # «красивые» шрифты приводятся к обычным буквам
    assert clean("a\u200bb\u202ec\x00") == "abc"                   # невидимое и управляющее убирается
    assert clean("Игрок 🔥") == "Игрок 🔥"                           # эмодзи остаются
    assert len(clean("a" + "\u0336" * 40)) <= 3                    # «зальго» ограничено
    assert clean("\u200b", "Герой") == "Герой"
    assert len(clean("Я" * 200, limit=20)) == 20
    # каждая строка реально рисуется (чернила на картинке), включая эмодзи и экзотические письменности
    for name in ("Привет", "Hello", "漢字 テスト", "한국어", "ไทย", "हिन्दी", "مرحبا", "🐉 Дракон 🔥", "★✦☠♛", "ꙮ ⚔ ♞"):
        img = Image.new("L", (600, 80), 0)
        text(ImageDraw.Draw(img), (10, 10), name, font(34, False), fill=255, shadow=False)
        assert img.getbbox(), name
        assert measure(clean(name), font(34, False)) > 10, name
    # карточки с «опасными» именами рисуются без исключений
    nasty = "😀🔥 Имя‮\u0000" + "Ш" * 80
    assert cards.hero_card(dict(name=nasty, cls="mage", level=5, xp=1, xp_need=10, hp=1, atk=1, power=1, premium=True,
                                guild=nasty, marks=0, title=nasty, rating=1000, **{"def": 1}))
    assert cards.arena_card({"name": nasty, "cls": "warrior", "level": 1}, {"name": "🐉", "cls": "mage", "level": 2, "rating": 1}, True, 5, 1005)
    assert cards.guild_card({"name": nasty, "level": 1, "xp": 0, "members": 1, "boss_level": 1})


def test_price_rules(db):
    async def go():
        import asyncio
        from bot.services import prices
        base = CRYSTAL_PACKS["gems_s"]["stars"]
        assert payments.resolve("pack:gems_s")["stars"] == base
        await prices.set_discount(db, prices.groups()["packs"], 50)
        assert payments.resolve("pack:gems_s")["stars"] == max(1, round(base / 2))
        await prices.set_price(db, "pack:gems_s", 10)
        assert payments.resolve("pack:gems_s")["stars"] == 5
        await prices.load(db)                      # правила переживают перезагрузку из БД
        assert payments.resolve("pack:gems_s")["stars"] == 5
        await prices.set_discount(db, prices.groups()["all"], 0)
        await prices.set_price(db, "pack:gems_s", None)
        assert payments.resolve("pack:gems_s")["stars"] == base
        await prices.set_discount(db, ["cr:energy"], 50, 0.0001)   # истекает почти сразу
        assert prices.discount("cr:energy") == 50
        await asyncio.sleep(0.5)
        assert prices.discount("cr:energy") == 0
        await prices.clear(db)
    run(go())
