"""Rule engine: decides WHETHER there is an alert and WHY.

Main rule (the critical moment):
    Once the Iso lines field announces that a cut is about to start (or is
    already running), the critical indicator ("Vacuum 1") must be proven ON:
    

        ON                      -> nada
        OFF                     -> WARNING (laranja)
        NOT_VISIBLE / UNKNOWN   -> WARNING  (laranja)

    The third case is the most important design decision here: the OSAI menu
    scrolls, so "Vacuum 1" may simply not be on screen. Staying quiet would
    be pretending all is well without having checked anything - so "could not
    verify" alerts too.

Secondary rule (legacy): the program name matches trigger_programs AND
some indicator is OFF -> alert. Still useful for installations whose
programs have descriptive names.

Pure on purpose (no I/O, no state): DetectionResult in, AlarmDecision out.
That makes it trivially testable and independent of the UI.
"""

from __future__ import annotations

from ..models import AlarmDecision, AlertLevel, DetectionResult, PumpState, RunPhase


class RuleEngine:
    def __init__(
        self,
        trigger_programs: list[str],
        critical_indicator: str = "Vacuum 1",
    ) -> None:
        # Normalise once; every comparison is upper case.
        self._triggers = [t.upper() for t in trigger_programs if t.strip()]
        self._critical = critical_indicator.strip()

    @property
    def critical_indicator(self) -> str:
        return self._critical

    def is_monitored_program(self, program_name: str) -> bool:
        """True if any trigger word appears in the program name."""
        name = program_name.upper()
        return bool(name) and any(t in name for t in self._triggers)

    def _critical_reading(self, result: DetectionResult):
        """Reads the critical indicator: exact name first, then ignoring spaces."""
        reading = result.indicators.get(self._critical)
        if reading is not None:
            return reading
        wanted = self._critical.lower().replace(" ", "")
        for name, value in result.indicators.items():
            if name.lower().replace(" ", "") == wanted:
                return value
        return None

    def evaluate(self, result: DetectionResult) -> AlarmDecision:
        monitored = self.is_monitored_program(result.program_name)
        offending = tuple(
            name for name, r in result.indicators.items() if r.state is PumpState.OFF
        )
        unknown = tuple(
            name for name, r in result.indicators.items()
            if not r.state.is_verifiable
        )

        level = AlertLevel.NONE
        reason = ""

        # -- Iso lines rule ------------------------------------------------
        # CLOSE THE DOORS = there is still time to switch the vacuum on.
        # Text changed after that = the machine is already cutting.
        if result.run_phase is RunPhase.DOORS:
            reading = self._critical_reading(result)
            state = reading.state if reading is not None else PumpState.NOT_VISIBLE
            if state is not PumpState.ON:
                level = AlertLevel.WARNING
                reason = (
                    f"CLOSE THE DOORS: turn {self._critical} ON before starting."
                    if state is PumpState.OFF
                    else f"CLOSE THE DOORS: could not verify {self._critical}. Check it."
                )
        elif result.run_phase is RunPhase.RUNNING:
            reading = self._critical_reading(result)
            state = reading.state if reading is not None else PumpState.NOT_VISIBLE
            if state is PumpState.OFF:
                level = AlertLevel.WARNING
                reason = f"Program started with {self._critical} OFF - STOP THE MACHINE."
            elif not state.is_verifiable:
                level = AlertLevel.WARNING
                reason = f"Program running and {self._critical} could not be verified."

        # -- secondary rule (legacy) ---------------------------------------
        if monitored and offending and level is AlertLevel.NONE:
            level = AlertLevel.WARNING
            reason = "OFF: " + ", ".join(offending)

        return AlarmDecision(
            is_monitored_program=monitored,
            offending=offending,
            unknown=unknown,
            level=level,
            reason=reason,
        )
