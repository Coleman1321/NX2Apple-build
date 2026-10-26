"""Entry point: python3 -m nspb_qt  (or run main.py)."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .model import Model
from .style import STYLE
from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('NS Port Builder')
    app.setApplicationDisplayName('NS Port Builder')
    app.setStyleSheet(STYLE)
    app.setStyle('Fusion')   # the same widget look on Windows and macOS
    model = Model()
    win = MainWindow(model)
    win.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
