DARK_THEME_QSS = """
QMainWindow, QWidget#centralWidget {
    background-color: #12141a;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

/* Modals, Pop-ups e Caixas de Mensagem */
QDialog, QMessageBox, QInputDialog, QFileDialog {
    background-color: #1a1e28;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel, QFileDialog QLabel {
    background-color: transparent;
    color: #f8fafc;
    font-size: 13px;
    font-weight: 500;
}

QDialog QLineEdit, QMessageBox QLineEdit, QInputDialog QLineEdit, QDialog QTextEdit {
    background-color: #12141c;
    color: #ffffff;
    border: 1.5px solid #4f46e5;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}

QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
    background-color: #272d3e;
    color: #ffffff;
    border: 1px solid #3e4862;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
    min-width: 80px;
}

QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
    background-color: #3b455e;
    border-color: #6366f1;
}

QDialog QPushButton:focus, QMessageBox QPushButton:focus, QInputDialog QPushButton:focus {
    border-color: #818cf8;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollBar:horizontal {
    border: none;
    background: #1a1e27;
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #3b4252;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #4c566a;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar:vertical {
    border: none;
    background: #1a1e27;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3b4252;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #4c566a;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Card Container */
QFrame.card {
    background-color: #1a1d26;
    border: 1px solid #2d3343;
    border-radius: 12px;
    padding: 16px;
}

QFrame.card:hover {
    border-color: #3e475d;
}

/* Home Menu Cards */
QFrame.menu-card {
    background-color: #161922;
    border: 1.5px solid #272f44;
    border-radius: 16px;
    padding: 24px 20px;
}

QFrame.menu-card:hover {
    border-color: #6366f1;
    background-color: #1b1f2e;
}

/* Drop Areas */
QFrame.drop-zone {
    background-color: #161922;
    border: 2px dashed #3a4256;
    border-radius: 12px;
    padding: 20px;
}

QFrame.drop-zone:hover {
    border-color: #6366f1;
    background-color: #1b1f2c;
}

QFrame.drop-zone-active {
    background-color: #1e1b4b;
    border: 2px dashed #818cf8;
}

QFrame.drop-zone-loaded {
    background-color: #161a24;
    border: 1.5px solid #22c55e;
    border-radius: 12px;
}

/* Buttons */
QPushButton {
    background-color: #262b3a;
    color: #f1f5f9;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #32394d;
    border-color: #4b5563;
}

QPushButton:pressed {
    background-color: #1f2330;
}

QPushButton:disabled {
    background-color: #1a1e28;
    color: #64748b;
    border-color: #272c39;
}

QPushButton.primary {
    background-color: #4f46e5;
    color: #ffffff;
    border: none;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 600;
    border-radius: 8px;
}

QPushButton.primary:hover {
    background-color: #4338ca;
}

QPushButton.primary:pressed {
    background-color: #3730a3;
}

QPushButton.primary:disabled {
    background-color: #2d334b;
    color: #636683;
}

QPushButton.danger {
    background-color: #7f1d1d;
    color: #fca5a5;
    border: 1px solid #991b1b;
}

QPushButton.danger:hover {
    background-color: #991b1b;
    color: #ffffff;
}

/* Inputs & Combos */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #161822;
    color: #f8fafc;
    border: 1px solid #333a4c;
    border-radius: 8px;
    padding: 8px 12px;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #6366f1;
}

QComboBox {
    background-color: #161822;
    color: #f8fafc;
    border: 1px solid #333a4c;
    border-radius: 8px;
    padding: 6px 12px;
    min-width: 120px;
}

QComboBox:hover {
    border-color: #4a546e;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1c202d;
    color: #f8fafc;
    border: 1px solid #333a4c;
    selection-background-color: #4f46e5;
    outline: none;
}

QDoubleSpinBox, QSpinBox {
    background-color: #161822;
    color: #f8fafc;
    border: 1px solid #333a4c;
    border-radius: 6px;
    padding: 4px 8px;
}

QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: #6366f1;
}

/* Progress Bar */
QProgressBar {
    background-color: #1a1e2b;
    border: 1px solid #2d3345;
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #06b6d4);
    border-radius: 7px;
}

/* Labels */
QLabel {
    color: #cbd5e1;
}

QLabel.title {
    font-size: 20px;
    font-weight: 700;
    color: #f8fafc;
}

QLabel.subtitle {
    font-size: 13px;
    color: #94a3b8;
}

QLabel.section-title {
    font-size: 15px;
    font-weight: 600;
    color: #f1f5f9;
}

QLabel.badge {
    background-color: #272f44;
    color: #93c5fd;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 500;
}

QLabel.badge-success {
    background-color: #14532d;
    color: #86efac;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 500;
}

QLabel.badge-warning {
    background-color: #713f12;
    color: #fde047;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 500;
}

QRadioButton {
    color: #e2e8f0;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
"""
