"""Orquestracao da deteccao (recorta ROIs, combina visao + OCR, arma o momento critico)."""

from .service import DetectionService
from .arming import IsoLineWatcher

__all__ = ["DetectionService", "IsoLineWatcher"]
