"""App shell: screens, pop-ups, the background worker and key routing."""

import os
import queue
import threading
import time
import traceback

from PIL import Image, ImageDraw

from . import __version__, pdf, ui
from .browser import Browser
from .state import State
from .ui import C
from .viewer import Viewer
from .widgets import Prompt, TextBox

LOG = os.environ.get("CZPDF_LOG", "/tmp/czpdf.log")

HELP_VIEWER = """Moving around:
 F / X  (Up / Down)   scroll
 Z / C  (Left / Right)   pan, or turn the page when it fits
 L / M  (PgUp / PgDn)   previous / next page
 Space, Enter   next screen      Bksp   previous screen
 , and .   previous / next page
 Home / End   first / last page
 G or a number   go to page

Zoom and view:
 + and -   zoom in / out
 W   fit width        P   whole page
 R   rotate           I   night colours
 T   text mode (reflowed text, + and - change the size)
 Tab   hide or show the status bar

Find:
 / or S   search      N   next match      Shift+N   previous
 Esc   clear the search
 O   contents (the PDF's outline)
 D   document info

Other:
 B   file browser     Q   quit
 Esc   back (to Files, if you came from there)
"""

HELP_BROWSER = """Files:
 F / X  (Up / Down)   move
 L / M  (PgUp / PgDn)   a screen up / down
 C, Right or Enter   open
 Z, Left or Bksp   up one folder
 Type letters   jump to a name (Shift+F/X/Z/C/L/M
   to start with one of those)
 Tab   recent files (Del forgets one)
 ' (apostrophe)   places: home folders, Downloads, USB sticks
 ~   home folder
 Ctrl+H   show hidden files
 Esc   quit

Only folders and PDF files are listed. The page you were on
is remembered for every file.
"""


class Worker:
    """One background thread runs every job that touches a document.
    Results come back to the main thread through drain()."""

    def __init__(self, sync=False):
        self.sync = sync
        self.inq = queue.Queue()
        self.outq = queue.Queue()
        self.pending = 0
        if not sync:
            threading.Thread(target=self._run, name="czpdf-worker", daemon=True).start()

    def submit(self, fn, done=None):
        if self.sync:            # tests and screenshots: run now, answer now
            try:
                r, e = fn(), None
            except Exception as ex:  # noqa: BLE001
                r, e = None, ex
            if done is not None:
                done(r, e)
            return
        self.pending += 1
        self.inq.put((fn, done))

    def _do(self, fn, done):
        try:
            r, e = fn(), None
        except Exception as ex:  # noqa: BLE001 - reported to the UI
            r, e = None, ex
        self.outq.put((done, r, e))

    def _run(self):
        while True:
            fn, done = self.inq.get()
            self._do(fn, done)

    def drain(self):
        n = 0
        while True:
            try:
                done, r, e = self.outq.get_nowait()
            except queue.Empty:
                return n
            self.pending -= 1
            n += 1
            if done is not None:
                done(r, e)


class App:
    def __init__(self, path=None, page=None, start_dir=None, state=None, sync=False):
        self.state = state if state is not None else State.load()
        self.worker = Worker(sync)
        self.running = True
        self.dirty = True
        self.overlays = []
        self.toast_msg = ""
        self.toast_until = 0.0
        self.esc_armed = False
        self.viewer = None
        self.browser = None
        self.opening = None
        self.last_path = None
        self.from_file = path is not None
        self._busy_shown = False
        if path:
            self.open_pdf(path, page=page)
        else:
            self.browser = Browser(self, start_dir)

    # ------------------------------------------------------------ screens --

    @property
    def screen(self):
        if self.viewer is not None:
            return self.viewer
        if self.browser is None:
            last = self.opening or self.last_path
            self.browser = Browser(self, os.path.dirname(last) if last else None)
        return self.browser

    def push(self, overlay):
        self.overlays.append(overlay)
        self.dirty = True

    def toast(self, msg, seconds=2.2):
        self.toast_msg = msg
        self.toast_until = time.monotonic() + seconds
        self.dirty = True

    def log(self, msg):
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        except OSError:
            pass

    def open_pdf(self, path, page=None, password=None):
        path = os.path.abspath(path)
        self.opening = self.last_path = path
        self.toast("Opening %s…" % os.path.basename(path), 30)

        def done(doc, err):
            self.opening = None
            self.toast_until = 0
            if isinstance(err, pdf.NeedPassword):
                self.push(Prompt("%s: %s" % (err, os.path.basename(path)),
                                 lambda pw: self.open_pdf(path, page, pw), secret=True,
                                 on_cancel=lambda: self._open_failed(path)))
                return
            if err is not None:
                self.log("open %s failed: %s" % (path, traceback.format_exception_only(
                    type(err), err)[-1].strip()))
                self.toast(str(err) if isinstance(err, pdf.PdfError) else pdf._short(err), 4)
                self._open_failed(path)
                return
            if self.viewer is not None:
                self.viewer.close()
            self.viewer = Viewer(self, doc, path, page)
            self.viewer.back_quits = self.from_file
            self.viewer.save()
            self.state.save()
            self.dirty = True

        self.worker.submit(lambda: pdf.open_document(path, password), done)

    def _open_failed(self, path=None):
        # Opened from Files and it didn't work: show the folder instead of a blank screen.
        if self.viewer is None:
            if self.browser is None:
                self.browser = Browser(self, os.path.dirname(path) if path else None)
            if path and os.path.isdir(os.path.dirname(path)):
                self.browser.view = "files"
                self.browser.chdir(os.path.dirname(path), select=path)
        self.from_file = False
        self.dirty = True

    def show_browser(self):
        if self.viewer is not None:
            path = self.viewer.path
            self.viewer.close()
            self.viewer = None
            self.state.save()
            if self.browser is None:
                self.browser = Browser(self, os.path.dirname(path))
            if os.path.dirname(path) == self.browser.cwd:
                self.browser.refresh()
                self.browser.chdir(self.browser.cwd, select=path)
            elif self.browser.view == "files" and self.from_file:
                self.browser.chdir(os.path.dirname(path), select=path)
        self.from_file = False
        self.dirty = True

    def show_help(self):
        if self.overlays and isinstance(self.overlays[-1], TextBox):
            self.overlays.pop()
        elif self.viewer is not None:
            self.push(TextBox("Keys  (PDF Viewer %s)" % __version__, HELP_VIEWER))
        else:
            self.push(TextBox("Keys  (PDF Viewer %s)" % __version__, HELP_BROWSER))
        self.dirty = True

    def show_info(self):
        v = self.viewer
        if v is None:
            return
        try:
            size = ui.human_size(os.path.getsize(v.path))
        except OSError:
            size = "?"
        lines = ["File:", " " + v.path, "", "Pages: %d    Size: %s" % (v.pages, size)]
        if v.doc.title:
            lines.append("Title: " + v.doc.title)
        if v.doc.author:
            lines.append("Author: " + v.doc.author)
        lines.append("Renderer: " + v.backend)
        self.push(TextBox("Document", "\n".join(lines)))

    def quit(self):
        self.running = False

    def go_back(self):
        if self.viewer is not None and not self.viewer.back_quits:
            self.show_browser()
        else:
            self.quit()

    def shutdown(self):
        if self.viewer is not None:
            self.viewer.save()
        self.state.save()

    # --------------------------------------------------------------- keys --

    def handle_key(self, ev):
        self.dirty = True
        if ev.key == "help":
            if ev.down:
                self.show_help()
            return
        if self.overlays:
            top = self.overlays[-1]
            top.handle_key(ev)
            if top.done and top in self.overlays:
                self.overlays.remove(top)
            self.esc_armed = False
            return
        if ev.key == "esc":
            # Act on release, so the key-up doesn't land in the app we return to.
            if ev.down:
                if not ev.repeat:
                    self.esc_armed = not (self.viewer is not None and self.viewer.on_escape())
            elif self.esc_armed:
                self.esc_armed = False
                self.go_back()
            return
        if self.opening and self.viewer is None:
            return
        self.screen.handle_key(ev)

    # ------------------------------------------------------------- frames --

    def tick(self, force=False):
        if self.worker.drain():
            self.dirty = True
        now = time.monotonic()
        if self.toast_msg and now > self.toast_until:
            self.toast_msg = ""
            self.dirty = True
        if self.viewer is not None and self.viewer.tick(now):
            self.dirty = True
        busy = self.worker.pending > 0
        if busy != self._busy_shown:
            self.dirty = True
        if not (self.dirty or force):
            return None
        self.dirty = False
        self._busy_shown = busy
        return self.render()

    def render_at(self, w, h):
        """The current frame laid out for another screen size (the built-in
        screen while the app runs on the EXT display)."""
        main = (ui.W, ui.H)
        ui.set_size(w, h)
        try:
            return self.render()
        finally:
            ui.set_size(*main)

    def render(self):
        img = Image.new("RGB", (ui.W, ui.H), C["bg"])
        if self.viewer is None and self.opening and self.browser is None:
            d = ImageDraw.Draw(img)
            ui.draw_bar(d, "PDF Viewer")
            d.text((10, ui.H // 2 - 8), "Opening %s…" % ui.ellipsize(
                ui.font("regular", 12), os.path.basename(self.opening), ui.W - 90),
                font=ui.font("regular", 12), fill=C["text"])
        else:
            self.screen.draw(img)
        d = ImageDraw.Draw(img)
        for ov in self.overlays:
            ov.draw(img, d)
        if self.toast_msg:
            f = ui.font("regular", 10)
            t = ui.ellipsize(f, self.toast_msg, ui.W - 30)
            w = int(ui.text_w(f, t)) + 14
            x0 = (ui.W - w) // 2
            y0 = ui.H - 40
            d.rounded_rectangle([x0, y0, x0 + w, y0 + 18], radius=6, fill=(0, 0, 0),
                                outline=C["accent"])
            d.text((x0 + 7, y0 + 3), t, font=f, fill=C["text"])
        if self._busy_shown:
            d.ellipse([ui.W - 11, 4, ui.W - 5, 10], fill=C["accent"], outline=(0, 0, 0))
        return img
