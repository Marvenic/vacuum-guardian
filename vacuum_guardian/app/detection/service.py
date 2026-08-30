"""DetectionService: transforma um frame bruto em um DetectionResult.

Responsabilidade unica: recortar as ROIs configuradas e delegar
- estado de cada indicador  -> TemplateMatcher (ROI fixa) ou IndicatorFinder
                               (busca por rotulo, tolerante a rolagem)
- nome do programa          -> TextReader (OCR)
- fase da execucao          -> TextReader (OCR) + IsoLineWatcher
Nao conhece mss, Qt nem regras de alarme; recebe dependencias prontas
(injecao de dependencia), o que permite testar com imagens sinteticas.

Templates por indicador seguem a convencao de nomes:
    assets/templates/<slug>_on.png        e  <slug>_off.png        (ROI fixa)
    assets/templates/<slug>_label.png                              (rotulo)
    assets/templates/<slug>_toggle_on.png e  <slug>_toggle_off.png (amostras)
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import numpy as np
from loguru import logger

from ..models import (
    AppConfig,
    DetectionResult,
    IndicatorConfig,
    IndicatorReading,
    PumpState,
    Roi,
    RunPhase,
)
from ..vision import TemplateMatcher
from ..vision.finder import IndicatorFinder
from ..vision.ocr import TextReader
from .arming import IsoLineWatcher


def build_matchers(
    templates_dir: Path, threshold: float, indicators: list[IndicatorConfig]
) -> dict[str, TemplateMatcher]:
    """Cria um TemplateMatcher por indicador, usando a convencao <slug>_on/off.png."""
    return {
        ind.name: TemplateMatcher(
            on_path=templates_dir / f"{ind.slug}_on.png",
            off_path=templates_dir / f"{ind.slug}_off.png",
            threshold=threshold,
        )
        for ind in indicators
    }


def build_finders(
    templates_dir: Path, config: AppConfig
) -> dict[str, IndicatorFinder]:
    """Cria um IndicatorFinder para cada indicador que tenha geometria de toggle.

    So entram os indicadores calibrados no modo "busca por rotulo"; os demais
    continuam no modo ROI fixa.
    """
    finders: dict[str, IndicatorFinder] = {}
    for ind in config.indicators:
        if ind.toggle is None:
            continue
        finder = IndicatorFinder(
            label_path=templates_dir / f"{ind.slug}_label.png",
            toggle=ind.toggle,
            threshold=config.label_threshold,
            on_sample_path=templates_dir / f"{ind.slug}_toggle_on.png",
            off_sample_path=templates_dir / f"{ind.slug}_toggle_off.png",
        )
        if finder.ready:
            finders[ind.name] = finder
        else:
            logger.warning("Label search for '{}' not ready (calibration pending)", ind.name)
    return finders


class DetectionService:
    def __init__(
        self,
        matchers: dict[str, TemplateMatcher],
        reader: TextReader,
        indicators: list[IndicatorConfig],
        program_roi: Roi | None,
        finders: dict[str, IndicatorFinder] | None = None,
        iso_watcher: IsoLineWatcher | None = None,
        iso_roi: Roi | None = None,
    ) -> None:
        self._matchers = matchers
        self._reader = reader
        self._indicators = indicators
        self._program_roi = program_roi
        self._finders = finders or {}
        self._iso_watcher = iso_watcher
        self._iso_roi = iso_roi

    @staticmethod
    def _crop(frame: np.ndarray, roi: Roi) -> np.ndarray | None:
        """Recorta a ROI do frame; None se a ROI sair dos limites (janela redimensionada)."""
        height, width = frame.shape[:2]
        if roi.x + roi.width > width or roi.y + roi.height > height:
            logger.warning(
                "ROI {} is outside the {}x{} frame - recalibration needed",
                roi, width, height,
            )
            return None
        return frame[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]

    def _read_indicator(self, frame: np.ndarray, ind: IndicatorConfig) -> IndicatorReading:
        """Le um indicador; qualquer impedimento resulta em estado nao verificavel."""
        # Modo preferencial: busca pelo rotulo (funciona com o menu rolado).
        finder = self._finders.get(ind.name)
        if finder is not None:
            found = finder.read(frame)
            return IndicatorReading(found.state, found.confidence)

        # Modo legado: ROI fixa + templates ON/OFF.
        if ind.roi is None or not ind.roi.is_valid():
            return IndicatorReading(PumpState.UNKNOWN, 0.0)
        crop = self._crop(frame, ind.roi)
        if crop is None:
            return IndicatorReading(PumpState.UNKNOWN, 0.0)
        matcher = self._matchers.get(ind.name)
        if matcher is None:
            return IndicatorReading(PumpState.UNKNOWN, 0.0)
        match = matcher.match(crop)
        return IndicatorReading(match.state, match.confidence)

    def _update_iso(self, frame: np.ndarray, freeze: bool = False) -> RunPhase:
        """Le o campo Iso lines (ROI pequena) e atualiza a fase da largada.

        `freeze=True` devolve a fase atual SEM ler nada. Usado quando algo
        cobre o campo na tela - inclusive o proprio popup de alarme. Sem isso
        o app lia os pixels do proprio aviso, via um texto diferente de
        "CLOSE THE DOORS" e concluia que o programa tinha comecado: o alerta
        laranja virava vermelho sozinho.
        """
        if self._iso_watcher is None or self._iso_roi is None or not self._iso_roi.is_valid():
            return RunPhase.IDLE
        if freeze:
            return self._iso_watcher.phase
        crop = self._crop(frame, self._iso_roi)
        if crop is None:
            return self._iso_watcher.phase
        return self._iso_watcher.update(self._reader.read_text(crop))

    def detect(self, frame: np.ndarray, freeze_phase: bool = False) -> DetectionResult:
        """Executa um ciclo completo de deteccao sobre o frame."""
        start = time.perf_counter()

        readings = {ind.name: self._read_indicator(frame, ind) for ind in self._indicators}
        phase = self._update_iso(frame, freeze_phase)

        program_name = ""
        if self._program_roi is not None and self._program_roi.is_valid():
            crop = self._crop(frame, self._program_roi)
            if crop is not None:
                program_name = self._reader.read_text(crop).upper()

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return DetectionResult(
            indicators=readings,
            program_name=program_name,
            timestamp=datetime.now(),
            elapsed_ms=elapsed_ms,
            run_phase=phase,
        )
