"""Regenerate mipmap launcher PNGs to match in-app companion orb (shell + bird emblem)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "res"
EMBLEM = ROOT / "drawable-nodpi" / "ic_launcher_emblem.png"

DENSITIES: dict[str, int] = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

# Match ic_launcher_background.xml + companion-orb-shell tones
BG_OUTER = (10, 18, 24, 255)
BG_MID = (26, 15, 18, 255)
BG_INNER = (42, 21, 32, 255)


def _orb_background(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG_OUTER)
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    draw.ellipse((2, 2, size - 2, size - 2), fill=BG_MID)
    inset = max(2, size // 12)
    draw.ellipse(
        (inset, inset, size - inset, size - inset),
        fill=BG_INNER,
    )
    return img


def _composite(size: int, emblem: Image.Image) -> Image.Image:
    base = _orb_background(size)
    # ~60% of canvas — bird sits inside orb shell like .companion-orb-face
    target = int(size * 0.62)
    em = emblem.copy()
    em.thumbnail((target, target), Image.Resampling.LANCZOS)
    x = (size - em.width) // 2
    y = (size - em.height) // 2
    base.alpha_composite(em, (x, y))
    return base


def main() -> None:
    if not EMBLEM.is_file():
        raise SystemExit(f"Missing emblem (orb asset): {EMBLEM}")
    emblem = Image.open(EMBLEM).convert("RGBA")
    for folder, size in DENSITIES.items():
        out_dir = ROOT / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        icon = _composite(size, emblem)
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            icon.save(out_dir / name, optimize=True)
        print(f"wrote {folder} {size}px")


if __name__ == "__main__":
    main()
