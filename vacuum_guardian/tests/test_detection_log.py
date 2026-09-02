"""Testes da trilha de auditoria CSV."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from app.logging import DetectionLog
from app.models import (
    AlarmDecision,
    AlertLevel,
    DetectionResult,
    IndicatorReading,
    PumpState,
)


def _result(pump: PumpState, vacuum1: PumpState, program: str = "SINK_01") -> DetectionResult:
    return DetectionResult(
        indicators={
            "Vacuum Pump": IndicatorReading(pump, 0.9),
            "Vacuum1": IndicatorReading(vacuum1, 0.9),
        },
        program_name=program,
        timestamp=datetime(2026, 8, 24, 14, 30, 5),
        elapsed_ms=42.5,
    )


def _rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_header_is_written_once(tmp_path: Path) -> None:
    path = tmp_path / "detections.csv"
    DetectionLog(path)
    DetectionLog(path)  # segunda execucao do app nao duplica cabecalho
    rows = _rows(path)
    assert len(rows) == 1
    assert rows[0][0] == "date"


def test_records_state_and_fields(tmp_path: Path) -> None:
    path = tmp_path / "detections.csv"
    log = DetectionLog(path)
    assert log.record(_result(PumpState.ON, PumpState.OFF), AlarmDecision(True, ("Vacuum1",), (), level=AlertLevel.WARNING))
    row = _rows(path)[1]
    assert row[0] == "2026-08-24"
    assert row[1] == "14:30:05"
    assert row[2] == "SINK_01"
    assert row[3] == "YES"                       # programa monitorado
    assert "Vacuum1=OFF" in row[4]
    assert row[5] == "YES"                       # alarme
    assert row[6] == "42.5"


def test_unchanged_state_is_not_repeated(tmp_path: Path) -> None:
    path = tmp_path / "detections.csv"
    log = DetectionLog(path)
    decision = AlarmDecision(True, (), ())
    assert log.record(_result(PumpState.ON, PumpState.ON), decision)
    assert not log.record(_result(PumpState.ON, PumpState.ON), decision)   # sem mudanca
    assert not log.record(_result(PumpState.ON, PumpState.ON), decision)
    assert len(_rows(path)) == 2  # cabecalho + 1 linha


def test_state_change_creates_new_row(tmp_path: Path) -> None:
    path = tmp_path / "detections.csv"
    log = DetectionLog(path)
    log.record(_result(PumpState.ON, PumpState.ON), AlarmDecision(True, (), ()))
    log.record(_result(PumpState.ON, PumpState.OFF), AlarmDecision(True, ("Vacuum1",), (), level=AlertLevel.WARNING))
    log.record(_result(PumpState.ON, PumpState.ON), AlarmDecision(True, (), ()))
    assert len(_rows(path)) == 4  # cabecalho + 3 transicoes


def test_program_change_creates_new_row(tmp_path: Path) -> None:
    path = tmp_path / "detections.csv"
    log = DetectionLog(path)
    decision = AlarmDecision(True, (), ())
    log.record(_result(PumpState.ON, PumpState.ON, "SINK_01"), decision)
    log.record(_result(PumpState.ON, PumpState.ON, "SINK_02"), decision)
    assert len(_rows(path)) == 3
