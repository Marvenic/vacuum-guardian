"""Main window: status panel, recent logs and actions.

Every decision arrives ready in the CycleOutcome; this file only renders and
forwards clicks to the AlarmController and engine. Closing the window
minimises to the tray (monitoring continues in the background); quitting for
real is the tray's "Exit" entry.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PySide2.QtCore import QByteArray, Qt, QTimer, Signal
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
from ..services.telemetry import new_install_id
from ..utils import resource_path
from .about_dialog import AboutDialog
from .alarm_popup import AlarmPopup
from .calibration_guide import CalibrationGuideDialog
from .roi_selector import RoiSelectorDialog
from .settings_dialog import SettingsDialog
from .telemetry_dialog import TelemetryDialog
from .worker import MonitorWorker

_STATE_COLORS = {
    PumpState.ON: "#2e7d32",           # verde
    PumpState.OFF: "#c62828",          # vermelho
    PumpState.UNKNOWN: "#757575",      # cinza
    PumpState.NOT_VISIBLE: "#ef6c00",  # orange: off screen, not verifiable
}
# Friendly wording: "NOT_VISIBLE" means nothing to an operator.
_STATE_LABELS = {
    PumpState.ON: "ON",
    PumpState.OFF: "OFF",
    PumpState.UNKNOWN: "UNREADABLE",
    PumpState.NOT_VISIBLE: "NOT ON SCREEN",
}


_ACCENT_OK = "#3ddc97"       # verde-agua: tudo sob controle
_ACCENT_WARN = "#ffa726"     # laranja: nao foi possivel verificar
_ACCENT_IDLE = "#9e9e9e"     # cinza: estado indefinido/sem leitura

_icon_cache: dict[str, QIcon] = {}


def _app_icon(accent: str) -> QIcon:
    """The shield icon tinted with the state colour.

    The SVG carries the colour as an {ACCENT} token; it is substituted here and
    rendered at several sizes. The result is cached because this function is
    called on every monitoring cycle.
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

        self._popup = AlarmPopup(on_acknowledge=self._engine.alarm.acknowledge)

        # loguru sink -> Qt signal (a queued connection lands on the UI thread).
        self.log_line.connect(self._append_log)
        logger.add(lambda msg: self.log_line.emit(str(msg).rstrip()), level="INFO")

        self._worker = MonitorWorker(engine, engine.config.capture_interval_s)
        self._worker.cycle_done.connect(self._on_cycle)
        self._worker.start()

        # Usage-report question: asked once, and only after the window is built
        # (asking earlier would put a dialog over an empty screen).
        # It only asks if there IS somewhere to send: with no telemetry_url the
        # consent would have no effect and the question would just annoy.
        if not engine.config.telemetry_prompted and engine.config.telemetry_url.strip():
            QTimer.singleShot(1500, lambda: self._open_telemetry(first_run=True))

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
        usage_action = QAction("Usage data…", menu)
        usage_action.triggered.connect(self._open_telemetry)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addAction(usage_action)
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
        """Renders a CycleOutcome (called via signal, already on the UI thread)."""
        for name, reading in outcome.result.indicators.items():
            label = self._lbl_indicators.get(name)
            if label is None:
                continue
            label.setText(_STATE_LABELS.get(reading.state, reading.state.value))
            label.setStyleSheet(f"color: {_STATE_COLORS.get(reading.state, '#757575')};")

        self._lbl_program.setText(outcome.result.program_name or "—")
        # Phase read from the Iso lines field: the app's only trigger.
        phase = outcome.result.run_phase
        if phase is RunPhase.RUNNING:
            text, colour = "RUNNING - vacuum required", "#c62828"
        elif phase is RunPhase.DOORS:
            text, colour = "CLOSE THE DOORS - check vacuum", "#e07000"
        elif not getattr(self._engine, "trigger_ready", True):
            # Without a calibrated Iso lines area the alarm never fires; saying
            # "stand-by" here would suggest everything is ready.
            text, colour = "NOT CALIBRATED - alarm disabled", "#c62828"
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
        # The tray icon shows the state without opening the panel.
        if alarm_active:
            accent = _ACCENT_WARN
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
            )
        elif self._popup.isVisible():
            self._popup.dismiss()
        # The popup covers the OSAI screen: tell the engine not to read the
        # warning's own pixels as if they were the Iso lines field.
        self._report_occlusion()

    def _report_occlusion(self) -> None:
        """Reports the popup rectangle to the engine, or None once it is gone."""
        if self._popup.isVisible():
            frame = self._popup.frameGeometry()
            self._engine.set_occlusion(
                (frame.x(), frame.y(), frame.width(), frame.height())
            )
        else:
            self._engine.set_occlusion(None)

    def _append_log(self, line: str) -> None:
        self._log_view.appendPlainText(line)

    # -- acoes -------------------------------------------------------------

    def _open_calibration(self) -> None:
        """Grabs a frame and opens the ROI selector; restarts the monitor if changed."""
        frame = self._engine.grab_frame()
        dialog = RoiSelectorDialog(
            frame,
            self._engine.config,
            self._root / "assets" / "templates",
            self._save_guide_language,
            self._engine.grab_frame,  # allows re-shooting without closing the window
        )
        dialog.exec_()
        if dialog.changed:
            self._config_service.save(self._engine.config)
            self._restart_monitor()

    def _open_guide(self) -> None:
        """Stand-alone calibration guide - to read before starting calibration."""
        CalibrationGuideDialog(
            self._engine.config,
            self._root / "assets" / "templates",
            self._save_guide_language,
        ).exec_()

    def _save_guide_language(self, language: str) -> None:
        """Persists the operator's EN/PT choice.

        Saved directly, without restarting the monitor: the guide language does
        not affect detection, and restarting would interrupt the watch.
        """
        self._engine.config.guide_language = language
        self._config_service.save(self._engine.config)

    def _open_telemetry(self, first_run: bool = False) -> None:
        """Usage-report consent plus the optional operator card.

        Called once on first run and whenever the operator wants to change their
        mind from the tray menu.
        """
        config = self._engine.config
        if not config.install_id:
            config.install_id = new_install_id()
        dialog = TelemetryDialog(config, self._engine.telemetry.payload(), self)
        if dialog.exec_():
            self._config_service.save(config)
        elif first_run:
            # Closed with the X: do not ask again, and send nothing.
            config.telemetry_prompted = True
            self._config_service.save(config)

    def _open_about(self) -> None:
        """Application credits; also reachable from the tray."""
        AboutDialog(_app_icon(_ACCENT_OK)).exec_()

    def _open_settings(self) -> None:
        """Opens settings; saving restarts the monitor with the new values."""
        dialog = SettingsDialog(self._engine.config)
        if dialog.exec_() and dialog.result_config is not None:
            self._config_service.save(dialog.result_config)
            self._restart_monitor()

    def _restart_monitor(self) -> None:
        """Restarts the monitor WITHOUT freezing the interface.

        The previous version called `worker.stop()` (a blocking 3 s wait) on the
        UI thread. When a cycle took longer than that - which happens on the CNC
        PC - the window froze and, worse, the old thread was ABANDONED while
        still running: two scans then competed for the CPU, and every
        recalibration added another one.
        

        Now: it asks the thread to stop, returns to the UI at once, and only
        builds the new engine once the old thread has really finished.
        """
        if self._restarting:
            return  # two quick clicks must not create two monitors
        self._restarting = True
        logger.info("Restarting monitoring with the new configuration")

        old_worker, old_engine = self._worker, self._engine
        old_worker.request_stop()
        # The reference is kept to the end: destroying a running QThread
        # aborts the process.
        old_worker.finished.connect(lambda: self._start_monitor(old_worker, old_engine))
        if not old_worker.isRunning():
            self._start_monitor(old_worker, old_engine)

    def _start_monitor(self, old_worker: MonitorWorker, old_engine: MonitorEngine) -> None:
        """Closes the old engine and starts the new one, once the thread ends."""
        if not self._restarting:
            return  # the `finished` signal can arrive twice
        self._restarting = False
        old_engine.close()  # only now: the engine is no longer in use
        old_worker.deleteLater()

        config = self._config_service.load()
        self._engine = MonitorEngine(config, self._root)
        self._popup._on_acknowledge = self._engine.alarm.acknowledge  # rebind
        self._build_ui()  # the indicator list may have changed
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
        """Closing minimises to the tray; monitoring continues in the background."""
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
