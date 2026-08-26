"""Tela de configuracoes (requisito 9).

Edita uma COPIA da AppConfig; so no "Salvar" a copia substitui a original e
e persistida. Isso evita que um cancelamento deixe o monitor rodando com
valores parcialmente alterados.

A validacao de faixa fica aqui (limites de widget), mas nenhuma regra de
negocio: a janela nao sabe o que e alarme, apenas quais campos existem.
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide2.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..models import AppConfig, IndicatorConfig
from ..utils import AutoStart


class SettingsDialog(QDialog):
    """Dialogo de configuracoes; leia `result_config` apos exec() == Accepted."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.setWindowTitle("Settings - Vacuum Guardian")
        self._draft = copy.deepcopy(config)  # edicao isolada ate o Salvar
        self.result_config: AppConfig | None = None

        self._title = QLineEdit(self._draft.window_title_hint)
        self._title.setToolTip("Part of the title of the OSAI window to monitor")

        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.2, 30.0)
        self._interval.setSingleStep(0.1)
        self._interval.setSuffix(" s")
        self._interval.setValue(self._draft.capture_interval_s)
        self._interval.setToolTip("Delay between detection cycles")

        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.30, 0.99)
        self._threshold.setSingleStep(0.01)
        self._threshold.setDecimals(2)
        self._threshold.setValue(self._draft.template_threshold)
        self._threshold.setToolTip(
            "Minimum template matching score. Too high = UNKNOWN readings; "
            "too low = risk of mistaking ON for OFF."
        )

        self._programs = QPlainTextEdit("\n".join(self._draft.trigger_programs))
        self._programs.setToolTip("One word per line; a match anywhere in the program name is enough")
        self._programs.setFixedHeight(90)

        self._indicators = QPlainTextEdit("\n".join(i.name for i in self._draft.indicators))
        self._indicators.setToolTip(
            "One indicator per line (e.g. Vacuum Pump 1, Vacuum 1).\n"
            "Renaming or adding one requires recalibrating its ROI and templates."
        )
        self._indicators.setFixedHeight(70)

        # Indicador que precisa estar ON no momento critico. Fica em campo
        # proprio porque a regra principal gira toda em torno dele.
        self._critical = QLineEdit(self._draft.critical_indicator)
        self._critical.setToolTip(
            "Indicator that must be ON once the program starts cutting "
            "(must match one of the names above)."
        )

        self._arming = QCheckBox("Alarm only after the OSAI confirmations")
        self._arming.setChecked(self._draft.arming_enabled)
        self._arming.setToolTip(
            "Watches for MATERIAL THICKNESS and EXCEEDING MATERIAL. The alarm "
            "only arms after both are confirmed - that is when the stone moves.\n"
            "Turning this off falls back to matching the program name."
        )

        # Autostart nao vive no config.json: seu estado real e a existencia do
        # atalho na pasta Startup, entao lemos e escrevemos direto de la.
        self._autostart = AutoStart()
        self._autostart_check = QCheckBox("Start automatically with Windows")
        self._autostart_check.setChecked(self._autostart.is_enabled())

        # Som opcional: fabricas barulhentas / PC da CNC sem alto-falante.
        self._sound_check = QCheckBox("Play alarm sound")
        self._sound_check.setChecked(self._draft.alarm_sound_enabled)
        self._sound_check.setToolTip(
            "The visual alarm always shows, with or without sound."
        )

        self._wav = QLineEdit(self._draft.alarm_wav)
        self._wav.setPlaceholderText("(empty = built-in alarm.wav)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_wav)
        wav_row = QHBoxLayout()
        wav_row.addWidget(self._wav)
        wav_row.addWidget(browse)

        # Escolher um WAV so faz sentido com o som ligado.
        def _sync_wav_row(enabled: bool) -> None:
            self._wav.setEnabled(enabled)
            browse.setEnabled(enabled)

        self._sound_check.toggled.connect(_sync_wav_row)
        _sync_wav_row(self._sound_check.isChecked())

        form = QFormLayout()
        form.addRow("Window title (substring):", self._title)
        form.addRow("Capture interval:", self._interval)
        form.addRow("Template threshold:", self._threshold)
        form.addRow("Monitored programs:", self._programs)
        form.addRow("Indicators:", self._indicators)
        form.addRow("Critical indicator:", self._critical)
        form.addRow("Trigger:", self._arming)
        form.addRow("Alarm sound:", self._sound_check)
        form.addRow("Sound file (WAV):", wav_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._autostart_check)
        layout.addWidget(
            QLabel("ROIs and templates are defined in the Calibration screen.")
        )
        layout.addWidget(buttons)
        self.resize(560, 420)

    def _pick_wav(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose alarm sound", "", "WAV (*.wav)")
        if path:
            self._wav.setText(path)

    def _apply(self) -> None:
        """Transfere os widgets para o rascunho e conclui o dialogo."""
        self._draft.window_title_hint = self._title.text().strip()
        self._draft.capture_interval_s = float(self._interval.value())
        self._draft.template_threshold = float(self._threshold.value())
        self._draft.trigger_programs = [
            line.strip().upper() for line in self._programs.toPlainText().splitlines() if line.strip()
        ]

        # Indicadores: preserva a ROI ja calibrada dos que mantiveram o nome.
        existing = {i.name: i for i in self._draft.indicators}
        names = [line.strip() for line in self._indicators.toPlainText().splitlines() if line.strip()]
        self._draft.indicators = [
            existing.get(name, IndicatorConfig(name)) for name in names
        ] or self._draft.indicators

        critical = self._critical.text().strip()
        self._draft.critical_indicator = critical or self._draft.critical_indicator
        self._draft.arming_enabled = self._arming.isChecked()

        self._draft.alarm_sound_enabled = self._sound_check.isChecked()
        wav = self._wav.text().strip()
        self._draft.alarm_wav = wav if not wav or Path(wav).exists() else ""

        # Aplica o autostart apenas se o usuario mudou a opcao.
        desired = self._autostart_check.isChecked()
        if desired != self._autostart.is_enabled():
            self._autostart.set_enabled(desired)
        self.result_config = self._draft
        self.accept()
