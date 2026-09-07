"""MonitorEngine: one full cycle of capture -> detection -> rules -> alarm.

No Qt dependency: the UI (or a test) calls run_cycle() at whatever pace it
likes and gets a CycleOutcome ready to display. That keeps the whole
business sequence testable and reusable (a headless mode, for instance).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..alarm import AlarmController, AlarmStatus, WinSoundPlayer
from ..capture import ScreenCapture, WindowLocator
from ..detection import DetectionService
from ..detection.arming import IsoLineWatcher
from ..detection.service import build_finders, build_matchers
from ..logging import AlarmActionLog, DetectionLog, OverrideLog
from ..models import AlarmDecision, AppConfig, DetectionResult, PumpState, RunPhase
from ..utils import resource_path
from ..vision.ocr import TextReader
from .rule_engine import RuleEngine
from .telemetry import TelemetryService


class NullReader:
    """Inert TextReader used when native OCR is missing (the app still starts)."""

    def read_text(self, roi_bgr) -> str:  # type: ignore[no-untyped-def]
        return ""


@dataclass(frozen=True)
class CycleOutcome:
    """Everything the UI needs to refresh one iteration of the panel."""

    result: DetectionResult
    decision: AlarmDecision
    alarm: AlarmStatus
    window_title: str | None  # None = full-screen fallback
    fps: float


class MonitorEngine:
    def __init__(self, config: AppConfig, project_root: Path) -> None:
        self._config = config
        self._root = project_root
        # Templates are written by calibration -> writable folder beside the .exe.
        templates_dir = project_root / "assets" / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

        self._capture = ScreenCapture(WindowLocator(config.window_title_hint))
        reader: TextReader
        try:
            from ..vision import WindowsOcrReader

            reader = WindowsOcrReader()
        except Exception as exc:
            logger.error("Native OCR unavailable ({}) - program name will stay empty", exc)
            reader = NullReader()
        self._detection = DetectionService(
            matchers=build_matchers(templates_dir, config.template_threshold, config.indicators),
            reader=reader,
            indicators=config.indicators,
            program_roi=config.program_roi,
            finders=build_finders(templates_dir, config),
            iso_watcher=IsoLineWatcher(config.close_doors_keyword) if config.iso_roi else None,
            iso_roi=config.iso_roi,
        )
        # With no calibrated "Iso lines" area there is no trigger: the app runs,
        # mostra os indicadores e NUNCA alarma. Falhar em silencio num app
        # de seguranca e inaceitavel - registra alto e claro.
        self.trigger_ready = bool(config.iso_roi and config.iso_roi.is_valid())
        if not self.trigger_ready:
            logger.warning(
                "Iso lines area NOT calibrated - no alarm can ever fire. "
                "Run the calibration wizard and capture the Iso lines area."
            )
        self._rules = RuleEngine(config.trigger_programs, config.critical_indicator)
        # The default WAV is a BUNDLED resource (it lives in _internal/ in the
        # executable), while templates are WRITABLE and sit beside the .exe - so
        # the two paths are resolved differently.
        wav = Path(config.alarm_wav) if config.alarm_wav else resource_path("assets/alarm.wav")
        if not config.alarm_sound_enabled:
            logger.info("Alarm sound disabled in settings - visual alarm only")
        elif not wav.exists():
            logger.error("Alarm sound not found at {} - the system beep will be used", wav)
        else:
            logger.info("Alarm sound: {}", wav)
        self.alarm = AlarmController(
            WinSoundPlayer(),
            wav,
            config.alarm_sound_enabled,
            AlarmActionLog(project_root / "logs" / "alarm_actions.csv"),
        )
        self.telemetry = TelemetryService(config, project_root)
        self._detection_log = DetectionLog(project_root / "logs" / "detections.csv")
        self._override_log = OverrideLog(project_root / "logs" / "overrides.csv")
        self._last_phase = RunPhase.IDLE
        self._last_cycle: float | None = None
        self._fps = 0.0
        # Rectangle (in SCREEN coordinates) of one of our own windows that is
        # covering OSAI. The UI reports it; the cycle uses it to avoid reading
        # the alarm popup's own pixels.
        self._occlusion: tuple[int, int, int, int] | None = None

    def set_occlusion(self, rect: tuple[int, int, int, int] | None) -> None:
        """Reports that one of our windows covers the screen (x, y, w, h).

        Called by the UI when the alarm popup is shown or hidden. A plain
        assignment: there is no dangerous race between the threads here, and a
        reading that is one cycle stale does no harm.
        """
        self._occlusion = rect

    def _iso_is_covered(self, window) -> bool:  # type: ignore[no-untyped-def]
        """Is the Iso lines ROI underneath one of our own windows?"""
        roi = self._config.iso_roi
        if self._occlusion is None or roi is None or not roi.is_valid():
            return False
        # The ROI is relative to the captured frame; convert to screen coords.
        offset_x, offset_y = (window.left, window.top) if window else (0, 0)
        left, top = roi.x + offset_x, roi.y + offset_y
        right, bottom = left + roi.width, top + roi.height
        ox, oy, ow, oh = self._occlusion
        return not (right <= ox or left >= ox + ow or bottom <= oy or top >= oy + oh)

    @property
    def config(self) -> AppConfig:
        return self._config

    def run_cycle(self) -> CycleOutcome:
        """Runs one cycle; never raises (logs and returns a neutral UNKNOWN state)."""
        now = time.perf_counter()
        if self._last_cycle is not None and now > self._last_cycle:
            # Simple moving average so the FPS figure does not jump every cycle.
            instant = 1.0 / (now - self._last_cycle)
            self._fps = instant if self._fps == 0.0 else (self._fps * 0.7 + instant * 0.3)
        self._last_cycle = now

        frame, window = self._capture.grab()
        result = self._detection.detect(frame, freeze_phase=self._iso_is_covered(window))
        decision = self._rules.evaluate(result)
        alarm_status = self.alarm.update(decision)
        self._detection_log.record(result, decision)  # grava apenas transicoes
        # Usage report counters (only ever sent with consent).
        self.telemetry.note_cycle(window is not None)
        if alarm_status.popup_should_show:
            self.telemetry.note_alarm()
        self.telemetry.maybe_send()
        self._record_override(result)

        logger.debug(
            "cycle: program='{}' phase={} indicators={} alarm={}/{} {:.0f}ms",
            result.program_name,
            result.run_phase.value,
            {k: v.state.value for k, v in result.indicators.items()},
            alarm_status.active,
            alarm_status.level.name,
            result.elapsed_ms,
        )
        return CycleOutcome(
            result=result,
            decision=decision,
            alarm=alarm_status,
            window_title=window.title if window else None,
            fps=self._fps,
        )

    def _record_override(self, result: DetectionResult) -> None:
        """Records the moment the operator started with the vacuum not ON.

        Only on the DOORS -> RUNNING transition: that is where the warning was
        seen and ignored. The alarm keeps going afterwards, but the event is
        already recorded - a manager wants one event per start, not per cycle.
        """
        previous, current = self._last_phase, result.run_phase
        self._last_phase = current
        if not (previous is RunPhase.DOORS and current is RunPhase.RUNNING):
            return
        critical = self._rules.critical_indicator
        reading = result.indicators.get(critical)
        state = reading.state if reading is not None else PumpState.NOT_VISIBLE
        if state is PumpState.ON:
            return  # started with the vacuum on: nothing to record
        self.telemetry.note_override()
        self._override_log.record(
            result.timestamp, result.program_name, critical, state.value
        )

    def grab_frame(self):  # type: ignore[no-untyped-def]
        """A one-off frame for the calibration screen (BGR np.ndarray)."""
        frame, _ = self._capture.grab()
        return frame

    def close(self) -> None:
        self.alarm.update(AlarmDecision(False, (), ()))  # garante som desligado
        self._capture.close()
