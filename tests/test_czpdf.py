"""Offline tests: python -m unittest discover -s tests"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czpdf import pdf  # noqa: E402
from czpdf.app import App  # noqa: E402
from czpdf.keyboard import Key  # noqa: E402
from czpdf.state import State  # noqa: E402

try:
    import pymupdf  # noqa: F401
    HAVE_MUPDF = True
except ImportError:
    HAVE_MUPDF = False


def press(app, key=None, char=None, ctrl=False):
    app.handle_key(Key(True, key=key, char=char, ctrl=ctrl))
    app.handle_key(Key(False, key=key, char=char, ctrl=ctrl))
    app.tick(force=True)


@unittest.skipUnless(HAVE_MUPDF, "needs PyMuPDF to make test files")
class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from czpdf.demo import make_sample_pdf
        cls.tmp = tempfile.mkdtemp(prefix="czpdf_test_")
        cls.pdf = make_sample_pdf(os.path.join(cls.tmp, "guide.pdf"), pages=6)
        make_sample_pdf(os.path.join(cls.tmp, "two.PDF"), pages=2)
        with open(os.path.join(cls.tmp, "notes.txt"), "w") as fh:
            fh.write("not a pdf")
        os.mkdir(os.path.join(cls.tmp, "sub"))
        import pymupdf
        doc = pymupdf.open(cls.pdf)
        cls.locked = os.path.join(cls.tmp, "locked.pdf")
        doc.save(cls.locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234",
                 owner_pw="owner")
        doc.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def state(self):
        return State(os.path.join(self.tmp, "state_%s.json" % self.id().split(".")[-1]))

    def test_browser_lists_folders_and_pdfs_only(self):
        app = App(start_dir=self.tmp, state=self.state(), sync=True)
        names = [e.name for e in app.browser.entries]
        self.assertIn("sub", names)
        self.assertIn("guide.pdf", names)
        self.assertIn("two.PDF", names)
        self.assertNotIn("notes.txt", names)
        self.assertLess(names.index("sub"), names.index("guide.pdf"))

    def test_open_from_browser_and_back(self):
        app = App(start_dir=self.tmp, state=self.state(), sync=True)
        for c in "guide":
            press(app, char=c)
        press(app, key="enter")
        self.assertIsNotNone(app.viewer)
        self.assertEqual(app.viewer.pages, 6)
        press(app, key="esc")
        self.assertIsNone(app.viewer)
        self.assertTrue(app.running)
        press(app, key="esc")
        self.assertFalse(app.running)

    def test_opened_with_file_esc_quits_on_release(self):
        app = App(self.pdf, state=self.state(), sync=True)
        app.tick(force=True)
        app.handle_key(Key(True, key="esc"))
        self.assertTrue(app.running, "must not quit on key-down")
        app.handle_key(Key(False, key="esc"))
        self.assertFalse(app.running)

    def test_page_turning_and_scroll_into_next_page(self):
        app = App(self.pdf, state=self.state(), sync=True)
        v = app.viewer
        self.assertEqual(v.page, 0)
        press(app, char=".")
        self.assertEqual(v.page, 1)
        press(app, key="pgup")
        self.assertEqual(v.page, 0)
        for _ in range(200):
            press(app, char=" ")
            if v.page == 1:
                break
        self.assertEqual(v.page, 1)
        self.assertEqual(v.oy, 0)
        press(app, key="bs")
        self.assertEqual(v.page, 0)
        self.assertGreater(v.oy, 0, "going back lands at the bottom of the page")
        press(app, key="end")
        self.assertEqual(v.page, 5)
        press(app, char=".")
        self.assertEqual(v.page, 5)

    def test_letter_arrows(self):
        app = App(self.pdf, state=self.state(), sync=True)
        v = app.viewer
        press(app, char="x")
        self.assertGreater(v.oy, 0)
        press(app, char="f")
        self.assertEqual(v.oy, 0)

    def test_letter_page_keys(self):
        app = App(self.pdf, state=self.state(), sync=True)
        v = app.viewer
        press(app, char="m")
        press(app, char="m")
        self.assertEqual(v.page, 2)
        press(app, char="l")
        self.assertEqual(v.page, 1)
        press(app, char="c")            # page fits the width: right turns the page
        self.assertEqual(v.page, 2)
        press(app, char="z")
        self.assertEqual(v.page, 1)

    def test_browser_letter_navigation_and_shift_jump(self):
        for name in ("fish.pdf", "lemon.pdf", "melon.pdf"):
            p = os.path.join(self.tmp, name)
            if not os.path.exists(p):
                shutil.copy(self.pdf, p)
        try:
            app = App(start_dir=self.tmp, state=self.state(), sync=True)
            b = app.browser
            start = b.sel
            press(app, char="x")
            self.assertEqual(b.sel, start + 1, "x moves down, doesn't jump")
            press(app, char="f")
            self.assertEqual(b.sel, start)
            press(app, char="m")
            self.assertGreater(b.sel, start)
            press(app, char="l")
            self.assertEqual(b.sel, 0)
            b.jump = ""
            press(app, char="F")            # Shift+F jumps to names starting with f
            self.assertEqual(b.current().name, "fish.pdf")
            b.jump = ""
            press(app, char="g")            # g starts a jump, then l and m are text
            press(app, char="u")
            self.assertEqual(b.current().name, "guide.pdf")
            b.jump = ""
            b.jump_t = 0
            press(app, char="M")
            press(app, char="e")
            press(app, char="l")
            self.assertEqual(b.current().name, "melon.pdf")
            press(app, char="z")           # still typing: no folder change
            self.assertEqual(b.cwd, os.path.abspath(self.tmp))
            b.jump = ""
            b.jump_t = 0
            press(app, char="z")            # z = left = up one folder
            self.assertEqual(b.cwd, os.path.dirname(os.path.abspath(self.tmp)))
        finally:
            for name in ("fish.pdf", "lemon.pdf", "melon.pdf"):
                os.remove(os.path.join(self.tmp, name))

    def test_letters_in_lists_and_prompts(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="o")
        press(app, char="x")
        press(app, char="x")
        press(app, key="enter")
        self.assertEqual(app.viewer.page, 1)
        press(app, char="/")
        for c in "fixm":
            press(app, char=c)
        self.assertEqual(app.overlays[-1].text, "fixm", "prompts take letters as text")
        press(app, key="esc")

    def test_second_screen_gets_its_own_layout(self):
        from czpdf import ui
        ui.set_size(320, 240)                  # running on the EXT display
        try:
            app = App(self.pdf, state=self.state(), sync=True)
            v = app.viewer
            big = app.tick(force=True)
            small = app.render_at(320, 170)
            self.assertEqual(big.size, (320, 240))
            self.assertEqual(small.size, (320, 170))
            self.assertEqual((ui.W, ui.H), (320, 240), "size restored")
            # at the top of the page both screens start at the top
            self.assertEqual(big.crop((0, 0, 316, 100)).tobytes(),
                             small.crop((0, 0, 316, 100)).tobytes())
            # whole page: the built-in shows the full page, scaled to fit
            press(app, char="p")
            app.toast_msg = ""
            small = app.render_at(320, 170)
            self.assertLessEqual(v._fit_img.height, 170 - 13)
            # bottom of a page: both screens end at the same place
            press(app, char="w")
            for _ in range(60):
                if v.oy >= v.img.height - v.view_size()[1]:
                    break
                press(app, key="down")
            app.toast_msg = ""
            big = app.tick(force=True)
            small = app.render_at(320, 170)
            self.assertEqual(big.crop((0, 240 - 13 - 60, 316, 240 - 13)).tobytes(),
                             small.crop((0, 170 - 13 - 60, 316, 170 - 13)).tobytes())
            # browser and help draw at both sizes
            app.show_help()
            self.assertEqual(app.render_at(320, 170).size, (320, 170))
        finally:
            ui.set_size(320, 170)

    def test_zoom_modes_and_rotation(self):
        app = App(self.pdf, state=self.state(), sync=True)
        v = app.viewer
        w0 = v.img.width
        self.assertEqual(w0, 320)
        press(app, char="+")
        self.assertGreater(v.img.width, w0)
        press(app, char="p")
        self.assertEqual(v.mode, "page")
        self.assertLessEqual(v.img.height, v.view_size()[1])
        press(app, char="w")
        press(app, char="r")
        self.assertEqual(v.rot, 90)
        self.assertEqual(v.img.width, 320)
        self.assertLess(v.img.height, 320)

    def test_goto_prompt(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="4")
        press(app, key="enter")
        self.assertEqual(app.viewer.page, 3)
        press(app, char="g")
        press(app, char="9")
        press(app, char="9")
        press(app, key="enter")
        self.assertEqual(app.viewer.page, 5)

    def test_search_finds_and_highlights(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="/")
        for c in "Shift+N":
            press(app, char=c)
        press(app, key="enter")
        v = app.viewer
        self.assertEqual(v.page, 2, "first page with 'Shift+N' is section 3")
        self.assertTrue(v.hits)
        press(app, char="n")
        self.assertEqual(v.page, 2, "second match is on the same page")
        press(app, char="n")
        self.assertEqual(v.page, 2, "wraps around to the only page with matches")
        self.assertEqual(v.hit_idx, 0)
        # Esc clears the search instead of leaving
        press(app, key="esc")
        self.assertEqual(v.search_q, "")
        self.assertTrue(app.running)

    def test_search_not_found(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="/")
        for c in "zebra":
            press(app, char=c)
        press(app, key="enter")
        self.assertIn("not found", app.toast_msg)
        self.assertEqual(app.viewer.page, 0)

    def test_text_mode(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="t")
        v = app.viewer
        self.assertTrue(v.text_mode)
        lines = v._text_layout()
        self.assertTrue(any("Getting started" in ln for ln in lines))
        press(app, char="+")
        self.assertEqual(app.state["text_size"], 14)

    def test_outline(self):
        app = App(self.pdf, state=self.state(), sync=True)
        press(app, char="o")
        ov = app.overlays[-1]
        self.assertEqual(ov.items[0][1], 0)
        press(app, key="down")
        press(app, key="down")
        press(app, key="enter")
        self.assertEqual(app.viewer.page, 1)

    def test_position_remembered(self):
        st = self.state()
        app = App(self.pdf, state=st, sync=True)
        press(app, char="3")
        press(app, key="enter")
        press(app, char="+")
        app.shutdown()
        st2 = State.load(st.path)
        app2 = App(self.pdf, state=st2, sync=True)
        self.assertEqual(app2.viewer.page, 2)
        self.assertAlmostEqual(app2.viewer.zoom, 1.25)
        self.assertEqual(st2["recent"][0]["path"], os.path.abspath(self.pdf))

    def test_page_argument_wins(self):
        app = App(self.pdf, page=4, state=self.state(), sync=True)
        self.assertEqual(app.viewer.page, 4)

    def test_password(self):
        app = App(self.locked, state=self.state(), sync=True)
        self.assertIsNone(app.viewer)
        for c in "1234":
            press(app, char=c)
        press(app, key="enter")
        self.assertIsNotNone(app.viewer)
        self.assertEqual(app.viewer.pages, 6)

    def test_wrong_password_then_cancel_shows_folder(self):
        app = App(self.locked, state=self.state(), sync=True)
        press(app, char="0")
        press(app, key="enter")
        self.assertTrue(app.overlays, "asks again")
        press(app, key="esc")
        self.assertIsNone(app.viewer)
        self.assertIsNotNone(app.browser)
        self.assertEqual(app.browser.cwd, os.path.abspath(self.tmp))

    def test_broken_file(self):
        bad = os.path.join(self.tmp, "broken.pdf")
        with open(bad, "wb") as fh:
            fh.write(b"%PDF-1.4 garbage")
        app = App(bad, state=self.state(), sync=True)
        self.assertIsNone(app.viewer)
        self.assertIsNotNone(app.browser)
        self.assertTrue(app.toast_msg)

    def test_help_and_ext_size_render(self):
        app = App(self.pdf, state=self.state(), sync=True)
        app.handle_key(Key(True, key="help"))
        img = app.tick(force=True)
        self.assertEqual(img.size, (320, 170))
        self.assertTrue(app.overlays)
        press(app, key="esc")
        self.assertFalse(app.overlays)
        self.assertTrue(app.running)

    def test_mupdf_rect_mapping_matches_render(self):
        doc = pdf.open_document(self.pdf)
        img, scale = doc.render(0, 1.0, 90)
        rects = doc.map_rects(0, doc.search(0, "Getting started"), scale, 90)
        self.assertTrue(rects)
        for x0, y0, x1, y1 in rects:
            self.assertTrue(0 <= x0 < x1 <= img.width + 1)
            self.assertTrue(0 <= y0 < y1 <= img.height + 1)
        doc.close()


class PlainTests(unittest.TestCase):
    def test_cap_scale(self):
        s = pdf.cap_scale(10, 612, 792)
        self.assertLessEqual((612 * s) * (792 * s), pdf.MAX_PIXELS * 1.001)
        self.assertEqual(pdf.cap_scale(0.5, 612, 792), 0.5)

    def test_missing_file(self):
        with self.assertRaises(pdf.PdfError):
            pdf.open_document("/nope/missing.pdf")

    def test_wrap(self):
        from czpdf import ui
        lines = ui.wrap_lines("one two three four five six seven", ui.font("regular", 12), 60)
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines), "one two three four five six seven")

    def test_state_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            st = State(os.path.join(d, "s.json"))
            st.remember("/x/a.pdf", 10, page=3)
            st.save()
            st2 = State.load(st.path)
            self.assertEqual(st2.position("/x/a.pdf")["page"], 3)
            st2.forget("/x/a.pdf")
            self.assertEqual(st2["recent"], [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
