"""Цены с правилами админа: своя цена и/или скидка (с необязательным сроком).

Ключи товаров:  pack:<id> · prem:<id> · starter:starter  (Stars)   и   cr:<id>  (кристаллы).
Правила хранятся в БД (price_rules) и держатся в памяти — чтение синхронное.
"""
from __future__ import annotations

from ..data.shop import CRYSTAL_PACKS, CRYSTAL_SHOP, PREMIUM_PLANS, STARTER_PACK
from ..utils.fmt import now

_rules: dict[str, dict] = {}


def catalog() -> dict[str, tuple[str, int]]:
    """key -> (название, базовая цена)."""
    out: dict[str, tuple[str, int]] = {}
    for k, d in CRYSTAL_PACKS.items():
        out[f"pack:{k}"] = (d["title"], d["stars"])
    for k, d in PREMIUM_PLANS.items():
        out[f"prem:{k}"] = (d["title"], d["stars"])
    out[f"starter:{STARTER_PACK['key']}"] = (STARTER_PACK["title"], STARTER_PACK["stars"])
    for k, d in CRYSTAL_SHOP.items():
        out[f"cr:{k}"] = (d["title"], d["cost"])
    return out


def groups() -> dict[str, list[str]]:
    keys = list(catalog())
    return {"all": keys, "stars": [k for k in keys if not k.startswith("cr:")],
            "packs": [k for k in keys if k.startswith("pack:")], "prem": [k for k in keys if k.startswith("prem:")],
            "cr": [k for k in keys if k.startswith("cr:")]}


def _active(rule: dict | None) -> dict | None:
    if not rule:
        return None
    if rule.get("until") and rule["until"] <= now():
        return None
    return rule


def base(key: str, default: int) -> int:
    r = _rules.get(key)
    return int(r["price"]) if r and r.get("price") else default


def discount(key: str) -> int:
    r = _active(_rules.get(key))
    return int(r["discount"]) if r else 0


def price(key: str, default: int) -> int:
    """Итоговая цена: своя цена (или базовая) минус скидка. Минимум 1."""
    p = base(key, default)
    d = discount(key)
    return max(1, round(p * (100 - d) / 100)) if d else max(1, p)


def mark(key: str, default: int, cur: str) -> str:
    """Текст цены для витрины: «<s>50</s> 25⭐ (−50%)» при скидке."""
    p, d = price(key, default), discount(key)
    if d:
        return f"<s>{base(key, default)}</s> {p}{cur} (−{d}%)"
    return f"{p}{cur}"


def stars(kind: str, key: str, default: int) -> int:
    return price(f"{kind}:{key}", default)


def cost(key: str, default: int) -> int:
    return price(f"cr:{key}", default)


async def load(q) -> None:
    _rules.clear()
    for r in await q.all("SELECT key, price, discount, until FROM price_rules"):
        _rules[r["key"]] = dict(r)


async def _save(q, key: str) -> None:
    r = _rules[key]
    if not r.get("price") and not r.get("discount"):
        _rules.pop(key, None)
        await q.execute("DELETE FROM price_rules WHERE key=?", (key,))
        return
    await q.execute(
        "INSERT INTO price_rules(key, price, discount, until) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET price=excluded.price, discount=excluded.discount, until=excluded.until",
        (key, r.get("price"), r.get("discount", 0), r.get("until")))


async def set_price(q, key: str, value: int | None) -> None:
    r = _rules.setdefault(key, {"key": key, "price": None, "discount": 0, "until": None})
    r["price"] = value
    await _save(q, key)


async def set_discount(q, keys: list[str], percent: int, hours: float | None = None) -> None:
    until = now() + hours * 3600 if (hours and percent) else None
    for key in keys:
        r = _rules.setdefault(key, {"key": key, "price": None, "discount": 0, "until": None})
        r["discount"], r["until"] = percent, until
        await _save(q, key)


async def clear(q) -> None:
    _rules.clear()
    await q.execute("DELETE FROM price_rules")


def describe() -> str:
    lines = []
    for key, (title, default) in catalog().items():
        cur = "⭐" if not key.startswith("cr:") else "💎"
        p, d = price(key, default), discount(key)
        extra = ""
        if base(key, default) != default:
            extra += f" · своя цена {base(key, default)}"
        if d:
            r = _rules[key]
            extra += f" · скидка {d}%" + (f" до {int((r['until'] - now()) // 3600)} ч" if r.get("until") else "")
        lines.append(f"<code>{key}</code> {title}: {default}{cur} → <b>{p}{cur}</b>{extra}")
    return "\n".join(lines)
