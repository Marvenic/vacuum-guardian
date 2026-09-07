"""Consent: the box starts unticked and the operator card is optional."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide2")

from app.models import AppConfig  # noqa: E402
from app.ui.telemetry_dialog import TelemetryDialog  # noqa: E402


def _dialog(qt_app, config: AppConfig) -> TelemetryDialog:  # type: ignore[no-untyped-def]
    return TelemetryDialog(config, {"install_id": "x", "usage": {}})


def test_checkbox_starts_unticked_for_a_new_install(qt_app) -> None:
    """Consent is given, never assumed."""
    assert not _dialog(qt_app, AppConfig())._share.isChecked()


def test_cancel_changes_nothing(qt_app) -> None:
    config = AppConfig()
    dialog = _dialog(qt_app, config)
    dialog._share.setChecked(True)
    dialog.reject()
    assert not config.telemetry_enabled


def test_saving_records_the_answer_and_stops_asking(qt_app) -> None:
    config = AppConfig()
    dialog = _dialog(qt_app, config)
    dialog._share.setChecked(True)
    dialog._apply()
    assert config.telemetry_enabled
    assert config.telemetry_prompted  # it will not ask again on every boot


def test_declining_is_also_remembered(qt_app) -> None:
    config = AppConfig()
    dialog = _dialog(qt_app, config)
    dialog._apply()  # without ticking the box
    assert not config.telemetry_enabled
    assert config.telemetry_prompted


def test_operator_card_is_saved_trimmed(qt_app) -> None:
    config = AppConfig()
    dialog = _dialog(qt_app, config)
    dialog._company.setText("  Stone Co  ")
    dialog._email.setText("a@b.com")
    dialog._apply()
    assert config.operator_company == "Stone Co"
    assert config.operator_email == "a@b.com"
    assert config.operator_phone == ""


def test_the_preview_shows_the_real_payload(qt_app) -> None:
    """The operator must see the document, not a description of it."""
    from PySide2.QtWidgets import QPlainTextEdit

    dialog = TelemetryDialog(AppConfig(), {"install_id": "abc123", "usage": {"cycles": 7}})
    preview = dialog.findChild(QPlainTextEdit)
    assert "abc123" in preview.toPlainText()
    assert "cycles" in preview.toPlainText()
