"""Shared fixtures: Qt in offscreen mode for UI tests."""

from __future__ import annotations

import os

import pytest

# Must be set BEFORE any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """A single QApplication for the whole session (Qt allows only one)."""
    from PySide2.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
