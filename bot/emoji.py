"""Система эмодзи с поддержкой Premium (кастомных) эмодзи.

В тексте везде используется e("gold") — это даёт либо обычный эмодзи-заглушку,
либо <tg-emoji emoji-id="...">🪙</tg-emoji>, если для имени задан ID.

ID можно задавать тремя способами:
  1) файл bot/data/premium_emoji.json  (имя -> id), подхватывается при старте;
  2) админ-команда  /setemoji gold 5368324170671202286
     или отправить боту /setemoji gold вместе с премиум-эмодзи в сообщении;
  3) напрямую в базе (таблица emoji_map).

ВАЖНО (Bot API 9.4, февраль 2026): бот может слать премиум-эмодзи, если у ВЛАДЕЛЬЦА бота есть
Telegram Premium. Без Premium Telegram покажет обычный эмодзи-заглушку.

Кнопки: Bot API 9.4 добавил поле icon_custom_emoji_id у inline-кнопок. Это включается отдельно
(PREMIUM_BUTTONS=1 в .env): ведущий эмодзи подписи кнопки заменяется на иконку-премиум.
Если Telegram отклонит такую кнопку, бот сам отключит иконки и продолжит работать.
"""
from __future__ import annotations

import json
from pathlib import Path

# имя -> эмодзи-заглушка
DEFAULTS: dict[str, str] = {
    # ресурсы
    "gold": "🪙", "crystal": "💎", "essence": "🔮", "xp": "✨", "mark": "🔥",
    "potion": "🧪", "stars": "⭐",
    # характеристики
    "hp": "❤️", "atk": "⚔️", "def": "🛡", "energy": "⚡", "level": "🎖", "power": "💪",
    "crit": "💥",
    # разделы меню
    "hero": "🧙", "idle": "⛏", "adventure": "🗺", "story": "📖", "quest": "📜",
    "bag": "🎒", "guild": "🏰", "market": "⚖️", "arena": "🏆", "shop": "🛒",
    "daily": "🎁", "top": "📊", "ref": "🤝", "help": "❓", "back": "◀️",
    "premium": "👑", "rebirth": "♻️",
    # классы
    "warrior": "🛡", "mage": "🧙", "rogue": "🗡",
    # здания
    "mine": "⛏", "shrine": "⛩", "forge": "🔨", "tavern": "🍺", "library": "📚",
    # бой
    "boss": "💀", "win": "🎉", "lose": "☠️", "skill": "🌀", "flee": "🏃", "chest": "📦",
    "time": "⏳", "ok": "✅", "no": "❌", "warn": "⚠️", "fire": "🔥", "tap": "👆",
    "up": "⬆️", "lock": "🔒",
    # редкость
    "r_common": "⚪", "r_uncommon": "🟢", "r_rare": "🔵", "r_epic": "🟣",
    "r_legendary": "🟠", "r_mythic": "🔴",
    # слоты экипировки
    "slot_weapon": "🗡", "slot_armor": "🥋", "slot_ring": "💍", "slot_amulet": "📿",
}

DATA_FILE = Path(__file__).resolve().parent / "data" / "premium_emoji.json"

# p("gold") возвращает эмодзи + невидимый маркер (символ из Private Use Area) с номером имени.
# Клавиатура по маркеру понимает, какой эмодзи стоит в начале кнопки, и может заменить его на премиум-иконку.
# Маркеры всегда вырезаются перед отправкой (см. EmojiRegistry.strip) и в Telegram не попадают.
_NAMES = list(DEFAULTS)
_MARK = 0xE000


class EmojiRegistry:
    def __init__(self) -> None:
        self.enabled = True
        self.button_icons = False   # PREMIUM_BUTTONS: ставить icon_custom_emoji_id на кнопки
        self.custom: dict[str, str] = {}

    # ---- загрузка -------------------------------------------------------
    def load_file(self) -> None:
        if DATA_FILE.exists():
            try:
                data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            for name, cid in data.items():
                if name in DEFAULTS and str(cid).isdigit():
                    self.custom[name] = str(cid)

    async def load_db(self, q) -> None:
        for row in await q.all("SELECT name, custom_id FROM emoji_map"):
            if row["name"] in DEFAULTS:
                self.custom[row["name"]] = row["custom_id"]

    async def set(self, q, name: str, custom_id: str) -> None:
        await q.execute(
            "INSERT INTO emoji_map(name, custom_id) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET custom_id=excluded.custom_id",
            (name, custom_id),
        )
        self.custom[name] = custom_id

    async def unset(self, q, name: str) -> None:
        await q.execute("DELETE FROM emoji_map WHERE name=?", (name,))
        self.custom.pop(name, None)

    # ---- вывод ----------------------------------------------------------
    def plain(self, name: str) -> str:
        return DEFAULTS.get(name, "▫️")

    def marked(self, name: str) -> str:
        """Эмодзи для подписи кнопки: заглушка + маркер имени."""
        fb = DEFAULTS.get(name, "▫️")
        idx = _NAMES.index(name) if name in DEFAULTS else -1
        return fb + (chr(_MARK + idx) if idx >= 0 else "")

    def strip(self, text: str) -> str:
        """Убрать маркеры из любого текста (страховка: в Telegram они попадать не должны)."""
        return "".join(ch for ch in text if not (_MARK <= ord(ch) < _MARK + len(_NAMES)))

    def split_button(self, text: str) -> tuple[str, str | None]:
        """Подпись кнопки -> (чистый текст, id премиум-иконки или None)."""
        clean = self.strip(text)
        if not (self.enabled and self.button_icons):
            return clean, None
        for i, ch in enumerate(text):
            if _MARK <= ord(ch) < _MARK + len(_NAMES):
                name = _NAMES[ord(ch) - _MARK]
                fb, cid = DEFAULTS[name], self.custom.get(name)
                # иконка заменяет эмодзи только в начале подписи: «<эмодзи> Текст»
                if cid and i == len(fb) and text.startswith(fb):
                    rest = clean[len(fb):].strip()
                    if rest:
                        return rest, cid
                break
        return clean, None

    def render(self, name: str) -> str:
        fallback = DEFAULTS.get(name, "▫️")
        cid = self.custom.get(name)
        if self.enabled and cid:
            return f'<tg-emoji emoji-id="{cid}">{fallback}</tg-emoji>'
        return fallback


EMOJI = EmojiRegistry()


def e(name: str) -> str:
    """Эмодзи для текста сообщения (parse_mode=HTML)."""
    return EMOJI.render(name)


def p(name: str) -> str:
    """Эмодзи для подписей кнопок (может стать премиум-иконкой, см. split_button)."""
    return EMOJI.marked(name)
