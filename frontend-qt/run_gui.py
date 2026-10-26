"""Entry point for the packaged build (PyInstaller uses this, not -m nspb_qt).

Kept as a plain script so a frozen executable has a real __main__ to start from: the package
form (-m) works for development, this for the .exe / .app.
"""
from __future__ import annotations

import os
import sys

# A frozen build puts the package next to the executable; a source run has it on the path.
if getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(sys.executable))

from nspb_qt.__main__ import main   # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
