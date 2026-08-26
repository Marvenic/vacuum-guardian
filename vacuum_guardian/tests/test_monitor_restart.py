"""Regressao: reiniciar o monitor nao pode travar a interface.

O que acontecia na fabrica: ao clicar em "Done" na calibracao, a janela
congelava e nao dava mais para mover nem minimizar. Causa: o reinicio
esperava (bloqueando a thread da UI) ate o ciclo em andamento terminar; como
um ciclo faz OCR da tela inteira e no PC da CNC passa de 3 s, a espera
estourava e a thread antiga era ABANDONADA ainda rodando - ficavam duas
varreduras disputando a CPU, e cada recalibracao somava mais uma.

Nota de teste: depois que a thread antiga termina, o objeto Qt e destruido
(deleteLater). Por isso os testes observam o sinal `finished` em vez de
consultar o objeto - consulta-lo levantaria "C++ object already deleted".
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide2")

from app.config import ConfigService  # noqa: E402
from app.services.monitor import MonitorEngine  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.worker import MonitorWorker  # noqa: E402

_SLOW_CYCLE_S = 2.0  # mais longo que qualquer espera aceitavel na UI


@pytest.fixture()
def window(qt_app, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Janela com um motor cujo ciclo e propositalmente lento."""
    service = ConfigService(tmp_path / "config.json")
    engine = MonitorEngine(service.load(), tmp_path)
    real_cycle = engine.run_cycle

    def slow_cycle():  # type: ignore[no-untyped-def]
        time.sleep(_SLOW_CYCLE_S)
        return real_cycle()

    engine.run_cycle = slow_cycle  # type: ignore[method-assign]
    win = MainWindow(engine, service, tmp_path)
    yield win
    # Cancela um reinicio pendente: sem isto o `finished` da thread antiga
    # dispararia depois do teardown e criaria um monitor orfao, que o proximo
    # teste contaria como "monitor a mais".
    win._restarting = False
    for worker in _live_monitors():
        worker.stop(5000)
    qt_app.processEvents()
    for worker in _live_monitors():
        worker.stop(5000)


def _pump(qt_app, seconds: float) -> None:
    """Roda o loop de eventos por um tempo, como a UI faria."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)


def _live_monitors() -> list[MonitorWorker]:
    """MonitorWorker cujo objeto Qt ainda existe (nao foi deleteLater)."""
    live = []
    for obj in gc.get_objects():
        if isinstance(obj, MonitorWorker):
            try:
                obj.isRunning()
            except RuntimeError:
                continue  # objeto Qt ja destruido
            live.append(obj)
    return live


def _running_monitors() -> int:
    """Quantos MonitorWorker vivos estao com a thread em execucao."""
    total = 0
    for obj in gc.get_objects():
        if isinstance(obj, MonitorWorker):
            try:
                total += int(obj.isRunning())
            except RuntimeError:
                pass  # objeto Qt ja destruido: nao esta rodando
    return total


def test_restart_does_not_block_the_ui(window, qt_app) -> None:
    """O clique em Done tem de devolver o controle a interface imediatamente."""
    started = time.time()
    window._restart_monitor()
    elapsed = time.time() - started
    assert elapsed < 0.5, f"a UI ficou bloqueada por {elapsed:.2f}s"


def test_old_monitor_finishes_and_a_new_one_takes_over(window, qt_app) -> None:
    """Duas threads varrendo a tela ao mesmo tempo saturam o PC da CNC."""
    old_worker = window._worker
    finished: list[bool] = []
    old_worker.finished.connect(lambda: finished.append(True))

    window._restart_monitor()
    _pump(qt_app, _SLOW_CYCLE_S + 2.0)

    assert finished, "a thread antiga nunca terminou"
    assert window._worker is not old_worker, "o monitor novo nao subiu"
    assert window._worker.isRunning()
    assert _running_monitors() == 1


def test_repeated_restarts_do_not_pile_up_monitors(window, qt_app) -> None:
    """Cada recalibracao somava um monitor; tres seguidas eram tres varreduras."""
    for _ in range(3):
        window._restart_monitor()
        _pump(qt_app, 0.3)
    _pump(qt_app, _SLOW_CYCLE_S + 2.0)

    assert _running_monitors() <= 1


def test_engine_is_closed_only_after_its_thread_stops(window, qt_app) -> None:
    """Fechar o motor com a thread ainda usando a captura corrompe o grabber."""
    old_engine = window._engine
    closed: list[float] = []
    original_close = old_engine.close

    def tracked_close() -> None:
        closed.append(time.time())
        original_close()

    old_engine.close = tracked_close  # type: ignore[method-assign]

    window._restart_monitor()
    assert not closed, "o motor foi fechado antes de a thread parar"

    _pump(qt_app, _SLOW_CYCLE_S + 2.0)
    assert closed, "o motor antigo nunca foi fechado"
