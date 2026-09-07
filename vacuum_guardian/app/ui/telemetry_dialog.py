"""Consent dialog for the optional usage report, plus the operator card.

Design rules, in order of importance:

1. The checkbox starts UNTICKED. Consent is given, never assumed.
2. The operator can read the exact JSON that would leave the machine - the
   "Show what is sent" box holds the real payload, not a description of it.
3. The operator card (company, name, email, phone) is optional and clearly
   separate from the anonymous counters. Empty fields are simply not sent.

Reachable again at any time from the tray menu, so the answer is never final.
"""

from __future__ import annotations

import json

from PySide2.QtCore import Qt
from PySide2.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..models import AppConfig


class TelemetryDialog(QDialog):
    """Asks to share usage data and collects the optional operator details."""

    def __init__(self, config: AppConfig, payload: dict, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Help improve Vacuum Guardian")

        intro = QLabel(
            "Vacuum Guardian is free. Sharing anonymous usage data helps us see "
            "which Windows versions and regions to support, and how much the app "
            "is really used on a machine.\n\n"
            "It never sends screen contents, program names or file paths, and it "
            "does not look up your location on the internet - the country comes "
            "from your own Windows region setting."
        )
        intro.setWordWrap(True)

        self._share = QCheckBox("Share anonymous usage data")
        self._share.setChecked(config.telemetry_enabled)

        preview = QPlainTextEdit(json.dumps(payload, indent=2))
        preview.setReadOnly(True)
        preview.setFixedHeight(150)
        preview_box = QGroupBox("What is sent")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(preview)

        self._company = QLineEdit(config.operator_company)
        self._name = QLineEdit(config.operator_name)
        self._email = QLineEdit(config.operator_email)
        self._phone = QLineEdit(config.operator_phone)
        for field in (self._company, self._name, self._email, self._phone):
            field.setPlaceholderText("optional")

        card = QGroupBox("Operator card (optional)")
        card_form = QFormLayout(card)
        card_form.addRow(
            QLabel(
                "Fill this in only if you want us to be able to reach you about "
                "the app. Leave it empty and nothing personal is sent."
            )
        )
        card_form.addRow("Company:", self._company)
        card_form.addRow("Name:", self._name)
        card_form.addRow("Email:", self._email)
        card_form.addRow("Phone:", self._phone)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self._share)
        layout.addWidget(preview_box)
        layout.addWidget(card)
        layout.addWidget(buttons)
        self.setMinimumWidth(560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

    def _apply(self) -> None:
        """Writes the answer into the config the caller will persist."""
        self._config.telemetry_enabled = self._share.isChecked()
        self._config.operator_company = self._company.text().strip()
        self._config.operator_name = self._name.text().strip()
        self._config.operator_email = self._email.text().strip()
        self._config.operator_phone = self._phone.text().strip()
        # Asked once: the dialog does not come back on every start, whatever
        # the answer was.
        self._config.telemetry_prompted = True
        self.accept()
