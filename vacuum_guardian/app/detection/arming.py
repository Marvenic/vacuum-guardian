"""Detects a program starting by reading the OSAI "Iso lines" field.

Shop-floor context: every program is named <number>.CNC, so the name says
nothing about whether the job has started. The "Iso lines" field (bottom
left) does: OSAI itself updates it as the program runs.


    stand-by -> irrelevant code
    loaded   -> "CLOSE THE DOORS"  -> time to check the vacuum
    started  -> the text changes   -> the stone can move

The previous version armed on the MATERIAL THICKNESS / EXCEEDING MATERIAL
dialogs. That was removed: the Iso lines field covers the same moment more
reliably, and without OCR over the whole screen.
"""

from __future__ import annotations

from loguru import logger

from ..models import RunPhase


class IsoLineWatcher:
    """Reads the "Iso lines" field and reports the phase of the start.

    More reliable than the program name (all are <number>.CNC) and more direct
    than the confirmation dialogs: OSAI itself writes CLOSE THE DOORS there
    before releasing the cut.

        stand-by -> any text, not relevant                 -> IDLE
        loaded   -> "CLOSE THE DOORS"                      -> DOORS
        started  -> the text changes (code lines appear)   -> RUNNING

    Going from DOORS straight to RUNNING is the evidence that the operator
    carried on: if the vacuum was off, the warning was ignored.
    """

    def __init__(self, keyword: str = "CLOSE THE DOOR") -> None:
        self._keyword = keyword.upper()
        self._phase = RunPhase.IDLE
        self._doors_text = ""  # exact warning text, used to detect the change

    @property
    def phase(self) -> RunPhase:
        return self._phase

    def _to(self, phase: RunPhase) -> None:
        if phase is not self._phase:
            logger.info("Iso lines: {} -> {}", self._phase.value, phase.value)
            self._phase = phase

    def update(self, iso_text: str) -> RunPhase:
        """Processes one cycle's Iso lines text."""
        text = (iso_text or "").upper().strip()

        if self._keyword in text:
            self._doors_text = text
            self._to(RunPhase.DOORS)
        elif self._phase is RunPhase.DOORS and text and text != self._doors_text:
            # The warning went away and other content took its place: it started.
            self._to(RunPhase.RUNNING)
        elif self._phase is RunPhase.RUNNING and not text:
            # ponytail: an empty field means back to stand-by. With no explicit
            # "finished" signal, that is what ends the cycle.
            self._to(RunPhase.IDLE)
        return self._phase

    def reset(self) -> None:
        self._to(RunPhase.IDLE)
        self._doors_text = ""
