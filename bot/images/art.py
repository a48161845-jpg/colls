"""Процедурные силуэты: монстры, герои, значки предметов и эмблемы разделов.

Всё рисуется Pillow-примитивами — никаких внешних файлов. Хочешь свою графику —
клади PNG в assets/images/ (см. images/theme.py::custom_background).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .theme import ROOT, lerp


class Pen:
    """Рисует в единицах масштаба s вокруг точки (cx, cy)."""

    def __init__(self, d: ImageDraw.ImageDraw, cx: float, cy: float, s: float, body, rim, glow) -> None:
        self.d, self.cx, self.cy, self.s = d, cx, cy, s
        self.body, self.rim, self.glow = body, rim, glow
        self.eyes: list[tuple[float, float, float]] = []

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (self.cx + x * self.s, self.cy + y * self.s)

    def ell(self, x0, y0, x1, y1, fill=None, outline=True) -> None:
        self.d.ellipse([*self.pt(x0, y0), *self.pt(x1, y1)], fill=fill or self.body,
                       outline=self.rim if outline else None, width=3)

    def poly(self, pts, fill=None) -> None:
        self.d.polygon([self.pt(*p) for p in pts], fill=fill or self.body, outline=self.rim, width=3)

    def rect(self, x0, y0, x1, y1, r: float = 0.07, fill=None) -> None:
        self.d.rounded_rectangle([*self.pt(x0, y0), *self.pt(x1, y1)], radius=max(2, int(r * self.s)),
                                 fill=fill or self.body, outline=self.rim, width=3)

    def line(self, pts, w: float = 0.07, fill=None) -> None:
        self.d.line([self.pt(*p) for p in pts], fill=fill or self.rim, width=max(2, int(w * self.s)), joint="curve")

    def eye(self, x: float, y: float, r: float = 0.09) -> None:
        px, py = self.pt(x, y)
        self.eyes.append((px, py, r * self.s))


# ---------------------------------------------------------------------- монстры
def _slime(p: Pen) -> None:
    p.ell(-1.0, -0.85, 1.0, 0.85)
    p.ell(-0.55, -0.55, -0.2, -0.25, fill=lerp(p.body, (255, 255, 255), 0.25), outline=False)
    p.eye(-0.33, -0.05, 0.12)
    p.eye(0.33, -0.05, 0.12)


def _beast(p: Pen) -> None:
    p.poly([(-1.1, -0.1), (-1.7, -0.55), (-1.35, 0.1)])  # хвост
    p.ell(-1.15, -0.25, 0.85, 0.6)  # тело
    for x in (-0.95, -0.55, 0.3, 0.6):  # лапы
        p.rect(x, 0.3, x + 0.2, 0.95, r=0.05)
    p.ell(0.5, -0.8, 1.3, -0.05)  # голова
    p.poly([(0.62, -0.7), (0.72, -1.1), (0.92, -0.75)])  # уши
    p.poly([(1.0, -0.75), (1.18, -1.1), (1.28, -0.65)])
    p.poly([(1.2, -0.45), (1.7, -0.28), (1.2, -0.1)])  # морда
    p.eye(1.0, -0.48, 0.1)


def _skeleton(p: Pen) -> None:
    p.rect(-0.07, -0.25, 0.07, 0.95, r=0.03)  # позвоночник
    for i in range(4):  # рёбра
        y = -0.15 + i * 0.22
        p.ell(-0.55 + i * 0.03, y - 0.1, 0.55 - i * 0.03, y + 0.14, fill=(0, 0, 0, 0))
    p.line([(-0.95, 0.55), (-0.6, -0.15), (0.6, -0.15), (0.95, 0.55)], w=0.09)  # плечи, руки
    p.rect(-0.46, -1.15, 0.46, -0.38)  # череп
    p.rect(-0.3, -0.42, 0.3, -0.22, r=0.04)  # челюсть
    p.ell(-0.3, -0.92, -0.06, -0.6, fill=(8, 8, 12), outline=False)
    p.ell(0.06, -0.92, 0.3, -0.6, fill=(8, 8, 12), outline=False)
    p.eye(-0.18, -0.76, 0.07)
    p.eye(0.18, -0.76, 0.07)


def _bat(p: Pen) -> None:
    p.poly([(-0.2, -0.1), (-1.65, -0.75), (-1.25, -0.1), (-1.45, 0.35), (-0.95, 0.12), (-0.7, 0.55), (-0.2, 0.25)])
    p.poly([(0.2, -0.1), (1.65, -0.75), (1.25, -0.1), (1.45, 0.35), (0.95, 0.12), (0.7, 0.55), (0.2, 0.25)])
    p.ell(-0.25, -0.35, 0.25, 0.5)
    p.ell(-0.22, -0.65, 0.22, -0.15)
    p.poly([(-0.2, -0.55), (-0.3, -0.95), (-0.05, -0.62)])
    p.poly([(0.2, -0.55), (0.3, -0.95), (0.05, -0.62)])
    p.eye(-0.09, -0.42, 0.06)
    p.eye(0.09, -0.42, 0.06)


def _golem(p: Pen) -> None:
    p.rect(-0.5, 0.55, -0.1, 1.1)
    p.rect(0.1, 0.55, 0.5, 1.1)
    p.rect(-0.75, -0.55, 0.75, 0.65, r=0.1)
    p.rect(-1.25, -0.5, -0.78, 0.55, r=0.1)
    p.rect(0.78, -0.5, 1.25, 0.55, r=0.1)
    p.rect(-0.38, -1.05, 0.38, -0.5, r=0.08)
    p.ell(-0.2, -0.12, 0.2, 0.28, fill=lerp(p.glow, (0, 0, 0), 0.3))
    p.eye(0, 0.08, 0.14)
    p.eye(-0.14, -0.78, 0.07)
    p.eye(0.14, -0.78, 0.07)


def _wraith(p: Pen) -> None:
    p.poly([(-0.5, -0.65), (0.5, -0.65), (0.95, 0.95), (0.62, 0.72), (0.3, 1.05), (0.0, 0.75),
            (-0.3, 1.05), (-0.62, 0.72), (-0.95, 0.95)])
    p.ell(-0.5, -1.25, 0.5, -0.3)
    p.ell(-0.3, -1.0, 0.3, -0.45, fill=(6, 6, 10), outline=False)
    p.eye(-0.14, -0.74, 0.08)
    p.eye(0.14, -0.74, 0.08)
    p.line([(-0.5, -0.3), (-1.1, 0.15)], w=0.08)
    p.line([(0.5, -0.3), (1.1, 0.15)], w=0.08)


def _dragon(p: Pen) -> None:
    p.poly([(-0.2, -0.3), (-0.85, -1.65), (-0.4, -1.2), (0.1, -1.75), (0.15, -0.9), (0.65, -1.4), (0.45, -0.3)])  # крыло
    p.poly([(-0.8, 0.1), (-1.75, 0.5), (-1.5, 0.72), (-0.7, 0.5)])  # хвост
    p.ell(-0.95, -0.35, 0.75, 0.65)
    p.rect(-0.7, 0.4, -0.45, 1.0, r=0.05)
    p.rect(0.2, 0.4, 0.45, 1.0, r=0.05)
    p.poly([(0.4, -0.15), (0.9, -0.95), (1.12, -0.85), (0.85, 0.1)])  # шея
    p.poly([(0.85, -1.05), (1.55, -0.95), (1.6, -0.72), (1.0, -0.66)])  # голова
    p.poly([(0.95, -1.03), (0.85, -1.45), (1.12, -1.05)])  # рог
    p.eye(1.18, -0.9, 0.07)


def _demon(p: Pen) -> None:
    p.poly([(-0.85, -0.15), (0.85, -0.15), (0.62, 0.95), (-0.62, 0.95)])
    p.poly([(-0.85, -0.1), (-1.35, 0.5), (-1.1, 0.62), (-0.7, 0.2)])
    p.poly([(0.85, -0.1), (1.35, 0.5), (1.1, 0.62), (0.7, 0.2)])
    p.poly([(-0.46, -0.75), (-0.95, -1.35), (-0.72, -1.4), (-0.2, -0.88)])
    p.poly([(0.46, -0.75), (0.95, -1.35), (0.72, -1.4), (0.2, -0.88)])
    p.ell(-0.52, -0.98, 0.52, -0.02)
    p.line([(-0.22, -0.28), (0.0, -0.2), (0.22, -0.28)], w=0.05)
    p.eye(-0.2, -0.6, 0.08)
    p.eye(0.2, -0.6, 0.08)


def _spider(p: Pen) -> None:
    for side in (-1, 1):
        for i in range(4):
            y0 = -0.1 + i * 0.12
            reach = 1.0 + (0.25 if i in (1, 2) else 0)
            p.line([(0.1 * side, y0), (0.75 * side, -0.75 + i * 0.12), (reach * side + 0.2 * side, 0.7 + i * 0.05)], w=0.06)
    p.ell(-0.55, -0.25, 0.4, 0.6)
    p.ell(0.25, -0.2, 0.8, 0.3)
    for dx in (0.45, 0.58, 0.7):
        p.eye(dx, -0.05, 0.05)


def _knight(p: Pen) -> None:
    p.rect(-0.45, 0.5, -0.1, 1.1, r=0.05)
    p.rect(0.1, 0.5, 0.45, 1.1, r=0.05)
    p.rect(-0.65, -0.45, 0.65, 0.55, r=0.1)
    p.ell(-0.95, -0.55, -0.45, -0.05)
    p.ell(0.45, -0.55, 0.95, -0.05)
    p.rect(-0.35, -1.1, 0.35, -0.45, r=0.1)
    p.poly([(0.0, -1.1), (0.45, -1.3), (0.35, -0.9)])  # плюмаж
    p.line([(-0.28, -0.82), (0.28, -0.82)], w=0.06, fill=(6, 6, 10))
    p.eye(-0.14, -0.82, 0.05)
    p.eye(0.14, -0.82, 0.05)
    p.poly([(1.15, -1.3), (1.28, -1.3), (1.28, 0.2), (1.15, 0.2)])  # меч
    p.rect(1.0, 0.18, 1.43, 0.3, r=0.03)
    p.ell(-1.35, -0.2, -0.75, 0.6)  # щит


MONSTER_ART: dict[str, Callable[[Pen], None]] = {
    "slime": _slime, "beast": _beast, "skeleton": _skeleton, "bat": _bat, "golem": _golem,
    "wraith": _wraith, "dragon": _dragon, "demon": _demon, "spider": _spider, "knight": _knight,
}


# ---------------------------------------------------------------------- герои
def _hero_warrior(p: Pen) -> None:
    p.rect(-0.4, 0.55, -0.08, 1.15, r=0.05)
    p.rect(0.08, 0.55, 0.4, 1.15, r=0.05)
    p.rect(-0.55, -0.4, 0.55, 0.6, r=0.1)
    p.rect(-0.3, -1.1, 0.3, -0.4, r=0.12)
    p.line([(-0.22, -0.78), (0.22, -0.78)], w=0.06, fill=(6, 6, 10))
    p.poly([(0.0, -1.1), (0.0, -1.35), (0.18, -1.12)])
    p.poly([(-1.2, -0.3), (-0.62, -0.3), (-0.62, 0.35), (-0.9, 0.7), (-1.2, 0.35)])  # щит
    p.poly([(0.95, -1.2), (1.07, -1.2), (1.07, 0.15), (0.95, 0.15)])  # меч
    p.rect(0.8, 0.12, 1.22, 0.24, r=0.03)
    p.line([(0.55, -0.1), (1.0, 0.15)], w=0.09)


def _hero_mage(p: Pen) -> None:
    p.poly([(-0.65, 1.15), (-0.4, -0.3), (0.4, -0.3), (0.65, 1.15)])  # роба
    p.rect(-0.38, -0.95, 0.38, -0.3, r=0.1)
    p.poly([(-0.6, -0.9), (0.0, -1.75), (0.6, -0.9)])  # шляпа
    p.rect(-0.7, -0.98, 0.7, -0.84, r=0.05)
    p.line([(0.75, 1.15), (0.9, -1.1)], w=0.07)  # посох
    p.ell(0.76, -1.35, 1.08, -1.03, fill=p.glow)
    p.eye(0.92, -1.19, 0.2)
    p.eye(-0.14, -0.62, 0.05)
    p.eye(0.14, -0.62, 0.05)


def _hero_rogue(p: Pen) -> None:
    p.poly([(-0.7, 1.15), (-0.45, -0.2), (0.45, -0.2), (0.7, 1.15), (0.0, 0.9)])  # плащ
    p.poly([(-0.5, -0.4), (0.0, -1.25), (0.5, -0.4)])  # капюшон
    p.ell(-0.3, -0.95, 0.3, -0.3, fill=(8, 8, 12), outline=False)
    p.eye(-0.12, -0.62, 0.06)
    p.eye(0.12, -0.62, 0.06)
    p.poly([(-1.0, -0.2), (-0.88, -0.2), (-0.7, 0.5), (-0.82, 0.5)])  # кинжалы
    p.poly([(1.0, -0.2), (0.88, -0.2), (0.7, 0.5), (0.82, 0.5)])
    p.line([(-0.45, 0.05), (-0.8, 0.5)], w=0.07)
    p.line([(0.45, 0.05), (0.8, 0.5)], w=0.07)


HERO_ART: dict[str, Callable[[Pen], None]] = {"warrior": _hero_warrior, "mage": _hero_mage, "rogue": _hero_rogue}


def _shade(layer: Image.Image, light, dark) -> Image.Image:
    """Объём: заливка фигуры получает вертикальный градиент света, нижний край темнеет, а по верхней кромке идёт блик."""
    alpha = layer.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return layer
    x0, y0, x1, y1 = bbox
    grad = Image.linear_gradient("L").resize((layer.width, max(1, y1 - y0))).transpose(Image.FLIP_TOP_BOTTOM)
    full = Image.new("L", layer.size, 128)
    full.paste(grad, (0, y0))
    lit = Image.new("RGBA", layer.size, (*light, 0))
    lit.putalpha(ImageChops.multiply(full.point(lambda v: int(max(0, v - 90) * 0.9)), alpha))
    shd = Image.new("RGBA", layer.size, (*dark, 0))
    shd.putalpha(ImageChops.multiply(full.point(lambda v: int(max(0, 150 - v) * 0.9)), alpha))
    out = layer.copy()
    out.alpha_composite(shd)
    out.alpha_composite(lit)
    # блик по верхне-левой кромке
    shifted = ImageChops.offset(alpha, 4, 5)
    edge = ImageChops.subtract(alpha, shifted).point(lambda v: min(255, v * 2))
    rimlight = Image.new("RGBA", layer.size, (*light, 0))
    rimlight.putalpha(edge.point(lambda v: int(v * 0.55)))
    out.alpha_composite(rimlight)
    out.putalpha(alpha)
    return out


SPRITE_DIR = ROOT / "assets" / "sprites"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


@lru_cache(maxsize=64)
def _load_sprite(kind: str, name: str) -> Image.Image | None:
    """Свои картинки: assets/sprites/<kind>/<имя>.png (прозрачный фон, фигура смотрит ВПРАВО у монстров/героев-справа).
    kind: monsters | heroes | items. Для монстров сначала ищется по названию, затем по типу силуэта."""
    for ext in ("png", "webp"):
        path = SPRITE_DIR / kind / f"{name}.{ext}"
        if path.exists():
            try:
                return Image.open(path).convert("RGBA")
            except OSError:
                return None
    return None


def _paste_sprite(img: Image.Image, sprite: Image.Image, cx, cy, s, glow, flip: bool, shadow: bool = True) -> None:
    target_h = s * 2.5
    scale = target_h / sprite.height
    sp = sprite.resize((max(1, int(sprite.width * scale)), max(1, int(target_h))), Image.LANCZOS)
    if flip:
        sp = sp.transpose(Image.FLIP_LEFT_RIGHT)
    x, y = int(cx - sp.width / 2), int(cy + s * 1.1 - sp.height)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([cx - sp.width * 0.4, cy + s * 0.95, cx + sp.width * 0.4, cy + s * 1.2], fill=(0, 0, 0, 130))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    aura = Image.new("RGBA", img.size, (0, 0, 0, 0))
    aura.paste(sp, (x, y))
    glowl = Image.new("RGBA", img.size, (*glow, 0))
    glowl.putalpha(aura.getchannel("A").filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.35)))
    img.alpha_composite(glowl)
    img.alpha_composite(aura)


def _compose(img: Image.Image, fn: Callable[[Pen], None], cx, cy, s, body, rim, glow, flip: bool = False,
             shadow: bool = True) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    # зеркалим весь холст, поэтому рисуем в симметричной точке — после отражения фигура встанет в (cx, cy)
    pen = Pen(ImageDraw.Draw(layer), (img.width - cx) if flip else cx, cy, s, body, rim, glow)
    fn(pen)
    layer = _shade(layer, lerp(rim, (255, 255, 255), 0.35), lerp(body, (0, 0, 0), 0.7))
    if flip:
        layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
        pen.eyes = [(img.width - x, y, r) for x, y, r in pen.eyes]
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([cx - s * 1.2, cy + s * 0.95, cx + s * 1.2, cy + s * 1.2], fill=(0, 0, 0, 130))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    # мягкое свечение вокруг силуэта
    aura = layer.filter(ImageFilter.GaussianBlur(14))
    tint = Image.new("RGBA", img.size, (*glow, 0))
    tint.putalpha(aura.getchannel("A").point(lambda v: int(v * 0.35)))
    img.alpha_composite(tint)
    img.alpha_composite(layer)
    from . import anim
    anim.note_eyes(pen.eyes)
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    for x, y, r in pen.eyes:
        gd.ellipse([x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2], fill=(*glow, 150))
    img.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(6)))
    core = Image.new("RGBA", img.size, (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    for x, y, r in pen.eyes:
        cd.ellipse([x - r, y - r, x + r, y + r], fill=(*lerp(glow, (255, 255, 255), 0.55), 255))
    img.alpha_composite(core)


def draw_monster(img: Image.Image, kind: str, cx: float, cy: float, s: float, accent, boss: bool = False,
                 flip: bool = False, name: str = "") -> None:
    sprite = (_load_sprite("monsters", _slug(name)) if name else None) or _load_sprite("monsters", kind)
    if sprite is not None:
        _paste_sprite(img, sprite, cx, cy, s * (1.15 if boss else 1.0), accent, flip)
        return
    fn = MONSTER_ART.get(kind, _slime)
    body = lerp((16, 16, 24), accent, 0.34 if not boss else 0.42)
    rim = lerp(accent, (255, 255, 255), 0.15)
    _compose(img, fn, cx, cy, s * (1.15 if boss else 1.0), body, rim, accent, flip)


def draw_hero(img: Image.Image, cls: str, cx: float, cy: float, s: float, color, flip: bool = False) -> None:
    sprite = _load_sprite("heroes", cls)
    if sprite is not None:
        _paste_sprite(img, sprite, cx, cy, s, color, flip)
        return
    fn = HERO_ART.get(cls, _hero_warrior)
    body = lerp((16, 16, 24), color, 0.35)
    rim = lerp(color, (255, 255, 255), 0.3)
    _compose(img, fn, cx, cy, s, body, rim, color, flip)


# ---------------------------------------------------------------------- предметы
def draw_item_icon(img: Image.Image, slot: str, cx: float, cy: float, s: float, color) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    body = lerp((20, 20, 28), color, 0.45)
    rim = lerp(color, (255, 255, 255), 0.35)
    p = Pen(ImageDraw.Draw(layer), cx, cy, s, body, rim, color)
    if slot == "weapon":
        p.poly([(-0.12, 0.55), (-0.12, -1.2), (0.0, -1.45), (0.12, -1.2), (0.12, 0.55)])
        p.rect(-0.5, 0.5, 0.5, 0.68, r=0.05)
        p.rect(-0.1, 0.66, 0.1, 1.15, r=0.04)
        p.ell(-0.16, 1.1, 0.16, 1.4)
    elif slot == "armor":
        p.poly([(-0.9, -0.8), (-0.45, -1.0), (0.0, -0.8), (0.45, -1.0), (0.9, -0.8), (0.7, 0.2),
                (0.55, 1.1), (-0.55, 1.1), (-0.7, 0.2)])
        p.line([(0, -0.8), (0, 1.1)], w=0.05)
        p.ell(-0.12, -0.15, 0.12, 0.1, fill=color)
    elif slot == "ring":
        p.ell(-0.8, -0.5, 0.8, 1.1, fill=(0, 0, 0, 0))
        p.ell(-0.55, -0.25, 0.55, 0.85, fill=(0, 0, 0, 0))
        p.poly([(-0.25, -0.5), (0.25, -0.5), (0.4, -0.95), (0.0, -1.35), (-0.4, -0.95)], fill=color)
    else:  # amulet
        p.line([(-0.9, -1.1), (-0.3, 0.1), (0.3, 0.1), (0.9, -1.1)], w=0.05)
        p.poly([(0.0, 0.0), (0.45, 0.55), (0.0, 1.2), (-0.45, 0.55)], fill=color)
        p.ell(-0.12, 0.45, 0.12, 0.7, fill=lerp(color, (255, 255, 255), 0.7), outline=False)
    aura = layer.filter(ImageFilter.GaussianBlur(22))
    tint = Image.new("RGBA", img.size, (*color, 0))
    tint.putalpha(aura.getchannel("A").point(lambda v: int(v * 0.8)))
    img.alpha_composite(tint)
    img.alpha_composite(layer)


# ---------------------------------------------------------------------- эмблемы разделов
def draw_emblem(img: Image.Image, name: str, cx: float, cy: float, s: float, color) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    body = lerp((20, 18, 26), color, 0.30)
    rim = lerp(color, (255, 255, 255), 0.25)
    p = Pen(ImageDraw.Draw(layer), cx, cy, s, body, rim, color)
    if name in ("idle", "daily", "shop", "premium"):  # монеты / гем
        if name in ("shop", "premium"):
            p.poly([(-0.7, -0.3), (-0.35, -0.8), (0.35, -0.8), (0.7, -0.3), (0.0, 0.95)])
            p.line([(-0.7, -0.3), (0.7, -0.3)], w=0.04)
            p.line([(-0.35, -0.8), (-0.15, -0.3), (0.0, 0.95)], w=0.03)
            p.line([(0.35, -0.8), (0.15, -0.3), (0.0, 0.95)], w=0.03)
        else:
            for i, y in enumerate((0.55, 0.25, -0.05, -0.35)):
                p.ell(-0.7, y - 0.22, 0.7, y + 0.22)
    elif name in ("arena", "adventure", "lose"):  # скрещённые мечи
        for sgn in (-1, 1):
            p.poly([(sgn * 0.85 - 0.08, -1.0), (sgn * 0.85 + 0.08, -1.0), (-sgn * 0.5 + 0.08, 0.7), (-sgn * 0.5 - 0.08, 0.7)])
        p.rect(-0.6, 0.45, -0.05, 0.6, r=0.04)
        p.rect(0.05, 0.45, 0.6, 0.6, r=0.04)
    elif name == "guild":  # щит
        p.poly([(-0.8, -0.9), (0.8, -0.9), (0.8, 0.1), (0.0, 1.1), (-0.8, 0.1)])
        p.line([(0, -0.9), (0, 1.0)], w=0.05)
        p.line([(-0.8, -0.2), (0.8, -0.2)], w=0.05)
    elif name == "market":  # весы
        p.line([(0, -1.0), (0, 0.9)], w=0.06)
        p.line([(-0.9, -0.6), (0.9, -0.6)], w=0.05)
        p.poly([(-1.1, 0.0), (-0.7, 0.0), (-0.9, 0.35)])
        p.poly([(0.7, 0.0), (1.1, 0.0), (0.9, 0.35)])
        p.rect(-0.45, 0.85, 0.45, 1.05, r=0.05)
    elif name in ("story", "quest", "help", "bag"):  # книга
        p.poly([(-1.0, -0.6), (-0.05, -0.45), (-0.05, 0.9), (-1.0, 0.75)])
        p.poly([(1.0, -0.6), (0.05, -0.45), (0.05, 0.9), (1.0, 0.75)])
        p.line([(-0.8, -0.2), (-0.25, -0.12)], w=0.03)
        p.line([(0.8, -0.2), (0.25, -0.12)], w=0.03)
    elif name in ("top", "win"):  # корона
        p.poly([(-0.9, 0.7), (-0.9, -0.5), (-0.45, 0.0), (0.0, -0.8), (0.45, 0.0), (0.9, -0.5), (0.9, 0.7)])
        p.rect(-0.9, 0.55, 0.9, 0.85, r=0.05)
    else:  # пламя
        p.poly([(0.0, -1.2), (0.55, -0.3), (0.75, 0.4), (0.4, 1.0), (-0.4, 1.0), (-0.75, 0.4), (-0.5, -0.3), (-0.2, -0.1)])
        p.poly([(0.0, 0.0), (0.3, 0.45), (0.15, 0.85), (-0.15, 0.85), (-0.3, 0.45)], fill=lerp(color, (255, 255, 255), 0.4))
    aura = layer.filter(ImageFilter.GaussianBlur(26))
    tint = Image.new("RGBA", img.size, (*color, 0))
    tint.putalpha(aura.getchannel("A").point(lambda v: int(v * 0.9)))
    img.alpha_composite(tint)
    img.alpha_composite(layer)
