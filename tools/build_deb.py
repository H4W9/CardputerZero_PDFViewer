#!/usr/bin/env python3
"""Build the APPLaunch .deb without dpkg-deb, so it works on Windows/macOS too.

    python tools/build_deb.py            -> dist/czpdf_<ver>-<rev>_all.deb

Produces the same layout as AppBuilder's scripts/pack-deb.sh (which also
works with this repo: it reads packaging/meta.env, build.sh and stage.sh).
"""

import gzip
import io
import os
import shlex
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "usr/share/APPLaunch"


def read_env(path):
    env = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            parts = shlex.split(v)
            env[k.strip()] = parts[0] if parts else ""
    return env


def _tar_add(tar, name, data, mode, mtime):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mode = mode
    ti.mtime = mtime
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    tar.addfile(ti, io.BytesIO(data))


def _tar_dir(tar, name, mtime):
    ti = tarfile.TarInfo(name)
    ti.type = tarfile.DIRTYPE
    ti.mode = 0o755
    ti.mtime = mtime
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    tar.addfile(ti)


def _targz(entries, mtime):
    """entries: list of (path, bytes|None, mode). None = directory."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path, data, mode in entries:
            if data is None:
                _tar_dir(tar, path, mtime)
            else:
                _tar_add(tar, path, data, mode, mtime)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=mtime) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _ar(members, mtime):
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        hdr = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, mtime, 0, 0, "100644", len(data))
        out.write(hdr.encode("ascii"))
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def read(rel):
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read()


def lf(data):
    return data.replace(b"\r\n", b"\n")


def main():
    meta = read_env(os.path.join(ROOT, "packaging", "meta.env"))
    pkg, ver = meta["PKG_NAME"], meta["PKG_VERSION"]
    rev = meta.get("PKG_REVISION", "m5stack1")
    arch = meta.get("PKG_ARCH", "all")
    mtime = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))

    # Make sure the code compiles before packaging it.
    src_dir = os.path.join(ROOT, "czpdf")
    sources = sorted(f for f in os.listdir(src_dir) if f.endswith(".py"))
    for f in sources:
        path = os.path.join(src_dir, f)
        with open(path, "rb") as fh:
            compile(fh.read(), path, "exec")   # syntax check only, nothing written

    app_dir = "%s/apps/%s" % (PREFIX, pkg)
    desktop = (
        "[Desktop Entry]\nName=%s\nExec=%s\nTerminal=%s\nIcon=%s\nType=Application\n"
        % (meta["APP_NAME"], meta["APP_EXEC"], meta.get("APP_TERMINAL", "false"),
           meta["APP_ICON"]))
    if meta.get("APP_MIMETYPE"):
        # Lets the Files app open these types with this app (see files-integration/).
        desktop += "MimeType=%s\n" % meta["APP_MIMETYPE"]
    desktop = desktop.encode()

    dirs = []
    for d in ("usr", "usr/share", PREFIX, PREFIX + "/applications", PREFIX + "/bin",
              PREFIX + "/share", PREFIX + "/share/images", PREFIX + "/apps",
              app_dir, app_dir + "/czpdf"):
        dirs.append(("./" + d + "/", None, 0o755))
    files = [
        ("./%s/applications/%s.desktop" % (PREFIX, pkg), desktop, 0o644),
        ("./%s/bin/%s" % (PREFIX, pkg), lf(read("packaging/run-czpdf")), 0o755),
        ("./%s/%s" % (PREFIX, meta["APP_ICON"]), read("packaging/icon.png"), 0o644),
    ]
    for f in sources:
        files.append(("./%s/czpdf/%s" % (app_dir, f), lf(read("czpdf/" + f)), 0o644))
    data_tgz = _targz([("./", None, 0o755)] + dirs + files, mtime)

    installed_kb = max(1, sum(len(d) for _, d, _ in files) // 1024)
    control = [
        "Package: %s" % pkg,
        "Version: %s" % ver,
        "Architecture: %s" % arch,
        "Maintainer: %s" % meta.get("PKG_MAINTAINER", "TODO <todo@example.com>"),
        "Section: APPLaunch",
        "Priority: optional",
        "Installed-Size: %d" % installed_kb,
        "Homepage: %s" % meta.get("PKG_HOMEPAGE", "https://cardputerzero.github.io"),
    ]
    if meta.get("PKG_DEPENDS"):
        control.append("Depends: %s" % meta["PKG_DEPENDS"])
    if meta.get("PKG_RECOMMENDS"):
        control.append("Recommends: %s" % meta["PKG_RECOMMENDS"])
    control.append("Description: %s" % meta["PKG_DESC"])
    ctl = [("./", None, 0o755), ("./control", ("\n".join(control) + "\n").encode(), 0o644)]
    for hook in ("postinst", "prerm", "postrm", "preinst"):
        p = os.path.join(ROOT, "packaging", hook)
        if os.path.exists(p):
            ctl.append(("./" + hook, lf(read("packaging/" + hook)), 0o755))
    control_tgz = _targz(ctl, mtime)

    deb = _ar([("debian-binary", b"2.0\n"), ("control.tar.gz", control_tgz),
               ("data.tar.gz", data_tgz)], mtime)
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s_%s-%s_%s.deb" % (pkg, ver, rev, arch))
    with open(out, "wb") as fh:
        fh.write(deb)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
