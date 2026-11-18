"""Home-screen navigation: view ids and menu-card builders.

Extracted from ``MainWindow`` so the menu structure is data (``MENU_CARDS``)
plus two small builders, both usable without a window instance.
"""

from app.ui.styles import apply_style
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
    MenuCardSpec("01", "Criar vídeo", "", "PDF ou MP4 + até quatro áudios",
        "Combine páginas ou um vídeo com narração, música e efeitos. Ajuste os tempos e exporte seu MP4.",
        "Criar meu vídeo →", MainView.CREATE_VIDEO, True),
    MenuCardSpec("02", "Gravar aula", "", "Seu conteúdo em cena",
        "Apresente até três PDFs, escreva no quadro e use quiz, Bíblia e teleprompter durante a gravação.",
        "Entrar no estúdio →", MainView.RECORD_CLASS),
    MenuCardSpec("03", "Gravar tela / reunião", "", "Demonstre enquanto explica",
        "Capture a tela para tutoriais e reuniões, com as fontes de áudio disponíveis no seu computador.",
        "Preparar gravação →", MainView.RECORD_MEET),
    MenuCardSpec("04", "Podcast", "", "Uma ideia que merece ser ouvida",
        "Grave ou importe seu áudio. Personalize a capa e transforme o episódio em vídeo com ondas sonoras.",
        "Criar episódio →", MainView.RECORD_PODCAST),
    MenuCardSpec("05", "Materiais da aula", "", "Recursos de IA opcionais",
        "Prepare slides, capas e materiais de apoio. As ferramentas de geração usam serviços online configurados por você.",
        "Preparar materiais →", MainView.GENERATE_MATERIALS),
)

def build_menu_card(spec: MenuCardSpec, on_open: Callable[[], None]) -> QFrame:
    """Builds one clickable home menu card from a spec."""
    card = QFrame()
    card.setProperty("class", "menu-card")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(20, 20, 20, 20)
    card_layout.setSpacing(12)

    icon = QLabel(spec.icon)
    apply_style(icon, "font-size: 30px; font-weight: 700; color: @primary@;")
    title = QLabel(spec.title)
    title.setWordWrap(True)
    apply_style(title, "font-size: 20px; font-weight: 700; color: @text@;")
    subtitle = QLabel(spec.subtitle)
    subtitle.setWordWrap(True)
    apply_style(subtitle, "font-size: 12px; font-weight: 600; color: @primary@;")
    description = QLabel(spec.description)
    description.setWordWrap(True)
    apply_style(description, "color: @secondary@; font-size: 13px;")

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
