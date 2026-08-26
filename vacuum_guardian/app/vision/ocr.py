"""Leitura do nome do programa via OCR.

Engine primaria: Windows.Media.Ocr (nativa do Windows 10/11, via pywinrt).
Motivos da escolha, comparada as alternativas:
- easyocr: exige PyTorch (~2.5 GB) e inicializacao lenta - exagero para ler
  texto nitido de UI; fica como fallback plugavel se a qualidade decepcionar.
- Tesseract: exige instalar executavel externo na maquina industrial.
- Windows OCR: zero dependencias pesadas, rapido, offline.

A interface TextReader permite trocar a engine sem tocar no resto do app
(Dependency Inversion): o DetectionService recebe qualquer TextReader.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import cv2
import numpy as np
from loguru import logger


# Limites de escala do OCR (ver WindowsOcrReader._prepare).
_UPSCALE_BELOW_WIDTH = 400  # recortes ate esta largura sao ampliados 2x
_MAX_WIDTH = 1280           # acima disso reduz: area e o que custa caro


class TextReader(Protocol):
    """Contrato minimo de uma engine de OCR."""

    def read_text(self, roi_bgr: np.ndarray) -> str:
        """Extrai o texto de uma imagem BGR; string vazia se nada for lido."""
        ...


class WindowsOcrReader:
    """TextReader usando a API nativa Windows.Media.Ocr."""

    def __init__(self) -> None:
        # Imports locais: modulos winrt so existem no Windows e so sao
        # necessarios se esta engine for usada (facilita testes em CI).
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        # Ingles cobre a UI do OSAI; se indisponivel, usa o idioma do sistema.
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
        except Exception as exc:  # OCR nunca pode derrubar o loop de monitoramento
            logger.error("OCR failed: {}", exc)
            return ""

    @staticmethod
    def _prepare(roi_bgr: np.ndarray) -> np.ndarray:
        """Ajusta a escala ao tamanho da entrada (custo do OCR cresce com a area).

        - Recortes pequenos (ROI do nome do programa): upscale 2x, que melhora
          sensivelmente o OCR em fontes pequenas de UI.
        - Frame inteiro (busca das janelas de confirmacao): NAO ampliar. Um
          1920x1080 ampliado vira 8 Mpx e o ciclo passa de ~1 s - mais lento
          que o proprio intervalo de captura. O texto dessas janelas e grande,
          entao reduzir ate _MAX_WIDTH nao atrapalha o reconhecimento.
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
