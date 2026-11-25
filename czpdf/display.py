"""Output backends: the Cardputer Zero framebuffer, a desktop Tk window,
and an offscreen backend for screenshots/tests."""

import os
import struct
import sys
import time

from PIL import Image, ImageChops

from . import ui
from .keyboard import Key

try:
    import numpy as np
except ImportError:  # optional, faster RGB565 packing
    np = None

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602

_HI_R = [v & 0xF8 for v in range(256)]
_HI_G = [v >> 5 for v in range(256)]
_LO_G = [(v << 3) & 0xE0 for v in range(256)]
_LO_B = [v >> 3 for v in range(256)]


def to_rgb565(img):
    """RGB image -> little-endian RGB565 bytes."""
    if np is not None:
        a = np.asarray(img, dtype=np.uint16)
        v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
        return v.astype("<u2").tobytes()
    r, g, b = img.split()
    hi = ImageChops.add(r.point(_HI_R), g.point(_HI_G))
    lo = ImageChops.add(g.point(_LO_G), b.point(_LO_B))
    return Image.merge("LA", (lo, hi)).tobytes()


def find_fb_device():
    for var in ("LV_LINUX_FBDEV_DEVICE", "APPLAUNCH_LINUX_FBDEV_DEVICE", "CZPDF_FB"):
        v = os.environ.get(var)
        if v:
            return v
    try:
        with open("/proc/fb") as fh:
            for line in fh:
                parts = line.split(None, 1)
                if len(parts) == 2 and "st7789" in parts[1].lower():
                    return "/dev/fb" + parts[0]
    except OSError:
        pass
    for p in ("/dev/fb1", "/dev/fb0"):
        if os.path.exists(p):
            return p
    return None


class FramebufferDisplay:
    def __init__(self, path=None):
        import fcntl
        import mmap

        self.path = path or find_fb_device()
        if not self.path:
            raise OSError("no framebuffer device found")
        self.fd = os.open(self.path, os.O_RDWR)
        var = bytearray(160)
        fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, var)
        self.xres, self.yres, _, _, _, _, self.bpp = struct.unpack_from("7I", var, 0)
        fix = bytearray(128)
        fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, fix)
        # struct fb_fix_screeninfo: id[16], unsigned long smem_start,
        # u32 smem_len,type,type_aux,visual; u16 xpan,ypan,ywrap; u32 line_length
        fields = struct.unpack_from("16sL4I3H2xI", fix, 0)
        smem_len, self.line_length = fields[2], fields[9]
        if not self.line_length:
            self.line_length = self.xres * self.bpp // 8
        size = min(smem_len or self.line_length * self.yres, self.line_length * self.yres)
        self.mm = mmap.mmap(self.fd, size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        self.w, self.h = self.xres, self.yres

    def show(self, img):
        # A portrait panel (EXT display with ROTATE 0/180) gets the frame turned.
        if self.w < self.h and img.width > img.height:
            img = img.transpose(Image.ROTATE_270)
        if img.size != (self.w, self.h):
            canvas = Image.new("RGB", (self.w, self.h), (0, 0, 0))
            canvas.paste(img.crop((0, 0, min(img.width, self.w), min(img.height, self.h))), (0, 0))
            img = canvas
        if self.bpp == 16:
            data = to_rgb565(img)
            bpp = 2
        else:
            data = img.convert("RGB").tobytes("raw", "BGRX")
            bpp = 4
        row = self.w * bpp
        if self.line_length == row and self.w == self.xres:
            self.mm.seek(0)
            self.mm.write(data)
        else:
            for y in range(self.h):
                self.mm.seek(y * self.line_length)
                self.mm.write(data[y * row:(y + 1) * row])

    def clear(self):
        try:
            self.show(Image.new("RGB", (self.w, self.h), (0, 0, 0)))
        except Exception:
            pass

    def close(self, clear=True):
        if clear:
            self.clear()
        try:
            self.mm.close()
            os.close(self.fd)
        except Exception:
            pass


def run_device(app, fps_idle=0.05, ext_path=None):
    """Main loop for the real device: framebuffer + evdev.

    With ext_path the app is drawn full size on the DisplayMOD EXT display
    and again at 320x170 on the built-in screen.
    """
    import signal

    from . import extdisplay
    from .keyboard import EvdevKeyboard

    builtin = ext = None
    if ext_path:
        ext = FramebufferDisplay(ext_path)
        try:
            builtin = FramebufferDisplay()
        except OSError:
            builtin = None
        extdisplay.claim()
        main = ext
    else:
        main = FramebufferDisplay()
    kbd = EvdevKeyboard()

    def _stop(_sig, _frm):
        app.running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        while app.running:
            for ev in kbd.poll(fps_idle):
                app.handle_key(ev)
            frame = app.tick()
            if frame is not None:
                main.show(frame)
                if builtin is not None:
                    # The built-in screen gets its own full-size layout, not a
                    # shrunken copy of the EXT frame.
                    bw, bh = max(builtin.w, builtin.h), min(builtin.w, builtin.h)
                    builtin.show(app.render_at(bw, bh))
    finally:
        kbd.close()
        if ext is not None:
            ext.close(clear=False)      # the DisplayMOD mirror repaints it
            extdisplay.release()
            if builtin is not None:
                builtin.close()
        else:
            main.close()


# ---------------------------------------------------------------- desktop --

_TK_KEYS = {
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Return": "enter", "KP_Enter": "enter", "Escape": "esc",
    "BackSpace": "bs", "Delete": "del", "Tab": "tab", "ISO_Left_Tab": "tab",
    "Home": "home", "End": "end", "Prior": "pgup", "Next": "pgdn", "F1": "help",
}


def run_desktop(app, scale=3):
    W, H = ui.W, ui.H
    """Preview in a desktop window (Windows/macOS/Linux) with Tk."""
    import tkinter as tk

    from PIL import ImageTk

    root = tk.Tk()
    root.title("PDF Viewer - Cardputer Zero preview")
    root.resizable(False, False)
    label = tk.Label(root, bd=0, bg="black")
    label.pack()
    held = set()
    state = {"photo": None}

    def on_press(e):
        ctrl = bool(e.state & 0x4)
        repeat = e.keysym in held
        held.add(e.keysym)
        if e.keysym in _TK_KEYS:
            app.handle_key(Key(True, key=_TK_KEYS[e.keysym], ctrl=ctrl, repeat=repeat))
        elif ctrl and e.keysym == "space":
            app.handle_key(Key(True, char=" ", ctrl=True, repeat=repeat))
        elif ctrl and len(e.keysym) == 1:
            app.handle_key(Key(True, char=e.keysym.lower(), ctrl=True, repeat=repeat))
        elif e.char and e.char.isprintable():
            app.handle_key(Key(True, char=e.char, repeat=repeat))

    def on_release(e):
        held.discard(e.keysym)
        if e.keysym in _TK_KEYS:
            app.handle_key(Key(False, key=_TK_KEYS[e.keysym]))

    root.bind("<KeyPress>", on_press)
    root.bind("<KeyRelease>", on_release)
    root.protocol("WM_DELETE_WINDOW", lambda: setattr(app, "running", False))

    def loop():
        if not app.running:
            root.destroy()
            return
        frame = app.tick()
        if frame is not None:
            big = frame.resize((W * scale, H * scale), Image.NEAREST)
            state["photo"] = ImageTk.PhotoImage(big)
            label.configure(image=state["photo"])
        root.after(30, loop)

    loop()
    root.mainloop()


def device_available():
    return sys.platform.startswith("linux") and find_fb_device() is not None


def pump(app, seconds=0.0):
    """Offscreen: run ticks for a while (lets worker jobs finish)."""
    end = time.time() + seconds
    frame = app.tick(force=True)
    while time.time() < end:
        time.sleep(0.02)
        f = app.tick()
        if f is not None:
            frame = f
    return app.tick(force=True) or frame
