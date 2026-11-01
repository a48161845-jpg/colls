"""Мелкие помощники форматирования."""
from __future__ import annotations

import html
import time


def now() -> float:
    return time.time()


def today() -> int:
    """Номер суток (UTC) — по нему сбрасываются дневные лимиты и квесты."""
    return int(time.time() // 86400)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


_SUFFIXES = ["", "K", "M", "B", "T", "Qa", "Qi"]


def num(n: float) -> str:
    """1234 -> 1 234, 12_345 -> 12.3K, 4_500_000 -> 4.5M"""
    n = int(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 10_000:
        return sign + f"{n:,}".replace(",", " ")
    idx = 0
    value = float(n)
    while value >= 1000 and idx < len(_SUFFIXES) - 1:
        value /= 1000
        idx += 1
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{sign}{text}{_SUFFIXES[idx]}"


def bar(cur: float, mx: float, width: int = 10) -> str:
    if mx <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * cur / mx)))
    return "█" * filled + "░" * (width - filled)


def dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}д {h}ч"
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с" if m < 5 else f"{m}м"
    return f"{s}с"


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
