"""Live Qt design tokens. Does not alter exported media or artwork colors."""
from __future__ import annotations
import re
import weakref
from pathlib import Path
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QPushButton
from shiboken6 import isValid

LIGHT = {
    "bg": "#F3EEE2", "surface": "#FFFDF7", "surface_alt": "#EAE5D9",
    "field": "#FFFFFF", "elevated": "#FFFDF7", "border": "#CCC6B8",
    "border_strong": "#807F72", "text": "#1B2A28", "secondary": "#43564F",
    "muted": "#59665F", "disabled": "#546059", "primary": "#0E4A4A",
    "primary_hover": "#0A3838", "primary_soft": "#DFE9DE", "on_primary": "#FFFFFF",
    "success": "#226336", "success_soft": "#E2EFDF", "warning": "#85421D",
    "warning_soft": "#FFF0D4", "danger": "#A52222", "danger_soft": "#FCE8E5",
    "focus": "#8F5D14", "stage": "#10201E", "stage_text": "#F5F2E8",
    "track1": "#0E6562", "track2": "#6A4698", "track3": "#985022", "track4": "#355E91",
}
DARK = {
    "bg": "#101A19", "surface": "#192725", "surface_alt": "#233532",
    "field": "#14211F", "elevated": "#263A36", "border": "#3F5550",
    "border_strong": "#7D9690", "text": "#F3F1E8", "secondary": "#C5D5CE",
    "muted": "#ADBCB5", "disabled": "#9EADA6", "primary": "#98D8C4",
    "primary_hover": "#B5E7D7", "primary_soft": "#28483E", "on_primary": "#102A23",
    "success": "#A3DBAB", "success_soft": "#223D2C", "warning": "#F5C783",
    "warning_soft": "#453721", "danger": "#FFB7AA", "danger_soft": "#4A2927",
    "focus": "#F5C783", "stage": "#10201E", "stage_text": "#F5F2E8",
    "track1": "#A0DCD0", "track2": "#CEBAF0", "track3": "#F2C590", "track4": "#ACCBF4",
}
for _name, _palette in (("light", LIGHT), ("dark", DARK)):
    for _icon in ("check", "chevron_down", "chevron_up"):
        _palette[_icon] = (Path(__file__).parent / "assets" / f"{_icon}-{_name}.svg").as_posix()
COLORS = LIGHT
FONT_FAMILY = '"Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif'
RADIUS = {"sm": 6, "md": 8, "lg": 12, "xl": 16}
SPACING = (4, 8, 12, 16, 24, 32)
_styles = weakref.WeakKeyDictionary()
_active = LIGHT


def tokens():
    return _active


def resolve(template: str) -> str:
    return re.sub(r"@([a-z0-9_]+)@", lambda m: _active[m[1]], template)


def apply_style(widget, template: str):
    """Keep layout/state styles live when changing the application theme."""
    # Legacy panels occasionally coupled a surface to inverse text, or used
    # an accent as both background and foreground. Normalize semantic pairs.
    def pair(match):
        block = match[0]
        solid = re.search(r"(?<![-\w])background(?:-color)?\s*:\s*@(primary|success|warning|danger)@", block)
        if solid or "qlineargradient" in block:
            if re.search(r"(?<![-\w])color\s*:", block):
                block = re.sub(r"(?<![-\w])color\s*:[^;]+;", "color: @on_primary@;", block)
            else:
                block += " color: @on_primary@;"
        elif re.search(r"background(?:-color)?\s*:\s*@(surface|surface_alt|field|bg)@", block):
            block = block.replace("color: @on_primary@", "color: @text@")
        return block
    template = re.sub(r"[^{}]+", pair, template)
    # A bare stylesheet applied to a panel also matches its descendants in Qt.
    # Scope it explicitly: a card border must never outline every child label.
    if "{" not in template:
        scope = str(id(widget))
        widget.setProperty("slidecastStyle", scope)
        selector = f'*[slidecastStyle="{scope}"]'
        template = f"{selector} {{ {template} }}"
        if isinstance(widget, QPushButton):
            widget.setMinimumHeight(max(44, widget.minimumHeight()))
            template += f"""
{selector}:disabled {{ background: @surface_alt@; color: @disabled@; border: 1px solid transparent; }}
{selector}:focus {{ border: 2px solid @focus@; }}
"""
    # A QFrame selector should style its panel, not every QLabel underneath.
    if "QFrame {" in template:
        widget.setProperty("themePanel", str(id(widget)))
        template = template.replace("QFrame {", f'QFrame[themePanel="{id(widget)}"] {{')
    _styles[widget] = template
    widget.setStyleSheet(resolve(template))


QSS = """
QWidget { color: @text@; font-family: "Segoe UI", "Noto Sans", "DejaVu Sans"; font-size: 13px; }
QMainWindow, QWidget#centralWidget, QDialog, QMessageBox, QFileDialog, QInputDialog { background: @bg@; }
QLabel { background: transparent; }
QLabel[class="title"] { font-size: 28px; font-weight: 700; }
QLabel[class="section-title"] { font-size: 17px; font-weight: 600; }
QLabel[class="subtitle"], QLabel[class="muted"] { color: @muted@; }
QFrame[class="card"], QFrame[class="menu-card"], QFrame[class="track"] {
    background: @surface@; border: 1px solid @border@; border-radius: 12px;
}
QFrame[class="menu-card"]:hover { border-color: @primary@; }
QFrame#appHeader { background: @surface@; border-bottom: 1px solid @border@; }
QLabel[class="badge"], QLabel[class="badge-success"], QLabel[class="badge-warning"] {
    border-radius: 6px; padding: 5px 9px; font-size: 12px; font-weight: 600;
}
QLabel[class="badge"] { background: @primary_soft@; color: @text@; }
QLabel[class="badge-success"] { background: @success_soft@; color: @success@; }
QLabel[class="badge-warning"] { background: @warning_soft@; color: @warning@; }
QPushButton, QToolButton { background: @surface@; color: @text@; border: 1px solid @border@;
    border-radius: 10px; padding: 9px 16px; min-height: 24px; font-weight: 600; }
QToolButton { padding: 7px 10px; min-height: 22px; }
QPushButton:hover, QToolButton:hover { background: @surface_alt@; border-color: @primary@; }
QPushButton:checked { background: @primary_soft@; color: @text@; border: 1px solid @primary@; }
QPushButton[class="primary"] { background: @primary@; color: @on_primary@; border-color: @primary@; min-height: 28px; }
QPushButton[class="primary"]:hover { background: @primary_hover@; }
QPushButton[class="danger"] { background: @danger_soft@; color: @danger@; border-color: @danger@; }
QPushButton:disabled, QToolButton:disabled { background: @surface_alt@; color: @disabled@; border-color: @border@; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox {
    background: @field@; color: @text@; border: 1px solid @border@; border-radius: 8px;
    padding: 8px 10px; min-height: 24px; selection-background-color: @primary@; selection-color: @on_primary@; placeholder-text-color: @muted@;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled { color: @disabled@; background: @surface_alt@; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QAbstractSpinBox:focus, QAbstractItemView:focus { border: 2px solid @focus@; }
QCheckBox, QRadioButton { spacing: 9px; padding: 6px 0; background: transparent; border: none; min-height: 24px; }
QCheckBox:focus, QRadioButton:focus { background: @primary_soft@; outline: 2px solid @focus@; }
QCheckBox::indicator, QRadioButton::indicator { width: 17px; height: 17px; background: @field@; border: 1px solid @border_strong@; }
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: @primary@; border: 1px solid @primary@; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: @focus@; }
QCheckBox::indicator:checked { image: url("@check@"); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url("@chevron_down@"); width: 12px; height: 12px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@chevron_up@"); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@chevron_down@"); width: 10px; height: 10px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 18px; border: none; }
QCheckBox:disabled, QRadioButton:disabled { color: @disabled@; }
QAbstractItemView, QComboBox QAbstractItemView { background: @field@; color: @text@;
    alternate-background-color: @surface_alt@; border: 1px solid @border@;
    selection-background-color: @primary@; selection-color: @on_primary@; placeholder-text-color: @muted@; }
QHeaderView::section { background: @surface_alt@; color: @text@; padding: 8px; border: 1px solid @border@; }
QTableCornerButton::section { background: @surface_alt@; }
QScrollArea, QStackedWidget { border: none; background: transparent; }
QScrollBar:vertical { background: @surface_alt@; width: 12px; margin: 0; }
QScrollBar:horizontal { background: @surface_alt@; height: 12px; margin: 0; }
QScrollBar::handle { background: @border_strong@; border-radius: 5px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QTabWidget::pane { border: 1px solid @border@; background: @surface@; }
QTabBar::tab { background: @surface_alt@; color: @secondary@; padding: 9px 14px; border: 1px solid @border@; }
QTabBar::tab:selected { background: @surface@; color: @text@; border-bottom: 2px solid @primary@; }
QGroupBox { border: 1px solid @border@; border-radius: 8px; margin-top: 18px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; padding: 0 6px; color: @text@; }
QProgressBar { background: @surface_alt@; border: 1px solid @border@; border-radius: 5px; min-height: 12px; text-align: center; }
QProgressBar::chunk { background: @primary@; border-radius: 4px; }
QSlider::groove:horizontal { height: 5px; background: @border_strong@; border-radius: 2px; }
QSlider::handle:horizontal { background: @primary@; width: 16px; margin: -6px 0; border-radius: 8px; }
QSlider:focus { border: 2px solid @focus@; }
QMenuBar, QMenu, QStatusBar { background: @surface@; color: @text@; }
QMenu { border: 1px solid @border_strong@; padding: 4px; }
QMenu::item { padding: 8px 18px; }
QMenu::item:selected, QMenuBar::item:selected { background: @primary@; color: @on_primary@; }
QMenu::item:disabled { color: @disabled@; }
QToolTip { background: @text@; color: @bg@; border: 1px solid @border_strong@; padding: 8px; }
QSplitter::handle { background: @border@; }
QFrame[class="drop-zone"], QFrame[class="drop-zone-active"], QFrame[class="drop-zone-loaded"] {
    background: @surface@; border: 2px dashed @border_strong@; border-radius: 12px;
}
QFrame[class="drop-zone-active"], QFrame[class="drop-zone-loaded"] { background: @primary_soft@; border-color: @primary@; }
"""
LIGHT_THEME_QSS = resolve(QSS)
_active = DARK
DARK_THEME_QSS = resolve(QSS)
_active = LIGHT
THEME_QSS = LIGHT_THEME_QSS


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, app: QApplication, settings=None):
        super().__init__(app)
        self.app = app
        self.settings = settings or QSettings("SlideCast", "Studio")
        self.name = "light"
        self.set_theme(str(self.settings.value("appearance/theme", "light")), persist=False)

    def set_theme(self, name: str, persist=True):
        global _active
        self.name = name if name in ("light", "dark") else "light"
        _active = LIGHT if self.name == "light" else DARK
        self.app.setStyle("Fusion")
        self.app.setFont(QFont("Noto Sans", 10))
        palette = QPalette()
        roles = {
            "Window": "bg", "WindowText": "text", "Base": "field", "AlternateBase": "surface_alt",
            "Text": "text", "Button": "surface", "ButtonText": "text", "Highlight": "primary",
            "HighlightedText": "on_primary", "ToolTipBase": "text", "ToolTipText": "bg",
            "PlaceholderText": "muted", "Link": "primary", "Light": "surface", "Mid": "border",
            "Dark": "border_strong", "BrightText": "text",
        }
        for role, token in roles.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(_active[token]))
        for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(_active["disabled"]))
        self.app.setPalette(palette)
        self.app.setStyleSheet(resolve(QSS))
        for widget, template in list(_styles.items()):
            if isValid(widget):
                widget.setStyleSheet(resolve(template))
                widget.update()
        if persist:
            self.settings.setValue("appearance/theme", self.name)
            self.settings.sync()
        self.changed.emit(self.name)


def theme_manager():
    app = QApplication.instance()
    if not hasattr(app, "slidecast_theme"):
        app.slidecast_theme = ThemeManager(app)
    return app.slidecast_theme
