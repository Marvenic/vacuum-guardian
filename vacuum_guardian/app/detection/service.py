"""DetectionService: transforma um frame bruto em um DetectionResult.

Responsabilidade unica: recortar as ROIs configuradas e delegar
- estado de cada indicador  -> TemplateMatcher (ROI fixa) ou IndicatorFinder
                               (busca por rotulo, tolerante a rolagem)
- nome do programa          -> TextReader (OCR)
- fase da execucao          -> TextReader (OCR) + IsoLineWatcher
It knows nothing about mss, Qt or alarm rules; dependencies are injected,
which is what lets tests drive it with synthetic images.

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
    """One TemplateMatcher per indicator, following the <slug>_on/off.png convention."""
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
    """One IndicatorFinder per indicator that has a toggle geometry.

    Only indicators calibrated in label-search mode are included; the rest
    stay in fixed-ROI mode.
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
        """Crops the ROI; None if it falls outside the frame (window resized)."""
        height, width = frame.shape[:2]
        if roi.x + roi.width > width or roi.y + roi.height > height:
            logger.warning(
                "ROI {} is outside the {}x{} frame - recalibration needed",
                roi, width, height,
            )
            return None
        return frame[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]

    def _read_indicator(self, frame: np.ndarray, ind: IndicatorConfig) -> IndicatorReading:
        """Reads one indicator; anything in the way yields an unverifiable state."""
        # Preferred mode: label search (survives the scrolling menu).
        finder = self._finders.get(ind.name)
        if finder is not None:
            found = finder.read(frame)
            return IndicatorReading(found.state, found.confidence)

        # Legacy mode: fixed ROI + ON/OFF templates.
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
        """Reads the Iso lines field (a small ROI) and updates the run phase.

        `freeze=True` devolve a fase atual SEM ler nada. Usado quando algo
        covers the field on screen - the alarm popup included. Without this the
        app read its own warning's pixels, saw text other than CLOSE THE DOORS
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
        """Runs one full detection cycle over the frame."""
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
