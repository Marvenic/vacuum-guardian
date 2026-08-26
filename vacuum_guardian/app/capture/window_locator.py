"""Localiza a janela do OSAI no Windows via API nativa (ctypes/user32).

Usamos ctypes em vez de pywin32 para nao adicionar dependencia: precisamos
apenas de EnumWindows + GetWindowText + GetWindowRect. A busca e por
substring do titulo (case-insensitive), configuravel em config.json
("window_title_hint"), porque nao sabemos ainda o titulo exato da janela
do OSAI no chao de fabrica.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

from loguru import logger

_user32 = ctypes.windll.user32

_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


@dataclass(frozen=True)
class WindowRect:
    """Retangulo absoluto (coordenadas de tela) de uma janela encontrada."""

    left: int
    top: int
    width: int
    height: int
    title: str


class WindowLocator:
    """Encontra a janela cujo titulo contem o hint configurado (SRP: so localiza)."""

    def __init__(self, title_hint: str) -> None:
        self._hint = title_hint.lower()

    def find(self) -> WindowRect | None:
        """Retorna o retangulo da primeira janela visivel que casa com o hint.

        Retorna None se nada for encontrado - o chamador decide o fallback
        (por exemplo, capturar o monitor inteiro).
        """
        matches: list[WindowRect] = []

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True  # continua a enumeracao
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if self._hint in title.lower():
                rect = wt.RECT()
                if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    if width > 0 and height > 0:
                        matches.append(
                            WindowRect(rect.left, rect.top, width, height, title)
                        )
            return True

        _user32.EnumWindows(_EnumWindowsProc(_callback), 0)

        if not matches:
            logger.debug("No window with a title containing '{}'", self._hint)
            return None
        if len(matches) > 1:
            logger.warning(
                "{} windows match '{}' - using the first one: '{}'",
                len(matches), self._hint, matches[0].title,
            )
        return matches[0]
