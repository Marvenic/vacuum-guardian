"""Tests for the settings screen.

They run offscreen (QT_QPA_PLATFORM=offscreen set in conftest), so they open
no real window and need no graphical session.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide2")

from app.models import AppConfig, IndicatorConfig, Roi  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402


def test_edits_are_isolated_until_saved(qt_app) -> None:
    original = AppConfig(capture_interval_s=1.0)
    dialog = SettingsDialog(original)
    dialog._interval.setValue(2.5)
    # Without calling _apply (the Cancel path), the original object is unchanged.
    assert original.capture_interval_s == 1.0
    assert dialog.result_config is None


def test_apply_transfers_all_fields(qt_app) -> None:
    dialog = SettingsDialog(AppConfig())
    dialog._title.setText("OSAI WinNC")
    dialog._interval.setValue(0.5)
    dialog._threshold.setValue(0.92)
    dialog._programs.setPlainText("sink\ncutout\n\nbowl")
    dialog._apply()

    saved = dialog.result_config
    assert saved is not None
    assert saved.window_title_hint == "OSAI WinNC"
    assert saved.capture_interval_s == 0.5
    assert saved.template_threshold == 0.92
    assert saved.trigger_programs == ["SINK", "CUTOUT", "BOWL"]  # normaliza e ignora vazios


def test_renaming_indicator_preserves_roi_of_unchanged_ones(qt_app) -> None:
    config = AppConfig(
        indicators=[
            IndicatorConfig("Vacuum Pump", Roi(1, 2, 30, 40)),
            IndicatorConfig("Vacuum1", Roi(5, 6, 30, 40)),
        ]
    )
    dialog = SettingsDialog(config)
    dialog._indicators.setPlainText("Vacuum Pump\nVacuum2")  # renomeia o segundo
    dialog._apply()

    saved = dialog.result_config
    assert saved is not None
    assert saved.indicators[0].roi == Roi(1, 2, 30, 40)  # ROI preservada
    assert saved.indicators[1].name == "Vacuum2"
    assert saved.indicators[1].roi is None               # novo indicador exige calibracao


def test_nonexistent_wav_falls_back_to_default(qt_app) -> None:
    dialog = SettingsDialog(AppConfig())
    dialog._wav.setText("C:/caminho/que/nao/existe.wav")
    dialog._apply()
    assert dialog.result_config is not None
    assert dialog.result_config.alarm_wav == ""  # vazio = assets/alarm.wav


def test_sound_toggle_is_saved(qt_app) -> None:
    dialog = SettingsDialog(AppConfig(alarm_sound_enabled=True))
    dialog._sound_check.setChecked(False)
    dialog._apply()
    assert dialog.result_config is not None
    assert dialog.result_config.alarm_sound_enabled is False


def test_wav_field_disabled_when_sound_is_off(qt_app) -> None:
    """Choosing a sound file with sound off would confuse the operator."""
    dialog = SettingsDialog(AppConfig(alarm_sound_enabled=True))
    assert dialog._wav.isEnabled()
    dialog._sound_check.setChecked(False)
    assert not dialog._wav.isEnabled()
