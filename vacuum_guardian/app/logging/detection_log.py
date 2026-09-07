"""Trilha de auditoria em CSV (requisito 8).

Por que um CSV separado do log do loguru:
- o .log e para diagnostico humano; o CSV e para analise (Excel, Power BI);
- stable columns allow correlating alarms with shifts and programs.

Estrategia de escrita: apenas MUDANCAS de estado (ou eventos de alarme) sao
gravadas. Registrar todos os ciclos geraria ~86 mil linhas/dia a 1 Hz, sem
gain in information. This keeps the file readable and the disk healthy under
operacao continua.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..models import AlarmDecision, DetectionResult


class DetectionLog:
    """Writes one row per detected state transition."""

    # New columns always go AT THE END: spreadsheets and reports built on
    # older files keep pointing at the same positions.
    _HEADER = [
        "date",
        "time",
        "program",
        "monitored_program",
        "indicators",
        "alarm",
        "elapsed_ms",
        "level",
        "phase",
    ]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._last_signature: str | None = None
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Creates the file with a header on first run."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:  # disco cheio/permissao: nunca derrubar o monitor
            logger.error("Could not prepare {}: {}", self._path, exc)

    @staticmethod
    def _signature(result: DetectionResult, decision: AlarmDecision) -> str:
        """Identity of the current state; a change means a row is worth writing."""
        states = ",".join(f"{k}={v.state.value}" for k, v in sorted(result.indicators.items()))
        return f"{result.program_name}|{states}|{decision.level.name}|{result.run_phase.value}"

    def record(self, result: DetectionResult, decision: AlarmDecision) -> bool:
        """Writes if the state changed since the last row. True when it wrote."""
        signature = self._signature(result, decision)
        if signature == self._last_signature:
            return False
        self._last_signature = signature

        row = [
            f"{result.timestamp:%Y-%m-%d}",
            f"{result.timestamp:%H:%M:%S}",
            result.program_name,
            "YES" if decision.is_monitored_program else "NO",
            " ".join(f"{k}={v.state.value}" for k, v in sorted(result.indicators.items())),
            "YES" if decision.should_alarm else "NO",
            f"{result.elapsed_ms:.1f}",
            decision.level.name,
            result.run_phase.value,
        ]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the CSV audit trail: {}", exc)
            return False
        return True


class OverrideLog:
    """Records when the operator started a program with the vacuum off.

    A file of its own (not a column in detections.csv) because the audience is
    different: a manager wants a short list of "ignored the warning and cut
    anyway", with date and time, without filtering thousands of rows.

    One row per event: the CLOSE THE DOORS -> running transition with the
    vacuum not in the ON state.
    """

    _HEADER = ["date", "time", "program", "indicator", "state_at_start"]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensure_header()

    def _ensure_header(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:
            logger.error("Could not prepare {}: {}", self._path, exc)

    def record(self, when: datetime, program: str, indicator: str, state: str) -> bool:
        """Records an override. True when it managed to write."""
        row = [
            f"{when:%Y-%m-%d}",
            f"{when:%H:%M:%S}",
            program,
            indicator,
            state,
        ]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the override log: {}", exc)
            return False
        logger.warning(
            "OVERRIDE: program started with {} = {} (recorded for the manager)",
            indicator, state,
        )
        return True


class AlarmActionLog:
    """Records what the operator did when the alarm appeared.

    A file of its own because the question is specific and frequent: "the alarm
    fired, did anyone see it?". One row per click, with the reason that was on
    screen and how long it was silenced for - once dismissed the popup is gone
    and this is the only proof it was seen.
    """

    _HEADER = ["date", "time", "action", "reason", "silenced_until"]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensure_header()

    def _ensure_header(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:
            logger.error("Could not prepare {}: {}", self._path, exc)

    def record(
        self, when: datetime, action: str, reason: str,
        silenced_until: datetime | None = None,
    ) -> bool:
        """Records an operator action. True when it managed to write."""
        row = [
            f"{when:%Y-%m-%d}",
            f"{when:%H:%M:%S}",
            action,
            reason,
            f"{silenced_until:%H:%M:%S}" if silenced_until else "",
        ]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the alarm action log: {}", exc)
            return False
        return True
