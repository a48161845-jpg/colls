"""Настройки проекта. Всё берётся из файла .env (см. .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _ids(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


@dataclass(frozen=True)
class Settings:
    token: str
    admin_ids: frozenset[int]
    db_path: str             # локальный SQLite (если не задан database_url)
    database_url: str        # postgresql://... — онлайн-БД (Supabase, Neon, Railway ...)
    premium_emoji: bool      # пробовать ли рисовать премиум-эмодзи (<tg-emoji>) в тексте
    premium_buttons: bool    # ставить премиум-иконки на кнопки (icon_custom_emoji_id, Bot API 9.4)
    animated_images: bool    # анимированные карточки (GIF); 0 — обычные JPEG
    log_level: str
    support: str             # @username поддержки (показывается в /help)


def load_settings(require_token: bool = True) -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if require_token and not token:
        raise SystemExit("Укажи BOT_TOKEN в файле .env (скопируй .env.example)")
    db_path = os.getenv("DB_PATH", str(ROOT / "ashen_realm.sqlite3"))
    return Settings(
        token=token,
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        db_path=db_path,
        database_url=os.getenv("DATABASE_URL", "").strip(),
        premium_emoji=os.getenv("PREMIUM_EMOJI", "1").strip() not in ("0", "false", "no"),
        premium_buttons=os.getenv("PREMIUM_BUTTONS", "0").strip() in ("1", "true", "yes"),
        animated_images=os.getenv("ANIMATED_IMAGES", "1").strip() not in ("0", "false", "no"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        support=os.getenv("SUPPORT", "").strip(),
    )
