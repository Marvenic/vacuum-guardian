"""Detection orchestration (crops ROIs, combines vision + OCR, tracks the run phase)."""

from .service import DetectionService
from .arming import IsoLineWatcher

__all__ = ["DetectionService", "IsoLineWatcher"]
