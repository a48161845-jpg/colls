"""Оживление картинок: из готовой карточки получается зацикленная GIF-анимация (Telegram покажет её как «гифку»).

Что движется: тлеющие искры поднимаются вверх, по кадру плывёт полоса света, глаза монстров и героев пульсируют,
по низу идёт дымка. Сама карточка (фон, фигуры, плашки с текстом) не перерисовывается на каждый кадр,
поэтому кодирование быстрое. Выключить: ANIMATED_IMAGES=0 в .env.
"""
from __future__ import annotations

import io
import math
import random
import threading
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FRAMES = 12
FRAME_MS = 90
SCALE_W = 800            # анимация чуть меньше статичного JPEG: быстрее грузится и кодируется

ctx = threading.local()   # какие глаза и какой акцентный цвет были на последней отрисованной карточке


def note_eyes(eyes: list[tuple[float, float, float]]) -> None:
    cur = getattr(ctx, "eyes", [])
    cur.extend(eyes)
    ctx.eyes = cur[-24:]


def note_accent(accent) -> None:
    ctx.accent = tuple(accent)


def take_context() -> tuple[list, tuple]:
    eyes, accent = getattr(ctx, "eyes", []), getattr(ctx, "accent", (255, 160, 80))
    ctx.eyes, ctx.accent = [], (255, 160, 80)
    return eyes, accent


@lru_cache(maxsize=64)
def _ember(r: int, color: tuple) -> Image.Image:
    size = r * 6
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([size / 2 - r * 2, size / 2 - r * 2, size / 2 + r * 2, size / 2 + r * 2], fill=(*color, 90))
    d.ellipse([size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r], fill=(*color, 255))
    return im.filter(ImageFilter.GaussianBlur(max(1, r * 0.8)))


@lru_cache(maxsize=8)
def _sweep(w: int, h: int) -> Image.Image:
    """Мягкая наклонная полоса света."""
    band = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(band)
    bw = int(w * 0.22)
    d.polygon([(bw, 0), (bw * 2, 0), (bw, h), (0, h)], fill=255)
    band = band.filter(ImageFilter.GaussianBlur(bw * 0.35))
    im = Image.new("RGBA", (bw * 2 + 40, h), (255, 244, 225, 0))
    im.putalpha(band.crop((0, 0, bw * 2 + 40, h)).point(lambda v: int(v * 0.10)))
    return im


@lru_cache(maxsize=32)
def _glow(r: int, color: tuple) -> Image.Image:
    size = r * 8
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([size / 2 - r * 2.2, size / 2 - r * 2.2, size / 2 + r * 2.2, size / 2 + r * 2.2], fill=(*color, 255))
    a = im.filter(ImageFilter.GaussianBlur(r * 1.3)).getchannel("A")
    out = Image.new("RGBA", (size, size), (*color, 0))
    out.putalpha(a)
    return out


def build(base: Image.Image, accent=(255, 160, 80), eyes=(), seed: int = 5, light: bool = False) -> bytes:
    """base — готовая карточка (любой размер) -> GIF-байты."""
    rng = random.Random(seed + len(eyes))
    w = 640 if light else SCALE_W        # light: карточки, которые меняются на каждый клик (бой), делаем компактнее
    nframes = 8 if light else FRAMES
    h = round(base.height * w / base.width)
    scale = w / base.width
    base = base.convert("RGBA").resize((w, h), Image.LANCZOS)
    color = tuple(int(c) for c in accent)
    warm = tuple(min(255, int(c * 0.6 + 120)) for c in color)

    # искры: (x0, y0, оборотов за цикл, амплитуда качания, фаза, радиус)
    embers = [(rng.uniform(0, w), rng.uniform(0, h), rng.choice((1, 1, 2)), rng.uniform(6, 22), rng.uniform(0, 6.28),
               rng.choice((2, 2, 3, 3, 4))) for _ in range(22 if light else 34)]
    eye_pts = [(x * scale, y * scale, max(3, int(r * scale))) for x, y, r in eyes]
    sweep = _sweep(w, h)
    fh = h // 2
    fog_noise = Image.effect_noise((w // 10, fh // 10), 70).resize((w, fh), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))
    fade = Image.linear_gradient("L").resize((w, fh))            # туман густеет к низу и без резкой верхней границы
    fade = fade.point(lambda v: int((v / 255) ** 1.6 * 255))

    frames: list[Image.Image] = []
    for i in range(nframes):
        t = i / nframes
        fr = base.copy()
        # дымка у земли: слой тумана медленно смещается по кругу
        shift = int(t * w)
        fm = ImageChops.offset(fog_noise, shift, 0).point(lambda v: int(max(0, v - 70) * 0.5))
        fog = Image.new("RGBA", (w, fh), (*warm, 0))
        fog.putalpha(ImageChops.multiply(fm, fade))
        fr.alpha_composite(fog, (0, h - fh))
        # свет скользит слева направо
        fr.alpha_composite(sweep, (int(-sweep.width + (w + sweep.width) * t), 0))
        # пульс глаз
        for k, (x, y, r) in enumerate(eye_pts):
            pulse = 0.55 + 0.45 * math.sin(2 * math.pi * (t + k * 0.17))
            g = _glow(r, color).copy()
            g.putalpha(g.getchannel("A").point(lambda v, p=pulse: int(v * 0.55 * p)))
            fr.alpha_composite(g, (int(x - g.width / 2), int(y - g.height / 2)))
        # искры
        for x0, y0, cyc, amp, ph, r in embers:
            y = (y0 - cyc * h * t) % h
            x = x0 + math.sin(2 * math.pi * t + ph) * amp
            e = _ember(r, warm if r > 2 else color)
            twinkle = 0.65 + 0.35 * math.sin(2 * math.pi * (t * 2 + ph))
            if twinkle < 0.98:
                e = e.copy()
                e.putalpha(e.getchannel("A").point(lambda v, tw=twinkle: int(v * tw)))
            fr.alpha_composite(e, (int(x - e.width / 2), int(y - e.height / 2)))
        frames.append(fr.convert("RGB"))

    pal = frames[nframes // 2].quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    out = [f.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for f in frames]
    buf = io.BytesIO()
    out[0].save(buf, "GIF", save_all=True, append_images=out[1:], duration=FRAME_MS, loop=0, optimize=False, disposal=1)
    return buf.getvalue()
