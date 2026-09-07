"""OpenCV template matching for an indicator in a fixed position.

Method: cv2.matchTemplate with TM_CCOEFF_NORMED.
- It is the classic method most robust to small brightness changes,
  because it normalises by the local mean (unlike TM_SQDIFF/TM_CCORR).
- The score is in [-1, 1]; treated as confidence and compared with the
  configurable threshold.

The OSAI screen is static (same resolution, same layout), the ideal case
for template matching - which is why it comes before OCR in priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from ..models import PumpState


@dataclass(frozen=True)
class TemplateMatch:
    """Result of comparing the ROI against both templates."""

    state: PumpState
    confidence: float  # score of the winning template
    score_on: float
    score_off: float


class TemplateMatcher:
    """Decides ON/OFF by comparing an indicator ROI with its two templates."""

    def __init__(self, on_path: Path, off_path: Path, threshold: float) -> None:
        self._threshold = threshold
        self._template_on = self._load(on_path)
        self._template_off = self._load(off_path)

    @property
    def ready(self) -> bool:
        """False while the templates have not been calibrated (files missing)."""
        return self._template_on is not None and self._template_off is not None

    @staticmethod
    def _load(path: Path) -> np.ndarray | None:
        if not path.exists():
            logger.warning("Missing template: {} (calibration pending)", path)
            return None
        # IMPORTANT: match in COLOUR (BGR), not greyscale - ON/OFF indicators
        # often differ only by colour (green/red at the same brightness would be
        # identical in greyscale).
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            logger.error("Failed to read template: {}", path)
        return image

    @staticmethod
    def _score(roi_bgr: np.ndarray, template: np.ndarray) -> float:
        """Best matchTemplate score; -1.0 when the ROI is smaller than the template."""
        if (
            roi_bgr.shape[0] < template.shape[0]
            or roi_bgr.shape[1] < template.shape[1]
        ):
            return -1.0
        result = cv2.matchTemplate(roi_bgr, template, cv2.TM_CCOEFF_NORMED)
        return float(result.max())

    def match(self, roi_bgr: np.ndarray) -> TemplateMatch:
        """Classifica a ROI da bomba.

        Regras:
        - templates ausentes -> UNKNOWN (nunca chutar em ambiente industrial);
        - nenhum score acima do threshold -> UNKNOWN;
        - senao, vence o template de maior score.
        """
        if self._template_on is None or self._template_off is None:
            return TemplateMatch(PumpState.UNKNOWN, 0.0, 0.0, 0.0)

        score_on = self._score(roi_bgr, self._template_on)
        score_off = self._score(roi_bgr, self._template_off)

        best = max(score_on, score_off)
        if best < self._threshold:
            state = PumpState.UNKNOWN
        elif score_on >= score_off:
            state = PumpState.ON
        else:
            state = PumpState.OFF
        return TemplateMatch(state, best, score_on, score_off)
