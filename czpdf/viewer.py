"""The page viewer: render, scroll, zoom, rotate, text mode, search, outline."""

import os
import time
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageOps

from . import pdf, ui
from .ui import C
from .widgets import PickList, Prompt

BAR_H = 13
STALE = object()
ZOOM_MAX = 6.0


class Viewer:
    typing = False

    def __init__(self, app, doc, path, page=None):
        self.app = app
        self.doc = doc                       # only used inside worker jobs
        self.path = os.path.abspath(path)
        self.pages = doc.page_count
        self.backend = doc.backend
        self.title = doc.title or os.path.basename(path)
        self.back_quits = False              # Esc leaves the app (opened from Files)
        pos = app.state.position(self.path)
        self.page = _clamp(page if page is not None else int(pos.get("page", 0)), 0, self.pages - 1)
        self.mode = pos.get("mode") if pos.get("mode") in ("width", "page") else "width"
        self.zoom = min(ZOOM_MAX, max(1.0, float(pos.get("zoom", 1.0) or 1.0)))
        self.rot = int(pos.get("rot", 0)) % 360
        self.text_mode = bool(pos.get("text", False))
        self.img = None
        self.key = None
        self.hits = []
        self.hit_idx = 0
        self.ox = self.oy = 0
        self.place = ("frac", float(pos.get("fy", 0.0) or 0.0)) if page is None else ("top",)
        self.want = None
        self.cache = OrderedDict()
        self.outline = None
        self.search_q = ""
        self.searching = False
        self.texts = {}
        self.text_want = None
        self.text_lines = None
        self.text_key = None
        self.text_top = 0
        self.text_place = "top"
        self.badge_until = 0.0
        self.request()

    # ------------------------------------------------------------ geometry --

    def view_size(self):
        bar = BAR_H if self.app.state.get("show_bar", True) else 0
        return ui.W, ui.H - bar

    def cur_key(self):
        vw, vh = self.view_size()
        return (self.page, self.mode, round(self.zoom, 3), self.rot, vw, vh,
                bool(self.app.state.get("invert")), self.search_q)

    # ----------------------------------------------------------- rendering --

    def request(self):
        if self.text_mode:
            self.request_text()
            return
        key = self.cur_key()
        if key == self.key:
            return
        if key in self.cache:
            self.cache.move_to_end(key)
            self._apply(key, *self.cache[key])
            self._prefetch()
            return
        if key == self.want:
            return
        self.want = key
        self.app.worker.submit(lambda k=key: self._job_render(k, check=True),
                               lambda r, e, k=key: self._rendered(k, r, e))

    def _job_render(self, key, check):
        if check and self.want != key:
            return STALE
        page, mode, zoom, rot, vw, vh, invert, q = key
        pw, ph = self.doc.page_size(page)
        rw, rh = pdf.rotated(pw, ph, rot)
        if mode == "page":
            scale = min(vw / rw, vh / rh)
        else:
            scale = vw / rw * zoom
        img, scale = self.doc.render(page, scale, rot)
        if invert:
            img = ImageOps.invert(img)
        hits = []
        if q:
            hits = self.doc.map_rects(page, self.doc.search(page, q), scale, rot)
        return img, hits

    def _rendered(self, key, result, err):
        if self.want == key:
            self.want = None
        if result is STALE:
            return
        if err is not None:
            self.app.toast("Page %d: %s" % (key[0] + 1, pdf._short(err)))
            self.app.log("render page %d failed: %r" % (key[0] + 1, err))
            return
        self._store(key, result)
        if key == self.cur_key():
            self._apply(key, *result)
            self._prefetch()
        self.app.dirty = True

    def _store(self, key, result):
        self.cache[key] = result
        self.cache.move_to_end(key)
        while len(self.cache) > 4:
            self.cache.popitem(last=False)

    def _prefetch(self):
        """Render the next page in the background so turning pages is quick."""
        if self.want is not None or self.page + 1 >= self.pages:
            return
        key = (self.page + 1,) + self.cur_key()[1:]
        if key in self.cache:
            return
        self.app.worker.submit(lambda k=key: self._job_render(k, check=False),
                               lambda r, e, k=key: (r is not STALE and e is None
                                                    and self._store(k, r)))

    def _apply(self, key, img, hits):
        vw, vh = self.view_size()
        old = self.img
        self.img, self.key, self.hits = img, key, hits
        maxx, maxy = max(0, img.width - vw), max(0, img.height - vh)
        place, self.place = self.place, None
        if place is None and old is not None:
            place = ("keep",)
        kind = place[0] if place else "top"
        if kind == "top":
            self.oy = 0
        elif kind == "bottom":
            self.oy = maxy
        elif kind == "frac":
            self.oy = int(place[1] * img.height)
        elif kind == "center":
            self.ox = int(place[1] * img.width - vw / 2)
            self.oy = int(place[2] * img.height - vh / 2)
        elif kind == "hit":
            if hits:
                self.hit_idx = place[1] % len(hits)
                self._show_hit()
            else:
                self.oy = 0
        if kind in ("top", "bottom", "frac"):
            self.ox = min(self.ox, maxx) if kind != "top" else 0
        self.ox = _clamp(self.ox, 0, maxx)
        self.oy = _clamp(self.oy, 0, maxy)

    def _show_hit(self):
        if not self.hits or self.img is None:
            return
        vw, vh = self.view_size()
        x0, y0, x1, y1 = self.hits[self.hit_idx]
        self.oy = _clamp(int((y0 + y1) / 2 - vh / 2), 0, max(0, self.img.height - vh))
        if self.img.width > vw:
            self.ox = _clamp(int((x0 + x1) / 2 - vw / 2), 0, self.img.width - vw)

    def _keep_center(self):
        if self.img is None:
            return
        vw, vh = self.view_size()
        fx = (min(self.ox, max(0, self.img.width - vw)) + vw / 2) / self.img.width
        fy = (self.oy + vh / 2) / self.img.height
        self.place = ("center", fx, fy)

    # ------------------------------------------------------------ text mode --

    def request_text(self):
        if self.page in self.texts or self.text_want == self.page:
            return
        self.text_want = p = self.page
        self.app.worker.submit(lambda: self.doc.text(p), lambda r, e: self._got_text(p, r, e))

    def _got_text(self, p, text, err):
        if self.text_want == p:
            self.text_want = None
        if err is not None:
            text = "(Can't read text on this page: %s)" % pdf._short(err)
        text = (text or "").strip("\n")
        self.texts[p] = text if text.strip() else (
            "(No text on this page. It may be a scanned image. Press T for the page view.)")
        if len(self.texts) > 12:
            self.texts.pop(next(iter(self.texts)))
        self.app.dirty = True

    def _text_layout(self):
        size = int(self.app.state.get("text_size", 13))
        vw, vh = self.view_size()
        key = (self.page, size, vw)
        if self.text_key != key and self.page in self.texts:
            f = ui.font("serif", size)
            raw = self.texts[self.page]
            # Join lines that were only broken by the PDF layout.
            paras = []
            for block in raw.replace("\r", "").split("\n\n"):
                paras.append(" ".join(ln.strip() for ln in block.split("\n") if ln.strip()))
            self.text_lines = ui.wrap_lines("\n\n".join(paras), f, vw - 12)
            self.text_key = key
            rows = self._text_rows()
            if self.text_place == "bottom":
                self.text_top = max(0, len(self.text_lines) - rows)
            else:
                self.text_top = 0
            self.text_place = "top"
        return self.text_lines if self.text_key == key else None

    def _text_rows(self):
        size = int(self.app.state.get("text_size", 13))
        return max(1, (self.view_size()[1] - 6) // (size + 4))

    def text_scroll(self, lines):
        ls = self._text_layout()
        if ls is None:
            return
        rows = self._text_rows()
        maxtop = max(0, len(ls) - rows)
        nt = self.text_top + lines
        if nt < 0:
            if self.text_top == 0 and self.page > 0:
                self.goto(self.page - 1, "bottom")
                return
            nt = 0
        elif nt > maxtop:
            if self.text_top >= maxtop and self.page + 1 < self.pages:
                self.goto(self.page + 1, "top")
                return
            nt = maxtop
        self.text_top = nt

    # ---------------------------------------------------------- navigation --

    def goto(self, page, where="top"):
        page = _clamp(page, 0, self.pages - 1)
        if page == self.page and isinstance(where, str) and not self.text_mode:
            if where == "top":
                self.oy = 0
            elif where == "bottom" and self.img is not None:
                self.oy = max(0, self.img.height - self.view_size()[1])
            return
        self.page = page
        self.place = ("top",) if where == "top" else ("bottom",) if where == "bottom" else where
        self.text_place = "bottom" if where == "bottom" else "top"
        self.text_key = None
        self.hit_idx = 0
        self.badge_until = time.monotonic() + 1.3
        self.request()

    def scroll(self, dy):
        if self.text_mode:
            size = int(self.app.state.get("text_size", 13))
            self.text_scroll(int(round(dy / (size + 4))) or (1 if dy > 0 else -1))
            return
        if self.img is None:
            return
        vh = self.view_size()[1]
        maxy = max(0, self.img.height - vh)
        ny = self.oy + dy
        if ny < 0:
            if self.oy == 0:
                if self.page > 0:
                    self.goto(self.page - 1, "bottom")
                return
            ny = 0
        elif ny > maxy:
            if self.oy >= maxy:
                if self.page + 1 < self.pages:
                    self.goto(self.page + 1, "top")
                return
            ny = maxy
        self.oy = ny

    def pan(self, dx):
        vw = self.view_size()[0]
        if self.text_mode or self.img is None or self.img.width <= vw:
            self.goto(self.page + (1 if dx > 0 else -1), "top")
            return
        maxx = self.img.width - vw
        if (dx < 0 and self.ox == 0) or (dx > 0 and self.ox >= maxx):
            return
        self.ox = _clamp(self.ox + dx, 0, maxx)

    def set_zoom(self, mode, zoom):
        if self.text_mode:
            return
        self._keep_center()
        self.mode, self.zoom = mode, min(ZOOM_MAX, max(1.0, zoom))
        self.request()
        self.app.toast(self.zoom_label(), 0.8)

    def zoom_label(self):
        if self.text_mode:
            return "Text %d" % self.app.state.get("text_size", 13)
        if self.mode == "page":
            return "Page"
        return "Width" if self.zoom == 1.0 else "%d%%" % round(self.zoom * 100)

    # ----------------------------------------------------------- searching --

    def start_search(self, q, start=None, step=1, place_last=False):
        q = q.strip()
        if not q:
            self.search_q = ""
            self.request()
            return
        if self.searching:
            return
        self.search_q = q
        self.searching = True
        first = self.page if start is None else start
        n = self.pages
        order = [(first + step * i) % n for i in range(n)]

        def job():
            for i in order:
                if self.doc.search(i, q):
                    return i
            return None

        def done(found, err):
            self.searching = False
            if err is not None or found is None:
                self.app.toast("\"%s\" not found" % q)
                self.request()
                return
            if start is not None and ((step > 0 and found <= self.page) or
                                      (step < 0 and found >= self.page)):
                self.app.toast("Search wrapped around", 1.0)
            self.goto(found, ("hit", -1 if place_last else 0))
            if found == self.page and self.key == self.cur_key():
                self.place = None
                self.hit_idx = (len(self.hits) - 1) if place_last and self.hits else 0
                self._show_hit()

        self.app.toast("Searching…", 0.6)
        self.app.worker.submit(job, done)
        self.request()

    def next_hit(self, back=False):
        if not self.search_q:
            self.ask_search()
            return
        if self.text_mode:
            self.text_mode = False
        if self.hits and not back and self.hit_idx + 1 < len(self.hits):
            self.hit_idx += 1
            self._show_hit()
        elif self.hits and back and self.hit_idx > 0:
            self.hit_idx -= 1
            self._show_hit()
        elif self.pages > 1:
            step = -1 if back else 1
            self.start_search(self.search_q, (self.page + step) % self.pages, step,
                              place_last=back)
        else:
            self.app.toast("No more matches", 1.0)

    def ask_search(self):
        self.app.push(Prompt("Find text", self.start_search, text=self.search_q,
                             hint="Enter search   Esc cancel   (empty clears)"))

    # ------------------------------------------------------------- outline --

    def show_outline(self):
        if self.outline is None:
            def done(r, e):
                self.outline = r or []
                self.show_outline()
            self.app.worker.submit(self.doc.outline, done)
            return
        if not self.outline:
            self.app.toast("This PDF has no contents list" +
                           (" (Poppler)" if self.backend == "Poppler" else ""))
            return
        items = [("%s  · %d" % (t, p + 1), p, lvl - 1) for lvl, t, p in self.outline]
        sel = 0
        for i, (_l, p, _i) in enumerate(items):
            if p <= self.page:
                sel = i
        self.app.push(PickList("Contents", items, lambda p: self.goto(p, "top"), sel=sel))

    def ask_goto(self, first=""):
        def go(text):
            try:
                self.goto(int(text) - 1, "top")
            except ValueError:
                pass
        self.app.push(Prompt("Go to page (1-%d)" % self.pages, go, text=first, digits=True))

    # ---------------------------------------------------------------- keys --

    def on_escape(self):
        """Esc pressed: clear a search first. True if that used the key."""
        if self.search_q:
            self.search_q = ""
            self.hits = []
            self.request()
            return True
        return False

    def handle_key(self, ev):
        if not ev.down:
            return
        k = ui.nav_key(ev)
        ch = ev.char if not ev.ctrl and k is None else None
        vw, vh = self.view_size()
        st = self.app.state
        if k == "up":
            self.scroll(-28)
        elif k == "down":
            self.scroll(28)
        elif k == "left":
            self.pan(-48)
        elif k == "right":
            self.pan(48)
        elif k == "pgup":
            self.goto(self.page - 1, "top")
        elif k == "pgdn":
            self.goto(self.page + 1, "top")
        elif k == "home":
            self.goto(0, "top")
        elif k == "end":
            self.goto(self.pages - 1, "top")
        elif k == "enter" or ch == " ":
            self.scroll(vh - 20)
        elif k == "bs":
            self.scroll(-(vh - 20))
        elif k == "tab":
            st["show_bar"] = not st.get("show_bar", True)
            self._keep_center()
            self.request()
        elif ch in (",", "[", "<"):
            self.goto(self.page - 1, "top")
        elif ch in (".", "]", ">"):
            self.goto(self.page + 1, "top")
        elif ch in ("+", "="):
            if self.text_mode:
                st["text_size"] = min(28, int(st.get("text_size", 13)) + 1)
                self.app.toast(self.zoom_label(), 0.8)
            elif self.mode == "page":
                self.set_zoom("width", 1.0)
            else:
                self.set_zoom("width", self.zoom * 1.25)
        elif ch in ("-", "_"):
            if self.text_mode:
                st["text_size"] = max(8, int(st.get("text_size", 13)) - 1)
                self.app.toast(self.zoom_label(), 0.8)
            elif self.mode == "width" and self.zoom > 1.0:
                z = self.zoom / 1.25
                self.set_zoom("width", 1.0 if z < 1.05 else z)
            else:
                self.set_zoom("page", 1.0)
        elif ch == "w" or ch == "0":
            self.set_zoom("width", 1.0)
        elif ch == "p":
            self.set_zoom("page", 1.0)
        elif ch == "r":
            self._keep_center()
            self.rot = (self.rot + 90) % 360
            self.request()
        elif ch == "i":
            st["invert"] = not st.get("invert")
            self.cache.clear()
            self.request()
        elif ch == "t":
            self.text_mode = not self.text_mode
            self.text_key = None
            self.request()
            self.app.toast("Text mode" if self.text_mode else "Page view", 0.8)
        elif ch == "g":
            self.ask_goto()
        elif ch and ch.isdigit():
            self.ask_goto(ch)
        elif ch in ("/", "s"):
            self.ask_search()
        elif ch == "n":
            self.next_hit()
        elif ch == "N":
            self.next_hit(back=True)
        elif ch == "o":
            self.show_outline()
        elif ch == "b":
            self.app.show_browser()
        elif ch in ("h", "?"):
            self.app.show_help()
        elif ch == "q":
            self.app.quit()
        elif ch == "d":
            self.app.show_info()
        self.request()
        self.app.dirty = True

    def tick(self, now):
        if self.badge_until and now > self.badge_until:
            self.badge_until = 0.0
            return True
        return False

    # ---------------------------------------------------------------- draw --

    def draw(self, img):
        d = ImageDraw.Draw(img)
        vw, vh = self.view_size()
        if self.text_mode:
            self._draw_text(img, d, vw, vh)
        else:
            self._draw_page(img, d, vw, vh)
        if self.app.state.get("show_bar", True):
            self._draw_bar(d)
        elif self.badge_until:
            self._draw_badge(d)

    def _draw_page(self, img, d, vw, vh):
        d.rectangle([0, 0, ui.W, ui.H], fill=C["desk"])
        page = self.img
        if page is None:
            f = ui.font("regular", 12)
            d.text((10, vh // 2 - 8), "Loading page %d…" % (self.page + 1), font=f,
                   fill=C["text"])
            return
        ox, oy, hits = self.ox, self.oy, self.hits
        mw, mh = (self.key[4], self.key[5]) if self.key else (vw, vh)
        if (vw, vh) != (mw, mh):
            # Second screen (built-in next to the EXT display): same page image,
            # its own window onto it, following the main screen's position.
            if self.mode == "page" and (page.width > vw or page.height > vh):
                page, f = self._fitted(page, vw, vh)
                hits = [tuple(v * f for v in r) for r in hits]
            ox = _clamp(_follow(ox, page.width, mw, vw), 0, max(0, page.width - vw))
            oy = _clamp(_follow(oy, page.height, mh, vh), 0, max(0, page.height - vh))
        x = (vw - page.width) // 2 if page.width <= vw else -ox
        y = (vh - page.height) // 2 if page.height <= vh else -oy
        box = (max(0, -x), max(0, -y), min(page.width, vw - x), min(page.height, vh - y))
        img.paste(page.crop(box), (x + box[0], y + box[1]))
        for i, (x0, y0, x1, y1) in enumerate(hits):
            col = C["hit_now"] if i == self.hit_idx else C["hit"]
            d.rectangle([x + x0 - 1, y + y0 - 1, x + x1 + 1, y + y1 + 1], outline=col,
                        width=2 if i == self.hit_idx else 1)
        if page.height > vh:
            th = max(6, vh * vh // page.height)
            ty = (vh - th) * oy // max(1, page.height - vh)
            d.rectangle([vw - 3, ty, vw - 1, ty + th], fill=C["accent"])
        if page.width > vw:
            tw = max(6, vw * vw // page.width)
            tx = (vw - tw) * ox // max(1, page.width - vw)
            d.rectangle([tx, vh - 3, tx + tw, vh - 1], fill=C["accent"])
        if self.key and self.key[0] != self.page:
            self._draw_badge(d, loading=True)

    def _fitted(self, page, vw, vh):
        """page scaled down to fit vw x vh (cached for the current image)."""
        f = min(vw / page.width, vh / page.height)
        key = (id(page), vw, vh)
        if getattr(self, "_fit_key", None) != key:
            self._fit_img = page.resize((max(1, int(page.width * f)), max(1, int(page.height * f))),
                                        Image.BILINEAR)
            self._fit_key = key
        return self._fit_img, f

    def _draw_text(self, img, d, vw, vh):
        dark = bool(self.app.state.get("invert"))
        bg, fg = (C["bg"], C["text"]) if dark else (C["paper"], C["ink"])
        d.rectangle([0, 0, ui.W, ui.H], fill=bg)
        lines = self._text_layout()
        size = int(self.app.state.get("text_size", 13))
        f = ui.font("serif", size)
        if lines is None:
            d.text((8, vh // 2 - 8), "Reading page %d…" % (self.page + 1),
                   font=ui.font("regular", 12), fill=fg)
            return
        rows = self._text_rows()
        y = 3
        q = self.search_q.lower()
        for line in lines[self.text_top:self.text_top + rows]:
            if q and q in line.lower():
                i = line.lower().index(q)
                x0 = 6 + ui.text_w(f, line[:i])
                d.rectangle([x0, y, x0 + ui.text_w(f, line[i:i + len(q)]), y + size + 2],
                            fill=C["hit"])
            d.text((6, y), line, font=f, fill=fg)
            y += size + 4
        if len(lines) > rows:
            th = max(6, vh * rows // len(lines))
            ty = (vh - th) * self.text_top // max(1, len(lines) - rows)
            d.rectangle([vw - 3, ty, vw - 1, ty + th], fill=C["accent"])

    def _draw_bar(self, d):
        y = ui.H - BAR_H
        d.rectangle([0, y, ui.W, ui.H], fill=C["panel"])
        f = ui.font("bold", 9)
        fr = ui.font("regular", 9)
        left = "%d/%d" % (self.page + 1, self.pages)
        right = self.zoom_label() + (" ↻%d" % self.rot if self.rot else "")
        if self.search_q:
            n = len(self.hits)
            right = ("\"%s\" %d/%d  " % (self.search_q[:12], self.hit_idx + 1 if n else 0, n)
                     + right)
        lw = ui.text_w(f, left)
        rw = ui.text_w(fr, right)
        d.text((4, y + 1), left, font=f, fill=C["accent"])
        d.text((ui.W - 4 - rw, y + 1), right, font=fr, fill=C["dim"])
        d.text((lw + 12, y + 1), ui.ellipsize(fr, self.title, ui.W - lw - rw - 26), font=fr,
               fill=C["text"])

    def _draw_badge(self, d, loading=False):
        f = ui.font("bold", 11)
        s = "%d / %d" % (self.page + 1, self.pages)
        if loading:
            s += " …"
        w = int(ui.text_w(f, s)) + 12
        x1, y1 = ui.W - 6, ui.H - 6
        d.rounded_rectangle([x1 - w, y1 - 18, x1, y1], radius=5, fill=C["panel"],
                            outline=C["accent"])
        d.text((x1 - w + 6, y1 - 16), s, font=f, fill=C["text"])

    # ---------------------------------------------------------------- save --

    def position(self):
        fy = 0.0
        if self.img is not None and self.img.height:
            fy = round(self.oy / self.img.height, 4)
        return {"page": self.page, "mode": self.mode, "zoom": self.zoom, "rot": self.rot,
                "text": self.text_mode, "fy": fy}

    def save(self):
        self.app.state.remember(self.path, self.pages, **self.position())

    def close(self):
        self.save()
        doc = self.doc
        self.app.worker.submit(doc.close)
        self.cache.clear()


def _follow(off, size, main_view, view):
    """Offset for a smaller view that tracks a bigger one scrolled to off:
    flush with the start at the start, with the end at the end."""
    span = size - main_view
    if span <= 0 or main_view <= view:
        return off
    return int(off + (main_view - view) * off / span)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v
