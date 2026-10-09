"""Home-screen navigation: view ids and menu-card builders.

Extracted from ``MainWindow`` so the menu structure is data (``MENU_CARDS``)
plus two small builders, both usable without a window instance.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class MainView(IntEnum):
    """Indices of the root QStackedWidget screens (order of addWidget calls)."""

    HOME = 0
    CREATE_VIDEO = 1
    RECORD_CLASS = 2
    RECORD_MEET = 3
    RECORD_PODCAST = 4
    GENERATE_MATERIALS = 5


@dataclass(frozen=True)
class MenuCardSpec:
    icon: str
    title: str
    title_color: str
    subtitle: str
    description: str
    button_text: str
    target: MainView
    primary: bool = False


MENU_CARDS: Tuple[MenuCardSpec, ...] = (
    MenuCardSpec(
        icon="🎬",
        title="1. Criar Vídeo",
        title_color="#38bdf8",
        subtitle="Slides (PDF) + Narração em Áudio",
        description=(
            "Transforme sua apresentação de slides em PDF e áudio em um vídeo MP4 "
            "com sincronização inteligente de transições utilizando IA."
        ),
        button_text="Abrir Criador de Vídeos →",
        target=MainView.CREATE_VIDEO,
        primary=True,
    ),
    MenuCardSpec(
        icon="🎓",
        title="2. Gravar Aula",
        title_color="#a78bfa",
        subtitle="Estúdio Educacional & Tutoriais de Tela",
        description=(
            "Grave videoaulas com apresentação de slides ou tutoriais de aplicativos capturando a tela "
            "do computador, com teleprompter no topo, câmera opcional, fundo musical e legendas IA."
        ),
        button_text="Abrir Gravador de Aula →",
        target=MainView.RECORD_CLASS,
    ),
    MenuCardSpec(
        icon="👥",
        title="3. Gravar Reunião do Meet",
        title_color="#34d399",
        subtitle="Captura do Google Meet & Chamadas",
        description=(
            "Grave reuniões completas do Google Meet diretamente do seu desktop, "
            "capturando com perfeição o som dos participantes e o microfone."
        ),
        button_text="Abrir Gravador do Meet →",
        target=MainView.RECORD_MEET,
    ),
    MenuCardSpec(
        icon="🎙️",
        title="4. Gravar Podcast",
        title_color="#f59e0b",
        subtitle="Áudio ao Vivo + Ondas Sonoras Dinâmicas",
        description=(
            "Grave episódios de podcast com capa fixa e ondas sonoras animadas em tempo real, "
            "teleprompter integrado no topo, microfone, fundo musical e legendas IA."
        ),
        button_text="Abrir Gravador de Podcast →",
        target=MainView.RECORD_PODCAST,
    ),
    MenuCardSpec(
        icon="🪄",
        title="5. Gerar Materiais da Aula",
        title_color="#818cf8",
        subtitle="Slides em PDF (até 100) & Prompts por Voz",
        description=(
            "Gere apresentações visuais de altíssimo padrão por IA (de 1 a 100 slides) com prompts "
            "digitados ou falados pelo microfone, exportando em PDF e E-books didáticos."
        ),
        button_text="Abrir Gerador de Materiais →",
        target=MainView.GENERATE_MATERIALS,
    ),
)


def build_menu_card(spec: MenuCardSpec, on_open: Callable[[], None]) -> QFrame:
    """Builds one clickable home menu card from a spec."""
    card = QFrame()
    card.setProperty("class", "menu-card")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(20, 20, 20, 20)
    card_layout.setSpacing(12)

    icon = QLabel(spec.icon)
    icon.setStyleSheet("font-size: 38px; margin-bottom: 2px;")
    title = QLabel(spec.title)
    title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {spec.title_color};")
    subtitle = QLabel(spec.subtitle)
    subtitle.setStyleSheet("font-size: 11px; font-weight: 600; color: #94a3b8;")
    description = QLabel(spec.description)
    description.setWordWrap(True)
    description.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.4;")

    button = QPushButton(spec.button_text)
    if spec.primary:
        button.setProperty("class", "primary")
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(on_open)

    card_layout.addWidget(icon)
    card_layout.addWidget(title)
    card_layout.addWidget(subtitle)
    card_layout.addWidget(description)
    card_layout.addStretch()
    card_layout.addWidget(button)
    return card


def build_home_menu(on_navigate: Callable[[MainView], None]) -> QVBoxLayout:
    """Builds the 2-row (3 + 2) home menu container layout."""
    container = QVBoxLayout()
    container.setContentsMargins(0, 0, 0, 0)
    container.setSpacing(16)

    rows = (MENU_CARDS[:3], MENU_CARDS[3:])
    for row_specs in rows:
        row_layout = QHBoxLayout()
        row_layout.setSpacing(18)
        for spec in row_specs:
            # NOTE: clicked(bool) passes `checked` positionally, so the lambda
            # must swallow it first or it would bind to `target`.
            row_layout.addWidget(
                build_menu_card(
                    spec, lambda checked=False, target=spec.target: on_navigate(target)
                )
            )
        container.addLayout(row_layout)
    return container
