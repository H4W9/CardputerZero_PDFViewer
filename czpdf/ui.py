"""Drawing helpers: screen size, theme, fonts, text measuring and wrapping."""

import os

from PIL import ImageFont

W, H = 320, 170   # built-in screen; set_size() switches to the EXT display (320x240)


# The Cardputer Zero prints the arrows on F (up), X (down), Z (left), C (right)
# and Page Up / Page Down on L / M; with Fn they send the real keys. On screens
# that aren't taking text the plain letters do the same.
NAV_LETTERS = {"f": "up", "x": "down", "z": "left", "c": "right", "l": "pgup", "m": "pgdn"}


def nav_key(ev):
    """Named key for ev, counting a plain F/X/Z/C/L/M as its printed arrow/page key."""
    if ev.key:
        return ev.key
    if ev.char and not ev.ctrl:
        return NAV_LETTERS.get(ev.char)
    return None


def set_size(w, h):
    """Pick the screen size. Call before importing app/display."""
    global W, H
    W, H = w, h


C = {
    "bg": (14, 16, 22),
    "desk": (54, 58, 66),        # behind the page
    "panel": (26, 30, 40),
    "bar": (176, 40, 40),
    "bar_text": (250, 244, 244),
    "text": (228, 232, 240),
    "dim": (132, 140, 158),
    "accent": (255, 120, 104),
    "sel": (92, 44, 48),
    "folder": (255, 200, 90),
    "warn": (255, 108, 88),
    "ok": (104, 208, 128),
    "cursor": (255, 255, 255),
    "field": (36, 40, 52),
    "hit": (255, 220, 0),
    "hit_now": (255, 120, 0),
    "paper": (250, 250, 246),
    "ink": (20, 20, 24),
}

_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "DejaVuSans.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ],
    "serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSerif.ttf",
    ],
}

_cache = {}


def font(kind="regular", size=11):
    key = (kind, size)
    f = _cache.get(key)
    if f is not None:
        return f
    paths = list(_CANDIDATES.get(kind, _CANDIDATES["regular"]))
    font_dir = os.environ.get("CZPDF_FONT_DIR")      # e.g. DejaVu for store screenshots
    if font_dir:
        name = {"bold": "DejaVuSans-Bold.ttf", "serif": "DejaVuSerif.ttf"}.get(kind, "DejaVuSans.ttf")
        paths.insert(0, os.path.join(font_dir, name))
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            break
        except (OSError, IOError):
            continue
    else:
        try:
            f = ImageFont.load_default(size)
        except TypeError:  # Pillow < 10.1
            f = ImageFont.load_default()
    _cache[key] = f
    return f


def text_w(fnt, s):
    return fnt.getlength(s)


def ellipsize(fnt, s, maxw):
    """Cut s so it fits in maxw pixels, adding an ellipsis when shortened."""
    s = s.replace("\n", " ").replace("\r", "").replace("\t", " ")
    if fnt.getlength(s) <= maxw:
        return s
    ell = "\u2026"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fnt.getlength(s[:mid] + ell) <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + ell


def ellipsize_middle(fnt, s, maxw):
    """Like ellipsize, but keeps the end (for paths and file names)."""
    if fnt.getlength(s) <= maxw:
        return s
    ell = "\u2026"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fnt.getlength(ell + s[-mid:]) <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return ell + (s[-lo:] if lo else "")


def wrap_lines(text, fnt, maxw):
    """Word-wrap text to maxw pixels. Newlines end a line."""
    out = []
    for para in text.split("\n"):
        _wrap_para(para, fnt, maxw, out)
    return out


def _wrap_para(s, fnt, maxw, out):
    if not s:
        out.append("")
        return
    while s:
        if fnt.getlength(s) <= maxw:
            out.append(s)
            return
        lo, hi = 1, len(s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fnt.getlength(s[:mid]) <= maxw:
                lo = mid
            else:
                hi = mid - 1
        brk = s.rfind(" ", 0, lo + 1)
        if brk > 0:
            out.append(s[:brk])
            s = s[brk + 1:]
        else:
            out.append(s[:lo])
            s = s[lo:]


def draw_bar(d, title, right=""):
    """Top title bar, 16 px tall."""
    d.rectangle([0, 0, W, 15], fill=C["bar"])
    fb = font("bold", 11)
    fr = font("regular", 10)
    rw = text_w(fr, right) if right else 0
    d.text((4, 1), ellipsize(fb, title, W - rw - 26), font=fb, fill=C["bar_text"])
    if right:
        d.text((W - 16 - rw, 2), right, font=fr, fill=C["bar_text"])


def draw_footer(d, hint):
    """Bottom key-hint bar, 13 px tall."""
    d.rectangle([0, H - 13, W, H], fill=C["panel"])
    f = font("regular", 9)
    d.text((4, H - 12), ellipsize(f, hint, W - 8), font=f, fill=C["dim"])


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d" % n
