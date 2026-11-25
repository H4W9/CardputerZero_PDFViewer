"""Settings, recent files and the last position in each document.

Stored in ~/.config/czpdf/state.json (APPLaunch runs apps as root, so on the
device that is /root/.config/czpdf/state.json).
"""

import json
import os
import time

MAX_RECENT = 40

DEFAULTS = {
    "last_dir": "",
    "invert": False,
    "show_bar": True,
    "text_size": 13,
    "show_hidden": False,
    "screen": "auto",          # auto | builtin
    "recent": [],              # [{"path", "page", "pages", "t"}], newest first
    "files": {},               # path -> {"page", "mode", "zoom", "rot", "text", "fy"}
}


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "czpdf")


def state_path():
    return os.environ.get("CZPDF_STATE") or os.path.join(config_dir(), "state.json")


class State(dict):
    def __init__(self, path=None):
        super().__init__()
        self.path = path or state_path()
        for k, v in DEFAULTS.items():
            self[k] = json.loads(json.dumps(v))

    @classmethod
    def load(cls, path=None):
        st = cls(path)
        try:
            with open(st.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data and isinstance(data[k], type(DEFAULTS[k])):
                        st[k] = data[k]
        except (OSError, ValueError):
            pass
        return st

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---- per document

    def position(self, path):
        p = self["files"].get(os.path.abspath(path))
        return dict(p) if isinstance(p, dict) else {}

    def remember(self, path, pages, **pos):
        path = os.path.abspath(path)
        self["files"][path] = pos
        rec = [r for r in self["recent"] if isinstance(r, dict) and r.get("path") != path]
        rec.insert(0, {"path": path, "page": pos.get("page", 0), "pages": pages,
                       "t": int(time.time())})
        del rec[MAX_RECENT:]
        self["recent"] = rec
        keep = {r["path"] for r in rec}
        for k in list(self["files"]):
            if k not in keep:
                del self["files"][k]

    def forget(self, path):
        path = os.path.abspath(path)
        self["recent"] = [r for r in self["recent"] if r.get("path") != path]
        self["files"].pop(path, None)
