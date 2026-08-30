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


# Janela minimizada no Windows fica em (-32000, -32000) COM largura e altura
# positivas, e IsWindowVisible ainda devolve True. Medido nesta maquina:
#   NORMAL     IsWindowVisible=True IsIconic=False rect=(1654,858) 532x388
#   MINIMIZADA IsWindowVisible=True IsIconic=True  rect=(-32000,-32000) 391x61
# Sem checar IsIconic, o app "achava" o OSAI minimizado e capturava uma regiao
# fora da tela: frame inutil, OCR vazio, alarme nunca disparava.
_OFFSCREEN = -20000


@dataclass(frozen=True)
class WindowCandidate:
    """Janela enumerada, antes de decidir se serve."""

    title: str
    left: int
    top: int
    width: int
    height: int
    minimized: bool

    @property
    def usable(self) -> bool:
        """Da para capturar? Precisa estar restaurada e dentro da tela."""
        return (
            not self.minimized
            and self.width > 0
            and self.height > 0
            and self.left > _OFFSCREEN
            and self.top > _OFFSCREEN
        )


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
        """Retorna o retangulo da melhor janela que casa com o hint.

        Retorna None se nada servir - o chamador decide o fallback (por
        exemplo, capturar o monitor inteiro).
        """
        return choose_window(self._enumerate(), self._hint)

    def _enumerate(self) -> list[WindowCandidate]:
        """Lista as janelas com titulo, sem julgar se servem."""
        candidates: list[WindowCandidate] = []

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True  # continua a enumeracao
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            rect = wt.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            candidates.append(
                WindowCandidate(
                    title=buffer.value,
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                    minimized=bool(_user32.IsIconic(hwnd)),
                )
            )
            return True

        _user32.EnumWindows(_EnumWindowsProc(_callback), 0)
        return candidates


def choose_window(candidates: list[WindowCandidate], hint: str) -> WindowRect | None:
    """Escolhe a janela a capturar entre as que casam com o hint.

    Duas decisoes que vieram de falhas reais na CNC:

    - MINIMIZADA nao serve. O Windows continua dizendo IsWindowVisible=True e
      devolve um retangulo fora da tela; capturar ali rende um frame inutil e
      o app parecia "achar" o OSAI sem conseguir ler nada.
    - Vence a MAIOR, nao a primeira. O hint "OSAI" tambem casa com janelas de
      servico como "OSAI BootController", que sao pequenas; a tela de operacao
      ocupa o monitor.
    """
    wanted = hint.lower()
    matching = [c for c in candidates if wanted in c.title.lower()]
    usable = [c for c in matching if c.usable]

    if not usable:
        if matching:
            # Diferenciar "nao existe" de "existe mas esta minimizada" poupa o
            # operador de procurar defeito no lugar errado.
            logger.warning(
                "Window '{}' found but not usable (minimised or off-screen): {}",
                hint, ", ".join(sorted({c.title for c in matching})),
            )
        else:
            logger.debug("No window with a title containing '{}'", hint)
        return None

    best = max(usable, key=lambda c: c.width * c.height)
    if len(usable) > 1:
        logger.debug(
            "{} windows match '{}' - using the largest: '{}'",
            len(usable), hint, best.title,
        )
    return WindowRect(best.left, best.top, best.width, best.height, best.title)
