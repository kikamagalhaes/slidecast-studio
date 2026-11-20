"""Account & Desktop License Dialog for SlideCast Studio.

Follows the SlideCast Qt design system (tokens, apply_style, ThemeManager).
Uses non-blocking background workers so network calls never freeze the UI.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import device_identity
from app.core.license_manager import get_license_manager
from app.core.license_models import ActivationResult, LicenseStatus
from app.ui.styles import apply_style, theme_manager

logger = logging.getLogger(__name__)


class LicenseWorker(QThread):
    """Background worker for network license operations."""

    completed = Signal(object)  # ActivationResult or bool
    failed = Signal(str)

    def __init__(self, action: str, license_key: str = "", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.action = action
        self.license_key = license_key
        self.mgr = get_license_manager()

    def run(self):
        try:
            if self.action == "activate":
                res = self.mgr.activate_online(self.license_key)
                self.completed.emit(res)
            elif self.action == "validate":
                res = self.mgr.validate_online()
                self.completed.emit(res)
            elif self.action == "deactivate":
                success = self.mgr.deactivate_online()
                self.completed.emit(success)
        except Exception as exc:
            logger.exception("Error in license worker: %s", exc)
            self.failed.emit(str(exc))


class LicenseDialog(QDialog):
    """Dialog for checking, activating, and managing desktop license seats."""

    license_updated = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Conta e Licença · SlideCast Studio")
        self.resize(560, 480)
        self.setMinimumSize(480, 420)
        self.mgr = get_license_manager()
        self._worker: Optional[LicenseWorker] = None
        self._build_ui()
        self._refresh_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("Licenciamento do SlideCast Studio")
        apply_style(title, "font-size: 20px; font-weight: 700; color: @text@;")
        subtitle = QLabel("Gerencie a ativação deste computador e o acesso aos recursos profissionais.")
        subtitle.setWordWrap(True)
        apply_style(subtitle, "color: @muted@; font-size: 13px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        root.addLayout(title_box)

        # Status Card
        self.card = QFrame()
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)
        apply_style(
            self.card,
            "background-color: @surface@; border: 1px solid @border@; border-radius: 8px;",
        )

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_lbl_title = QLabel("Situação atual:")
        apply_style(status_lbl_title, "font-size: 14px; font-weight: 600; color: @text@;")
        status_row.addWidget(status_lbl_title)

        self.lbl_badge = QLabel("Não ativado")
        self.lbl_badge.setProperty("class", "badge-warning")
        apply_style(
            self.lbl_badge,
            "padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 12px;",
        )
        status_row.addWidget(self.lbl_badge)
        status_row.addStretch()
        card_layout.addLayout(status_row)

        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        apply_style(self.lbl_details, "color: @secondary@; font-size: 13px; line-height: 1.4;")
        card_layout.addWidget(self.lbl_details)

        root.addWidget(self.card)

        # Device identity card
        dev_card = QFrame()
        dev_layout = QHBoxLayout(dev_card)
        dev_layout.setContentsMargins(14, 10, 14, 10)
        apply_style(
            dev_card,
            "background-color: @surface_alt@; border: 1px solid @border@; border-radius: 6px;",
        )

        dev_name = device_identity.get_device_name()
        dev_id = device_identity.get_device_id()
        short_id = f"{dev_id[:8]}...{dev_id[-6:]}"
        lbl_dev = QLabel(f"💻 Computador: <b>{dev_name}</b> · ID: <tt>{short_id}</tt>")
        apply_style(lbl_dev, "color: @text@; font-size: 12px;")
        dev_layout.addWidget(lbl_dev, 1)

        btn_copy_id = QPushButton("Copiar ID")
        btn_copy_id.setToolTip("Copiar identificador anônimo para o suporte")
        apply_style(btn_copy_id, "padding: 3px 8px; font-size: 11px;")
        btn_copy_id.clicked.connect(self._copy_device_id)
        dev_layout.addWidget(btn_copy_id)

        root.addWidget(dev_card)

        # Activation Form
        form_layout = QVBoxLayout()
        form_layout.setSpacing(8)
        lbl_key = QLabel("Chave de Licença:")
        apply_style(lbl_key, "font-weight: 600; color: @text@; font-size: 13px;")
        form_layout.addWidget(lbl_key)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.txt_key = QLineEdit()
        self.txt_key.setPlaceholderText("SCST-XXXX-XXXX-XXXX-XXXX")
        apply_style(
            self.txt_key,
            "padding: 8px 12px; font-size: 14px; font-family: monospace; border: 1px solid @border_strong@; border-radius: 6px; background: @field@; color: @text@;",
        )
        self.txt_key.textChanged.connect(self._format_key_input)
        key_row.addWidget(self.txt_key, 1)

        self.btn_activate = QPushButton("Ativar neste computador")
        apply_style(
            self.btn_activate,
            "padding: 8px 16px; font-weight: 700; background-color: @primary@; color: @on_primary@; border-radius: 6px;",
        )
        self.btn_activate.clicked.connect(self._on_activate_clicked)
        key_row.addWidget(self.btn_activate)
        form_layout.addLayout(key_row)

        root.addLayout(form_layout)

        # Progress indicator
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        root.addStretch()

        # Action bar
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_buy = QPushButton("Adquirir ou renovar licença")
        apply_style(actions_row.widget() or self.btn_buy, "color: @primary@; font-weight: 600;")
        self.btn_buy.clicked.connect(self._open_buy_page)
        actions_row.addWidget(self.btn_buy)

        self.btn_deactivate = QPushButton("Desativar este computador")
        apply_style(self.btn_deactivate, "color: @danger@; border: 1px solid @border@; border-radius: 6px; padding: 6px 12px;")
        self.btn_deactivate.clicked.connect(self._on_deactivate_clicked)
        actions_row.addWidget(self.btn_deactivate)

        actions_row.addStretch()

        btn_close = QPushButton("Fechar")
        apply_style(btn_close, "padding: 6px 16px; border-radius: 6px; border: 1px solid @border@;")
        btn_close.clicked.connect(self.accept)
        actions_row.addWidget(btn_close)

        root.addLayout(actions_row)

    def _copy_device_id(self):
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(device_identity.get_device_id())
            QMessageBox.information(self, "Identificador copiado", "Identificador anônimo copiado para a área de transferência.")

    def _open_buy_page(self):
        url = self.mgr.get_server_url()
        QDesktopServices.openUrl(QUrl(url))

    def _format_key_input(self, text: str):
        # Auto-uppercase
        cleaned = text.upper()
        if cleaned != text:
            cursor_pos = self.txt_key.cursorPosition()
            self.txt_key.setText(cleaned)
            self.txt_key.setCursorPosition(cursor_pos)

    def _refresh_state(self):
        status = self.mgr.status
        lease = self.mgr.lease

        self.lbl_badge.setText(status.label_pt)
        self.lbl_badge.setProperty("class", status.badge_class)

        if status in (LicenseStatus.ACTIVE, LicenseStatus.NO_CONNECTION):
            key_masked = lease.license_key if lease else "Ativo"
            exp = lease.lease_expires_at[:10] if lease and lease.lease_expires_at else "Sem data"
            email = f"Conta: {lease.user_email} · " if lease and lease.user_email else ""
            if status == LicenseStatus.NO_CONNECTION:
                details = f"✓ Licença válida localmente em modo offline.<br>{email}Chave: <tt>{key_masked}</tt><br>Válido localmente até: {exp}."
            else:
                details = f"✓ Licença ativa e autenticada.<br>{email}Chave: <tt>{key_masked}</tt><br>Próxima verificação automática: {exp}."
            self.lbl_details.setText(details)
            self.txt_key.setEnabled(False)
            self.txt_key.setText(lease.license_key if lease else "")
            self.btn_activate.setEnabled(False)
            self.btn_deactivate.show()
        elif status == LicenseStatus.LIMIT_REACHED:
            self.lbl_details.setText("O limite de computadores autorizados para esta chave foi atingido. Desative um dos computadores anteriores para liberar a vaga.")
            self.txt_key.setEnabled(True)
            self.btn_activate.setEnabled(True)
            self.btn_deactivate.hide()
        elif status == LicenseStatus.EXPIRED:
            self.lbl_details.setText("Sua licença ou o período offline expirou. Conecte-se à internet ou renove sua chave para continuar com todas as funcionalidades.")
            self.txt_key.setEnabled(True)
            self.btn_activate.setEnabled(True)
            self.btn_deactivate.hide()
        else:
            self.lbl_details.setText("Você está no modo gratuito de avaliação. Suas gravações e projetos são preservados localmente no seu computador.")
            self.txt_key.setEnabled(True)
            self.btn_activate.setEnabled(True)
            self.btn_deactivate.hide()

    def _set_loading(self, loading: bool):
        if loading:
            self.progress.show()
            self.btn_activate.setEnabled(False)
            self.btn_deactivate.setEnabled(False)
        else:
            self.progress.hide()
            self.btn_activate.setEnabled(True)
            self.btn_deactivate.setEnabled(True)

    def _on_activate_clicked(self):
        key = self.txt_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Chave necessária", "Digite ou cole sua chave de licença no formato SCST-XXXX-XXXX-XXXX-XXXX.")
            return

        self._set_loading(True)
        self._worker = LicenseWorker("activate", license_key=key, parent=self)
        self._worker.completed.connect(self._on_activation_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_activation_finished(self, result: ActivationResult):
        self._set_loading(False)
        if result.success:
            QMessageBox.information(self, "Sucesso", "SlideCast Studio ativado com sucesso neste computador!")
            self._refresh_state()
            self.license_updated.emit()
        else:
            if result.status == LicenseStatus.LIMIT_REACHED:
                devs_text = ""
                if result.active_devices:
                    devs_text = "\n\nDispositivos ativos atualmente:\n" + "\n".join(
                        f"• {d.get('device_name', 'Dispositivo')} ({d.get('platform', '')})"
                        for d in result.active_devices
                    )
                QMessageBox.warning(
                    self,
                    "Limite de computadores atingido",
                    f"{result.message}{devs_text}",
                )
            else:
                QMessageBox.warning(self, "Falha na ativação", result.message)
            self._refresh_state()

    def _on_deactivate_clicked(self):
        confirm = QMessageBox.question(
            self,
            "Desativar este computador?",
            "Ao desativar, este computador liberará a vaga para outro dispositivo. Seus arquivos locais e projetos continuam salvos normalmente.\n\nDeseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._set_loading(True)
        self._worker = LicenseWorker("deactivate", parent=self)
        self._worker.completed.connect(self._on_deactivation_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_deactivation_finished(self, success: bool):
        self._set_loading(False)
        QMessageBox.information(
            self,
            "Dispositivo desativado",
            "A licença foi desvinculada deste computador. A vaga está liberada.",
        )
        self._refresh_state()
        self.license_updated.emit()

    def _on_worker_failed(self, error_msg: str):
        self._set_loading(False)
        QMessageBox.warning(self, "Erro de comunicação", f"Ocorreu um erro: {error_msg}")
        self._refresh_state()
