"""MonitorWorker: roda o MonitorEngine em uma QThread.

Unica responsabilidade: chamar run_cycle() no intervalo configurado e emitir
o CycleOutcome como sinal Qt (conexao queued entrega no thread da UI).
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
            except Exception:  # nunca deixar o loop morrer silenciosamente
                from loguru import logger

                logger.exception("Error in the monitoring cycle")
            # msleep e interrompivel via requestInterruption? Simples: fatiar a espera
            # para que stop() responda em ate ~100ms.
            waited = 0
            while self._running and waited < self._interval_ms:
                step = min(100, self._interval_ms - waited)
                self.msleep(step)
                waited += step

    def request_stop(self) -> None:
        """Pede a parada SEM bloquear quem chamou.

        A UI nunca pode esperar por um ciclo: um ciclo faz OCR e, num PC de
        chao de fabrica, pode passar de varios segundos. Quem precisa saber
        quando terminou escuta o sinal `finished` da QThread.
        """
        self._running = False

    def stop(self, timeout_ms: int = 15000) -> bool:
        """Para e espera de fato. Usar apenas ao encerrar o aplicativo.

        Destruir uma QThread ainda em execucao aborta o processo, entao aqui
        a espera e longa de proposito: melhor demorar a fechar do que morrer
        de forma feia.
        """
        self._running = False
        return self.wait(timeout_ms)
