"""Setup do loguru: console + arquivo rotativo.

Requisito 8: logs persistidos em arquivo com data/hora. A rotacao diaria com
retencao de 30 dias evita que o disco da maquina industrial encha com o app
rodando 24/7.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, console_level: str = "INFO") -> None:
    """Configura sinks do loguru. Chamar uma unica vez, no inicio do app."""
    logger.remove()  # remove o sink default para controlar o formato

    # Executavel sem console (PyInstaller console=False) nao recebe stdout/stderr
    # do Windows: sys.stderr e None e o loguru rejeita esse sink. O log em
    # arquivo abaixo e o que realmente importa em producao.
    if sys.stderr is not None:
        logger.add(sys.stderr, level=console_level)
    logger.add(
        log_dir / "vacuum_guardian_{time:YYYY-MM-DD}.log",
        rotation="00:00",       # novo arquivo a meia-noite
        retention="30 days",    # apaga logs com mais de 30 dias
        level="DEBUG",
        encoding="utf-8",
        enqueue=True,           # escrita em thread separada - nao trava o loop de captura
    )
