"""Visual language: the dark card look of the SwiftUI app, in Qt style sheets.

The SwiftUI window uses rounded cards on a dark background, a coloured dot per state and
monospaced secondary text. Qt can do all of that with a style sheet; keeping it in one module
means the two front ends stay recognisable as the same product.
"""
from __future__ import annotations

# The palette, taken from the SwiftUI app's screenshots.
BG = '#1c1f24'          # window background
CARD = '#252a31'        # a card's fill
CARD_EDGE = '#31373f'   # a card's hairline
TEXT = '#e6e9ed'
MUTED = '#8b949e'
GREEN = '#34c759'       # ok / done
ORANGE = '#ff9f0a'      # attention
RED = '#ff453a'         # missing / failed
ACCENT = '#0a84ff'      # buttons

STYLE = f"""
QMainWindow, QDialog, QScrollArea, QWidget#body {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-size: 9pt;   /* pt, not px: a handheld at 150% scaling keeps readable text and a window that fits */
}}
QLabel {{
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: {BG};
}}

/* ---- cards: a plain frame, the title is a label inside it ---- */
QFrame#card {{
    background: {CARD};
    border: 1px solid {CARD_EDGE};
    border-radius: 8px;
}}

/* ---- buttons ---- */
QPushButton {{
    background: #333a43;
    border: 1px solid #3d444d;
    border-radius: 6px;
    padding: 3px 10px;   /* compact: a 7-inch panel must fit the whole form */
    color: {TEXT};
}}
QPushButton:hover {{ background: #3c444e; }}
QPushButton:pressed {{ background: #2b3138; }}
QPushButton:disabled {{ color: #5c646e; background: #2a2f36; border-color: #333940; }}

QPushButton#primary {{
    background: {ACCENT};
    border: none;
    color: white;
    font-size: 10pt;
    font-weight: 600;
    padding: 6px 16px;
}}
QPushButton#primary:hover {{ background: #3a9bff; }}
QPushButton#primary:disabled {{ background: #2c3a4a; color: #6b7683; }}

QPushButton#danger {{
    background: {RED};
    border: none;
    color: white;
    font-size: 10pt;
    font-weight: 600;
    padding: 6px 16px;
}}

/* ---- labels ---- */
QLabel#title {{ font-size: 17pt; font-weight: 700; background: transparent; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 9pt; background: transparent; }}
QLabel#note {{ color: {MUTED}; font-size: 8pt; background: transparent; }}
QLabel#mono {{ color: {MUTED}; font-family: Menlo, Consolas, monospace; font-size: 8pt; background: transparent; }}
QLabel#ok {{ color: {GREEN}; font-weight: 600; background: transparent; }}
QLabel#warn {{ color: {ORANGE}; font-weight: 600; }}
QLabel#bad {{ color: {RED}; font-weight: 600; background: transparent; }}
QLabel#rowname {{ font-size: 10pt; background: transparent; }}
QLabel#footer {{ color: {MUTED}; font-size: 8pt; padding: 4px 2px; background: transparent; }}

/* ---- the log ---- */
QTextEdit {{
    background: #14171b;
    border: 1px solid {CARD_EDGE};
    border-radius: 8px;
    padding: 8px;
    color: #b9c2cc;
    font-family: Menlo, Consolas, monospace;
    font-size: 8pt;
}}

/* ---- progress ---- */
QProgressBar {{
    background: #2a2f36;
    border: none;
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {GREEN};
    border-radius: 4px;
}}

/* ---- scrollbars ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #3d444d;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a525c; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ---- dialogs inherit the dark look ---- */
QFileDialog, QMessageBox {{ background: {BG}; }}
QLineEdit, QComboBox {{
    background: #2a2f36;
    border: 1px solid {CARD_EDGE};
    border-radius: 6px;
    padding: 5px 8px;
    color: {TEXT};
}}
"""
