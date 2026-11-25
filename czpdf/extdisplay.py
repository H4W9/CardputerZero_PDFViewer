"""Use the DisplayMOD EXT display (2.8" ILI9341, 320x240) when it's connected.

DisplayMOD brings the panel up as an fbtft framebuffer named "...ili9341" in
/proc/fb and mirrors the built-in screen onto it. While PDF Viewer draws there,
we ask DisplayMOD to pause the mirror, the same way its own settings app does:

  - DisplayMOD 3.x: /usr/lib/displaymod/displaymod-send ui on PID / ui off
    (the service also resumes the mirror by itself if our PID goes away)
  - DisplayMOD 2.x: flag file /run/user/UID/displaymod-ui holding our PID,
    the mirror answers with /run/user/UID/displaymod-ui-ack

No ui import here: this runs before the screen size is chosen.
"""

import glob
import os
import subprocess
import time

SEND = "/usr/lib/displaymod/displaymod-send"
EXT_W, EXT_H = 320, 240

_legacy_flags = []


def find_ext_fb(proc="/proc/fb"):
    """Path of the EXT display framebuffer, or None if it isn't up."""
    try:
        with open(proc) as fh:
            lines = fh.readlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2 and "ili9341" in parts[1].lower():
            path = "/dev/fb" + parts[0]
            if os.access(path, os.R_OK | os.W_OK):
                return path
    return None


def claim():
    """Pause the DisplayMOD mirror while we draw on the EXT display."""
    pid = str(os.getpid())
    if os.access(SEND, os.X_OK):
        try:
            subprocess.run([SEND, "ui", "on", pid], timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
        return
    # DisplayMOD 2.x: the mirror runs as the launcher user
    dirs = ["/run/user/%d" % os.getuid()]
    if os.getuid() == 0:
        dirs = sorted(glob.glob("/run/user/[0-9]*"))
    acks = []
    for d in dirs:
        flag = os.path.join(d, "displaymod-ui")
        try:
            with open(flag, "w") as fh:
                fh.write(pid + "\n")
            _legacy_flags.append(flag)
            acks.append(flag + "-ack")
        except OSError:
            continue
    end = time.time() + 2.0
    while acks and time.time() < end and not any(os.path.exists(a) for a in acks):
        time.sleep(0.1)


def release():
    """Let the mirror take the EXT display back."""
    if os.access(SEND, os.X_OK):
        try:
            subprocess.run([SEND, "ui", "off"], timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
    while _legacy_flags:
        try:
            os.unlink(_legacy_flags.pop())
        except OSError:
            pass


def choose(pref):
    """EXT framebuffer path to use, or None for the built-in screen.

    pref: "auto" (default) or "builtin"; CZPDF_SCREEN overrides it.
    """
    pref = (os.environ.get("CZPDF_SCREEN") or pref or "auto").lower()
    if pref == "builtin":
        return None
    return find_ext_fb()
