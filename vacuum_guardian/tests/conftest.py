"""Fixtures compartilhadas: Qt em modo offscreen para testes de UI."""

from __future__ import annotations

import os

import pytest

# Precisa ser definido ANTES de qualquer QApplication ser criada.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """QApplication unica para toda a sessao (Qt nao permite duas)."""
    from PySide2.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
