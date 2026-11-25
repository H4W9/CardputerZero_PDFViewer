"""Sample PDFs and store screenshots (desktop only; needs PyMuPDF)."""

import os
import tempfile

from . import ui

SECTIONS = [
    ("Getting started", [
        "The Cardputer Zero is a pocket Linux computer with a keyboard, a small colour "
        "screen and a battery. This guide shows how to copy documents to it and read them.",
        "Copy PDF files into your home folder, Documents or Downloads. Airfiles, SFTP and "
        "USB sticks all work. Open the PDF Viewer and pick a file from the list.",
    ]),
    ("Reading a page", [
        "Pages open at the full width of the screen. Scroll with the arrow keys, or press "
        "Space to move down one screen at a time. At the bottom of a page the next one "
        "starts by itself.",
        "Press P to see the whole page, W to go back to the page width, and + or - to "
        "zoom. Small print is easier to read in text mode: press T and the words are "
        "wrapped to fit the screen.",
    ]),
    ("Finding things", [
        "Press / to search the whole document. Matches are marked on the page; N jumps to "
        "the next one and Shift+N goes back. O opens the contents list when the PDF has one.",
    ]),
    ("Picking up where you left off", [
        "Every file opens at the page you were reading, with the same zoom. Press Tab in "
        "the file list to see your recent files.",
    ]),
]


def make_sample_pdf(path, pages=6):
    import pymupdf as fitz

    doc = fitz.open()
    toc = []
    for n in range(pages):
        page = doc.new_page(width=595, height=842)       # A4
        sec = SECTIONS[n % len(SECTIONS)]
        title = "%d. %s" % (n + 1, sec[0])
        toc.append([1, title, n + 1])
        page.draw_rect(fitz.Rect(0, 0, 595, 70), color=None, fill=(0.69, 0.16, 0.16))
        page.insert_text((40, 46), "Pocket Reader Guide", fontsize=24, color=(1, 1, 1),
                         fontname="helv")
        page.insert_text((40, 120), title, fontsize=20, fontname="hebo")
        y = 150
        for para in sec[1] * 2:
            rect = fitz.Rect(40, y, 555, y + 140)
            page.insert_textbox(rect, para, fontsize=12, fontname="tiro")
            y += 110
        # a small chart so the page isn't only text
        x0, y0 = 60, 640
        for i, h in enumerate((40, 90, 65, 120, 80)):
            page.draw_rect(fitz.Rect(x0 + i * 70, y0 + 130 - h, x0 + i * 70 + 45, y0 + 130),
                           color=None, fill=(0.2 + i * 0.12, 0.35, 0.65))
        page.insert_text((40, 810), "Page %d of %d" % (n + 1, pages), fontsize=10,
                         fontname="helv", color=(0.4, 0.4, 0.4))
        if n % 3 == 1:
            toc.append([2, "Zoom and text mode", n + 1])
    doc.set_toc(toc)
    doc.set_metadata({"title": "Pocket Reader Guide", "author": "PDF Viewer"})
    doc.save(path)
    doc.close()
    return path


def sample_dir():
    d = os.path.join(tempfile.gettempdir(), "czpdf-demo")
    docs = os.path.join(d, "Documents")
    os.makedirs(docs, exist_ok=True)
    guide = os.path.join(docs, "Pocket Reader Guide.pdf")
    if not os.path.exists(guide):
        make_sample_pdf(guide)
    for name, pages in (("Recipes.pdf", 3), ("Train timetable.pdf", 2),
                        ("Manual - Cardputer Zero.pdf", 4)):
        p = os.path.join(docs, name)
        if not os.path.exists(p):
            make_sample_pdf(p, pages)
    for sub in ("Books", "Work"):
        os.makedirs(os.path.join(docs, sub), exist_ok=True)
    return docs


def screenshots(out_dir):
    from .app import App
    from .keyboard import Key
    from .state import State

    os.makedirs(out_dir, exist_ok=True)
    docs = sample_dir()
    st = State(os.path.join(tempfile.gettempdir(), "czpdf-demo", "state.json"))
    guide = os.path.join(docs, "Pocket Reader Guide.pdf")
    out = []

    def shot(app, name):
        img = app.tick(force=True)
        p = os.path.join(out_dir, name)
        img.save(p)
        out.append(p)

    def keys(app, *ks):
        for k in ks:
            ev = Key(True, char=k) if len(k) == 1 else Key(True, key=k)
            app.handle_key(ev)
            app.handle_key(Key(False, key=ev.key, char=ev.char))
            app.tick(force=True)

    app = App(start_dir=docs, state=st, sync=True)
    app.browser.shown_cwd = "/home/user/Documents"   # not the temp folder on the PC
    app.browser.sel = 3
    shot(app, "browser.png")
    app = App(guide, state=st, sync=True)
    shot(app, "page-width.png")
    keys(app, "p")
    app.toast_msg = ""
    shot(app, "whole-page.png")
    keys(app, "w", "t")
    app.toast_msg = ""
    shot(app, "text-mode.png")
    keys(app, "t", "/")
    for c in "screen":
        keys(app, c)
    keys(app, "enter")
    app.toast_msg = ""
    shot(app, "search.png")
    keys(app, "o")
    shot(app, "contents.png")
    return out


def run_demo_window():
    from .app import App
    from .display import run_desktop
    run_desktop(App(start_dir=sample_dir()))


if __name__ == "__main__":
    print(ui.W, ui.H)
