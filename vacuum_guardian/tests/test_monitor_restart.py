"""Regression: restarting the monitor must not freeze the interface.

What happened at the factory: clicking "Done" in calibration froze the
window, which could then be neither moved nor minimised. Cause: the restart
waited (blocking the UI thread) for the running cycle to end; since a cycle
runs OCR and on the CNC PC takes more than 3 s, the wait timed out and the
old thread was ABANDONED while still running - two scans then competed for
the CPU, and every recalibration added another.

Test note: once the old thread finishes, the Qt object is destroyed
(deleteLater). That is why these tests watch the `finished` signal instead
of querying the object, which would raise "C++ object already deleted".
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
    """A window whose engine has a deliberately slow cycle."""
    service = ConfigService(tmp_path / "config.json")
    engine = MonitorEngine(service.load(), tmp_path)
    real_cycle = engine.run_cycle

    def slow_cycle():  # type: ignore[no-untyped-def]
        time.sleep(_SLOW_CYCLE_S)
        return real_cycle()

    engine.run_cycle = slow_cycle  # type: ignore[method-assign]
    win = MainWindow(engine, service, tmp_path)
    yield win
    # Cancels a pending restart: without this the old thread's `finished`
    # would fire after teardown and create an orphan monitor, which the next
    # test would count as "one monitor too many".
    win._restarting = False
    for worker in _live_monitors():
        worker.stop(5000)
    qt_app.processEvents()
    for worker in _live_monitors():
        worker.stop(5000)


def _pump(qt_app, seconds: float) -> None:
    """Runs the event loop for a while, the way the UI would."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)


def _live_monitors() -> list[MonitorWorker]:
    """MonitorWorkers whose Qt object still exists (not yet deleted)."""
    live = []
    for obj in gc.get_objects():
        if isinstance(obj, MonitorWorker):
            try:
                obj.isRunning()
            except RuntimeError:
                continue  # Qt object already destroyed
            live.append(obj)
    return live


def _running_monitors() -> int:
    """How many live MonitorWorkers have a running thread."""
    total = 0
    for obj in gc.get_objects():
        if isinstance(obj, MonitorWorker):
            try:
                total += int(obj.isRunning())
            except RuntimeError:
                pass  # Qt object already destroyed: not running
    return total


def test_restart_does_not_block_the_ui(window, qt_app) -> None:
    """The Done click must hand control back to the interface at once."""
    started = time.time()
    window._restart_monitor()
    elapsed = time.time() - started
    assert elapsed < 0.5, f"the UI was blocked for {elapsed:.2f}s"


def test_old_monitor_finishes_and_a_new_one_takes_over(window, qt_app) -> None:
    """Two threads scanning the screen at once saturate the CNC PC."""
    old_worker = window._worker
    finished: list[bool] = []
    old_worker.finished.connect(lambda: finished.append(True))

    window._restart_monitor()
    _pump(qt_app, _SLOW_CYCLE_S + 2.0)

    assert finished, "the old thread never finished"
    assert window._worker is not old_worker, "the new monitor did not start"
    assert window._worker.isRunning()
    assert _running_monitors() == 1


def test_repeated_restarts_do_not_pile_up_monitors(window, qt_app) -> None:
    """Each recalibration added a monitor; three in a row meant three scans."""
    for _ in range(3):
        window._restart_monitor()
        _pump(qt_app, 0.3)
    _pump(qt_app, _SLOW_CYCLE_S + 2.0)

    assert _running_monitors() <= 1


def test_engine_is_closed_only_after_its_thread_stops(window, qt_app) -> None:
    """Closing the engine while the thread still captures corrupts the grabber."""
    old_engine = window._engine
    closed: list[float] = []
    original_close = old_engine.close

    def tracked_close() -> None:
        closed.append(time.time())
        original_close()

    old_engine.close = tracked_close  # type: ignore[method-assign]

    window._restart_monitor()
    assert not closed, "the engine was closed before the thread stopped"

    _pump(qt_app, _SLOW_CYCLE_S + 2.0)
    assert closed, "the old engine was never closed"
