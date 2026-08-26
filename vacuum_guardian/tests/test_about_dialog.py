"""Testes da tela About: creditos corretos e versao vinda da fonte unica."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide2")

from PySide2.QtGui import QIcon  # noqa: E402
from PySide2.QtWidgets import QLabel  # noqa: E402

from app import __version__  # noqa: E402
from app.ui.about_dialog import AboutDialog  # noqa: E402


def _text(dialog: AboutDialog) -> str:
    return " ".join(label.text() for label in dialog.findChildren(QLabel))


def test_credits_are_present(qt_app) -> None:
    text = _text(AboutDialog(QIcon()))
    assert "Marcos Souza" in text
    assert "Andrea Cursino" in text
    assert "Abilix Digital" in text
    assert "www.abilixdigital.com" in text


def test_shows_version_from_package(qt_app) -> None:
    """Versao nao pode ser hardcoded na tela - evita divergir do pacote."""
    assert __version__ in _text(AboutDialog(QIcon()))


def test_website_link_is_clickable(qt_app) -> None:
    dialog = AboutDialog(QIcon())
    body = next(
        label for label in dialog.findChildren(QLabel) if "abilixdigital" in label.text()
    )
    assert body.openExternalLinks()
    assert "https://www.abilixdigital.com" in body.text()


def test_window_title(qt_app) -> None:
    assert AboutDialog(QIcon()).windowTitle() == "About Vacuum Guardian"
