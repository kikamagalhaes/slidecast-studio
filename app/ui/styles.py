"""SlideCast Studio design system — KikaMeet visual identity (light).

Tokens are plain Python constants so views/dialogs can reuse the same
colors in inline styles instead of hard-coding hex values. The QSS below
covers every widget family used by the app; keep new colors here first.
"""

# --- Design tokens ---------------------------------------------------------
COLORS = {
    "bg": "#F3EEE2", "surface": "#FFFDF7", "surface_alt": "#EFE7D3",
    "border": "#D8CDB2", "border_strong": "#7D8F88",
    "text": "#1B2A28", "text_secondary": "#43564F", "text_muted": "#5C6F68",
    "primary": "#0E4A4A", "primary_hover": "#0A3838", "primary_pressed": "#0A3838",
    "primary_soft": "#E3EBDD", "teal": "#0E4A4A", "violet": "#C05F33",
    "success": "#1F7A3A", "success_soft": "#E3EBDD",
    "warning": "#96431E", "warning_soft": "#FFF3D6",
    "danger": "#B42318", "danger_hover": "#7A1F16", "danger_soft": "#FDECEC",
    "stage": "#10201E", "focus": "#B98A2F", "gold": "#B98A2F",
    "terra": "#C05F33", "sage": "#6E8F67",
}
FONT_FAMILY = '"Segoe UI", "Inter", "Cantarell", "Noto Sans", sans-serif'
RADIUS = {"sm": 6, "md": 8, "lg": 12, "xl": 16}

LIGHT_THEME_QSS = """
QMainWindow, QWidget#centralWidget {
    background-color: #F3EEE2;
    color: #1B2A28;
    font-family: "Segoe UI", "Inter", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
}
QWidget { color: #1B2A28; }

/* Dialogs */
QDialog, QMessageBox, QInputDialog, QFileDialog {
    background-color: #FFFDF7;
    color: #1B2A28;
    font-family: "Segoe UI", "Inter", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
}
QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel, QFileDialog QLabel {
    background-color: transparent;
    color: #1B2A28;
    font-size: 13px;
    font-weight: 500;
}
QDialog QLineEdit, QMessageBox QLineEdit, QInputDialog QLineEdit, QDialog QTextEdit {
    background-color: #ffffff;
    color: #1B2A28;
    border: 1.5px solid #7D8F88;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #E3EBDD;
}
QDialog QLineEdit:focus, QInputDialog QLineEdit:focus { border-color: #0E4A4A; }
QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
    background-color: #FFFDF7;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    min-width: 80px;
}
QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
    background-color: #EFE7D3;
    border-color: #0E4A4A;
}
QDialog QPushButton:focus, QMessageBox QPushButton:focus, QInputDialog QPushButton:focus,
QPushButton:focus, QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1.5px solid #B98A2F;
    outline: none;
}

/* Scrollbars */
QScrollArea { border: none; background-color: transparent; }
QScrollBar:horizontal { border: none; background: #EFE7D3; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #7D8F88; min-width: 20px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #7D8F88; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar:vertical { border: none; background: #EFE7D3; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #7D8F88; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #7D8F88; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

/* Cards and home menu */
QFrame.card {
    background-color: #FFFDF7;
    border: 1px solid #D8CDB2;
    border-radius: 12px;
    padding: 16px;
}
QFrame.card:hover { border-color: #7D8F88; }
QFrame.menu-card {
    background-color: #FFFDF7;
    border: 1.5px solid #D8CDB2;
    border-radius: 16px;
    padding: 24px 20px;
}
QFrame.menu-card:hover { border-color: #0E4A4A; background-color: #f8fbff; }
QFrame.drop-zone {
    background-color: #FFFDF7;
    border: 2px dashed #7D8F88;
    border-radius: 12px;
    padding: 20px;
}
QFrame.drop-zone:hover { border-color: #0E4A4A; background-color: #eef4ff; }
QFrame.drop-zone-active { background-color: #E3EBDD; border: 2px dashed #0E4A4A; }
QFrame.drop-zone-loaded { background-color: #E3EBDD; border: 1.5px solid #22c55e; border-radius: 12px; }

/* Buttons: one primary, quiet secondary, clear danger */
QPushButton {
    background-color: #FFFDF7;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover { background-color: #EFE7D3; border-color: #0E4A4A; }
QPushButton:pressed { background-color: #E3EBDD; }
QPushButton:disabled { background-color: #EFE7D3; color: #7D8F88; border-color: #D8CDB2; }
QPushButton.primary {
    background-color: #0E4A4A;
    color: #FFFDF7;
    border: none;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 600;
    border-radius: 8px;
}
QPushButton.primary:hover { background-color: #0A3838; }
QPushButton.primary:pressed { background-color: #0A3838; }
QPushButton.primary:disabled { background-color: #A9C6A2; color: #E3EBDD; }
QPushButton.danger { background-color: #FFFDF7; color: #B42318; border: 1px solid #D98A8A; }
QPushButton.danger:hover { background-color: #FDECEC; border-color: #B42318; }

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #E3EBDD;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #0E4A4A; }
QComboBox {
    background-color: #ffffff;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    border-radius: 8px;
    padding: 6px 12px;
    min-width: 120px;
}
QComboBox:hover { border-color: #7D8F88; }
QComboBox::drop-down { border: none; padding-right: 8px; }
QComboBox QAbstractItemView {
    background-color: #FFFDF7;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    selection-background-color: #E3EBDD;
    selection-color: #1B2A28;
    outline: none;
}
QDoubleSpinBox, QSpinBox {
    background-color: #FFFDF7;
    color: #1B2A28;
    border: 1px solid #7D8F88;
    border-radius: 6px;
    padding: 4px 8px;
}
QDoubleSpinBox:focus, QSpinBox:focus { border-color: #0E4A4A; }
QCheckBox { color: #1B2A28; spacing: 8px; }
QRadioButton { color: #1B2A28; spacing: 8px; }
QRadioButton::indicator { width: 16px; height: 16px; }

/* Progress */
QProgressBar {
    background-color: #EFE7D3;
    border: 1px solid #D8CDB2;
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: #1B2A28;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar::chunk { background-color: #0E4A4A; border-radius: 7px; }

/* Labels and hierarchy */
QLabel { color: #43564F; }
QLabel.title { font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; font-size: 22px; font-weight: 700; color: #10201E; }
QLabel.subtitle { font-size: 13px; color: #43564F; }
QLabel.section-title { font-size: 15px; font-weight: 600; color: #1B2A28; }
QLabel.badge { background-color: #E3EBDD; color: #0A3838; border-radius: 6px; padding: 3px 8px; font-size: 12px; font-weight: 600; }
QLabel.badge-success { background-color: #E3EBDD; color: #1F7A3A; border-radius: 6px; padding: 3px 8px; font-size: 12px; font-weight: 600; }
QLabel.badge-warning { background-color: #FFF3D6; color: #96431E; border-radius: 6px; padding: 3px 8px; font-size: 12px; font-weight: 600; }
QTabBar::tab { background: #EFE7D3; color: #43564F; border: 1px solid #D8CDB2; padding: 8px 16px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #FFFDF7; color: #1B2A28; font-weight: 600; }
QToolTip { background-color: #1B2A28; color: #FFFDF7; border: none; padding: 6px 8px; }
"""

# Backwards-compatible name: the light theme is the product default now.
DARK_THEME_QSS = LIGHT_THEME_QSS
THEME_QSS = LIGHT_THEME_QSS
