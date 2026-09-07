"""The Iso lines trigger: warn on CLOSE THE DOORS, alert once it starts.

The real machine flow:
    stand-by          -> irrelevant text
    file loaded       -> "CLOSE THE DOORS"  -> check Vacuum 1
    operator started  -> the text changes   -> alert, and it is recorded
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from app.detection.arming import IsoLineWatcher
from app.logging import OverrideLog
from app.models import (
    AlertLevel,
    DetectionResult,
    IndicatorReading,
    PumpState,
    RunPhase,
)
from app.services import RuleEngine

_DOORS = "CLOSE THE DOORS"
_CODE = "#(WOS,{PROTEZIONI_MAG_1_APERTE}= {TRUE})"
_STANDBY = "(ENDIF) M3 SE209 E209=E209+E208"


# -- reading the Iso lines field -------------------------------------------

def test_standby_text_is_not_a_trigger() -> None:
    watcher = IsoLineWatcher()
    assert watcher.update(_STANDBY) is RunPhase.IDLE


def test_close_the_doors_arms_the_check() -> None:
    watcher = IsoLineWatcher()
    watcher.update(_STANDBY)
    assert watcher.update(_DOORS) is RunPhase.DOORS


def test_text_changing_after_the_warning_means_the_program_started() -> None:
    watcher = IsoLineWatcher()
    watcher.update(_DOORS)
    assert watcher.update(_CODE) is RunPhase.RUNNING


def test_warning_repeated_does_not_count_as_started() -> None:
    """OCR reads the same screen many times a second - that is not a start."""
    watcher = IsoLineWatcher()
    watcher.update(_DOORS)
    for _ in range(5):
        assert watcher.update(_DOORS) is RunPhase.DOORS


def test_singular_close_the_door_also_matches() -> None:
    """OCR may drop the final S; the keyword is singular on purpose."""
    assert IsoLineWatcher().update("CLOSE THE DOOR") is RunPhase.DOORS


def test_change_without_a_previous_warning_is_ignored() -> None:
    """Scrolling code on stand-by must not become 'program running'."""
    watcher = IsoLineWatcher()
    watcher.update(_STANDBY)
    assert watcher.update(_CODE) is RunPhase.IDLE


def test_empty_field_returns_to_standby() -> None:
    watcher = IsoLineWatcher()
    watcher.update(_DOORS)
    watcher.update(_CODE)
    assert watcher.update("") is RunPhase.IDLE


# -- severity --------------------------------------------------------------

ENGINE = RuleEngine([], critical_indicator="Vacuum 1")


def _result(state: PumpState, phase: RunPhase) -> DetectionResult:
    return DetectionResult(
        indicators={"Vacuum 1": IndicatorReading(state, 0.95)},
        program_name="5185_P5.CNC",
        timestamp=datetime.now(),
        elapsed_ms=10.0,
        run_phase=phase,
    )


def test_doors_with_vacuum_off_is_a_warning_not_red() -> None:
    """There is still time to switch it on: warn without shouting."""
    decision = ENGINE.evaluate(_result(PumpState.OFF, RunPhase.DOORS))
    assert decision.level is AlertLevel.WARNING
    assert "CLOSE THE DOORS" in decision.reason


def test_doors_with_vacuum_on_is_silent() -> None:
    assert ENGINE.evaluate(_result(PumpState.ON, RunPhase.DOORS)).level is AlertLevel.NONE


def test_doors_with_unreadable_vacuum_warns() -> None:
    decision = ENGINE.evaluate(_result(PumpState.NOT_VISIBLE, RunPhase.DOORS))
    assert decision.level is AlertLevel.WARNING


def test_running_with_vacuum_off_alerts() -> None:
    """Ignored the warning and cut anyway."""
    decision = ENGINE.evaluate(_result(PumpState.OFF, RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING
    assert "STOP THE MACHINE" in decision.reason


def test_running_with_vacuum_on_is_silent() -> None:
    assert ENGINE.evaluate(_result(PumpState.ON, RunPhase.RUNNING)).level is AlertLevel.NONE


def test_running_with_unreadable_vacuum_warns_but_is_not_red() -> None:
    """Could not read is not proof of off - alert, never silence."""
    decision = ENGINE.evaluate(_result(PumpState.UNKNOWN, RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING


def test_idle_never_alarms() -> None:
    assert ENGINE.evaluate(_result(PumpState.OFF, RunPhase.IDLE)).level is AlertLevel.NONE


# -- the record for the manager --------------------------------------------

def _rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_override_is_recorded_with_date_and_time(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    log = OverrideLog(path)
    assert log.record(datetime(2026, 8, 26, 14, 30, 5), "5185_P5.CNC", "Vacuum 1", "OFF")

    row = _rows(path)[1]
    assert row[0] == "2026-08-26"
    assert row[1] == "14:30:05"
    assert row[2] == "5185_P5.CNC"
    assert row[3] == "Vacuum 1"
    assert row[4] == "OFF"


def test_header_is_not_duplicated_between_runs(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    OverrideLog(path)
    OverrideLog(path)
    assert len(_rows(path)) == 1


# -- end to end: the engine writes the override ----------------------------

def test_engine_records_one_override_per_start(tmp_path: Path) -> None:
    """One event per start - not one per cycle while the alarm sounds."""
    from app.models import AppConfig
    from app.services.monitor import MonitorEngine

    engine = MonitorEngine(AppConfig(), tmp_path)

    def cycle(phase: RunPhase, state: PumpState) -> None:
        engine._record_override(_result(state, phase))

    cycle(RunPhase.DOORS, PumpState.OFF)      # warning on screen, vacuum off
    cycle(RunPhase.RUNNING, PumpState.OFF)    # started anyway -> recorded
    for _ in range(5):
        cycle(RunPhase.RUNNING, PumpState.OFF)  # alarm continues: no repeat

    rows = _rows(tmp_path / "logs" / "overrides.csv")
    assert len(rows) == 2  # header + one event
    assert rows[1][3] == "Vacuum 1"


def test_engine_does_not_record_when_the_vacuum_was_on(tmp_path: Path) -> None:
    from app.models import AppConfig
    from app.services.monitor import MonitorEngine

    engine = MonitorEngine(AppConfig(), tmp_path)
    engine._record_override(_result(PumpState.ON, RunPhase.DOORS))
    engine._record_override(_result(PumpState.ON, RunPhase.RUNNING))

    assert len(_rows(tmp_path / "logs" / "overrides.csv")) == 1  # header only
