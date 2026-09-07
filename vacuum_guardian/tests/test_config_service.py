"""ConfigService: round-trip, defaults and tolerance of a corrupted file."""

from __future__ import annotations

from pathlib import Path

from app.config import ConfigService
from app.models import AppConfig, IndicatorConfig, Roi


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    service = ConfigService(tmp_path / "config.json")
    config = service.load()
    assert config == AppConfig()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    service = ConfigService(path)
    original = AppConfig(
        window_title_hint="OSAI WinNC",
        capture_interval_s=0.5,
        trigger_programs=["SINK", "BOWL"],
        template_threshold=0.9,
        indicators=[
            IndicatorConfig("Vacuum Pump", Roi(10, 20, 100, 50)),
            IndicatorConfig("Vacuum1", Roi(10, 80, 100, 50)),
        ],
        program_roi=Roi(0, 0, 300, 30),
        alarm_wav="C:/sons/alarme.wav",
    )
    service.save(original)
    assert path.exists()
    assert service.load() == original


def test_corrupted_json_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ isto nao e json", encoding="utf-8")
    assert ConfigService(path).load() == AppConfig()


def test_trigger_programs_are_normalized_to_uppercase(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"trigger_programs": ["sink", "Bowl"]}', encoding="utf-8")
    config = ConfigService(path).load()
    assert config.trigger_programs == ["SINK", "BOWL"]


def test_roi_validity() -> None:
    assert Roi(0, 0, 10, 10).is_valid()
    assert not Roi(0, 0, 0, 10).is_valid()
    assert not Roi(-1, 0, 10, 10).is_valid()


def test_sound_option_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    service = ConfigService(path)
    service.save(AppConfig(alarm_sound_enabled=False))
    assert service.load().alarm_sound_enabled is False


def test_missing_sound_option_defaults_to_enabled(tmp_path: Path) -> None:
    """An older config (without the field) must keep the sound on - fail-safe."""
    path = tmp_path / "config.json"
    path.write_text('{"window_title_hint": "OSAI"}', encoding="utf-8")
    assert ConfigService(path).load().alarm_sound_enabled is True
