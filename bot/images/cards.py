"""Карточки-картинки для экранов бота. Все функции синхронные и возвращают JPEG-байты."""
from __future__ import annotations

from PIL import ImageDraw

from ..data.classes import CLASSES
from ..data.items import RARITY, SLOTS
from ..data.monsters import LOC
from ..utils.fmt import num
from . import art
from .theme import H, THEMES, W, bar, clean, font, lerp, panel, text, theme_background, to_bytes, fit

GOLD = (255, 205, 80)
WHITE = (245, 240, 230)
GREY = (170, 170, 180)


def _stat_row(d, x, y, label, value, color, w=300) -> None:
    text(d, (x, y), label, font(22, False), GREY)
    text(d, (x + w, y), value, font(26), color, anchor="ra")


# ------------------------------------------------------------------ баннеры
def banner(title: str, subtitle: str = "", theme: str = "menu") -> bytes:
    img = theme_background(theme)
    accent = THEMES.get(theme, THEMES["menu"])[2]
    art.draw_emblem(img, theme, W - 230, H / 2 - 20, 150, accent)
    panel(img, (40, H - 210, W - 330, H - 40), fill=(6, 6, 12, 150))
    d = ImageDraw.Draw(img)
    text(d, (70, H - 190), title, fit(d, title, W - 420, 56, 28), WHITE)
    if subtitle:
        text(d, (72, H - 112), subtitle, fit(d, subtitle, W - 420, 26, 16, False), lerp(accent, WHITE, 0.4))
    return to_bytes(img)


def location_card(loc_key: str, subtitle: str = "") -> bytes:
    loc = LOC[loc_key]
    from .theme import background, custom_background
    img = custom_background(f"loc_{loc_key}") or background(*loc["bg"], seed=sum(map(ord, loc_key)), accent=loc["accent"])
    kind = loc["boss"][1]
    art.draw_monster(img, kind, W - 260, H / 2 + 20, 150, loc["accent"], boss=True, name=loc["boss"][0])
    panel(img, (40, H - 210, W - 430, H - 40), fill=(6, 6, 12, 160))
    d = ImageDraw.Draw(img)
    text(d, (70, H - 190), loc["name"], fit(d, loc["name"], W - 520, 54, 28), WHITE)
    text(d, (72, H - 112), subtitle or f"Уровни {loc['min']}–{loc['max'] if loc['max'] < 900 else '∞'}",
         font(26, False), lerp(loc["accent"], WHITE, 0.4))
    return to_bytes(img)


# ------------------------------------------------------------------ профиль
def hero_card(h: dict) -> bytes:
    """h: name, cls, level, xp, xp_need, hp, atk, def, power, premium, guild, marks, title, rating"""
    cls = CLASSES[h["cls"]]
    color = cls["color"]
    img = theme_background("menu")
    # цветная подсветка класса слева
    from .theme import gradient
    tint = gradient(lerp((10, 10, 16), color, 0.35), (8, 8, 14), (W, H))
    tint.putalpha(110)
    img.alpha_composite(tint)
    art.draw_hero(img, h["cls"], 235, 300, 150, color)
    panel(img, (440, 36, W - 36, H - 36), fill=(6, 6, 12, 185), outline=(*lerp(color, WHITE, 0.2), 255))
    d = ImageDraw.Draw(img)
    name = ("♛ " if h.get("premium") else "") + clean(h["name"], "Герой", 22)
    text(d, (470, 56), name, fit(d, name, W - 36 - 470 - 30, 44, 24), WHITE)
    sub = cls["name"] + (f" · «{clean(h['title'], '', 24)}»" if h.get("title") else "")
    text(d, (472, 108), sub, font(24, False), lerp(color, WHITE, 0.5))
    # уровень + опыт
    text(d, (470, 156), f"Уровень {h['level']}", font(34), GOLD)
    bar(d, 470, 204, 420, 20, h["xp"] / max(1, h["xp_need"]), (120, 200, 255))
    text(d, (680, 232), f"опыт {num(h['xp'])} / {num(h['xp_need'])}", font(18, False), GREY, anchor="ma")
    y = 268
    _stat_row(d, 470, y, "Здоровье", num(h["hp"]), (255, 110, 110), 420)
    _stat_row(d, 470, y + 42, "Атака", num(h["atk"]), (255, 190, 100), 420)
    _stat_row(d, 470, y + 84, "Защита", num(h["def"]), (130, 190, 255), 420)
    _stat_row(d, 470, y + 126, "Сила героя", num(h["power"]), GOLD, 420)
    foot = []
    if h.get("guild"):
        foot.append(f"Гильдия: {clean(h['guild'], '', 18)}")
    if h.get("marks"):
        foot.append(f"Метки пепла: {h['marks']}")
    foot.append(f"Рейтинг арены: {h.get('rating', 1000)}")
    text(d, (470, H - 92), "  ·  ".join(foot), fit(d, "  ·  ".join(foot), 420, 22, 14, False), GREY)
    return to_bytes(img)


# ------------------------------------------------------------------ бой
def battle_card(st: dict) -> bytes:
    from .theme import background
    loc = LOC[st["loc"]]
    img = background(*loc["bg"], seed=sum(map(ord, st["loc"])), accent=loc["accent"])
    M, P = st["m"], st["p"]
    color = CLASSES[P["cls"]]["color"]
    art.draw_hero(img, P["cls"], 235, 335, 125, color)
    art.draw_monster(img, M["kind"], 700, 320, 140, loc["accent"], boss=st["boss"], flip=True, name=M["name"])
    d = ImageDraw.Draw(img)
    # плашки здоровья
    panel(img, (24, 20, 456, 112), fill=(6, 6, 12, 190), radius=16)
    panel(img, (W - 456, 20, W - 24, 112), fill=(6, 6, 12, 190), radius=16)
    d = ImageDraw.Draw(img)
    text(d, (44, 30), f"{CLASSES[P['cls']]['name']}", font(24), WHITE)
    bar(d, 44, 68, 392, 24, P["hp"] / P["max"], (220, 70, 70))
    text(d, (240, 80), f"{num(P['hp'])} / {num(P['max'])}", font(18), WHITE, anchor="mm")
    mname = ("☠ " if st["boss"] else "") + f"{M['name']}  ур.{M['lvl']}"
    text(d, (W - 436, 30), mname, fit(d, mname, 392, 24, 14), WHITE)
    bar(d, W - 436, 68, 392, 24, M["hp"] / M["max"], (230, 150, 50) if not st["boss"] else (200, 60, 200))
    text(d, (W - 240, 80), f"{num(M['hp'])} / {num(M['max'])}", font(18), WHITE, anchor="mm")
    # раунд и статус
    panel(img, (W / 2 - 110, H - 70, W / 2 + 110, H - 22), fill=(6, 6, 12, 190), radius=16)
    d = ImageDraw.Draw(img)
    text(d, (W / 2, H - 46), f"Раунд {st['round']}", font(26), GOLD, anchor="mm")
    status = []
    if st.get("poison"):
        status.append(f"яд ×{st['poison']}")
    if st.get("guard"):
        status.append("щит")
    if status:
        text(d, (W / 2, H - 92), " · ".join(status), font(20), (160, 255, 170), anchor="mm")
    return to_bytes(img, light=True)


# ------------------------------------------------------------------ предмет
def item_card(it: dict, caption: str = "") -> bytes:
    rar = RARITY[it["rarity"]]
    color = rar["color"]
    img = theme_background("bag")
    from .theme import gradient
    tint = gradient(lerp((8, 8, 12), color, 0.30), (8, 8, 12), (W, H))
    tint.putalpha(120)
    img.alpha_composite(tint)
    art.draw_item_icon(img, it["slot"], 245, 290, 150, color)
    panel(img, (470, 36, W - 36, H - 36), fill=(6, 6, 12, 190), outline=(*color, 255))
    d = ImageDraw.Draw(img)
    text(d, (500, 58), rar["name"].upper(), font(22), color)
    nm = it["name"] + (f" +{it['plus']}" if it.get("plus") else "")
    text(d, (500, 92), nm, fit(d, nm, W - 36 - 500 - 20, 36, 20), WHITE)
    text(d, (502, 150), f"{SLOTS[it['slot']]['name']} · ур. {it['ilvl']}", font(22, False), GREY)
    from ..services.formulas import item_mult
    m = item_mult(it.get("plus", 0))
    y = 210
    for label, key, col in (("Атака", "atk", (255, 190, 100)), ("Защита", "def", (130, 190, 255)),
                            ("Здоровье", "hp", (255, 110, 110))):
        if it.get(key):
            _stat_row(d, 500, y, label, f"+{num(int(it[key] * m))}", col, 400)
            y += 46
    if it.get("idle"):
        _stat_row(d, 500, y, "Idle-доход", f"+{it['idle']}%", GOLD, 400)
    if caption:
        text(d, (500, H - 92), caption, fit(d, caption, 400, 24, 14, False), lerp(color, WHITE, 0.5))
    return to_bytes(img)


# ------------------------------------------------------------------ арена
def arena_card(me: dict, opp: dict, win: bool, delta: int, rating: int) -> bytes:
    img = theme_background("arena")
    cm, co = CLASSES[me["cls"]]["color"], CLASSES[opp["cls"]]["color"]
    art.draw_hero(img, me["cls"], 215, 320, 125, cm)
    art.draw_hero(img, opp["cls"], W - 215, 320, 125, co, flip=True)
    panel(img, (W / 2 - 150, 120, W / 2 + 150, 290), fill=(6, 6, 12, 190))
    d = ImageDraw.Draw(img)
    text(d, (W / 2, 160), "ПОБЕДА" if win else "ПОРАЖЕНИЕ", font(34), (120, 240, 140) if win else (255, 100, 100), anchor="mm")
    sign = "+" if delta >= 0 else ""
    text(d, (W / 2, 215), f"{sign}{delta}", font(54), GOLD if win else (255, 150, 150), anchor="mm")
    text(d, (W / 2, 262), f"рейтинг {rating}", font(22, False), GREY, anchor="mm")
    panel(img, (24, 24, 420, 96), fill=(6, 6, 12, 190), radius=16)
    panel(img, (W - 420, 24, W - 24, 96), fill=(6, 6, 12, 190), radius=16)
    d = ImageDraw.Draw(img)
    text(d, (44, 36), clean(me["name"], "Герой", 22), fit(d, clean(me["name"], "Герой", 22), 360, 26, 14), WHITE)
    text(d, (44, 66), f"ур. {me['level']}", font(18, False), GREY)
    text(d, (W - 400, 36), clean(opp["name"], "Герой", 22), fit(d, clean(opp["name"], "Герой", 22), 360, 26, 14), WHITE)
    text(d, (W - 400, 66), f"ур. {opp['level']}  ·  рейтинг {opp['rating']}", font(18, False), GREY)
    return to_bytes(img)


# ------------------------------------------------------------------ босс гильдии
_BOSS_KINDS = ["golem", "dragon", "demon", "wraith", "spider", "knight", "skeleton", "beast"]


def guild_boss_card(g: dict) -> bytes:
    from .theme import background
    kind = _BOSS_KINDS[(g["boss_level"] - 1) % len(_BOSS_KINDS)]
    accent = lerp((255, 90, 70), (190, 90, 255), (g["boss_level"] % 5) / 5)
    img = background((20, 14, 30), (70, 26, 40), seed=g["boss_level"], accent=accent)
    art.draw_monster(img, kind, W / 2, 310, 165, accent, boss=True)
    panel(img, (60, 24, W - 60, 110), fill=(6, 6, 12, 190), radius=18)
    d = ImageDraw.Draw(img)
    text(d, (W / 2, 52), f"Босс гильдии «{clean(g['name'], 'Гильдия', 20)}» · ур. {g['boss_level']}", fit(d, "x" * 40, W - 160, 28, 16), WHITE, anchor="mm")
    bar(d, 90, 74, W - 180, 24, g["boss_hp"] / max(1, g["boss_max"]), (200, 60, 200))
    text(d, (W / 2, 86), f"{num(g['boss_hp'])} / {num(g['boss_max'])}", font(18), WHITE, anchor="mm")
    return to_bytes(img)


def guild_card(g: dict) -> bytes:
    img = theme_background("guild")
    art.draw_emblem(img, "guild", W - 220, H / 2 - 10, 150, (150, 170, 255))
    panel(img, (40, 60, W - 400, H - 60), fill=(6, 6, 12, 175))
    d = ImageDraw.Draw(img)
    text(d, (70, 82), clean(g["name"], "Гильдия", 20), fit(d, clean(g["name"], "Гильдия", 20), W - 480, 50, 24), WHITE)
    text(d, (72, 150), f"Уровень {g['level']}", font(32), GOLD)
    from ..services.formulas import guild_xp_needed
    bar(d, 72, 200, 400, 20, g["xp"] / guild_xp_needed(g["level"]), (150, 170, 255))
    text(d, (72, 232), f"{num(g['xp'])} / {num(guild_xp_needed(g['level']))} опыта гильдии", font(18, False), GREY)
    text(d, (72, 290), f"Участников: {g['members']}", font(26), WHITE)
    text(d, (72, 336), f"Босс гильдии: ур. {g['boss_level']}", font(26), (230, 150, 255))
    return to_bytes(img)
