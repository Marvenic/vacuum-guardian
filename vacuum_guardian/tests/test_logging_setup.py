"""Tests for the logging setup.

Important regression: in the console-less executable (PyInstaller
console=False) Windows provides no stdout/stderr and sys.stderr is None.
loguru rejects that sink with a TypeError, killing the app before the window
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from loguru import logger

from app.logging import setup_logging


def test_works_without_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The console-less .exe case: it must configure only the file, with no error."""
    monkeypatch.setattr(sys, "stderr", None)
    setup_logging(tmp_path)  # nao pode lancar TypeError
    logger.info("linha de teste")
    logger.complete()  # flushes the sink that uses enqueue=True
    assert list(tmp_path.glob("*.log")), "the file log should have been created"


def test_writes_to_file(tmp_path: Path) -> None:
    setup_logging(tmp_path)
    logger.info("mensagem gravada")
    logger.complete()
    content = next(tmp_path.glob("*.log")).read_text(encoding="utf-8")
    assert "mensagem gravada" in content
