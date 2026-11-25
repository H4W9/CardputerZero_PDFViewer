"""File browser: folders and PDF files, recent files and quick places."""

import glob
import os
import time

from PIL import ImageDraw

from . import ui
from .ui import C
from .widgets import PickList

DOC_EXTS = (".pdf",)
ROW = 15
JUMP_TIMEOUT = 1.2


def is_pdf(name):
    return name.lower().endswith(DOC_EXTS)


def user_homes():
    """Home folders worth offering: $HOME plus real users under /home."""
    out = []
    home = os.path.expanduser("~")
    for h in sorted(glob.glob("/home/*")) + [home]:
        if os.path.isdir(h) and h not in out:
            out.append(h)
    return out


def default_dir():
    """Where to start the first time: the user's Documents/Downloads or home."""
    homes = user_homes()
    # Under APPLaunch HOME is /root; prefer the real user's folders.
    homes.sort(key=lambda h: h.startswith("/root"))
    for h in homes:
        for sub in ("Documents", "Downloads"):
            p = os.path.join(h, sub)
            if os.path.isdir(p) and _has_pdf(p):
                return p
    for h in homes:
        if _has_pdf(h):
            return h
    return homes[0] if homes else "/"


def _has_pdf(d):
    try:
        return any(is_pdf(n) for n in os.listdir(d))
    except OSError:
        return False


def places():
    """(label, path) shortcuts that exist on this machine."""
    out = []
    for h in user_homes():
        out.append((h, h))
        for sub in ("Documents", "Downloads", "Airfiles"):
            p = os.path.join(h, sub)
            if os.path.isdir(p):
                out.append(("  " + sub, p))
    for pat in ("/media/*", "/media/*/*", "/mnt/*", "/run/media/*/*"):
        for p in sorted(glob.glob(pat)):
            if os.path.ismount(p):
                out.append(("USB  " + p, p))
    out.append(("/  (root)", "/"))
    return out


class Entry:
    __slots__ = ("name", "path", "is_dir", "size", "mtime")

    def __init__(self, name, path, is_dir, size=0, mtime=0):
        self.name, self.path, self.is_dir, self.size, self.mtime = name, path, is_dir, size, mtime


class Browser:
    """Folders + PDFs. Tab switches between Files and Recent."""

    typing = True

    def __init__(self, app, start=None):
        self.app = app
        self.view = "files"             # files | recent
        self.cwd = None
        self.entries = []
        self.sel = 0
        self.top = 0
        self.error = ""
        self.jump = ""
        self.jump_t = 0.0
        start = start or app.state.get("last_dir") or ""
        if not os.path.isdir(start):
            start = default_dir()
        self.chdir(start)

    # ------------------------------------------------------------ listing --

    def chdir(self, path, select=None):
        path = os.path.abspath(path)
        try:
            names = os.listdir(path)
        except OSError as e:
            self.app.toast("Can't open folder: %s" % (e.strerror or e))
            if self.cwd is None:
                path, names = "/", sorted(os.listdir("/"))
            else:
                return
        hidden = self.app.state.get("show_hidden")
        dirs, docs = [], []
        for n in names:
            if n.startswith(".") and not hidden:
                continue
            p = os.path.join(path, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if os.path.isdir(p):
                dirs.append(Entry(n, p, True, 0, st.st_mtime))
            elif is_pdf(n):
                docs.append(Entry(n, p, False, st.st_size, st.st_mtime))
        key = lambda e: e.name.lower()  # noqa: E731
        self.entries = sorted(dirs, key=key) + sorted(docs, key=key)
        if path != "/":
            self.entries.insert(0, Entry("..", os.path.dirname(path), True))
        self.cwd = path
        self.sel = 0
        self.top = 0
        if select:
            for i, e in enumerate(self.entries):
                if e.path == select:
                    self.sel = i
                    break
        elif len(self.entries) > 1 and self.entries[0].name == "..":
            self.sel = 1
        self.app.state["last_dir"] = path
        self.app.dirty = True

    def refresh(self):
        cur = self.current()
        self.chdir(self.cwd, select=cur.path if cur else None)

    def current(self):
        items = self.items()
        if 0 <= self.sel < len(items):
            return items[self.sel]
        return None

    def items(self):
        if self.view == "recent":
            out = []
            for r in self.app.state.get("recent", []):
                p = r.get("path", "")
                if os.path.isfile(p):
                    e = Entry(os.path.basename(p), p, False)
                    e.size = r.get("page", 0)
                    e.mtime = r.get("pages", 0)
                    out.append(e)
            return out
        return self.entries

    # -------------------------------------------------------------- keys ---

    def rows(self):
        return max(1, (ui.H - 16 - 13) // ROW)

    def handle_key(self, ev):
        if not ev.down:
            return
        items = self.items()
        n = len(items)
        k = ev.key
        jumping = bool(self.jump) and time.monotonic() - self.jump_t <= JUMP_TIMEOUT
        if k is None and not jumping:
            k = ui.nav_key(ev)          # F X Z C L M navigate unless a name is being typed
        if k is not None and ev.char and not ev.key:
            ev = None                   # used as a key, not as text
        if k == "up" and n:
            self.sel = (self.sel - 1) % n
        elif k == "down" and n:
            self.sel = (self.sel + 1) % n
        elif k == "pgup":
            self.sel = max(0, self.sel - self.rows())
        elif k == "pgdn" and n:
            self.sel = min(n - 1, self.sel + self.rows())
        elif k == "home":
            self.sel = 0
        elif k == "end" and n:
            self.sel = n - 1
        elif k in ("enter", "right"):
            self.open_current()
        elif k in ("bs", "left"):
            if self.view == "recent":
                self.view = "files"
                self.sel = 0
            elif self.cwd != "/":
                self.chdir(os.path.dirname(self.cwd), select=self.cwd)
        elif k == "tab":
            self.view = "recent" if self.view == "files" else "files"
            self.sel = 0
            self.top = 0
        elif k == "del" and self.view == "recent" and n:
            self.app.state.forget(items[self.sel].path)
            self.app.state.save()
            self.sel = max(0, min(self.sel, n - 2))
        elif ev is None:
            pass
        elif ev.char and ev.ctrl and ev.char == "h":
            self.app.state["show_hidden"] = not self.app.state.get("show_hidden")
            self.refresh()
            self.app.toast("Hidden files %s" % ("shown" if self.app.state["show_hidden"] else "hidden"))
        elif ev.char and not ev.ctrl:
            c = ev.char
            if c == "?":
                self.app.show_help()
            elif c == "~":
                self.chdir(user_homes()[0] if user_homes() else "/")
            elif c == "`" or c == "'":
                self.show_places()
            elif c == " " and not self.jump:
                self.open_current()
            else:
                self.type_jump(c)
        self.app.dirty = True

    def type_jump(self, c):
        now = time.monotonic()
        if now - self.jump_t > JUMP_TIMEOUT:
            self.jump = ""
        self.jump_t = now
        self.jump += c.lower()        # Shift+F starts a jump at "f"
        items = self.items()
        for i, e in enumerate(items):
            if e.name.lower().startswith(self.jump) and e.name != "..":
                self.sel = i
                return
        for i, e in enumerate(items):
            if self.jump in e.name.lower():
                self.sel = i
                return

    def show_places(self):
        items = [(label, path, 0) for label, path in places()]
        self.app.push(PickList("Go to", items, self._go_place))

    def _go_place(self, path):
        self.view = "files"
        self.chdir(path)

    def open_current(self):
        e = self.current()
        if e is None:
            return
        if e.is_dir:
            self.chdir(e.path, select=self.cwd if e.name == ".." else None)
        else:
            self.app.open_pdf(e.path)

    # -------------------------------------------------------------- draw ---

    def draw(self, img):
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, ui.W, ui.H], fill=C["bg"])
        items = self.items()
        if self.view == "recent":
            ui.draw_bar(d, "Recent", "%d" % len(items))
        else:
            shown = getattr(self, "shown_cwd", None) or self.cwd
            ui.draw_bar(d, ui.ellipsize_middle(ui.font("bold", 11), shown, ui.W - 80),
                        "%d PDF" % sum(1 for e in items if not e.is_dir))
        rows = self.rows()
        if self.sel >= len(items):
            self.sel = max(0, len(items) - 1)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        f = ui.font("regular", 11)
        fs = ui.font("regular", 9)
        y = 17
        if not items:
            msg = ("No recent files yet" if self.view == "recent"
                   else "No PDF files here. Backspace goes up.")
            d.text((8, 24), msg, font=f, fill=C["dim"])
        for i in range(self.top, min(len(items), self.top + rows)):
            e = items[i]
            sel = i == self.sel
            if sel:
                d.rectangle([0, y - 1, ui.W, y + ROW - 2], fill=C["sel"])
            self._icon(d, 4, y + 1, e.is_dir)
            if self.view == "recent":
                right = "p.%d/%d" % (e.size + 1, e.mtime) if e.mtime else ""
            elif e.is_dir:
                right = ""
            else:
                right = ui.human_size(e.size)
            rw = ui.text_w(fs, right) if right else 0
            name = e.name if e.name != ".." else ".. (up)"
            d.text((20, y), ui.ellipsize(f, name, ui.W - 30 - rw), font=f,
                   fill=C["folder"] if e.is_dir else C["text"])
            if right:
                d.text((ui.W - 6 - rw, y + 2), right, font=fs, fill=C["dim"])
            y += ROW
        if len(items) > rows:
            area = ui.H - 16 - 13
            th = max(8, area * rows // len(items))
            ty = 16 + (area - th) * self.top // max(1, len(items) - rows)
            d.rectangle([ui.W - 2, ty, ui.W, ty + th], fill=C["accent"])
        if self.view == "recent":
            ui.draw_footer(d, "Enter open  Del forget  Tab files  ' places  Fn+H help")
        else:
            ui.draw_footer(d, "F/X move  C open  Z up  L/M page  Tab recent  Fn+H help")

    @staticmethod
    def _icon(d, x, y, folder):
        if folder:
            d.rectangle([x, y + 2, x + 11, y + 10], fill=C["folder"])
            d.rectangle([x, y, x + 5, y + 2], fill=C["folder"])
        else:
            d.polygon([(x + 1, y), (x + 8, y), (x + 11, y + 3), (x + 11, y + 11), (x + 1, y + 11)],
                      fill=C["paper"])
            d.rectangle([x, y + 5, x + 9, y + 9], fill=C["bar"])
