#!/usr/bin/env python3
"""Draw the launcher icon (packaging/icon.png, 100x100) and store icon (store/icon.png, 256x256)."""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 8                       # supersampling (drawn at 800 px)
N = 100 * S


def font(size):
    for p in ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(size=100):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 18 * S, 6 * S, 82 * S, 94 * S
    fold = 20 * S
    # shadow
    d.polygon([(x0 + 3 * S, y0 + 3 * S), (x1 - fold + 3 * S, y0 + 3 * S), (x1 + 3 * S, y0 + fold + 3 * S),
               (x1 + 3 * S, y1 + 3 * S), (x0 + 3 * S, y1 + 3 * S)], fill=(0, 0, 0, 90))
    # sheet
    d.polygon([(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)],
              fill=(250, 250, 246, 255), outline=(150, 150, 150, 255))
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(214, 214, 208, 255))
    # text lines
    for i, w in enumerate((40, 34, 40, 26)):
        y = y0 + (18 + i * 8) * S
        d.rounded_rectangle([x0 + 8 * S, y, x0 + (8 + w) * S, y + 3 * S], radius=S, fill=(170, 176, 186, 255))
    # red PDF band
    by0, by1 = 58 * S, 80 * S
    d.rounded_rectangle([8 * S, by0, 92 * S, by1], radius=4 * S, fill=(196, 36, 36, 255))
    f = font(17 * S)
    t = "PDF"
    tw = d.textlength(t, font=f)
    d.text(((N - tw) / 2, by0 + 1.5 * S), t, font=f, fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def main():
    # 100 px in the package (the launcher's centre-card size), 256 px for the store.
    for rel, size in (("packaging/icon.png", 100), ("store/icon.png", 256)):
        p = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        make(size).save(p)
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
