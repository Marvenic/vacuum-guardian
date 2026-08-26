"""Orquestracao da deteccao (recorta ROIs, combina visao + OCR, arma o momento critico)."""

from .service import DetectionService
from .arming import ArmingDetector, ArmingState

__all__ = ["DetectionService", "ArmingDetector", "ArmingState"]
