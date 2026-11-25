# Files app: open files with installed apps

`files-open-with-apps.patch` applies to [CardputerZero/Files](https://github.com/CardputerZero/Files) v1.0.3 (main, 2026-11-17).

Files has a fixed set of previewers (image, audio, video, text, info). This patch adds one more that hands a file to any installed APPLaunch app whose `.desktop` entry declares the type:

```
[Desktop Entry]
Name=PDF Viewer
Exec=bin/czpdf
MimeType=application/pdf;
```

- `MimeType=` is matched against a small table of document types (PDF, XPS, EPUB, FB2, MOBI, CBZ, DjVu, Office and OpenDocument files).
- `X-Files-Extensions=.pdf;.xps;` claims extensions directly, including ones Files previews itself.
- The file path is added after `Exec`, or put where `%f`/`%F`/`%u`/`%U` is. A relative `Exec` is resolved against `/usr/share/APPLaunch`, like the launcher does.
- While the app runs, Files stops drawing and ignores the keyboard. When it exits, Files redraws and is back on the file list where it was.
- The applications folder is read when a file is opened, so newly installed apps work without restarting Files. `FILES_APPLICATIONS_DIR` overrides the folder.

Changed files: `src/preview/external/external_preview.{hpp,cpp}` (new), `preview_support.{hpp,cpp}`, `view_model.hpp`, `preview_view_model.{hpp,cpp}`, `core/files_app.cpp`.

Apply and build:

```
git -C Files apply ../files-open-with-apps.patch
cd Files && ./bootstrap.sh && ./packaging/deb/package_deb.sh
```
