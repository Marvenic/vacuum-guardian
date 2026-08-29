"""MonitorEngine: orquestra um ciclo completo captura -> deteccao -> regras -> alarme.

Sem nenhuma dependencia de Qt: a UI (ou um teste) chama run_cycle() no ritmo
que quiser e recebe um CycleOutcome pronto para exibir. Isso mantem toda a
sequencia de negocio testavel e reaproveitavel (ex.: modo headless futuro).
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
from ..logging import DetectionLog, OverrideLog
from ..models import AlarmDecision, AppConfig, DetectionResult, PumpState, RunPhase
from ..utils import resource_path
from ..vision.ocr import TextReader
from .rule_engine import RuleEngine


class NullReader:
    """TextReader inerte, usado se o OCR nativo indisponivel (app sobe mesmo assim)."""

    def read_text(self, roi_bgr) -> str:  # type: ignore[no-untyped-def]
        return ""


@dataclass(frozen=True)
class CycleOutcome:
    """Tudo que a UI precisa para atualizar uma iteracao do painel."""

    result: DetectionResult
    decision: AlarmDecision
    alarm: AlarmStatus
    window_title: str | None  # None = fallback de tela inteira
    fps: float


class MonitorEngine:
    def __init__(self, config: AppConfig, project_root: Path) -> None:
        self._config = config
        self._root = project_root
        # Templates sao gravados pela calibracao -> pasta gravavel ao lado do .exe.
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
        self._rules = RuleEngine(config.trigger_programs, config.critical_indicator)
        # O WAV padrao e recurso EMPACOTADO (fica em _internal/ no executavel),
        # enquanto os templates sao GRAVAVEIS e ficam ao lado do .exe - por isso
        # os dois caminhos sao resolvidos de formas diferentes.
        wav = Path(config.alarm_wav) if config.alarm_wav else resource_path("assets/alarm.wav")
        if not config.alarm_sound_enabled:
            logger.info("Alarm sound disabled in settings - visual alarm only")
        elif not wav.exists():
            logger.error("Alarm sound not found at {} - the system beep will be used", wav)
        else:
            logger.info("Alarm sound: {}", wav)
        self.alarm = AlarmController(WinSoundPlayer(), wav, config.alarm_sound_enabled)
        self._detection_log = DetectionLog(project_root / "logs" / "detections.csv")
        self._override_log = OverrideLog(project_root / "logs" / "overrides.csv")
        self._last_phase = RunPhase.IDLE
        self._last_cycle: float | None = None
        self._fps = 0.0

    @property
    def config(self) -> AppConfig:
        return self._config

    def run_cycle(self) -> CycleOutcome:
        """Executa um ciclo; nunca lanca excecao (loga e devolve estado neutro via UNKNOWN)."""
        now = time.perf_counter()
        if self._last_cycle is not None and now > self._last_cycle:
            # Media movel simples para o FPS nao "pular" a cada ciclo.
            instant = 1.0 / (now - self._last_cycle)
            self._fps = instant if self._fps == 0.0 else (self._fps * 0.7 + instant * 0.3)
        self._last_cycle = now

        frame, window = self._capture.grab()
        result = self._detection.detect(frame)
        decision = self._rules.evaluate(result)
        alarm_status = self.alarm.update(decision)
        self._detection_log.record(result, decision)  # grava apenas transicoes
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
        """Grava o momento em que o operador partiu com o vacuo fora de ON.

        So na TRANSICAO DOORS -> RUNNING: e ali que ele viu o aviso e seguiu
        assim mesmo. Depois disso o alarme continua, mas o evento ja foi
        registrado - o gerente quer um evento por partida, nao um por ciclo.
        """
        previous, current = self._last_phase, result.run_phase
        self._last_phase = current
        if not (previous is RunPhase.DOORS and current is RunPhase.RUNNING):
            return
        critical = self._rules.critical_indicator
        reading = result.indicators.get(critical)
        state = reading.state if reading is not None else PumpState.NOT_VISIBLE
        if state is PumpState.ON:
            return  # partiu com o vacuo ligado: nada a registrar
        self._override_log.record(
            result.timestamp, result.program_name, critical, state.value
        )

    def grab_frame(self):  # type: ignore[no-untyped-def]
        """Frame avulso para a tela de calibracao (np.ndarray BGR)."""
        frame, _ = self._capture.grab()
        return frame

    def close(self) -> None:
        self.alarm.update(AlarmDecision(False, (), ()))  # garante som desligado
        self._capture.close()
