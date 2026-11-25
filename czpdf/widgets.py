"""Pop-up layers drawn over a screen: line input, pick list, help text."""

from . import ui
from .ui import C


class Overlay:
    done = False

    def handle_key(self, ev):
        return True

    def draw(self, img, d):
        pass


def _box(d, x0, y0, x1, y1, title):
    d.rectangle([x0, y0, x1, y1], fill=C["panel"], outline=C["accent"])
    d.rectangle([x0, y0, x1, y0 + 14], fill=C["bar"])
    fb = ui.font("bold", 10)
    d.text((x0 + 5, y0 + 1), ui.ellipsize(fb, title, x1 - x0 - 10), font=fb, fill=C["bar_text"])


class Prompt(Overlay):
    """One line of text. on_done(text) on Enter, on_cancel() on Esc."""

    def __init__(self, title, on_done, text="", digits=False, secret=False, hint="",
                 on_cancel=None):
        self.title = title
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.text = text
        self.digits = digits
        self.secret = secret
        self.hint = hint

    def handle_key(self, ev):
        if not ev.down:
            return True
        if ev.key == "esc":
            self.done = True
            if self.on_cancel:
                self.on_cancel()
        elif ev.key == "enter":
            self.done = True
            self.on_done(self.text)
        elif ev.key == "bs":
            self.text = self.text[:-1]
        elif ev.char and not ev.ctrl:
            if self.digits and not ev.char.isdigit():
                return True
            if len(self.text) < 120:
                self.text += ev.char
        return True

    def draw(self, img, d):
        w = min(ui.W - 20, 280)
        x0 = (ui.W - w) // 2
        y0 = ui.H // 2 - 34
        _box(d, x0, y0, x0 + w, y0 + 62, self.title)
        f = ui.font("regular", 12)
        shown = "•" * len(self.text) if self.secret else self.text
        d.rectangle([x0 + 6, y0 + 20, x0 + w - 6, y0 + 38], fill=C["field"])
        t = ui.ellipsize_middle(f, shown, w - 22)
        d.text((x0 + 10, y0 + 22), t, font=f, fill=C["text"])
        cx = x0 + 10 + int(ui.text_w(f, t)) + 1
        d.line([cx, y0 + 22, cx, y0 + 36], fill=C["cursor"])
        fs = ui.font("regular", 9)
        d.text((x0 + 6, y0 + 44), ui.ellipsize(fs, self.hint or "Enter OK   Esc cancel", w - 12),
               font=fs, fill=C["dim"])


class PickList(Overlay):
    """Scrollable list. items: [(label, value, indent)]; on_pick(value)."""

    def __init__(self, title, items, on_pick, sel=0, empty="Nothing here"):
        self.title = title
        self.items = items
        self.on_pick = on_pick
        self.sel = max(0, min(sel, len(items) - 1)) if items else 0
        self.top = 0
        self.empty = empty

    def _rows(self):
        return max(1, (ui.H - 40) // 14)

    def handle_key(self, ev):
        if not ev.down:
            return True
        n = len(self.items)
        k = ui.nav_key(ev)
        if ev.key == "esc" or ev.char == "q":
            self.done = True
        elif k == "up" and n:
            self.sel = (self.sel - 1) % n
        elif k == "down" and n:
            self.sel = (self.sel + 1) % n
        elif k in ("pgup", "left") and n:
            self.sel = max(0, self.sel - self._rows())
        elif k in ("pgdn", "right") and n:
            self.sel = min(n - 1, self.sel + self._rows())
        elif k == "home":
            self.sel = 0
        elif k == "end" and n:
            self.sel = n - 1
        elif ev.key == "enter" and n:
            self.done = True
            self.on_pick(self.items[self.sel][1])
        return True

    def draw(self, img, d):
        x0, y0, x1, y1 = 8, 8, ui.W - 8, ui.H - 8
        _box(d, x0, y0, x1, y1, self.title)
        f = ui.font("regular", 11)
        rows = self._rows()
        if not self.items:
            d.text((x0 + 8, y0 + 22), self.empty, font=f, fill=C["dim"])
            return
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        y = y0 + 18
        for i in range(self.top, min(len(self.items), self.top + rows)):
            label, _value, indent = self.items[i]
            if i == self.sel:
                d.rectangle([x0 + 2, y - 1, x1 - 2, y + 13], fill=C["sel"])
            x = x0 + 6 + min(indent, 6) * 8
            d.text((x, y), ui.ellipsize(f, label, x1 - x - 8), font=f,
                   fill=C["text"] if i == self.sel else C["dim"] if indent else C["text"])
            y += 14
        if len(self.items) > rows:
            th = max(8, (y1 - y0 - 22) * rows // len(self.items))
            ty = y0 + 18 + (y1 - y0 - 22 - th) * self.top // max(1, len(self.items) - rows)
            d.rectangle([x1 - 4, ty, x1 - 2, ty + th], fill=C["accent"])


class TextBox(Overlay):
    """Scrollable help / info text."""

    def __init__(self, title, text):
        self.title = title
        self.lines = ui.wrap_lines(text, ui.font("regular", 10), ui.W - 30)
        self.top = 0

    def handle_key(self, ev):
        if not ev.down:
            return True
        rows = max(1, (ui.H - 36) // 12)
        k = ui.nav_key(ev)
        if k == "up":
            self.top = max(0, self.top - 1)
        elif k == "down":
            self.top = min(max(0, len(self.lines) - rows), self.top + 1)
        elif k in ("pgup", "left"):
            self.top = max(0, self.top - rows)
        elif k in ("pgdn", "right") or ev.char == " ":
            self.top = min(max(0, len(self.lines) - rows), self.top + rows)
        elif k in ("home", "end"):
            self.top = 0 if k == "home" else max(0, len(self.lines) - rows)
        elif ev.char and ev.char.isupper():
            pass                                  # Shift on its way to a letter
        else:
            self.done = True
        return True

    def draw(self, img, d):
        x0, y0, x1, y1 = 6, 6, ui.W - 6, ui.H - 6
        _box(d, x0, y0, x1, y1, self.title)
        f = ui.font("regular", 10)
        rows = max(1, (ui.H - 36) // 12)
        y = y0 + 18
        for line in self.lines[self.top:self.top + rows]:
            bold = line.endswith(":") and not line.startswith(" ")
            d.text((x0 + 8, y), line, font=ui.font("bold", 10) if bold else f,
                   fill=C["accent"] if bold else C["text"])
            y += 12
        if len(self.lines) > rows:
            d.text((x1 - 60, y1 - 12), "%d/%d" % (min(len(self.lines), self.top + rows),
                                                len(self.lines)),
                   font=ui.font("regular", 8), fill=C["dim"])
