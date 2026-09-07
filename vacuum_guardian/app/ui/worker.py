"""MonitorWorker: runs the MonitorEngine on a QThread.

Single responsibility: call run_cycle() at the configured interval and emit
the CycleOutcome as a Qt signal (a queued connection delivers it on the UI
"""

from __future__ import annotations

from PySide2.QtCore import QThread, Signal

from ..services.monitor import CycleOutcome, MonitorEngine


class MonitorWorker(QThread):
    cycle_done = Signal(object)  # payload: CycleOutcome

    def __init__(self, engine: MonitorEngine, interval_s: float) -> None:
        super().__init__()
        self._engine = engine
        self._interval_ms = int(interval_s * 1000)
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                outcome: CycleOutcome = self._engine.run_cycle()
                self.cycle_done.emit(outcome)
            except Exception:  # never let the loop die silently
                from loguru import logger

                logger.exception("Error in the monitoring cycle")
            # Slice the wait instead of one long sleep, so stop() is honoured within
            # about 100 ms.
            waited = 0
            while self._running and waited < self._interval_ms:
                step = min(100, self._interval_ms - waited)
                self.msleep(step)
                waited += step

    def request_stop(self) -> None:
        """Asks the thread to stop WITHOUT blocking the caller.

        The UI must never wait for a cycle: a cycle runs OCR and, on a shop-floor
        PC, can take several seconds. Whoever needs to know when it finished
        listens to the QThread's `finished` signal.
        """
        self._running = False

    def stop(self, timeout_ms: int = 15000) -> bool:
        """Stops and really waits. Use only when quitting the application.

        Destroying a running QThread aborts the process, so the wait here is
        deliberately long: better a slow exit than an ugly crash.
        of that kind.
        """
        self._running = False
        return self.wait(timeout_ms)
