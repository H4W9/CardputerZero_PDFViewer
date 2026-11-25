#!/usr/bin/env python3
"""Package a patched Files build like CardputerZero/Files packaging/deb/package_deb.sh,
without dpkg-deb (works on Windows).

    python files-integration/pack_files_deb.py <Files checkout> [version]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from build_deb import _ar, _targz  # noqa: E402

PREFIX = "usr/share/APPLaunch"


def main():
    src = sys.argv[1]
    version = sys.argv[2] if len(sys.argv) > 2 else "1.0.3+openwith1"
    rd = lambda p: open(os.path.join(src, p), "rb").read()  # noqa: E731
    mtime = int(time.time())
    files = [
        ("./%s/bin/M5CardputerZero-Files" % PREFIX, rd("dist/M5CardputerZero-Files"), 0o755),
        ("./%s/applications/files.desktop" % PREFIX,
         rd("packaging/deb/files.desktop.in").replace(b"\r\n", b"\n"), 0o644),
        ("./%s/share/images/files.png" % PREFIX, rd("packaging/deb/images/files.png"), 0o644),
    ]
    dirs = [("./" + d + "/", None, 0o755) for d in
            ("usr", "usr/share", PREFIX, PREFIX + "/bin", PREFIX + "/applications",
             PREFIX + "/share", PREFIX + "/share/images")]
    data = _targz([("./", None, 0o755)] + dirs + files, mtime)
    control = "\n".join([
        "Package: m5cardputerzero-files",
        "Version: %s" % version,
        "Section: utils",
        "Priority: optional",
        "Architecture: arm64",
        "Maintainer: H4W9 <H4W9@users.noreply.github.com>",
        "Depends: libc6, ffmpeg",
        "Installed-Size: %d" % (sum(len(d) for _, d, _ in files) // 1024),
        "Description: Files application for M5CardputerZero APPLaunch",
        " Files application and launcher entry. Opens files with installed apps",
        " that declare the type (MimeType= in their .desktop entry).",
    ]) + "\n"
    ctl = _targz([("./", None, 0o755), ("./control", control.encode(), 0o644)], mtime)
    deb = _ar([("debian-binary", b"2.0\n"), ("control.tar.gz", ctl), ("data.tar.gz", data)], mtime)
    out = os.path.join(os.path.dirname(HERE), "dist",
                       "m5cardputerzero-files_%s_arm64.deb" % version)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(deb)
    print(out)


if __name__ == "__main__":
    main()
