"""Keyboard input.

`Key` is the event type every backend produces. `EvdevKeyboard` reads the
Cardputer Zero's TCA8418 keypad (and any USB keyboard) straight from
/dev/input, with no python-evdev dependency. It follows the launcher's
keymap rule (cp0_keyboard_keymap.c): the custom codes in
/usr/share/keymaps/tca8418_keypad_m5stack_keymap.map come first, then the
standard US layout.
"""

import glob
import os
import select
import struct
import time


class Key:
    """One key event.

    down  - True on press/repeat, False on release
    key   - named key ('up','down','left','right','enter','esc','bs','del',
            'tab','home','end','pgup','pgdn') or None
    char  - printable text produced, or None
    ctrl  - Ctrl held
    """

    __slots__ = ("down", "key", "char", "ctrl", "repeat")

    def __init__(self, down, key=None, char=None, ctrl=False, repeat=False):
        self.down = down
        self.key = key
        self.char = char
        self.ctrl = ctrl
        self.repeat = repeat

    def __repr__(self):
        return "Key(%s, key=%r, char=%r, ctrl=%r)" % (
            "down" if self.down else "up", self.key, self.char, self.ctrl)


# ---------------------------------------------------------------- evdev ----

EV_KEY = 1
EVENT_FMT = "llHHi"  # struct input_event: timeval(2 x long), type, code, value
EVENT_SIZE = struct.calcsize(EVENT_FMT)

KEYPAD_PATH = "/dev/input/by-path/platform-3f804000.i2c-event"
KEYMAP_PATH = "/usr/share/keymaps/tca8418_keypad_m5stack_keymap.map"

KEY_LEFTSHIFT, KEY_RIGHTSHIFT = 42, 54
KEY_LEFTCTRL, KEY_RIGHTCTRL = 29, 97
KEY_CAPSLOCK = 58
KEY_FN = 0x1D0

REPEAT_DELAY = 0.5   # same timing as the launcher (cp0_keyboard_navigation_contract.h)
REPEAT_RATE = 0.05
REPEAT_KEYS = ("bs", "del", "left", "right", "up", "down", "pgup", "pgdn")

NAMED = {
    1: "esc", 14: "bs", 15: "tab", 28: "enter", 96: "enter", 59: "help",
    138: "help",  # KEY_HELP: the Cardputer Zero sends this for Fn+H
    102: "home", 103: "up", 104: "pgup", 105: "left", 106: "right",
    107: "end", 108: "down", 109: "pgdn", 111: "del",
}

_ROW_NUM = "1234567890"
_ROW_NUM_S = "!@#$%^&*()"
US = {}
for _i, _c in enumerate(_ROW_NUM):
    US[2 + _i] = (_c, _ROW_NUM_S[_i])
for _start, _row in ((16, "qwertyuiop"), (30, "asdfghjkl"), (44, "zxcvbnm")):
    for _i, _c in enumerate(_row):
        US[_start + _i] = (_c, _c.upper())
US.update({
    12: ("-", "_"), 13: ("=", "+"), 26: ("[", "{"), 27: ("]", "}"),
    39: (";", ":"), 40: ("'", '"'), 41: ("`", "~"), 43: ("\\", "|"),
    51: (",", "<"), 52: (".", ">"), 53: ("/", "?"), 57: (" ", " "),
})

# The launcher's built-in fallback table, used only if the keymap file is
# missing (same rule as cp0_keyboard_keymap_lookup()).
DEFAULT_CUSTOM = {
    26: "!", 27: "@", 39: "#", 40: "$", 41: "%", 43: "^", 51: "&", 52: "*",
    53: "(", 94: ")", 55: "~", 69: "`", 70: "_", 71: "-", 72: "+", 73: "=",
    74: "[", 75: "]", 76: "{", 77: "}", 79: ";", 80: ":", 81: "'", 82: '"',
    83: "<", 85: ">", 86: "\\", 89: "|", 90: ",", 91: ".", 92: "/", 93: "?",
}

# xkb keysym names -> text, for the keymap file.
SYM_CHARS = {
    "exclam": "!", "at": "@", "numbersign": "#", "dollar": "$",
    "percent": "%", "asciicircum": "^", "ampersand": "&", "asterisk": "*",
    "parenleft": "(", "parenright": ")", "asciitilde": "~", "grave": "`",
    "underscore": "_", "minus": "-", "plus": "+", "equal": "=",
    "bracketleft": "[", "bracketright": "]", "braceleft": "{",
    "braceright": "}", "semicolon": ";", "colon": ":", "apostrophe": "'",
    "quotedbl": '"', "less": "<", "greater": ">", "backslash": "\\",
    "bar": "|", "comma": ",", "period": ".", "slash": "/", "question": "?",
    "space": " ",
}
SYM_KEYS = {
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Escape": "esc", "BackSpace": "bs", "Tab": "tab", "Return": "enter",
    "KP_Enter": "enter", "Delete": "del", "Home": "home", "End": "end",
    "Prior": "pgup", "Page_Up": "pgup", "Next": "pgdn", "Page_Down": "pgdn",
}

# Fn + key -> navigation, a fallback in case the keypad sends no arrow codes.
# Only used if the keypad reports Fn as its own key. The Cardputer Zero driver
# normally handles Fn itself: Fn+F/X/Z/C arrive as arrow keys, Fn+H as KEY_HELP.
FN_NAV = {57: "mic", 35: "help"}  # Fn+Space dictate, Fn+H help


def load_custom_keymap(path=KEYMAP_PATH):
    """Parse 'keycode N = symname' lines. Returns {code: ('char'|'key', v)}."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return {k: ("char", v) for k, v in DEFAULT_CUSTOM.items()}
    out = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 4 or parts[0] != "keycode" or parts[2] != "=":
            continue
        try:
            code = int(parts[1])
        except ValueError:
            continue
        sym = parts[3]
        if sym in SYM_KEYS:
            out[code] = ("key", SYM_KEYS[sym])
        elif sym in SYM_CHARS:
            out[code] = ("char", SYM_CHARS[sym])
        elif len(sym) == 1:
            out[code] = ("char", sym)
    return out


class EvdevKeyboard:
    def __init__(self):
        self.fds = []
        paths = []
        if os.path.exists(KEYPAD_PATH):
            paths.append(os.path.realpath(KEYPAD_PATH))
        for p in sorted(glob.glob("/dev/input/event*")):
            if p not in paths:
                paths.append(p)
        for p in paths:
            try:
                self.fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.custom = load_custom_keymap()
        self.shift = self.ctrl = self.fn = self.caps = False
        self.rep = None             # (code, Key, next due time) for software repeat
        self.kernel_repeat = False
        # code -> Key produced at press time, so the release reports the same
        # key even if Fn/Shift were let go first (matters for long-Esc).
        self.pressed = {}

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []

    def poll(self, timeout=0.0):
        if not self.fds:
            if timeout:
                time.sleep(timeout)
            return []
        rep = getattr(self, "rep", None)
        if rep is not None and not self.kernel_repeat:
            timeout = max(0.0, min(timeout, rep[2] - time.monotonic()))
        try:
            ready, _, _ = select.select(self.fds, [], [], timeout)
        except (OSError, ValueError):
            return []
        events = []
        for fd in ready:
            try:
                data = os.read(fd, EVENT_SIZE * 64)
            except (BlockingIOError, OSError):
                continue
            for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, etype, code, value = struct.unpack_from(EVENT_FMT, data, off)
                if etype == EV_KEY:
                    ev = self._translate(code, value)
                    if ev is not None:
                        events.append(ev)
        events.extend(self._soft_repeat())
        return events

    def _soft_repeat(self, now=None):
        """The Cardputer Zero keypad sends no auto-repeat, so held keys are
        repeated here like the launcher does: 500 ms delay, then every 50 ms."""
        rep = getattr(self, "rep", None)
        if rep is None or getattr(self, "kernel_repeat", False):
            return []
        now = time.monotonic() if now is None else now
        code, ev, due = rep
        out = []
        while due <= now and len(out) < 4:
            out.append(Key(True, key=ev.key, char=ev.char, ctrl=ev.ctrl, repeat=True))
            due += REPEAT_RATE
        if due <= now:
            due = now + REPEAT_RATE
        self.rep = (code, ev, due)
        return out

    def keytest(self, seconds=30):
        """Print raw key events and what the app makes of them."""
        mods = {KEY_LEFTSHIFT: "LSHIFT", KEY_RIGHTSHIFT: "RSHIFT", KEY_LEFTCTRL: "LCTRL",
                KEY_RIGHTCTRL: "RCTRL", KEY_CAPSLOCK: "CAPS", KEY_FN: "FN", 56: "LALT",
                100: "RALT", 125: "META", 59: "F1"}

        class _Names(dict):
            def get(self, code, default="?"):
                if code in mods:
                    return mods[code]
                if code in NAMED:
                    return NAMED[code].upper()
                if code in US:
                    return repr(US[code][0])
                return default

        names = _Names()
        print("Reading %d input device(s). Press keys on the Cardputer (Fn+H, arrows...)."
              % len(self.fds))
        print("Stops after %d s or Ctrl+C here.\n" % seconds)
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select(self.fds, [], [], 0.2)
            for fd in ready:
                try:
                    data = os.read(fd, EVENT_SIZE * 64)
                except OSError:
                    continue
                for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    _, _, etype, code, value = struct.unpack_from(EVENT_FMT, data, off)
                    if etype != EV_KEY:
                        continue
                    ev = self._translate(code, value)
                    state = {0: "up", 1: "down", 2: "repeat"}.get(value, value)
                    print("code %3d %-14s %-6s fn=%d shift=%d ctrl=%d -> %s"
                          % (code, names.get(code, "?"), state, self.fn, self.shift,
                             self.ctrl, ev))

    def _translate(self, code, value):
        down = value != 0
        if code in (KEY_LEFTSHIFT, KEY_RIGHTSHIFT):
            self.shift = down
            return None
        if code in (KEY_LEFTCTRL, KEY_RIGHTCTRL):
            self.ctrl = down
            return None
        if code == KEY_FN:
            self.fn = down
            return None
        if code == KEY_CAPSLOCK:
            if value == 1:
                self.caps = not self.caps
            return None
        if not down:
            rep = getattr(self, "rep", None)
            if rep is not None and rep[0] == code:
                self.rep = None
            ev = self.pressed.pop(code, None)
            if ev is None:
                return None
            return Key(False, key=ev.key, char=ev.char, ctrl=ev.ctrl)
        if value == 2:
            self.kernel_repeat = True  # the kernel repeats after all: stop ours
        ev = self._map(code, value == 2)
        if ev is not None:
            self.pressed[code] = ev
            if value == 1:
                repeatable = (ev.char and not ev.ctrl) or ev.key in REPEAT_KEYS
                self.rep = (code, ev, time.monotonic() + REPEAT_DELAY) if repeatable else None
        return ev

    def _map(self, code, repeat):
        down = True
        if self.fn and code in FN_NAV:
            return Key(down, key=FN_NAV[code], ctrl=self.ctrl, repeat=repeat)
        m = self.custom.get(code)
        if m is not None:
            kind, v = m
            if kind == "key":
                return Key(down, key=v, ctrl=self.ctrl, repeat=repeat)
            return Key(down, char=v, ctrl=self.ctrl, repeat=repeat)
        if code in NAMED:
            return Key(down, key=NAMED[code], ctrl=self.ctrl, repeat=repeat)
        if code in US:
            lo, hi = US[code]
            upper = self.shift
            if lo.isalpha() and self.caps:
                upper = not upper
            return Key(down, char=hi if upper else lo, ctrl=self.ctrl, repeat=repeat)
        return None
