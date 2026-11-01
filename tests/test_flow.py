"""Сквозные тесты: настоящие обработчики aiogram + поддельный Telegram (см. harness.py)."""
import logging

import pytest

from bot.data import balance as B
from bot.emoji import EMOJI
from bot.services import players
from bot.utils.fmt import now

from .conftest import run
from .harness import make_harness


@pytest.fixture(autouse=True)
def _reset_state():
    EMOJI.custom.clear()
    EMOJI.enabled = True
    yield
    EMOJI.custom.clear()
    root = logging.getLogger()
    for h in list(root.handlers):
        if h.__class__.__name__ == "_ErrorCatcher":
            root.removeHandler(h)


async def start_player(h, uid=1, cls="warrior"):
    await h.say("/start", user=uid)
    await h.press(f"start:cls:{cls}", user=uid)


# ------------------------------------------------------------------ старт / меню
def test_start_flow_and_menu(db):
    async def go():
        h = await make_harness(db)
        await h.say("/start")
        assert "Выбери путь героя" in h.text()
        assert h.buttons() == ["start:cls:warrior", "start:cls:mage", "start:cls:rogue"]
        assert h.last().kind == "photo"
        await h.press("start:cls:mage")
        assert "Герой создан" in h.text()
        p = await players.get(db, 1)
        assert p["cls"] == "mage" and p["gold"] == 150
        assert len(await players.equipped_items(db, 1)) == 2
        await h.say("/menu")
        assert "Ур." in h.text() and "Энергия" in h.text()
        for target in ("profile", "help", "ref", "daily", "dq", "top:level", "top:arena", "top:rich", "top:guild",
                       "shop", "shop:prem", "shop:gems", "shop:cr", "mk", "g", "ar", "story", "adv", "inv:0", "idle", "idle:b", "idle:rb"):
            await h.press(target)
        h.assert_no_errors()
    run(go())


def test_double_class_click_and_unknown_player(db):
    async def go():
        h = await make_harness(db)
        await h.say("/start", user=5)
        await h.press("start:cls:rogue", user=5)
        await h.press("start:cls:warrior", user=5)  # повторный клик не пересоздаёт героя
        assert (await players.get(db, 5))["cls"] == "rogue"
        # игрок без героя нажимает чужую кнопку -> просьба нажать /start
        await h.say("/start", user=6)
        await h.press("idle:tap", user=6)
        assert any("/start" in t for t, alert in h.session.toasts)
        assert await players.get(db, 6) is None
        h.assert_no_errors()
    run(go())


def test_referral_flow(db):
    async def go():
        h = await make_harness(db)
        await start_player(h, 1)
        await h.say("/start ref_1", user=2)
        await h.press("start:cls:rogue:1", user=2)
        p2 = await players.get(db, 2)
        assert p2["ref_by"] == 1 and p2["crystals"] == B.REF_BONUS_NEW["crystals"]
        assert any(o.chat_id == 1 and "новый герой" in o.text for o in h.session.outs)  # пригласившему пришло уведомление
        await h.press("ref", user=1)
        assert "start=ref_1" in h.text(1)
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ рудник
def test_idle_tap_collect_upgrade(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await h.press("idle")
        g0 = (await players.get(db, 1))["gold"]
        for _ in range(16):
            await h.press("idle:tap")
        assert (await players.get(db, 1))["gold"] > g0
        assert (await players.get(db, 1))["taps"] == 16
        await db.execute("UPDATE players SET last_collect=? WHERE user_id=1", (now() - 4 * 3600,))
        await h.press("idle")
        before = (await players.get(db, 1))["gold"]
        await h.press("idle:collect")
        assert (await players.get(db, 1))["gold"] > before
        await db.execute("UPDATE players SET gold=100000 WHERE user_id=1")
        await h.press("idle:b")
        await h.press("idle:up:mine")
        assert "Улучшено" in h.text()
        await h.press("idle:up:library")  # закрыто по уровню
        assert h.session.toasts[-1][1] is True
        h.assert_no_errors()
    run(go())


def test_rebirth_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await db.execute("UPDATE players SET level=40 WHERE user_id=1")
        await h.press("idle:rb")
        assert "Переродиться" in " ".join(h.last().labels)
        await h.press("idle:rb:yes")
        p = await players.get(db, 1)
        assert p["level"] == 1 and p["marks"] >= 1
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ бой
def test_battle_through_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await db.execute("UPDATE players SET level=6, potions=3 WHERE user_id=1")
        await h.press("adv")
        await h.press("adv:loc:forest")
        await h.press("adv:go:forest:0")
        assert "bt:attack" in h.buttons()
        await h.press("bt:skill")
        await h.press("bt:skill")  # на кулдауне — не ломается
        await h.press("bt:potion")
        for _ in range(80):
            if "bt:attack" not in h.buttons():
                break
            await h.press("bt:attack")
        assert any(b.startswith("adv:go:") for b in h.buttons())  # экран итога
        text = h.text()
        assert "Победа" in text or "Поражение" in text
        assert (await players.get(db, 1))["energy"] < B.ENERGY_MAX
        await h.press("bt:attack")  # бой уже закончен
        h.assert_no_errors()
    run(go())


def test_battle_requires_energy(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await db.execute("UPDATE players SET energy=0, energy_ts=? WHERE user_id=1", (now(),))
        await h.press("adv")
        await h.press("adv:loc:forest")
        await h.press("adv:go:forest:1")
        assert h.session.toasts[-1][1] and "энерг" in h.session.toasts[-1][0].lower()
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ сюжет и задания
def test_story_walkthrough_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h, cls="rogue")
        await h.press("story")
        await h.press("story:ch:1")
        for _ in range(30):
            btns = [b for b in h.buttons() if b.startswith("story:c:")]
            if not btns:
                break
            await h.press(btns[0])
        assert "Глава завершена" in h.text()
        assert 1 in __import__("bot.services.story", fromlist=["load"]).load(await players.get(db, 1))["done"]
        h.assert_no_errors()
    run(go())


def test_daily_and_quests_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await h.press("daily")
        await h.press("daily:claim")
        assert "уже получена" in h.text()
        await h.press("daily:claim")
        assert h.session.toasts[-1][1] is True
        await h.press("dq")
        from bot.services import quests
        for q in await quests.list_today(db, await players.get(db, 1)):
            await quests.progress(db, 1, q["key"], 9999)
        await h.press("dq")
        claims = [b for b in h.buttons() if b.startswith("dq:claim:")]
        assert len(claims) == B.DAILY_QUESTS_PER_DAY
        for c in claims:
            await h.press(c)
            await h.press(c)  # повторный клик безопасен
        assert (await players.get(db, 1))["crystals"] >= B.DAILY_QUESTS_BONUS_CRYSTALS
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ сумка / рынок
def test_inventory_market_trade_between_players(db):
    async def go():
        h = await make_harness(db)
        await start_player(h, 1)
        await start_player(h, 2, "mage")
        from bot.services import items as items_svc
        async with db.transaction() as tx:
            iid = await items_svc.create(tx, 1, items_svc.roll_item(8, rarity="rare", slot="ring"))
        await db.execute("UPDATE players SET gold=100000, essence=1000 WHERE user_id=1")
        await h.press("inv:0")
        await h.press(f"inv:item:{iid}")
        await h.press(f"inv:enh:{iid}")
        await h.press(f"inv:equip:{iid}")
        await h.press(f"inv:unequip:{iid}")
        # выставляем на рынок через FSM
        await h.press(f"inv:list:{iid}")
        await h.say("abc")  # не число
        assert "Нужно число" in h.text()
        await h.say("5k")
        assert "Выставлено" in h.text()
        listing = await db.one("SELECT * FROM market")
        assert listing["price"] == 5000
        # второй игрок покупает
        await db.execute("UPDATE players SET gold=6000 WHERE user_id=2")
        await h.press("mk", user=2)
        await h.press("mk:b:ring:0", user=2)
        await h.press(f"mk:v:{listing['id']}", user=2)
        await h.press(f"mk:buy:{listing['id']}", user=2)
        assert "Куплено" in h.text(2)
        assert (await players.get(db, 2))["gold"] == 1000
        assert any(o.chat_id == 1 and "куплен" in o.text for o in h.session.outs)  # продавец уведомлён
        await h.press(f"mk:buy:{listing['id']}", user=2)  # лот уже продан
        await h.press("mk:mine", user=1)
        h.assert_no_errors()
    run(go())


def test_sell_junk_and_item_sale(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        from bot.services import items as items_svc
        async with db.transaction() as tx:
            ids = [await items_svc.create(tx, 1, items_svc.roll_item(5, rarity="common")) for _ in range(4)]
        await h.press("inv:junk")
        await h.press("inv:junk:yes")
        assert await db.scalar("SELECT COUNT(*) FROM items WHERE owner_id=1 AND equipped=0", (), 0) == 0
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ гильдия
def test_guild_flow_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h, 1)
        await start_player(h, 2)
        await db.execute("UPDATE players SET gold=50000, level=20 WHERE user_id=1")
        await db.execute("UPDATE players SET level=20 WHERE user_id=2")
        await h.press("g", user=1)
        await h.press("g:create", user=1)
        await h.say("!", user=1)  # невалидное имя
        assert "Название" in h.text(1)
        await h.say("Пепельный Орден", user=1)
        assert "Гильдия создана" in h.text(1)
        await h.press("g", user=1)
        assert "Пепельный Орден" in h.text(1)
        await h.press("g:list:0", user=2)
        await h.press("g:join:1", user=2)
        await h.press("g:don", user=1)
        await h.press("g:don:1000", user=1)
        await h.press("g:boss", user=2)
        await h.press("g:hit", user=2)
        assert "урона" in h.text(2)
        await h.press("g:mem", user=1)
        await h.press("g:kick:2", user=1)
        assert (await players.get(db, 2))["guild_id"] is None
        await h.press("g:leave", user=1)
        await h.press("g:leave:yes", user=1)
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ арена
def test_arena_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h, 1)
        await start_player(h, 2, "mage")
        await h.press("ar")
        await h.press("ar:fight")
        assert "раундов" in h.text()
        for _ in range(B.ARENA_TRIES):
            await h.press("ar:fight")
        assert any(b == "ar:buy" for b in h.buttons()) or "ar:fight" not in h.buttons()
        await db.execute("UPDATE players SET crystals=100 WHERE user_id=1")
        await h.press("ar")
        await h.press("ar:buy")
        await h.press("top:arena")
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ донат
def test_shop_payment_flow(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await h.press("shop:buy:prem:prem_30")
        inv = h.session.invoices[-1]
        assert inv.currency == "XTR" and inv.provider_token == "" and inv.prices[0].amount == 150
        assert len(inv.title) <= 32 and len(inv.description) <= 255
        await h.pay(inv.payload, 150, "ch-1")
        assert h.session.precheckout[-1].ok is True
        p = await players.get(db, 1)
        assert players.is_premium(p) and p["crystals"] == 50
        await h.pay(inv.payload, 150, "ch-1")  # повторная доставка того же платежа
        assert (await players.get(db, 1))["crystals"] == 50
        await h.pay("pack:gems_m", 125, "ch-2")
        assert (await players.get(db, 1))["crystals"] == 50 + 550
        assert (await db.scalar("SELECT SUM(stars) FROM payments")) == 275
        h.assert_no_errors()
    run(go())


def test_precheckout_rejects_bad_payloads(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        for payload, stars in (("hack:x", 1), ("pack:gems_s", 1), ("pack:nope", 25)):
            await h.pay(payload, stars, f"bad-{payload}")
            assert h.session.precheckout[-1].ok is False, payload
        # набор новичка нельзя купить дважды
        await h.press("shop:buy:starter:starter")
        await h.pay("starter:starter", 49, "st-1")
        assert (await players.get(db, 1))["starter_bought"] == 1
        await h.press("shop:buy:starter:starter")
        assert h.session.toasts[-1][1] is True
        await h.pay("starter:starter", 49, "st-2")
        assert h.session.precheckout[-1].ok is False
        h.assert_no_errors()
    run(go())


def test_paid_unknown_payload_is_recorded_and_reported(db):
    """Защитная ветка: деньги пришли, а товар не найден — платёж сохранён, игрок получает инструкцию."""
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await h.pay("pack:deleted_item", 77, "orphan-1", skip_precheckout=True)
        assert "поддержку" in h.text()
        assert "orphan-1" in h.text()  # ID платежа для обращения
        assert await db.scalar("SELECT stars FROM payments WHERE charge_id='orphan-1'") == 77
        assert any("unknown payload" in r.getMessage() for r in h.errors.records)  # залогировано как ERROR
        h.errors.records.clear()
        h.assert_no_errors()
    run(go())


def test_crystal_shop_via_ui(db):
    async def go():
        h = await make_harness(db)
        await start_player(h)
        await db.execute("UPDATE players SET crystals=400 WHERE user_id=1")
        await h.press("shop:cr")
        await h.press("shop:crc:chest_g")
        assert "Шансы" in h.text()
        await h.press("shop:crb:chest_g")
        assert (await players.get(db, 1))["crystals"] == 400 - 60
        for key in ("energy", "warp4", "potions", "chest_s", "arena"):
            await h.press(f"shop:crc:{key}")
            await h.press(f"shop:crb:{key}")
        h.assert_no_errors()
    run(go())


# ------------------------------------------------------------------ админка и премиум-эмодзи
def test_admin_commands_and_premium_emoji(db):
    async def go():
        h = await make_harness(db, admin_ids=(777,))
        await start_player(h, 1)
        await h.say("/admin", user=1)   # обычному игроку админка недоступна
        assert not any("Админ-панель" in o.text for o in h.session.outs)
        await start_player(h, 777)
        await h.say("/admin", user=777)
        assert "Админ-панель" in h.text(777)
        await h.say("/give 1 gold 12345", user=777)
        assert (await players.get(db, 1))["gold"] == 150 + 12345
        await h.say("/give 1 hacks 5", user=777)
        assert "Не удалось" in h.text(777)
        await h.say("/ban 1", user=777)
        await h.say("/menu", user=1)
        assert (await players.get(db, 1))["banned"] == 1
        await h.say("/unban 1", user=777)
        # премиум-эмодзи: по id
        await h.say("/setemoji gold 5368324170671202286", user=777)
        assert EMOJI.render("gold") == '<tg-emoji emoji-id="5368324170671202286">🪙</tg-emoji>'
        assert await db.scalar("SELECT custom_id FROM emoji_map WHERE name='gold'") == "5368324170671202286"
        await h.say("/menu", user=1)
        assert '<tg-emoji emoji-id="5368324170671202286">' in h.text(1)
        # премиум-эмодзи прямо в сообщении
        ent = [{"type": "bot_command", "offset": 0, "length": 9},
               {"type": "custom_emoji", "offset": 15, "length": 2, "custom_emoji_id": "5111111111111111111"}]
        await h.say("/setemoji crystal 💎", user=777, entities=ent)
        await h.say("/emojis", user=777)
        # ловец ID: любое сообщение с премиум-эмодзи
        await h.say("test 🔥", user=777, entities=[{"type": "custom_emoji", "offset": 5, "length": 2, "custom_emoji_id": "5222222222222222222"}])
        assert "5222222222222222222" in h.text(777)
        await h.say("/delemoji gold", user=777)
        assert EMOJI.render("gold") == "🪙"
        h.assert_no_errors()
    run(go())


def test_premium_emoji_can_be_disabled(db):
    async def go():
        h = await make_harness(db, premium_emoji=False)
        EMOJI.enabled = False
        EMOJI.custom["gold"] = "123"
        await start_player(h)
        await h.say("/menu")
        assert "<tg-emoji" not in h.text()
        h.assert_no_errors()
    run(go())


def test_spam_throttle_drops_fast_clicks(db):
    async def go():
        from bot.middlewares.throttle import ThrottleMiddleware
        t = ThrottleMiddleware(interval=10, tap_interval=10)
        calls = []

        async def handler(ev, data):
            calls.append(1)

        class U:
            id = 1

        await t(object(), {"event_from_user": U()}) if False else None
        # прямой вызов с сообщением-пустышкой
        from aiogram.types import CallbackQuery
        cb = CallbackQuery.model_construct(id="1", data="x", chat_instance="c", from_user=None)
        answered = []

        async def fake_answer(*a, **k):
            answered.append(1)

        object.__setattr__(cb, "answer", fake_answer)
        await t(handler, cb, {"event_from_user": U()})
        await t(handler, cb, {"event_from_user": U()})
        assert len(calls) == 1 and len(answered) == 1
    run(go())


# ------------------------------------------------------------------ рассылка
def test_broadcast_keeps_formatting_media_and_reply(db):
    import asyncio

    from bot.handlers import admin as admin_h
    from bot.services import broadcast

    async def finish(h):
        await h.press(h.find_button("bc:go:", 777), user=777)
        await asyncio.gather(*admin_h._tasks)

    async def go():
        h = await make_harness(db, admin_ids=(777,))   # у админа НЕТ героя — админка всё равно работает
        await start_player(h, 1)
        await start_player(h, 2)
        await h.say("/ban 2", user=777)
        await h.say("/unban 2", user=777)

        # 1) форматирование Telegram + премиум-эмодзи -> HTML
        ents = [{"type": "bot_command", "offset": 0, "length": 10},
                {"type": "bold", "offset": 18, "length": 6},
                {"type": "custom_emoji", "offset": 25, "length": 2, "custom_emoji_id": "5111111111111111111"}]
        await h.say("/broadcast Привет жирный 🔥", user=777, entities=ents)
        assert "<b>жирный</b>" in h.session.outs[-2].text and "Получателей: <b>2</b>" in h.text(777)
        await finish(h)
        for uid in (1, 2):
            t = [o.text for o in h.session.outs if o.chat_id == uid][-1]
            assert t == 'Привет <b>жирный</b> <tg-emoji emoji-id="5111111111111111111">🔥</tg-emoji>'
        assert "Доставлено: <b>2/2</b>" in h.text(777)

        # 2) HTML, написанный руками
        await h.say("/broadcast <i>курсив</i> и <a href=\"https://t.me/x\">ссылка</a>", user=777,
                    entities=[{"type": "bot_command", "offset": 0, "length": 10}])
        await finish(h)
        assert [o.text for o in h.session.outs if o.chat_id == 1][-1] == '<i>курсив</i> и <a href="https://t.me/x">ссылка</a>'

        # 3) фото с подписью: уходит копией с новой подписью
        await h.say("/broadcast Акция!", user=777, entities=[{"type": "bot_command", "offset": 0, "length": 10}],
                    extra={"photo": [{"file_id": "F", "file_unique_id": "U", "width": 10, "height": 10}]})
        await finish(h)
        assert h.session.copies[-1].caption == "Акция!" and h.session.copies[-1].parse_mode == "HTML"

        # 4) ответом на сообщение: копия как есть
        n = len(h.session.copies)
        await h.say("/broadcast", user=777, entities=[{"type": "bot_command", "offset": 0, "length": 10}],
                    extra={"reply_to_message": {"message_id": 5, "date": 1, "chat": {"id": 777, "type": "private"},
                                                 "text": "оригинал"}})
        await finish(h)
        assert len(h.session.copies) == n + 3 and h.session.copies[-1].message_id == 5  # предпросмотр + 2 игрока

        # 5) отмена и пустая команда
        await h.say("/broadcast тест", user=777, entities=[{"type": "bot_command", "offset": 0, "length": 10}])
        before = len(h.session.outs)
        await h.press(h.find_button("bc:no:", 777), user=777)
        assert not [o for o in h.session.outs[before:] if o.chat_id in (1, 2)]
        await h.say("/broadcast", user=777)
        assert "Рассылка" in h.text(777)
        # обычному игроку недоступно
        await h.say("/broadcast взлом", user=1)
        assert not any(o.text == "взлом" for o in h.session.outs)
        h.assert_no_errors()

    run(go())


# ------------------------------------------------------------------ приглашения в гильдию по ID
def test_guild_invite_by_id(db):
    from bot.services import guilds

    async def go():
        h = await make_harness(db)
        for uid in (1, 2, 3):
            await start_player(h, uid)
        await db.execute("UPDATE players SET gold=100000 WHERE user_id=1")
        await h.press("g", user=1)
        await h.press("g:create", user=1)
        await h.say("Орден Пепла", user=1)
        assert (await players.get(db, 1))["guild_role"] == "leader"

        # через кнопку и ввод ID
        await h.press("g", user=1)
        await h.press("g:inv", user=1)
        await h.say("не число", user=1)
        assert "число" in h.text(1)
        await h.say("2", user=1)
        assert "Приглашение отправлено" in h.text(1)
        assert "приглашает тебя в гильдию" in [o.text for o in h.session.outs if o.chat_id == 2][-1]
        await h.say("/invite 2", user=1)
        assert "уже отправлено" in h.text(1)
        # ошибки
        await h.say("/invite 999", user=1)
        assert "не найден" in h.text(1)
        await h.say("/invite 1", user=1)
        assert "Себя" in h.text(1)

        # игрок 2 принимает
        await h.press(h.find_button("g:inv:yes:", 2), user=2)
        p2 = await players.get(db, 2)
        assert p2["guild_id"] and p2["guild_role"] == "member"
        assert "принял приглашение" in [o.text for o in h.session.outs if o.chat_id == 1][-1]
        assert await db.scalar("SELECT COUNT(*) FROM guild_invites WHERE user_id=2") == 0
        await h.say("/invite 2", user=1)
        assert "уже состоит" in h.text(1)
        await h.say("/invite 3", user=2)                      # обычный участник приглашать не может
        assert "только глава" in h.text(2)
        await db.execute("DELETE FROM guild_invites")

        # отказ
        await h.say("/invite 3", user=1)
        await h.press(h.find_button("g:inv:no:", 3), user=3)
        assert (await players.get(db, 3))["guild_id"] is None
        assert "отклонил" in [o.text for o in h.session.outs if o.chat_id == 1][-1]
        await h.press("g:inv:yes:1", user=3)                  # старая кнопка после отказа
        assert (await players.get(db, 3))["guild_id"] is None

        # устаревшее приглашение
        await h.say("/invite 3", user=1)
        await db.execute("UPDATE guild_invites SET created_at=created_at-999999")
        assert not (await guilds.accept_invite(db, 3, 1))["ok"]
        assert await guilds.my_invites(db, 3) == []
        h.assert_no_errors()

    run(go())


def test_vein_break_via_ui(db):
    from bot.services import idle

    async def go():
        h = await make_harness(db)
        await start_player(h)
        idle._vein.clear()
        await h.press("idle")
        for _ in range(40):
            await h.press("idle:tap")
        assert any("обрушилась" in t for t, _ in h.session.toasts)
        assert "idle:repair" in h.buttons() and "idle:tap" not in h.buttons()
        assert "Жила обрушилась" in h.text()
        await db.execute("UPDATE players SET gold=100000 WHERE user_id=1")
        await h.press("idle:repair")
        assert "idle:tap" in h.buttons()
        h.assert_no_errors()

    run(go())


def test_admin_panel_tabs_and_user_card(db):
    async def go():
        h = await make_harness(db, admin_ids=(777,))          # у админа нет героя
        await start_player(h, 1)
        await start_player(h, 2, "mage")
        await h.say("/admin", user=777)
        assert "обзор" in h.text(777) and "Игроков: <b>2</b>" in h.text(777)
        from bot.services import payments
        await payments.grant(db, 1, "pack:gems_s", "charge-AAAAAAAAAAAA", 50)
        for tab, word in (("mn", "Деньги"), ("pl", "Игроки"), ("ec", "Экономика"), ("cmd", "Команды"), ("ov", "обзор")):
            await h.press(f"adm:{tab}", user=777)
            assert word in h.text(777), tab
        await h.press("adm:mn", user=777)
        assert "50⭐" in h.text(777) and "Платящих: <b>1</b>" in h.text(777)
        await h.say("/user 1", user=777)
        assert "Донат: 50⭐" in h.text(777)
        await h.say("/user user2", user=777)
        assert "mage" in h.text(777)
        await h.say("/user 12345", user=777)
        assert "не найден" in h.text(777)
        await h.press("adm:mn", user=1)                        # обычный игрок: ничего
        h.assert_no_errors()

    run(go())


def test_animated_cards_are_sent_as_animations_and_cached(db):
    from bot import ui
    from bot.images import theme

    async def go():
        ui._file_ids.clear()
        h = await make_harness(db, animated=True)
        try:
            await start_player(h)                  # баннер/профиль уходят как GIF-анимация
            await h.say("/menu")
            await h.press("world")
            await h.press("adv")
            await h.press("profile")
            assert h.session.animations, "ни одна карточка не ушла как анимация"
            uploads = lambda: sum(1 for a in h.session.animations if not isinstance(a.animation, str))  # noqa: E731
            first = uploads()
            await h.say("/menu")                   # повторный показ берёт file_id из кэша, файл не загружается заново
            assert uploads() == first
            assert all(v[1] for v in ui._file_ids.values())
            h.assert_no_errors()
        finally:
            theme.ANIMATE = False

    run(go())


def test_admin_price_and_discount(db):
    async def go():
        from bot.services import prices
        h = await make_harness(db, admin_ids=(777,))
        await start_player(h, 1)
        await start_player(h, 777)
        await h.say("/price", user=777)
        assert "pack:gems_s" in h.text(777)
        await h.say("/discount packs 50 24", user=777)
        assert "50%" in h.text(777)
        await h.say("/price prem:prem_30 77", user=777)
        assert prices.price("prem:prem_30", 150) == 77
        await h.say("/price pack:gems_s abc", user=777)
        assert "целое число" in h.text(777)
        await h.say("/discount nope 10", user=777)
        assert "Не знаю" in h.text(777)
        await h.say("/discount packs 200", user=777)
        assert "Формат" in h.text(777)
        await h.press("shop:gems", user=1)           # игрок видит старую цену и новую
        assert "<s>" in h.text(1)
        await h.say("/price", user=777)
        await h.say("/discount off", user=777)
        await h.say("/price prem:prem_30 reset", user=777)
        assert prices.discount("pack:gems_s") == 0 and prices.price("prem:prem_30", 150) == 150
        await h.say("/price", user=1)                # игроку недоступно
        h.assert_no_errors()
    run(go())


def test_flood_control_falls_back_to_caption(db):
    """Telegram ответил 429 на смену картинки — экран обновляется подписью, бот не падает."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import EditMessageCaption
    from aiogram.types import CallbackQuery, Message
    from bot import ui

    async def go():
        calls = {"media": 0, "caption": 0}
        msg = SimpleNamespace(photo=[1], animation=None, chat=SimpleNamespace(id=5), message_id=9)

        async def edit_media(*a, **k):
            calls["media"] += 1
            raise TelegramRetryAfter(method=EditMessageCaption(chat_id=5, caption="x"), message="flood", retry_after=200)

        async def edit_caption(**k):
            calls["caption"] += 1
            return True

        msg.edit_media, msg.edit_caption = edit_media, edit_caption
        cb = SimpleNamespace(message=msg)
        # обходим isinstance-проверки ui.screen
        orig_cb, orig_msg = ui.CallbackQuery, ui.Message
        ui.CallbackQuery, ui.Message = type(cb), type(msg)
        try:
            await ui.screen(cb, "текст", None, img=b"x", cache="k1")
            assert calls == {"media": 1, "caption": 1}
            await ui.screen(cb, "текст 2", None, img=b"x", cache="k2")     # пока действует лимит — картинку не трогаем
            assert calls == {"media": 1, "caption": 2}
        finally:
            ui.CallbackQuery, ui.Message = orig_cb, orig_msg
            ui._flood_until.clear()
    run(go())
