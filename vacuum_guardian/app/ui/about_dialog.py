"""About screen: identity, version and authorship.

The version comes from app.__version__ (single source) so there is no
duplicated number between code, installer and this screen.

All operator-facing text is in English (the language of the shop floor).
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
    """Modal credits dialog; holds no business logic."""

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("About Vacuum Guardian")
        self.setWindowIcon(icon)

        logo = QLabel()
        logo.setPixmap(icon.pixmap(96, 96))
        logo.setAlignment(Qt.AlignTop)

        # Secondary colour taken from the system palette (not hardcoded #666):
        # that keeps the version line readable in both light and dark themes.
        muted = self.palette().color(QPalette.PlaceholderText).name()

        # A single rich-text block: simpler to maintain than several QLabels and
        # it gives us the clickable website link.
        body = QLabel(
            f"<h2 style='margin-bottom:2px'>Vacuum Guardian</h2>"
            f"<p style='color:{muted}; margin-top:0'>Version {__version__}</p>"
            f"<p>Vacuum monitoring for CMS Brembana / OSAI.<br>"
            f"Watches the Iso lines field and alerts when a program runs "
            f"without vacuum. Acknowledge silences it for 5 minutes.</p>"
            f"<p style='color:{muted}'>Free to use. Optional anonymous usage "
            f"reporting - tray icon, Usage data.</p>"
            f"<p><b>Created by</b><br>{_AUTHORS}<br>Abilix Digital<br>"
            f"<a href='{_WEBSITE}'>www.abilixdigital.com</a></p>"
        )
        body.setTextFormat(Qt.RichText)
        body.setOpenExternalLinks(True)  # opens the site in the default browser
        body.setWordWrap(True)
        body.setFixedWidth(440)

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
        # ponytail: the TEXT carries the fixed width, not the dialog. With the
        # label free, the dialog's sizeHint got the height wrong and clipped the
        # credits; fixing the text width makes the height a simple sum.
        self.adjustSize()
