"""Общие кирпичики для рисования: шрифты, фоны, панели, полоски."""
from __future__ import annotations

import io
import math
import random
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "assets" / "fonts"
ASSET_DIR = ROOT / "assets" / "images"
W, H = 960, 540

# палитры: имя -> (верх, низ, акцент)
THEMES: dict[str, tuple] = {
    "menu":    ((20, 12, 30), (92, 34, 38), (255, 150, 70)),
    "idle":    ((14, 20, 14), (78, 62, 22), (255, 205, 80)),
    "adventure": ((18, 24, 30), (60, 50, 44), (255, 150, 70)),
    "shop":    ((26, 14, 36), (100, 60, 22), (255, 200, 90)),
    "premium": ((34, 18, 8), (120, 72, 14), (255, 215, 100)),
    "guild":   ((14, 20, 38), (62, 42, 86), (150, 170, 255)),
    "market":  ((14, 26, 28), (48, 70, 52), (120, 230, 170)),
    "arena":   ((32, 10, 12), (96, 26, 30), (255, 90, 80)),
    "story":   ((18, 16, 28), (70, 52, 70), (230, 190, 255)),
    "quest":   ((24, 20, 12), (88, 70, 30), (255, 220, 130)),
    "daily":   ((16, 24, 34), (40, 80, 90), (130, 240, 255)),
    "top":     ((22, 16, 30), (80, 54, 22), (255, 210, 90)),
    "help":    ((14, 18, 28), (44, 56, 80), (160, 200, 255)),
    "bag":     ((20, 16, 14), (70, 50, 36), (230, 180, 120)),
    "win":     ((14, 30, 20), (52, 100, 48), (255, 230, 120)),
    "lose":    ((30, 10, 10), (70, 16, 20), (255, 80, 80)),
    "rebirth": ((26, 10, 30), (110, 30, 60), (255, 120, 190)),
}


_SYSTEM_FONTS = {
    True: ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
           "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    False: ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"),
}


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Шрифт с кириллицей. Порядок: свой assets/fonts/*.ttf -> системный DejaVu/Arial -> встроенный в Pillow.
    Положи свой .ttf в assets/fonts/ под именем DejaVuSans.ttf / DejaVuSans-Bold.ttf, чтобы заменить шрифт."""
    candidates = [str(FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), *_SYSTEM_FONTS[bold]]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)      # Pillow >= 10.1: масштабируемый шрифт без кириллицы, но без падения
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


# ----------------------------------------------------------------------------- текст с запасными шрифтами
# Основной шрифт (кириллица, латиница, значки), дальше по цепочке: FreeSans (много письменностей), GNU Unifont
# (почти весь Юникод), а эмодзи рисуются цветными из Noto Color Emoji. Ничего не вырезается: если символа нет
# в основном шрифте, берётся следующий. Только совсем невидимое и «зальго» (стопки диакритики) чистится.
_EMOJI_FONT = FONT_DIR / "NotoColorEmoji.ttf"
_CHAIN_FILES = {
    True: ("DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "unifont.otf"),
    False: ("DejaVuSans.ttf", "FreeSans.ttf", "unifont.otf"),
}


@lru_cache(maxsize=256)
def _font_at(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return None


def font_chain(size: int, bold: bool = True) -> list:
    out = []
    for i, name in enumerate(_CHAIN_FILES[bold]):
        f = _font_at(str(FONT_DIR / name), size)
        if f is None and i == 0:
            f = font(size, bold)
        if f is not None:
            out.append(f)
    return out


@lru_cache(maxsize=16)
def _notdef(path: str) -> bytes:
    return _render_with(_font_at(path, 40), "\U0010FFFF")


def _render_with(f, ch: str) -> bytes:
    im = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(im).text((8, 4), ch, font=f, fill=255)
    return im.tobytes()


@lru_cache(maxsize=8192)
def _covers(path: str, ch: str) -> bool:
    f = _font_at(path, 40)
    if f is None:
        return False
    if ch in " \u00a0":
        return True
    try:
        raw = _render_with(f, ch)
    except Exception:  # noqa: BLE001
        return False
    return any(raw) and raw != _notdef(path)


_VS, _ZWJ, _KEYCAP = {0xFE0E, 0xFE0F}, 0x200D, 0x20E3


def _is_emoji_base(ch: str, nxt: str = "") -> bool:
    o = ord(ch)
    if nxt == "\ufe0f":                      # символ + VS16 = эмодзи-представление (❤️, ☺️)
        return True
    return o >= 0x1F000 and not (0x1F100 <= o <= 0x1F1FF and not 0x1F1E6 <= o <= 0x1F1FF) or 0x1F1E6 <= o <= 0x1F1FF


def split_runs(s: str) -> list[tuple[str, str]]:
    """Строка -> [("t", текст), ("e", эмодзи), ...]. Модификаторы эмодзи (VS, ZWJ, оттенки кожи, теги) убираются,
    а составные эмодзи рисуются поочерёдно."""
    runs: list[tuple[str, str]] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        o = ord(ch)
        nxt = s[i + 1] if i + 1 < n else ""
        if o in _VS or o == _ZWJ or o == _KEYCAP or 0x1F3FB <= o <= 0x1F3FF or 0xE0020 <= o <= 0xE007F:
            i += 1
            continue
        if _is_emoji_base(ch, nxt):
            runs.append(("e", ch))
        elif runs and runs[-1][0] == "t":
            runs[-1] = ("t", runs[-1][1] + ch)
        else:
            runs.append(("t", ch))
        i += 1
    return runs


def _pick_font(ch: str, chain: list):
    for f in chain:
        if _covers(f.path, ch):
            return f
    return None


def _text_pieces(txt: str, chain: list) -> list[tuple[object, str]]:
    """Текст -> куски (шрифт, строка): подряд идущие символы одного шрифта идут одним куском (для лигатур/арабского)."""
    pieces: list[tuple[object, str]] = []
    prev = None
    for ch in txt:
        if prev is not None and unicodedata.category(ch)[0] == "M":     # знак держится за предыдущую букву и её шрифт
            f = prev
        else:
            f = _pick_font(ch, chain)
        prev = f
        if f is None:
            f, ch = chain[0], "?"
        if pieces and pieces[-1][0] is f:
            pieces[-1] = (f, pieces[-1][1] + ch)
        else:
            pieces.append((f, ch))
    return pieces


@lru_cache(maxsize=512)
def _emoji_img(ch: str, px: int) -> Image.Image | None:
    f = _font_at(str(_EMOJI_FONT), 109)          # у bitmap-шрифта Noto единственный размер — 109
    if f is None:
        return None
    try:
        im = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((0, 0), ch, font=f, embedded_color=True)
        box = im.getbbox()
        if not box:
            return None
        im = im.crop((0, 0, 136, 128)).resize((int(136 * px / 128), px), Image.LANCZOS)
        return im
    except Exception:  # noqa: BLE001
        return None


def _layout(s: str, size: int, bold: bool) -> tuple[list, float]:
    """-> (элементы [("t", font, str, width) | ("e", img, width)], общая ширина)"""
    chain = font_chain(size, bold)
    items, total = [], 0.0
    for kind, txt in split_runs(s):
        if kind == "e":
            img = _emoji_img(txt, int(size * 1.12))
            if img is not None:
                w = img.width + size * 0.12
                items.append(("e", img, w))
                total += w
                continue
            txt = "□"
        for f, piece in _text_pieces(txt, chain):
            w = f.getlength(piece)
            items.append(("t", f, piece, w))
            total += w
    return items, total


def measure(s: str, f) -> float:
    return _layout(s, f.size, "Bold" in f.path)[1]


def clean(s: object, fallback: str = "", limit: int = 60) -> str:
    """Подготовка строки к рисованию: «рукописные» и широкие шрифты приводятся к обычным буквам (𝓗𝓮𝓵𝓵𝓸 -> Hello),
    невидимые и управляющие знаки убираются, стопки диакритики («зальго») ограничиваются двумя знаками на букву,
    пробелы схлопываются, длинные строки обрезаются. Эмодзи и экзотические письменности остаются."""
    out, marks = [], 0
    for ch in unicodedata.normalize("NFKC", str(s)):
        cat = unicodedata.category(ch)
        o = ord(ch)
        if cat in ("Cc", "Zl", "Zp", "Cs", "Co", "Cn") or (cat == "Cf" and o not in (_ZWJ, 0xFE0F, 0xFE0E) and not 0xE0020 <= o <= 0xE007F):
            continue
        if o in (0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069):   # управление направлением
            continue
        if cat in ("Mn", "Me"):
            marks += 1
            if marks > 2 or o in _VS:
                if o not in _VS:
                    continue
            out.append(ch)
            continue
        marks = 0
        out.append(" " if ch.isspace() else ch)
    res = " ".join("".join(out).split())
    if len(res) > limit:
        res = res[: limit - 1].rstrip() + "…"
    return res or fallback


def lerp(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def mix(a, b, t: float):
    return lerp(a, b, t)


def gradient(top, bottom, size=(W, H)) -> Image.Image:
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        d.line([(0, y), (size[0], y)], fill=lerp(top, bottom, y / max(1, size[1] - 1)))
    return img.convert("RGBA")


def vignette(img: Image.Image, strength: int = 200) -> Image.Image:
    mask = Image.radial_gradient("L").resize(img.size)
    mask = mask.point(lambda v: int(max(0, v - 80) * strength / 175))
    black = Image.new("RGBA", img.size, (0, 0, 0, 255))
    black.putalpha(mask)
    return Image.alpha_composite(img, black)


def embers(img: Image.Image, rng: random.Random, color, n: int = 45) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.randint(0, img.width), rng.randint(0, img.height)
        r = rng.choice([1, 1, 2, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*color, rng.randint(110, 255)))
    glow = layer.filter(ImageFilter.GaussianBlur(5))
    img.alpha_composite(glow)
    img.alpha_composite(layer)


def skyline(img: Image.Image, rng: random.Random, color, base: float = 0.78, jag: int = 70) -> None:
    """Тёмный силуэт гор/леса по низу кадра."""
    pts = [(0, img.height)]
    x = 0
    while x <= img.width + 40:
        pts.append((x, img.height * base + rng.randint(-jag, jag // 2)))
        x += rng.randint(30, 90)
    pts.append((img.width, img.height))
    ImageDraw.Draw(img).polygon(pts, fill=color)


def _ridge(rng: random.Random, base: float, amp: float, rough: int) -> list[tuple[int, float]]:
    """Линия хребта: суммa нескольких синусов + случайные пики (получаются мягкие холмы и острые скалы)."""
    ph = [rng.uniform(0, 6.28) for _ in range(4)]
    pts = []
    for x in range(0, W + 8, 8):
        t = x / W
        y = (math.sin(t * 5 + ph[0]) * 0.5 + math.sin(t * 11 + ph[1]) * 0.3 + math.sin(t * 23 + ph[2]) * 0.15
             + math.sin(t * 47 + ph[3]) * 0.08)
        pts.append((x, H * base + y * amp + rng.randint(-rough, rough)))
    return pts


def _layer(img: Image.Image, pts, color, haze_color, haze: float) -> None:
    """Слой гор с воздушной дымкой: чем дальше слой, тем он светлее и сильнее растворяется в небе."""
    poly = [(0, H)] + pts + [(W, H)]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon(poly, fill=(*lerp(color, haze_color, haze), 255))
    # градиент внутри слоя: у вершины светлее, к низу темнее
    shade = Image.linear_gradient("L").resize(img.size).point(lambda v: int(v * 0.55))
    dark = Image.new("RGBA", img.size, (0, 0, 0, 255))
    dark.putalpha(ImageChops.multiply(shade, layer.getchannel("A")))
    layer.alpha_composite(dark)
    img.alpha_composite(layer)


def _fog(img: Image.Image, y: float, color, strength: int) -> None:
    band = Image.new("RGBA", img.size, (*color, 0))
    grad = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(grad)
    for yy in range(H):
        k = max(0.0, 1 - abs(yy - y) / (H * 0.16))
        d.line([(0, yy), (W, yy)], fill=int(strength * k * k))
    band.putalpha(grad)
    img.alpha_composite(band)


def _celestial(img: Image.Image, rng: random.Random, accent) -> None:
    cx, cy = rng.randint(int(W * 0.2), int(W * 0.8)), rng.randint(int(H * 0.16), int(H * 0.36))
    r = rng.randint(34, 52)
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([cx - r * 4, cy - r * 4, cx + r * 4, cy + r * 4], fill=(*accent, 60))
    hd.ellipse([cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2], fill=(*accent, 70))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(34)))
    disc = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*lerp(accent, (255, 255, 255), 0.65), 235))
    img.alpha_composite(disc.filter(ImageFilter.GaussianBlur(1.5)))
    # лучи света
    rays = Image.new("RGBA", img.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for _ in range(7):
        ang = rng.uniform(0.35, 2.8)
        ln = rng.randint(500, 900)
        wdt = rng.uniform(0.05, 0.12)
        pts = [(cx, cy), (cx + math.cos(ang - wdt) * ln, cy + math.sin(ang - wdt) * ln),
               (cx + math.cos(ang + wdt) * ln, cy + math.sin(ang + wdt) * ln)]
        rd.polygon(pts, fill=(*accent, 22))
    img.alpha_composite(rays.filter(ImageFilter.GaussianBlur(10)))


def _stars(img: Image.Image, rng: random.Random, n: int = 70) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.randint(0, W), rng.randint(0, int(H * 0.5))
        r = rng.choice([0.6, 0.8, 1.0, 1.4])
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 245, 235, rng.randint(70, 200)))
    img.alpha_composite(layer)


def _trees(img: Image.Image, rng: random.Random, color, base: float) -> None:
    """Передний план: силуэты деревьев/пик по краям кадра."""
    d = ImageDraw.Draw(img)
    for x0 in list(range(-20, 170, 40)) + list(range(W - 190, W + 20, 40)):
        h = rng.randint(130, 260)
        w = rng.randint(30, 52)
        top = H * base - h
        d.polygon([(x0, H), (x0 + w // 2, top), (x0 + w, H)], fill=color)
        for k in range(3):  # ярусы лап
            yy = top + h * (0.25 + 0.22 * k)
            d.polygon([(x0 - 10 + k * 3, yy + 40), (x0 + w // 2, yy - 22), (x0 + w + 10 - k * 3, yy + 40)], fill=color)


@lru_cache(maxsize=32)
def _background_cached(top, bottom, seed: int, accent) -> bytes:
    rng = random.Random(seed)
    img = gradient(lerp(top, accent, 0.10), lerp(bottom, accent, 0.30))        # небо светлеет к горизонту
    if sum(top) < 140:
        _stars(img, rng)
    _celestial(img, rng, accent)
    haze = lerp(bottom, accent, 0.35)
    dark = lerp(top, (0, 0, 0), 0.62)
    _layer(img, _ridge(rng, 0.60, 80, 5), dark, haze, 0.72)
    _layer(img, _ridge(rng, 0.69, 65, 7), dark, haze, 0.50)
    _fog(img, H * 0.72, haze, 120)
    _layer(img, _ridge(rng, 0.79, 50, 9), dark, haze, 0.25)
    _fog(img, H * 0.86, lerp(bottom, (0, 0, 0), 0.4), 90)
    _trees(img, rng, lerp(top, (0, 0, 0), 0.82), 1.02)
    embers(img, rng, accent, 55)
    img = vignette(img)
    return img.tobytes()


def background(top, bottom, seed: int = 1, accent=(255, 160, 80)) -> Image.Image:
    """Готовый фон (кэшируется, возвращается свежая копия)."""
    from . import anim
    anim.note_accent(accent)
    raw = _background_cached(tuple(top), tuple(bottom), seed, tuple(accent))
    return Image.frombytes("RGBA", (W, H), raw)


def custom_background(name: str) -> Image.Image | None:
    """Если положить assets/images/<name>.png|jpg — используем его вместо нарисованного фона."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        path = ASSET_DIR / f"{name}.{ext}"
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA")
                return img.resize((W, H), Image.LANCZOS)
            except OSError:
                return None
    return None


def theme_background(name: str) -> Image.Image:
    custom = custom_background(name)
    if custom:
        return custom
    top, bottom, accent = THEMES.get(name, THEMES["menu"])
    return background(top, bottom, seed=sum(map(ord, name)), accent=accent)


def panel(img: Image.Image, box, fill=(8, 8, 14, 175), radius: int = 22, outline=None) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if outline else 0)
    img.alpha_composite(layer)


def _draw_items(d: ImageDraw.ImageDraw, items: list, x: float, base_y: float, fill) -> None:
    for it in items:
        if it[0] == "t":
            _k, f, piece, w = it
            d.text((x, base_y), piece, font=f, fill=fill, anchor="ls")
            x += w
        else:
            _k, img, w = it
            im = d._image
            layer = img if im.mode == "RGBA" else img.convert("RGBA")
            im.paste(layer, (int(x), int(base_y - img.height * 0.82)), layer)
            x += w


def text(d: ImageDraw.ImageDraw, xy, s: str, f, fill=(245, 240, 230), anchor: str = "la", shadow: bool = True) -> None:
    """Рисует строку с запасными шрифтами и цветными эмодзи. anchor: l/m/r + a/m/s (как в Pillow)."""
    s = clean(s, limit=200)
    if not s:
        return
    items, width = _layout(s, f.size, "Bold" in f.path)
    asc, desc = f.getmetrics()
    x = xy[0] - (width if anchor[0] == "r" else width / 2 if anchor[0] == "m" else 0)
    v = anchor[1] if len(anchor) > 1 else "a"
    base_y = xy[1] + (asc if v == "a" else (asc - desc) / 2 if v == "m" else 0)
    if shadow:
        _draw_items(d, [it for it in items if it[0] == "t"], x + 2, base_y + 2, (0, 0, 0, 200))
    _draw_items(d, items, x, base_y, fill)


def fit(d: ImageDraw.ImageDraw, s: str, max_w: int, start: int, minimum: int = 18, bold: bool = True):
    size = start
    s = clean(s, limit=200)
    while size > minimum and measure(s, font(size, bold)) > max_w:
        size -= 2
    return font(size, bold)


def bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, frac: float, fg, bg=(26, 26, 34), border=(0, 0, 0)) -> None:
    frac = max(0.0, min(1.0, frac))
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg, outline=border, width=2)
    if frac > 0:
        fw = max(h, int(w * frac))
        d.rounded_rectangle([x + 2, y + 2, x + fw - 2, y + h - 2], radius=max(2, h // 2 - 2), fill=fg)


ANIMATE = True   # включается/выключается настройкой ANIMATED_IMAGES (см. app.py)


def finish(img: Image.Image, seed: int = 7, grain: bool = True) -> Image.Image:
    """Общая «плёночная» обработка: мягкое свечение ярких мест, лёгкое зерно, подъём контраста.
    Снимает ощущение плоской векторной картинки."""
    base = img.convert("RGB")
    bright = base.point(lambda v: max(0, v - 150) * 2)
    bloom = bright.filter(ImageFilter.GaussianBlur(14))
    out = ImageChops.screen(base, bloom.point(lambda v: int(v * 0.55)))
    if grain:
        noise = Image.effect_noise(out.size, 7).convert("RGB")   # серое зерно около 128
        out = ImageChops.add(out, noise, scale=1.0, offset=-128)
    return out.convert("RGBA")


def to_bytes(img: Image.Image, quality: int = 88, light: bool = False) -> bytes:
    """Готовая карточка -> байты. С ANIMATE это зацикленная GIF (начинается с b"GIF8"), иначе JPEG."""
    from . import anim
    eyes, accent = anim.take_context()
    if ANIMATE:
        return anim.build(finish(img, grain=False), accent, eyes, light=light)
    buf = io.BytesIO()
    finish(img).convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, subsampling=0)
    return buf.getvalue()
