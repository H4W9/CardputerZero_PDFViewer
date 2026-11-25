"""Entry point: python3 -m czpdf [FILE.pdf] [--page N] [--window] [--ext]"""

import argparse
import os
import sys

from . import __version__


def main(argv=None):
    p = argparse.ArgumentParser(prog="czpdf", description="PDF Viewer for the Cardputer Zero")
    p.add_argument("file", nargs="?", help="PDF to open (the Files app passes one)")
    p.add_argument("--page", type=int, help="page to open at (1 = first)")
    p.add_argument("--dir", help="folder to start the file browser in")
    p.add_argument("--window", action="store_true", help="force the desktop preview window")
    p.add_argument("--scale", type=int, default=3, help="desktop window zoom (default 3)")
    p.add_argument("--ext", action="store_true",
                   help="use the 320x240 EXT display layout (desktop preview, screenshots)")
    p.add_argument("--screenshots", metavar="DIR", help="render store screenshots and exit")
    p.add_argument("--keytest", action="store_true",
                   help="print what the keyboard sends (run over SSH, press keys on the device)")
    p.add_argument("--check", action="store_true", help="print the PDF renderer in use and exit")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    from . import ui
    ext_path = None
    if args.ext:
        ui.set_size(320, 240)
    elif not args.window and not args.screenshots:
        from . import extdisplay
        from .state import State
        ext_path = extdisplay.choose(State.load().get("screen", "auto"))
        if ext_path:
            ui.set_size(extdisplay.EXT_W, extdisplay.EXT_H)

    if args.check:
        from . import pdf
        print("PDF renderer:", pdf.backend_name() or "none (install python3-pymupdf or poppler-utils)")
        return 0 if pdf.backend_name() else 1

    if args.keytest:
        from .keyboard import EvdevKeyboard
        kb = EvdevKeyboard()
        try:
            kb.keytest()
        except KeyboardInterrupt:
            pass
        finally:
            kb.close()
        return 0

    if args.screenshots:
        from .demo import screenshots
        for path in screenshots(args.screenshots):
            print(path)
        return 0

    path = args.file
    if path and path.startswith("file://"):
        from urllib.parse import unquote
        path = unquote(path[7:])
    if path and os.path.isdir(path):
        args.dir, path = path, None

    from .app import App
    app = App(path, page=(args.page - 1) if args.page else None, start_dir=args.dir)

    from .display import device_available, run_desktop, run_device
    try:
        if args.window or not device_available():
            run_desktop(app, scale=args.scale)
        else:
            run_device(app, ext_path=ext_path)
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
