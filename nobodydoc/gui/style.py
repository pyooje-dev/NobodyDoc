"""Apparence : sobre, lisible, grands boutons."""

ACCENT = "#2457d6"
ACCENT_HOVER = "#1c46ad"
TEXT = "#1d2433"
MUTED = "#5d6678"
BORDER = "#d5dae3"
SURFACE = "#ffffff"
BACKGROUND = "#f4f6fa"
WARNING = "#a15c00"
ERROR = "#b3261e"
SUCCESS = "#1e7d45"

STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QDialog, QStackedWidget > QWidget {{
    background: {BACKGROUND};
}}
QLabel#title {{
    font-size: 17pt;
    font-weight: 600;
}}
QLabel#subtitle, QLabel.muted {{
    color: {MUTED};
}}
QLabel#sectionTitle {{
    font-size: 11pt;
    font-weight: 600;
}}
QFrame#dropZone {{
    background: {SURFACE};
    border: 2px dashed #9fb0d4;
    border-radius: 12px;
}}
QFrame#dropZone[hover="true"] {{
    background: #eaf0fe;
    border-color: {ACCENT};
}}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{
    background: #eef1f6;
}}
QPushButton:disabled {{
    color: #a0a7b4;
}}
QPushButton#primary {{
    background: {ACCENT};
    color: white;
    border: none;
    font-weight: 600;
    padding: 10px 22px;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#primary:disabled {{
    background: #a9b8de;
    color: #eef1f8;
}}
QPushButton#link {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 2px 4px;
    text-align: left;
}}
QPushButton#link:hover {{
    text-decoration: underline;
}}
QListWidget, QTableWidget, QLineEdit, QComboBox, QPlainTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLineEdit, QComboBox {{
    padding: 5px 8px;
}}
QListWidget::item {{
    padding: 5px;
}}
QTableWidget {{
    gridline-color: #eceff4;
    selection-background-color: #dce6fd;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: #eef1f6;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-weight: 600;
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {SURFACE};
    height: 14px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {SURFACE};
}}
QTabBar::tab {{
    padding: 9px 18px;
    font-size: 10.5pt;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 2px solid {ACCENT};
}}
"""
