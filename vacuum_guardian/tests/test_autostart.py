"""Testes do inicio automatico.

A pasta Startup real nunca e tocada: APPDATA e redirecionado para um tmp_path,
entao o atalho e criado e removido em area descartavel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.utils import AutoStart

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="somente Windows")


@pytest.fixture()
def fake_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_disabled_by_default(fake_appdata: Path) -> None:
    assert not AutoStart().is_enabled()


def test_enable_creates_shortcut(fake_appdata: Path) -> None:
    autostart = AutoStart()
    assert autostart.enable()
    assert autostart.is_enabled()
    assert autostart.shortcut_path.suffix == ".lnk"
    assert autostart.shortcut_path.stat().st_size > 0


def test_disable_removes_shortcut(fake_appdata: Path) -> None:
    autostart = AutoStart()
    autostart.enable()
    assert autostart.disable()
    assert not autostart.is_enabled()


def test_disable_is_idempotent(fake_appdata: Path) -> None:
    assert AutoStart().disable()  # remover o que nao existe nao e erro


def test_set_enabled_toggles(fake_appdata: Path) -> None:
    autostart = AutoStart()
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not autostart.is_enabled()
