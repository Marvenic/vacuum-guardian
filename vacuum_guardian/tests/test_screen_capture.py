"""Testes da captura de tela.

Motivados por uma falha real na CNC: durante a calibracao, esconder e reexibir
a janela invalidou o handle GDI e a segunda captura morreu com "Could not take
a new screenshot", travando o operador no passo da amostra OFF.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.capture import screen_capture as sc
from app.capture.screen_capture import ScreenCapture


class _FakeLocator:
    """Locator que nunca acha a janela: exercita o fallback de tela inteira."""

    def find(self):  # type: ignore[no-untyped-def]
        return None


class _FakeShot:
    """Imita o mss.ScreenShot: expoe um buffer que o mss REAPROVEITA."""

    def __init__(self, buffer: np.ndarray) -> None:
        self._buffer = buffer

    def __array__(self, dtype=None):  # type: ignore[no-untyped-def]
        return self._buffer if dtype is None else self._buffer.astype(dtype, copy=False)


class _FakeMss:
    """mss falso; `fail_times` simula handles GDI mortos."""

    instances: list["_FakeMss"] = []

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.closed = False
        self.grabs = 0
        # Buffer unico e reutilizado - exatamente o que o mss faz no Windows.
        self.buffer = np.zeros((4, 4, 4), np.uint8)
        self.monitors = [{}, {"left": 0, "top": 0, "width": 4, "height": 4}]
        _FakeMss.instances.append(self)

    def grab(self, region):  # type: ignore[no-untyped-def]
        self.grabs += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OSError("gdi32.GetDIBits() failed")
        return _FakeShot(self.buffer)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_instances():  # type: ignore[no-untyped-def]
    _FakeMss.instances.clear()
    yield
    _FakeMss.instances.clear()


def _install(monkeypatch, fail_times: int = 0) -> None:  # type: ignore[no-untyped-def]
    """Faz o proximo mss() criado falhar `fail_times` vezes antes de funcionar."""
    state = {"first": True}

    def factory():  # type: ignore[no-untyped-def]
        if state["first"]:
            state["first"] = False
            return _FakeMss(fail_times)
        return _FakeMss(0)

    monkeypatch.setattr(sc, "mss", factory)


def test_grab_returns_bgr_frame(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _install(monkeypatch)
    frame, window = ScreenCapture(_FakeLocator()).grab()
    assert window is None            # fallback de tela inteira
    assert frame.shape == (4, 4, 3)  # canal alfa descartado


def test_dead_gdi_handle_is_retried_with_a_fresh_grabber(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A falha que travou a calibracao na maquina: precisa se recuperar sozinha."""
    _install(monkeypatch, fail_times=1)
    capture = ScreenCapture(_FakeLocator())

    frame, _ = capture.grab()  # nao pode levantar excecao

    assert frame.shape == (4, 4, 3)
    assert len(_FakeMss.instances) == 2      # o grabber morto foi descartado
    assert _FakeMss.instances[0].closed      # e fechado
    assert _FakeMss.instances[1].grabs == 1  # o novo tirou a foto


def test_persistent_failure_still_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Duas falhas seguidas sao problema de verdade - nao mascarar."""
    monkeypatch.setattr(sc, "mss", lambda: _FakeMss(fail_times=5))
    with pytest.raises(OSError):
        ScreenCapture(_FakeLocator()).grab()


def test_frame_is_a_copy_not_a_view_of_the_reused_buffer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """O mss reaproveita o buffer: uma view viraria os pixels da foto seguinte.

    A calibracao guarda o frame por varios segundos enquanto o operador mexe no
    OSAI - com uma view, a amostra ON seria gravada com pixels do momento OFF.
    """
    _install(monkeypatch)
    capture = ScreenCapture(_FakeLocator())

    first, _ = capture.grab()
    _FakeMss.instances[0].buffer[:] = 255  # proxima captura sobrescreve o buffer
    capture.grab()

    assert first.max() == 0, "o frame guardado mudou sozinho (era uma view)"


def test_close_allows_capturing_again(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """close() e usado no restart do monitor; nao pode inutilizar o objeto."""
    _install(monkeypatch)
    capture = ScreenCapture(_FakeLocator())
    capture.grab()
    capture.close()
    assert _FakeMss.instances[0].closed

    frame, _ = capture.grab()  # cria um grabber novo
    assert frame.shape == (4, 4, 3)


def test_close_is_safe_when_never_used(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _install(monkeypatch)
    ScreenCapture(_FakeLocator()).close()  # nao pode levantar excecao
