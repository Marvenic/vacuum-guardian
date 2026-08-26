"""Testes do setup de logging.

Regressao importante: no executavel sem console (PyInstaller console=False),
o Windows nao fornece stdout/stderr e sys.stderr fica None. O loguru recusa
esse sink com TypeError, derrubando o app antes mesmo da janela abrir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from loguru import logger

from app.logging import setup_logging


def test_works_without_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cenario do .exe sem console: deve configurar so o arquivo, sem erro."""
    monkeypatch.setattr(sys, "stderr", None)
    setup_logging(tmp_path)  # nao pode lancar TypeError
    logger.info("linha de teste")
    logger.complete()  # garante o flush do sink com enqueue=True
    assert list(tmp_path.glob("*.log")), "log em arquivo deveria ter sido criado"


def test_writes_to_file(tmp_path: Path) -> None:
    setup_logging(tmp_path)
    logger.info("mensagem gravada")
    logger.complete()
    content = next(tmp_path.glob("*.log")).read_text(encoding="utf-8")
    assert "mensagem gravada" in content
