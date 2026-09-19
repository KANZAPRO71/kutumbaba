"""Generate Play Store feature graphic 1024x500 for Papua AI."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1024, 500
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "play-store" / "feature-graphic-1024x500.png"
EMBLEM_PATH = ROOT / "docs" / "play-store" / "cenderawasih-emblem.jpg"

BG = (3, 7, 13)
GOLD = (232, 196, 122)
GOLD_BRIGHT = (245, 230, 192)
CYAN = (34, 211, 238)
EMERALD = (20, 184, 122)
MUTED = (161, 161, 170)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _radial_gradient(size: tuple[int, int], center: tuple[float, float], radius: float, inner, outer) -> Image.Image:
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xs - center[0]) ** 2 + (ys - center[1]) ** 2)
    t = np.clip(dist / radius, 0, 1)
    layer = np.zeros((h, w, 4), dtype=np.uint8)
    for i in range(4):
        layer[:, :, i] = (inner[i] * (1 - t) + outer[i] * t).astype(np.uint8)
    return Image.fromarray(layer, "RGBA")


def _draw_glass_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill=(255, 255, 255, 18), outline=(255, 255, 255, 38), width=2)
    draw.line((x0 + 24, y0 + 52, x1 - 24, y0 + 52), fill=(232, 196, 122, 80), width=1)


def _load_emblem_rgba(path: Path, max_side: int) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    arr = np.array(im, dtype=np.float32)
    rgb = arr[:, :, :3]
    lum = rgb.mean(axis=2)
    # Black backdrop → transparent; keep gold bird + glow
    alpha = np.clip((lum - 10.0) * 4.2, 0, 255)
    alpha = np.maximum(alpha, arr[:, :, 3] * (lum > 18))
    out = np.zeros_like(arr, dtype=np.uint8)
    out[:, :, :3] = rgb.astype(np.uint8)
    out[:, :, 3] = alpha.astype(np.uint8)
    emblem = Image.fromarray(out, "RGBA")
    emblem.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return emblem


def _draw_orb(base: Image.Image, cx: int, cy: int, r: int, emblem: Image.Image | None = None) -> None:
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(12):
        rr = r + 40 - i * 3
        alpha = 8 + i * 3
        gdraw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(34, 211, 238, alpha), width=2)
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    base.alpha_composite(glow)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k in range(r, 0, -1):
        t = k / r
        col = (
            int(8 + 30 * t),
            int(17 + 80 * t),
            int(30 + 90 * t),
            255,
        )
        d.ellipse((cx - k, cy - k, cx + k, cy + k), fill=col)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=GOLD + (255,), width=4)
    base.alpha_composite(layer)

    if emblem is not None:
        ew, eh = emblem.size
        base.alpha_composite(emblem, (cx - ew // 2, cy - eh // 2 - 6))


def _draw_wave_strip(base: Image.Image, y: int) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    points = []
    for x in range(0, W + 8, 8):
        amp = 12 + 8 * math.sin(x * 0.04)
        points.append((x, y + amp * math.sin(x * 0.025)))
    for offset, alpha in ((0, 120), (3, 60)):
        shifted = [(p[0], p[1] + offset) for p in points]
        d.line(shifted, fill=CYAN + (alpha,), width=2, joint="curve")
    base.alpha_composite(layer)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rgb = Image.new("RGB", (W, H), BG)
    img = rgb.convert("RGBA")

    img.alpha_composite(_radial_gradient((W, H), (280, 200), 420, (56, 189, 248, 0), (56, 189, 248, 55)))
    img.alpha_composite(_radial_gradient((W, H), (860, 360), 380, (212, 175, 55, 0), (212, 175, 55, 45)))
    img.alpha_composite(_radial_gradient((W, H), (720, 120), 260, (20, 184, 122, 0), (20, 184, 122, 35)))

    _draw_wave_strip(img, H - 72)

    draw = ImageDraw.Draw(img)
    _draw_glass_panel(draw, (48, 88, 620, 412))

    title = _font(64, bold=True)
    sub = _font(28)
    tags = _font(20)
    badge = _font(18, bold=True)

    draw.text((88, 118), "Papua AI", font=title, fill=GOLD_BRIGHT)
    draw.text((88, 198), "Ngobrol & Mop", font=sub, fill=(250, 250, 250))
    draw.text((88, 248), "Suara live · logat dekat · BYOK Gemini", font=tags, fill=MUTED)
    draw.text((88, 292), "Backend lokal di HP — privasi kamu yang utama", font=tags, fill=(134, 239, 172))

    draw.rounded_rectangle((88, 340, 248, 378), radius=18, fill=(30, 58, 138, 200), outline=CYAN + (140,), width=2)
    draw.text((108, 348), "Buka Suara", font=badge, fill=(236, 254, 255))

    orb_r = 92
    emblem = _load_emblem_rgba(EMBLEM_PATH, max_side=int(orb_r * 2.05)) if EMBLEM_PATH.exists() else None
    _draw_orb(img, 820, 250, orb_r, emblem=emblem)

    # Bottom gold rule
    draw.rectangle((0, H - 5, W, H), fill=GOLD)

    final = Image.new("RGB", (W, H), BG)
    final.paste(img, (0, 0), img)
    final.save(OUT, "PNG", optimize=True)
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
