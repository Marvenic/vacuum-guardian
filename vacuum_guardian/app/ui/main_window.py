"""Janela principal (requisito 7): painel de status + logs + acoes.

Toda decisao vem pronta no CycleOutcome; aqui so ha renderizacao e repasse
de cliques para o AlarmController/engine. Fechar a janela minimiza para a
bandeja (o monitoramento continua em segundo plano); sair de verdade e pela
opcao "Sair" da bandeja.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PySide2.QtCore import QByteArray, Qt, Signal
from PySide2.QtGui import QCloseEvent, QFont, QIcon, QImage, QPainter, QPixmap
from PySide2.QtSvg import QSvgRenderer
from PySide2.QtWidgets import (
    QAction,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigService
from ..models import PumpState, RunPhase
from ..services.monitor import CycleOutcome, MonitorEngine
from ..utils import resource_path
from .about_dialog import AboutDialog
from .alarm_popup import AlarmPopup
from .calibration_guide import CalibrationGuideDialog
from .roi_selector import RoiSelectorDialog
from .settings_dialog import SettingsDialog
from .worker import MonitorWorker

_STATE_COLORS = {
    PumpState.ON: "#2e7d32",           # verde
    PumpState.OFF: "#c62828",          # vermelho
    PumpState.UNKNOWN: "#757575",      # cinza
    PumpState.NOT_VISIBLE: "#ef6c00",  # laranja: fora da tela, nao verificavel
}
# Texto amigavel: "NOT_VISIBLE" nao diz nada ao operador.
_STATE_LABELS = {
    PumpState.ON: "ON",
    PumpState.OFF: "OFF",
    PumpState.UNKNOWN: "UNREADABLE",
    PumpState.NOT_VISIBLE: "NOT ON SCREEN",
}


_ACCENT_OK = "#3ddc97"       # verde-agua: tudo sob controle
_ACCENT_ALARM = "#ff5252"    # vermelho: alarme critico
_ACCENT_WARN = "#ffa726"     # laranja: nao foi possivel verificar
_ACCENT_IDLE = "#9e9e9e"     # cinza: estado indefinido/sem leitura

_icon_cache: dict[str, QIcon] = {}


def _app_icon(accent: str) -> QIcon:
    """Icone do escudo tingido com a cor de estado.

    O SVG traz a cor como token {ACCENT}; aqui ele e substituido e renderizado
    em varias resolucoes. O resultado e cacheado porque esta funcao e chamada
    a cada ciclo de monitoramento.
    """
    cached = _icon_cache.get(accent)
    if cached is not None:
        return cached

    svg = resource_path("assets/icon.svg").read_text(encoding="utf-8").replace("{ACCENT}", accent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(QPixmap.fromImage(image))
    _icon_cache[accent] = icon
    return icon


class MainWindow(QMainWindow):
    log_line = Signal(str)  # sinal para entregar logs do loguru na thread da UI

    def __init__(self, engine: MonitorEngine, config_service: ConfigService, project_root: Path) -> None:
        super().__init__()
        self._engine = engine
        self._config_service = config_service
        self._root = project_root
        self._quitting = False
        self._restarting = False  # evita dois monitores em paralelo

        self.setWindowTitle("Vacuum Guardian")
        self.setWindowIcon(_app_icon(_ACCENT_OK))
        self._build_ui()
        self._build_tray()

        self._popup = AlarmPopup(
            on_acknowledge=self._engine.alarm.acknowledge,
            on_silence=self._engine.alarm.silence,
        )

        # Sink do loguru -> sinal Qt (conexao queued garante thread da UI).
        self.log_line.connect(self._append_log)
        logger.add(lambda msg: self.log_line.emit(str(msg).rstrip()), level="INFO")

        self._worker = MonitorWorker(engine, engine.config.capture_interval_s)
        self._worker.cycle_done.connect(self._on_cycle)
        self._worker.start()

    # -- construcao da UI --------------------------------------------------

    def _build_ui(self) -> None:
        font_value = QFont("Segoe UI", 14, QFont.Bold)

        self._lbl_indicators: dict[str, QLabel] = {}
        grid = QGridLayout()
        row = 0
        for ind in self._engine.config.indicators:
            grid.addWidget(QLabel(f"{ind.name}:"), row, 0)
            value = QLabel("—")
            value.setFont(font_value)
            grid.addWidget(value, row, 1)
            self._lbl_indicators[ind.name] = value
            row += 1

        self._lbl_program = QLabel("—")
        self._lbl_program.setFont(font_value)
        self._lbl_armed = QLabel("—")
        self._lbl_armed.setFont(font_value)
        self._lbl_monitoring = QLabel("Starting…")
        self._lbl_last = QLabel("—")
        self._lbl_fps = QLabel("—")
        for label_text, widget in [
            ("Program:", self._lbl_program),
            ("Machine state:", self._lbl_armed),
            ("Monitoring:", self._lbl_monitoring),
            ("Last detection:", self._lbl_last),
            ("FPS:", self._lbl_fps),
        ]:
            grid.addWidget(QLabel(label_text), row, 0)
            grid.addWidget(widget, row, 1)
            row += 1

        calibrate = QPushButton("Calibrate ROIs / Templates")
        calibrate.clicked.connect(self._open_calibration)
        settings = QPushButton("Settings")
        settings.clicked.connect(self._open_settings)
        guide = QPushButton("Calibration guide")
        guide.clicked.connect(self._open_guide)
        about = QPushButton("About")
        about.clicked.connect(self._open_about)
        buttons = QHBoxLayout()
        buttons.addWidget(calibrate)
        buttons.addWidget(guide)
        buttons.addWidget(settings)
        buttons.addWidget(about)
        buttons.addStretch()

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)  # limita memoria dos logs na tela

        layout = QVBoxLayout()
        layout.addLayout(grid)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Recent logs:"))
        layout.addWidget(self._log_view)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.resize(700, 500)

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(_app_icon(_ACCENT_OK), self)
        menu = QMenu()
        show_action = QAction("Open panel", menu)
        show_action.triggered.connect(self._show_from_tray)
        about_action = QAction("About", menu)
        about_action.triggered.connect(self._open_about)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("Vacuum Guardian - monitoring")
        self._tray.activated.connect(
            lambda reason: self._show_from_tray()
            if reason == QSystemTrayIcon.DoubleClick
            else None
        )
        self._tray.show()

    # -- ciclo de monitoramento -------------------------------------------

    def _on_cycle(self, outcome: CycleOutcome) -> None:
        """Renderiza um CycleOutcome (chamado via sinal, ja na thread da UI)."""
        for name, reading in outcome.result.indicators.items():
            label = self._lbl_indicators.get(name)
            if label is None:
                continue
            label.setText(_STATE_LABELS.get(reading.state, reading.state.value))
            label.setStyleSheet(f"color: {_STATE_COLORS.get(reading.state, '#757575')};")

        self._lbl_program.setText(outcome.result.program_name or "—")
        # Fase lida no campo Iso lines: e o unico gatilho do app.
        phase = outcome.result.run_phase
        if phase is RunPhase.RUNNING:
            text, colour = "RUNNING - vacuum required", "#c62828"
        elif phase is RunPhase.DOORS:
            text, colour = "CLOSE THE DOORS - check vacuum", "#e07000"
        else:
            text, colour = "stand-by", "#757575"
        self._lbl_armed.setText(text)
        self._lbl_armed.setStyleSheet(f"color: {colour};")
        self._lbl_monitoring.setText(
            f"Window: {outcome.window_title}" if outcome.window_title
            else "OSAI window not found (full screen)"
        )
        self._lbl_last.setText(
            f"{outcome.result.timestamp:%H:%M:%S} ({outcome.result.elapsed_ms:.0f} ms)"
        )
        self._lbl_fps.setText(f"{outcome.fps:.1f}")

        alarm_active = outcome.alarm.popup_should_show
        # Icone da bandeja reflete o estado sem precisar abrir o painel.
        if alarm_active:
            accent = _ACCENT_ALARM if outcome.alarm.is_critical else _ACCENT_WARN
        elif any(not r.state.is_verifiable for r in outcome.result.indicators.values()):
            accent = _ACCENT_IDLE
        else:
            accent = _ACCENT_OK
        self._tray.setIcon(_app_icon(accent))
        if alarm_active:
            self._popup.show_alarm(
                outcome.alarm.reason,
                outcome.result.program_name,
                outcome.alarm.sound_enabled,
                outcome.alarm.level,
            )
        elif self._popup.isVisible():
            self._popup.dismiss()

    def _append_log(self, line: str) -> None:
        self._log_view.appendPlainText(line)

    # -- acoes -------------------------------------------------------------

    def _open_calibration(self) -> None:
        """Captura um frame e abre o seletor de ROI; reinicia o monitor se mudou algo."""
        frame = self._engine.grab_frame()
        dialog = RoiSelectorDialog(
            frame,
            self._engine.config,
            self._root / "assets" / "templates",
            self._save_guide_language,
            self._engine.grab_frame,  # permite refotografar sem fechar a janela
        )
        dialog.exec_()
        if dialog.changed:
            self._config_service.save(self._engine.config)
            self._restart_monitor()

    def _open_guide(self) -> None:
        """Guia de calibracao avulso - para ler antes de abrir a calibracao."""
        CalibrationGuideDialog(
            self._engine.config,
            self._root / "assets" / "templates",
            self._save_guide_language,
        ).exec_()

    def _save_guide_language(self, language: str) -> None:
        """Persiste a escolha EN/PT do operador.

        Grava direto, sem reiniciar o monitor: idioma do guia nao afeta
        deteccao, e reiniciar por causa disso interromperia a vigilancia.
        """
        self._engine.config.guide_language = language
        self._config_service.save(self._engine.config)

    def _open_about(self) -> None:
        """Creditos do aplicativo; acessivel tambem pela bandeja."""
        AboutDialog(_app_icon(_ACCENT_OK)).exec_()

    def _open_settings(self) -> None:
        """Abre as configuracoes; salvar reinicia o monitor com os novos valores."""
        dialog = SettingsDialog(self._engine.config)
        if dialog.exec_() and dialog.result_config is not None:
            self._config_service.save(dialog.result_config)
            self._restart_monitor()

    def _restart_monitor(self) -> None:
        """Reinicia o monitor SEM travar a interface.

        A versao anterior fazia `worker.stop()` (espera bloqueante de 3 s) na
        thread da UI. Quando um ciclo demorava mais que isso - o que acontece
        no PC da CNC, onde o OCR varre a tela inteira - a janela congelava e,
        pior, a thread antiga era abandonada ainda rodando: ficavam duas
        varreduras simultaneas disputando a CPU, e cada recalibracao somava
        mais uma.

        Agora: pede a parada, devolve o controle a UI na hora e so monta o
        novo motor quando a thread antiga realmente terminou.
        """
        if self._restarting:
            return  # dois cliques seguidos nao podem criar dois monitores
        self._restarting = True
        logger.info("Restarting monitoring with the new configuration")

        old_worker, old_engine = self._worker, self._engine
        old_worker.request_stop()
        # A referencia fica guardada ate o fim: destruir uma QThread rodando
        # aborta o processo.
        old_worker.finished.connect(lambda: self._start_monitor(old_worker, old_engine))
        if not old_worker.isRunning():
            self._start_monitor(old_worker, old_engine)

    def _start_monitor(self, old_worker: MonitorWorker, old_engine: MonitorEngine) -> None:
        """Fecha o motor antigo e sobe o novo. Chamado quando a thread termina."""
        if not self._restarting:
            return  # o sinal `finished` pode chegar duas vezes
        self._restarting = False
        old_engine.close()  # so agora: o motor nao esta mais em uso
        old_worker.deleteLater()

        config = self._config_service.load()
        self._engine = MonitorEngine(config, self._root)
        self._popup._on_acknowledge = self._engine.alarm.acknowledge  # rebind dos botoes
        self._popup._on_silence = self._engine.alarm.silence
        self._build_ui()  # a lista de indicadores pode ter mudado
        self._worker = MonitorWorker(self._engine, config.capture_interval_s)
        self._worker.cycle_done.connect(self._on_cycle)
        self._worker.start()
        logger.info("Monitoring restarted")

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self._worker.stop()
        self._engine.close()
        self._tray.hide()
        from PySide2.QtWidgets import QApplication

        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Fechar = minimizar para a bandeja; o monitoramento continua (segundo plano)."""
        if self._quitting:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "Vacuum Guardian",
            "Still monitoring in the background. Use 'Exit' in the tray to quit.",
            QSystemTrayIcon.Information,
            3000,
        )
