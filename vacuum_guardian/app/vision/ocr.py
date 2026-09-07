"""Reads text from the screen with OCR.

Primary engine: Windows.Media.Ocr (native to Windows 10/11, via pywinrt).
Why, compared with the alternatives:
- easyocr: needs PyTorch (~2.5 GB) and starts slowly - overkill for crisp
  UI text; it stays a pluggable fallback if quality disappoints.
- Tesseract: needs an external executable on the industrial PC.
- Windows OCR: no heavy dependency, fast, offline.

The TextReader interface allows swapping the engine without touching the
rest of the app: DetectionService accepts any TextReader.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import cv2
import numpy as np
from loguru import logger


# OCR scaling limits (see WindowsOcrReader._prepare).
_UPSCALE_BELOW_WIDTH = 400  # crops up to this width are upscaled 2x
_MAX_WIDTH = 1280           # above this, shrink: area is what costs


class TextReader(Protocol):
    """Minimum contract for an OCR engine."""

    def read_text(self, roi_bgr: np.ndarray) -> str:
        """Extracts text from a BGR image; empty string when nothing is read."""
        ...


class WindowsOcrReader:
    """TextReader backed by the native Windows.Media.Ocr API."""

    def __init__(self) -> None:
        # Local imports: winrt modules only exist on Windows and are only needed
        # if this engine is used (which keeps CI tests simple).
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        # English covers the OSAI UI; otherwise fall back to the system language.
        engine = None
        english = Language("en-US")
        if OcrEngine.is_language_supported(english):
            engine = OcrEngine.try_create_from_language(english)
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("No OCR language pack available in Windows")
        self._engine = engine

    def read_text(self, roi_bgr: np.ndarray) -> str:
        try:
            return asyncio.run(self._read_async(roi_bgr))
        except Exception as exc:  # OCR must never break the monitoring loop
            logger.error("OCR failed: {}", exc)
            return ""

    @staticmethod
    def _prepare(roi_bgr: np.ndarray) -> np.ndarray:
        """Scales the input by size (OCR cost grows with area).

        - Small crops (the program-name ROI): upscale 2x, which noticeably helps
          OCR on small UI fonts.
        - A whole frame: do NOT upscale. A 1920x1080 image doubled becomes 8 Mpx
          and the cycle goes past ~1 s - slower than the capture interval itself.
          The text there is large, so shrinking to _MAX_WIDTH does not hurt
          recognition.
        """
        width = roi_bgr.shape[1]
        if width <= _UPSCALE_BELOW_WIDTH:
            factor = 2.0
        elif width > _MAX_WIDTH:
            factor = _MAX_WIDTH / float(width)
        else:
            return roi_bgr
        interpolation = cv2.INTER_CUBIC if factor > 1.0 else cv2.INTER_AREA
        return cv2.resize(roi_bgr, None, fx=factor, fy=factor, interpolation=interpolation)

    async def _read_async(self, roi_bgr: np.ndarray) -> str:
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.security.cryptography import CryptographicBuffer

        roi = self._prepare(roi_bgr)
        bgra = cv2.cvtColor(roi, cv2.COLOR_BGR2BGRA)
        height, width = bgra.shape[:2]

        buffer = CryptographicBuffer.create_from_byte_array(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.BGRA8, width, height
        )
        result = await self._engine.recognize_async(bitmap)
        return result.text.strip()
