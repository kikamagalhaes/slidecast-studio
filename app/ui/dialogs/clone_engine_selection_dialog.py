import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QRadioButton,
    QButtonGroup,
    QFrame,
    QMessageBox,
    QScrollArea,
)

from app.core.config_manager import (
    get_replicate_api_key,
    set_replicate_api_key,
)


class CloneEngineSelectionDialog(QDialog):
    """
    Dialog to let the teacher choose the lip-sync technology before rendering:
    1. Cloud Neural Engine (Replicate Lipsync-2 - Studio Quality via cloud GPU)
    2. Local Smart Engine (Cadence and Pause-Gated Synchronization - Instant, 100% Free & Offline)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tecnologia de Sincronia Labial do Clone Digital")
        self.resize(740, 620)
        self.setMinimumSize(640, 480)

        self.selected_engine = "cloud_replicate"
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Header
        lbl_title = QLabel("🎭 Escolha a Tecnologia de Sincronia do seu Clone")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        lbl_sub = QLabel(
            "Selecione como a inteligência artificial deve animar os lábios e os movimentos da professora nesta videoaula:"
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: #94a3b8; font-size: 13px; margin-bottom: 2px;")
        root.addWidget(lbl_title)
        root.addWidget(lbl_sub)

        # Scroll area for cards so content is never cut off on smaller screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        sc_layout = QVBoxLayout(scroll_content)
        sc_layout.setContentsMargins(2, 4, 12, 4)
        sc_layout.setSpacing(14)

        self.button_group = QButtonGroup(self)

        # ----------------------------------------------------
        # OPTION 1: CLOUD NEURAL (REPLICATE)
        # ----------------------------------------------------
        self.card_cloud = QFrame()
        self.card_cloud.setStyleSheet(
            "QFrame { background-color: #1e1b4b; border: 2px solid #818cf8; border-radius: 10px; padding: 4px; }"
        )
        cc_layout = QVBoxLayout(self.card_cloud)
        cc_layout.setContentsMargins(16, 14, 16, 14)
        cc_layout.setSpacing(10)

        top_cloud = QHBoxLayout()
        self.radio_cloud = QRadioButton("🌐 Opção 1: Sincronia Neural em Nuvem (IA Replicate - Lipsync-2)")
        self.radio_cloud.setChecked(True)
        self.radio_cloud.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        self.button_group.addButton(self.radio_cloud, 1)

        badge_cloud = QLabel("⭐ ALTA FIDELIDADE")
        badge_cloud.setStyleSheet(
            "background: #4338ca; color: #a5b4fc; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px;"
        )
        top_cloud.addWidget(self.radio_cloud)
        top_cloud.addStretch()
        top_cloud.addWidget(badge_cloud)
        cc_layout.addLayout(top_cloud)

        lbl_cloud_desc = QLabel(
            "• Sincronia labial neural fonema a fonema em alta definição na nuvem.\n"
            "• Renderização rápida (15 a 45 segundos) processada em supercomputadores com GPU dedicada.\n"
            "• Requer Token de API do Replicate (gratuito para testes)."
        )
        lbl_cloud_desc.setWordWrap(True)
        lbl_cloud_desc.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-left: 22px; line-height: 1.4;")
        cc_layout.addWidget(lbl_cloud_desc)

        # Token input box (PROMINENT & CLEAR)
        self.token_box = QFrame()
        self.token_box.setStyleSheet("""
            QFrame {
                background: #0f172a;
                border: 2px solid #6366f1;
                border-radius: 8px;
            }
        """)
        tb_layout = QVBoxLayout(self.token_box)
        tb_layout.setContentsMargins(12, 12, 12, 12)
        tb_layout.setSpacing(8)

        lbl_t_prompt = QLabel("🔑 ONDE COLOCAR SEU TOKEN REPLICATE (Começa com r8_):")
        lbl_t_prompt.setStyleSheet("font-size: 12px; font-weight: 800; color: #38bdf8; border: none;")
        tb_layout.addWidget(lbl_t_prompt)

        t_row = QHBoxLayout()
        t_row.setSpacing(8)

        self.edit_token = QLineEdit()
        self.edit_token.setPlaceholderText("Cole aqui seu token que começa com r8_...")
        curr_token = get_replicate_api_key() or ""
        self.edit_token.setText(curr_token)
        self.edit_token.setStyleSheet(
            "background: #1e293b; color: #f8fafc; font-family: monospace; font-size: 12px; "
            "padding: 8px 10px; border-radius: 6px; border: 1px solid #475569;"
        )
        self.edit_token.textChanged.connect(self._on_token_changed)

        btn_paste = QPushButton("📋 Colar Token")
        btn_paste.setCursor(Qt.PointingHandCursor)
        btn_paste.setStyleSheet(
            "background: #4f46e5; color: #ffffff; font-weight: 700; font-size: 11px; padding: 7px 12px; border-radius: 6px;"
        )
        btn_paste.clicked.connect(self._paste_token)

        self.btn_toggle = QPushButton("👁️")
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setToolTip("Mostrar ou ocultar token")
        self.btn_toggle.setStyleSheet(
            "background: #334155; color: #f8fafc; font-size: 13px; padding: 7px 10px; border-radius: 6px;"
        )
        self.btn_toggle.clicked.connect(self._toggle_token_visibility)

        btn_how_token = QPushButton("🌐 Pegar Token no Replicate")
        btn_how_token.setCursor(Qt.PointingHandCursor)
        btn_how_token.setStyleSheet(
            "background: #0284c7; color: #ffffff; font-weight: 700; font-size: 11px; padding: 7px 12px; border-radius: 6px;"
        )
        btn_how_token.clicked.connect(self._open_replicate_guide)

        t_row.addWidget(self.edit_token, stretch=3)
        t_row.addWidget(btn_paste)
        t_row.addWidget(self.btn_toggle)
        t_row.addWidget(btn_how_token)
        tb_layout.addLayout(t_row)

        lbl_token_hint = QLabel(
            "💡 <b>Como obter o token:</b> Crie uma conta gratuita em <b>replicate.com</b> (com Google ou GitHub), "
            "acesse <i>API Tokens</i>, copie o código que começa com <code>r8_</code> e clique em <b>'Colar Token'</b> acima."
        )
        lbl_token_hint.setWordWrap(True)
        lbl_token_hint.setStyleSheet("color: #94a3b8; font-size: 11px; border: none;")
        tb_layout.addWidget(lbl_token_hint)

        cc_layout.addWidget(self.token_box)
        sc_layout.addWidget(self.card_cloud)

        # ----------------------------------------------------
        # OPTION 2: LOCAL SMART CADENCE (100% OFFLINE & FREE)
        # ----------------------------------------------------
        self.card_local = QFrame()
        self.card_local.setStyleSheet(
            "QFrame { background-color: #0f172a; border: 1.5px solid #2d3748; border-radius: 10px; padding: 4px; }"
        )
        cl_layout = QVBoxLayout(self.card_local)
        cl_layout.setContentsMargins(16, 14, 16, 14)
        cl_layout.setSpacing(10)

        top_l = QHBoxLayout()
        self.radio_local = QRadioButton("💻 Opção 2: Motor Local Inteligente (Gratuito / Sem Replicate)")
        self.radio_local.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        self.button_group.addButton(self.radio_local, 2)

        badge_l = QLabel("🌿 100% GRATUITO & OFFLINE")
        badge_l.setStyleSheet(
            "background: #065f46; color: #6ee7b7; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px;"
        )
        top_l.addWidget(self.radio_local)
        top_l.addStretch()
        top_l.addWidget(badge_l)
        cl_layout.addLayout(top_l)

        lbl_l_desc = QLabel(
            "• Sincroniza a fala com a movimentação ativa do clone e fecha a boca nas pausas da narração.\n"
            "• Transição suavizada temporalmente (sem cortes bruscos), ritmo natural e cadência didática.\n"
            "• 100% offline e imediato (menos de 5 segundos): não requer internet, computador potente nem chaves de API."
        )
        lbl_l_desc.setWordWrap(True)
        lbl_l_desc.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-left: 22px; line-height: 1.5;")
        cl_layout.addWidget(lbl_l_desc)

        sc_layout.addWidget(self.card_local)
        sc_layout.addStretch()

        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        # Hook radio toggle for card styles
        self.radio_cloud.toggled.connect(self._update_cards_style)
        self.radio_local.toggled.connect(self._update_cards_style)

        # Action Buttons (Pinned at Bottom)
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("background: #1e293b; color: #cbd5e1; padding: 10px 18px; border-radius: 8px;")
        btn_cancel.clicked.connect(self.reject)

        self.btn_proceed = QPushButton("▶ Iniciar Renderização da Videoaula")
        self.btn_proceed.setCursor(Qt.PointingHandCursor)
        self.btn_proceed.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #ec4899); "
            "color: #ffffff; font-weight: 800; font-size: 13px; padding: 12px 24px; border-radius: 8px;"
        )
        self.btn_proceed.clicked.connect(self._on_proceed)

        btn_bar.addWidget(btn_cancel)
        btn_bar.addStretch()
        btn_bar.addWidget(self.btn_proceed)
        root.addLayout(btn_bar)

    def _paste_token(self):
        clipboard = QGuiApplication.clipboard()
        txt = clipboard.text().strip()
        if txt:
            self.edit_token.setText(txt)
            set_replicate_api_key(txt)

    def _toggle_token_visibility(self):
        if self.edit_token.echoMode() == QLineEdit.Password:
            self.edit_token.setEchoMode(QLineEdit.Normal)
            self.btn_toggle.setText("👁️")
        else:
            self.edit_token.setEchoMode(QLineEdit.Password)
            self.btn_toggle.setText("🙈")

    def _on_token_changed(self, text: str):
        val = text.strip()
        if val:
            set_replicate_api_key(val)

    def _update_cards_style(self):
        if self.radio_cloud.isChecked():
            self.card_cloud.setStyleSheet(
                "QFrame { background-color: #1e1b4b; border: 2px solid #818cf8; border-radius: 10px; }"
            )
            self.card_local.setStyleSheet(
                "QFrame { background-color: #0f172a; border: 1.5px solid #2d3748; border-radius: 10px; }"
            )
            self.token_box.show()
        else:
            self.card_cloud.setStyleSheet(
                "QFrame { background-color: #0f172a; border: 1.5px solid #2d3748; border-radius: 10px; }"
            )
            self.card_local.setStyleSheet(
                "QFrame { background-color: #064e3b; border: 2px solid #34d399; border-radius: 10px; }"
            )
            self.token_box.hide()

    def _open_replicate_guide(self):
        webbrowser.open("https://replicate.com/account/api-tokens")

        msg = QMessageBox(self)
        msg.setWindowTitle("Como Obter o Token Gratuito do Replicate")
        msg.setText(
            "<h3>Como gerar seu token em 3 passos:</h3>"
            "<ol>"
            "<li>Na página aberta no seu navegador (<b>replicate.com</b>), clique em <b>Sign In</b> e entre com sua conta Google ou GitHub.</li>"
            "<li>Acesse o menu <b>API Tokens</b> (ou vá em <a href='https://replicate.com/account/api-tokens'>replicate.com/account/api-tokens</a>).</li>"
            "<li>Clique em <b>Create Token</b>, copie o código que começa com <code>r8_...</code> e clique no botão <b>'Colar Token'</b> aqui no aplicativo!</li>"
            "</ol>"
            "<p><i>O Replicate fornece créditos gratuitos iniciais para geração em alta fidelidade!</i></p>"
        )
        msg.setIcon(QMessageBox.Information)
        msg.exec()

    def _on_proceed(self):
        if self.radio_cloud.isChecked():
            token = self.edit_token.text().strip()
            if not token:
                reply = QMessageBox.question(
                    self,
                    "Token Não Informado",
                    "Você selecionou a opção em Nuvem (Replicate), mas o campo de Token está vazio.\n\n"
                    "Deseja abrir a página para obter o token agora?\n"
                    "(Se clicar em Não, a renderização usará o Motor Local Inteligente).",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._open_replicate_guide()
                    return
                else:
                    self.selected_engine = "local_cadence"
                    self.accept()
                    return

            set_replicate_api_key(token)
            self.selected_engine = "cloud_replicate"
        else:
            self.selected_engine = "local_cadence"

        self.accept()

    def get_selected_engine(self) -> str:
        return self.selected_engine
