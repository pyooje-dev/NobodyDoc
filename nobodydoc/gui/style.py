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
QTabWidget::tab-bar {{
    left: 12px;
}}
QTabBar {{
    background: {SURFACE};
}}
QTabBar::tab {{
    background: {SURFACE};
    color: {MUTED};
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 20px;
    margin-right: 4px;
    font-size: 10.5pt;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background: #eef1f6;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 3px solid {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: #dce6fd;
    selection-color: {TEXT};
    outline: none;
    padding: 2px;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #dce6fd;
}}
QToolTip {{
    background: {TEXT};
    color: white;
    border: none;
    padding: 5px 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #c3cad6;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #a3acbb;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #c3cad6;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
    width: 0;
    height: 0;
}}
QScrollArea#help {{
    background: {BACKGROUND};
    border: none;
}}
QWidget#helpContent {{
    background: {BACKGROUND};
}}
QLabel#helpTitle {{
    font-size: 12.5pt;
    font-weight: 600;
    color: {ACCENT};
}}
QLabel#helpBody {{
    font-size: 10.5pt;
}}
"""


def apply(app) -> None:
    """Thème clair imposé : sinon le mode sombre de Windows rend certains éléments
    (onglets, listes déroulantes, barres de défilement) illisibles."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:  # Qt < 6.8
        pass
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.Window: BACKGROUND, QPalette.WindowText: TEXT, QPalette.Base: SURFACE,
        QPalette.AlternateBase: "#f7f8fb", QPalette.Text: TEXT, QPalette.Button: SURFACE,
        QPalette.ButtonText: TEXT, QPalette.ToolTipBase: TEXT, QPalette.ToolTipText: "#ffffff",
        QPalette.Highlight: "#dce6fd", QPalette.HighlightedText: TEXT, QPalette.Link: ACCENT,
        QPalette.PlaceholderText: "#8a93a3", QPalette.BrightText: "#ffffff",
        QPalette.Light: "#ffffff", QPalette.Midlight: "#eef1f6", QPalette.Mid: BORDER,
        QPalette.Dark: "#a0a7b4", QPalette.Shadow: "#6b7280",
    }
    for role, color in colors.items():
        palette.setColor(QPalette.All, role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#a0a7b4"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
