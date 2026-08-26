"""Captura de frames com mss.

mss e a opcao mais rapida em Python puro para screenshot de regiao no
Windows (usa a API GDI diretamente). Comparado a alternativas:
- PIL.ImageGrab: mais lento e sem controle fino de regiao/monitor;
- pygetwindow + pyautogui: mais dependencias para o mesmo resultado.

O frame retorna como numpy array BGR (padrao OpenCV), pronto para a camada
de visao sem conversoes extras.
"""

from __future__ import annotations

import threading

import numpy as np
from loguru import logger
from mss import mss

from .window_locator import WindowLocator, WindowRect


class ScreenCapture:
    """Captura a janela do OSAI; cai para o monitor primario se nao a achar."""

    def __init__(self, locator: WindowLocator) -> None:
        self._locator = locator
        # mss usa handles GDI validos apenas na thread que os criou; como o
        # grab() roda na thread de monitoramento (e a calibracao na thread da
        # UI), mantemos uma instancia mss POR THREAD via threading.local.
        self._local = threading.local()
        self._warned_fallback = False

    @property
    def _sct(self) -> mss:
        if not hasattr(self._local, "sct"):
            self._local.sct = mss()
        return self._local.sct

    def grab(self) -> tuple[np.ndarray, WindowRect | None]:
        """Captura um frame.

        Returns:
            (frame BGR, retangulo da janela ou None se caiu no fallback
            de tela inteira). O retangulo e devolvido para que as ROIs
            (relativas a janela) possam ser aplicadas pelo chamador.
        """
        window = self._locator.find()
        if window is not None:
            region = {
                "left": window.left,
                "top": window.top,
                "width": window.width,
                "height": window.height,
            }
            self._warned_fallback = False
        else:
            # Fallback: monitor primario inteiro. Logamos apenas uma vez
            # para nao inundar o log enquanto o OSAI estiver fechado.
            if not self._warned_fallback:
                logger.warning("OSAI window not found - capturing the primary monitor")
                self._warned_fallback = True
            region = self._sct.monitors[1]  # [0] = todos os monitores juntos

        shot = self._grab_region(region)
        # np.array (e NAO asarray): o mss reaproveita o buffer interno entre
        # capturas do mesmo tamanho. Uma view viraria os pixels da captura
        # seguinte - e a tela de calibracao guarda o frame por varios segundos
        # enquanto o operador mexe no OSAI.
        # mss entrega BGRA; descartamos o canal alfa -> BGR (formato OpenCV).
        # ascontiguousarray: alem de COPIAR (o buffer do mss e reciclado),
        # garante memoria contigua e propria. Fatiar BGRA->BGR deixa o array
        # com stride quebrado, e o OpenCV recebendo uma view nao-contigua
        # sobre memoria de terceiros foi o que derrubava o processo sem
        # traceback ("VacuumGuardian.exe has stopped working").
        frame = np.ascontiguousarray(np.array(shot, dtype=np.uint8)[:, :, :3])
        return frame, window

    def _grab_region(self, region):  # type: ignore[no-untyped-def]
        """Captura a regiao, recriando o grabber se o handle GDI morreu.

        Handles GDI do Windows sao invalidados por eventos comuns - esconder e
        reexibir uma janela (o que a calibracao faz a cada amostra), trocar de
        sessao, mudar DPI. Sem esta segunda tentativa, uma falha passageira
        deixava a calibracao presa em "Could not take a new screenshot".
        """
        try:
            return self._sct.grab(region)
        except Exception as exc:
            logger.warning("Screen capture failed ({}) - recreating the grabber", exc)
            self._reset()
            return self._sct.grab(region)

    def _reset(self) -> None:
        """Descarta o grabber desta thread; o proximo acesso cria um novo."""
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:  # ja pode estar invalido - fechar e best effort
                pass
            del self._local.sct

    def close(self) -> None:
        self._reset()
