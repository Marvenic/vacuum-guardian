"""Tela "About": identidade, versao e autoria do aplicativo.

A versao vem de app.__version__ (fonte unica) para nao existir numero
duplicado entre codigo, instalador e tela sobre.

Todo texto visivel ao operador esta em ingles (idioma de operacao da fabrica).
"""

from __future__ import annotations

from PySide2.QtCore import Qt
from PySide2.QtGui import QIcon, QPalette
from PySide2.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .. import __version__

_WEBSITE = "https://www.abilixdigital.com"
_AUTHORS = "Marcos Souza"


class AboutDialog(QDialog):
    """Dialogo modal com creditos; nao contem logica de negocio."""

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("About Vacuum Guardian")
        self.setWindowIcon(icon)

        logo = QLabel()
        logo.setPixmap(icon.pixmap(96, 96))
        logo.setAlignment(Qt.AlignTop)

        # Cor secundaria tirada da paleta do sistema (e nao fixa em #666):
        # assim a linha da versao continua legivel em tema claro e escuro.
        muted = self.palette().color(QPalette.PlaceholderText).name()

        # Um unico rich-text: mais simples de manter que varios QLabel e
        # permite o link clicavel do site.
        body = QLabel(
            f"<h2 style='margin-bottom:2px'>Vacuum Guardian</h2>"
            f"<p style='color:{muted}; margin-top:0'>Version {__version__}</p>"
            f"<p>Vacuum monitoring for CMS Brembana / OSAI.<br>"
            f"Watches the OSAI screen and raises an alarm when a monitored "
            f"program runs without vacuum.</p>"
            f"<p><b>Created by</b><br>{_AUTHORS}<br>Abilix Digital<br>"
            f"<a href='{_WEBSITE}'>www.abilixdigital.com</a></p>"
        )
        body.setTextFormat(Qt.RichText)
        body.setOpenExternalLinks(True)  # abre o site no navegador padrao
        body.setWordWrap(True)

        content = QHBoxLayout()
        content.addWidget(logo)
        content.addSpacing(16)
        content.addWidget(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(content)
        layout.addWidget(buttons)
        self.setFixedWidth(480)
