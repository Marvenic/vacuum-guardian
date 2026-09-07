"""Loguru setup: console plus a rotating file.

Logs are persisted to file with date and time. Daily rotation with 30-day
retention keeps the disk of an industrial PC healthy with the app running
24/7.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, console_level: str = "INFO") -> None:
    """Configures the loguru sinks. Call once, at start-up."""
    logger.remove()  # remove o sink default para controlar o formato

    # A console-less executable (PyInstaller console=False) gets no stdout or
    # stderr from Windows: sys.stderr is None and loguru rejects that sink.
    # The file log below is the one that matters in production anyway.
    if sys.stderr is not None:
        logger.add(sys.stderr, level=console_level)
    logger.add(
        log_dir / "vacuum_guardian_{time:YYYY-MM-DD}.log",
        rotation="00:00",       # novo arquivo a meia-noite
        retention="30 days",    # apaga logs com mais de 30 dias
        level="DEBUG",
        encoding="utf-8",
        enqueue=True,           # written on its own thread - never blocks capture
    )
