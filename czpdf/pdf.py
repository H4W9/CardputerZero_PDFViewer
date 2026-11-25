"""PDF backends.

MuPDF (python3-pymupdf) is used when it is installed: it is fast, renders in
process and gives the outline and text positions for search highlights.
Without it the poppler-utils tools (pdfinfo, pdftoppm, pdftotext) are used.

A document object is only ever touched from one thread (the app's worker).
"""

import io
import os
import re
import shutil
import subprocess

from PIL import Image

MAX_PIXELS = 4_500_000       # biggest page image we render (about 9 MB RGB)


class PdfError(Exception):
    pass


class NeedPassword(PdfError):
    pass


def _fitz():
    for name in ("pymupdf", "fitz"):
        try:
            mod = __import__(name)
        except ImportError:
            continue
        if hasattr(mod, "open") and hasattr(mod, "Matrix"):
            return mod
    return None


def _poppler_ok():
    return bool(shutil.which("pdftoppm") and shutil.which("pdfinfo"))


def backend_name():
    if _fitz() is not None:
        return "MuPDF"
    if _poppler_ok():
        return "Poppler"
    return None


def open_document(path, password=None):
    if not os.path.isfile(path):
        raise PdfError("File not found")
    fz = _fitz()
    if fz is not None:
        return MuDoc(fz, path, password)
    if _poppler_ok():
        return PopplerDoc(path, password)
    raise PdfError("No PDF renderer found. Install python3-pymupdf or poppler-utils.")


def cap_scale(scale, w, h):
    """Lower scale so a w x h (points) page stays under MAX_PIXELS."""
    if w <= 0 or h <= 0:
        return scale
    px = (w * scale) * (h * scale)
    if px > MAX_PIXELS:
        scale *= (MAX_PIXELS / px) ** 0.5
    return max(0.05, scale)


def rotated(w, h, rot):
    return (h, w) if rot % 180 else (w, h)


# ------------------------------------------------------------------ MuPDF --

class MuDoc:
    backend = "MuPDF"

    def __init__(self, fz, path, password=None):
        self.fz = fz
        self.path = path
        try:
            self.doc = fz.open(path)
        except Exception as e:  # noqa: BLE001 - MuPDF raises many types
            raise PdfError("Can't open: %s" % _short(e))
        if self.doc.needs_pass:
            if not password or not self.doc.authenticate(password):
                self.doc.close()
                raise NeedPassword("Password needed" if not password else "Wrong password")
        self.page_count = self.doc.page_count
        if self.page_count <= 0:
            self.doc.close()
            raise PdfError("The file has no pages")
        meta = self.doc.metadata or {}
        self.title = (meta.get("title") or "").strip()
        self.author = (meta.get("author") or "").strip()

    def page_size(self, i):
        r = self.doc[i].rect
        return r.width, r.height

    def render(self, i, scale, rot=0):
        page = self.doc[i]
        scale = cap_scale(scale, page.rect.width, page.rect.height)
        mat = self.fz.Matrix(scale, scale).prerotate(rot)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img, scale

    def text(self, i):
        """Page text, one paragraph (MuPDF block) per blank-line-separated chunk."""
        page = self.doc[i]
        try:
            blocks = page.get_text("blocks", sort=True)
        except Exception:  # noqa: BLE001
            return page.get_text("text")
        parts = [b[4].strip() for b in blocks if len(b) > 6 and b[6] == 0 and b[4].strip()]
        return "\n\n".join(parts)

    def search(self, i, needle):
        """Hit rectangles (page space) for needle on page i."""
        try:
            return [tuple(r) for r in self.doc[i].search_for(needle)]
        except Exception:  # noqa: BLE001
            return []

    def map_rects(self, i, rects, scale, rot):
        """Page-space rectangles -> pixel boxes in render(i, scale, rot)."""
        fz = self.fz
        page = self.doc[i]
        mat = fz.Matrix(scale, scale).prerotate(rot)
        box = page.rect * mat
        out = []
        for r in rects:
            if r is None:
                continue
            rr = fz.Rect(r) * page.rotation_matrix * mat
            out.append((rr.x0 - box.x0, rr.y0 - box.y0, rr.x1 - box.x0, rr.y1 - box.y0))
        return out

    def outline(self):
        out = []
        try:
            toc = self.doc.get_toc(simple=True)
        except Exception:  # noqa: BLE001
            return out
        for lvl, title, page in toc:
            if page >= 1:
                out.append((max(1, lvl), (title or "").strip() or "(untitled)", page - 1))
        return out

    def close(self):
        try:
            self.doc.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- Poppler --

_SIZE_RE = re.compile(r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", re.M)
_ROT_RE = re.compile(r"^Page\s+(\d+)\s+rot:\s+(\d+)", re.M)


class PopplerDoc:
    backend = "Poppler"

    def __init__(self, path, password=None):
        self.path = path
        self.pw = ["-upw", password] if password else []
        info = self._run(["pdfinfo"] + self.pw + [path], check=False)
        err = info.stderr.decode("utf-8", "replace")
        out = info.stdout.decode("utf-8", "replace")
        if info.returncode != 0:
            if "password" in err.lower():
                raise NeedPassword("Wrong password" if password else "Password needed")
            raise PdfError("Can't open: %s" % (err.strip().splitlines() or ["unknown error"])[-1])
        fields = {}
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields.setdefault(k.strip(), v.strip())
        try:
            self.page_count = int(fields.get("Pages", "0"))
        except ValueError:
            self.page_count = 0
        if self.page_count <= 0:
            raise PdfError("The file has no pages")
        self.title = fields.get("Title", "")
        self.author = fields.get("Author", "")
        self.sizes = {}
        size = fields.get("Page size", "")
        m = re.match(r"([\d.]+)\s+x\s+([\d.]+)", size)
        self.default_size = (float(m.group(1)), float(m.group(2))) if m else (612.0, 792.0)
        # Per-page sizes, read in one go (fast even for big files).
        big = self._run(["pdfinfo"] + self.pw + ["-f", "1", "-l", str(self.page_count), path],
                        check=False)
        text = big.stdout.decode("utf-8", "replace")
        rots = {int(n): int(r) for n, r in _ROT_RE.findall(text)}
        for n, w, h in _SIZE_RE.findall(text):
            w, h = float(w), float(h)
            self.sizes[int(n) - 1] = rotated(w, h, rots.get(int(n), 0))

    @staticmethod
    def _run(cmd, check=True, timeout=60):
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            raise PdfError("%s failed: %s" % (cmd[0], e))
        if check and r.returncode != 0:
            msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise PdfError("%s: %s" % (cmd[0], msg[-1] if msg else "error %d" % r.returncode))
        return r

    def page_size(self, i):
        return self.sizes.get(i, self.default_size)

    def render(self, i, scale, rot=0):
        w, h = self.page_size(i)
        scale = cap_scale(scale, w, h)
        dpi = "%.2f" % (scale * 72.0)
        r = self._run(["pdftoppm"] + self.pw + ["-f", str(i + 1), "-l", str(i + 1), "-r", dpi,
                                                "-png", "-singlefile", self.path, "-"])
        img = Image.open(io.BytesIO(r.stdout))
        img.load()
        img = img.convert("RGB")
        if rot:
            img = img.rotate(-rot, expand=True)
        return img, scale

    def text(self, i):
        r = self._run(["pdftotext"] + self.pw + ["-f", str(i + 1), "-l", str(i + 1),
                                                 "-layout", "-enc", "UTF-8", self.path, "-"],
                      check=False)
        return r.stdout.decode("utf-8", "replace").replace("\f", "")

    def search(self, i, needle):
        if not shutil.which("pdftotext"):
            return []
        n = " ".join(self.text(i).split()).lower().count(" ".join(needle.split()).lower())
        return [None] * n

    def map_rects(self, i, rects, scale, rot):
        return []

    def outline(self):
        return []

    def close(self):
        pass


def _short(e):
    s = str(e).strip() or e.__class__.__name__
    return s.splitlines()[0][:80]
