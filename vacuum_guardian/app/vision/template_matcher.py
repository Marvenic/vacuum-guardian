"""Template matching com OpenCV para o indicador da Vacuum Pump.

Metodo escolhido: cv2.matchTemplate com TM_CCOEFF_NORMED.
- E o metodo classico mais robusto a pequenas variacoes de brilho, pois
  normaliza pela media local (ao contrario de TM_SQDIFF/TM_CCORR).
- Score em [-1, 1]; tratamos como confianca e comparamos com o threshold
  configuravel (requisito 9).

A tela do OSAI e estatica (mesma resolucao, mesmo layout), o cenario ideal
para template matching - por isso ele vem antes de OCR/IA na prioridade.
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
    """Resultado do confronto entre a ROI da bomba e os dois templates."""

    state: PumpState
    confidence: float  # score do template vencedor
    score_on: float
    score_off: float


class TemplateMatcher:
    """Decide ON/OFF comparando a ROI de um indicador com seus dois templates."""

    def __init__(self, on_path: Path, off_path: Path, threshold: float) -> None:
        self._threshold = threshold
        self._template_on = self._load(on_path)
        self._template_off = self._load(off_path)

    @property
    def ready(self) -> bool:
        """False enquanto os templates nao tiverem sido calibrados (arquivos ausentes)."""
        return self._template_on is not None and self._template_off is not None

    @staticmethod
    def _load(path: Path) -> np.ndarray | None:
        if not path.exists():
            logger.warning("Missing template: {} (calibration pending)", path)
            return None
        # IMPORTANTE: matching em COR (BGR), nao em cinza - indicadores ON/OFF
        # frequentemente diferem apenas pela cor (verde/vermelho com o mesmo
        # brilho seriam identicos em escala de cinza).
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            logger.error("Failed to read template: {}", path)
        return image

    @staticmethod
    def _score(roi_bgr: np.ndarray, template: np.ndarray) -> float:
        """Maior score de matchTemplate; retorna -1.0 se a ROI for menor que o template."""
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
