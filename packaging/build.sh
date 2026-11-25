#!/usr/bin/env bash
# Pure Python: just make sure every module compiles.
set -euo pipefail
python3 -m py_compile czpdf/*.py
