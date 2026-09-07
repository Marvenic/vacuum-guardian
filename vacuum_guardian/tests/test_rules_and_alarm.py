"""Tests for the rule engine and the alarm state machine."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.alarm import AlarmController
from app.models import (
    AlarmDecision,
    AlertLevel,
    DetectionResult,
    IndicatorReading,
    PumpState,
    RunPhase,
)
from app.services import RuleEngine


def _result(
    pump: PumpState, vacuum1: PumpState, program: str,
    phase: RunPhase = RunPhase.IDLE,
) -> DetectionResult:
    return DetectionResult(
        indicators={
            "Vacuum Pump": IndicatorReading(pump, 0.95),
            "Vacuum1": IndicatorReading(vacuum1, 0.95),
        },
        program_name=program,
        timestamp=datetime.now(),
        elapsed_ms=10.0,
        run_phase=phase,
    )


ENGINE = RuleEngine(["SINK", "CUTOUT", "BOWL"], critical_indicator="Vacuum1")


# -- Rule Engine -----------------------------------------------------------

def test_alarm_when_any_indicator_off_in_monitored_program() -> None:
    # Vacuum Pump ON mas Vacuum1 OFF -> alarme (regra do adendo: AMBOS devem estar ON).
    decision = ENGINE.evaluate(_result(PumpState.ON, PumpState.OFF, "SINK_CUTOUT_01"))
    assert decision.should_alarm
    assert decision.offending == ("Vacuum1",)


def test_no_alarm_when_both_indicators_on() -> None:
    decision = ENGINE.evaluate(_result(PumpState.ON, PumpState.ON, "SINK_CUTOUT_01"))
    assert not decision.should_alarm


def test_no_alarm_for_unmonitored_program() -> None:
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.OFF, "FACHADA_02"))
    assert not decision.should_alarm
    assert decision.offending == ("Vacuum Pump", "Vacuum1")  # reportado, mas sem alarme


def test_no_alarm_for_empty_program_name() -> None:
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.OFF, ""))
    assert not decision.should_alarm


def test_unknown_never_alarms_but_is_reported() -> None:
    decision = ENGINE.evaluate(_result(PumpState.UNKNOWN, PumpState.UNKNOWN, "BOWL_A"))
    assert not decision.should_alarm
    assert decision.unknown == ("Vacuum Pump", "Vacuum1")


def test_trigger_match_is_case_insensitive_substring() -> None:
    assert ENGINE.is_monitored_program("prog_sink_v2")
    assert ENGINE.is_monitored_program("CUTOUT")
    assert not ENGINE.is_monitored_program("POLIMENTO")


# -- AlarmController -------------------------------------------------------

class FakePlayer:
    def __init__(self) -> None:
        self.playing = False
        self.start_calls = 0

    def start_loop(self, wav_path: Path) -> None:
        self.playing = True
        self.start_calls += 1

    def stop(self) -> None:
        self.playing = False


ALARM = AlarmDecision(
    True, ("Vacuum1",), (), level=AlertLevel.WARNING, reason="OFF: Vacuum1"
)
WARN = AlarmDecision(
    False, (), ("Vacuum1",), level=AlertLevel.WARNING,
    reason="Could not verify Vacuum1",
)
CLEAR = AlarmDecision(True, (), ())


def _controller() -> tuple[AlarmController, FakePlayer]:
    player = FakePlayer()
    return AlarmController(player, Path("alarm.wav")), player


def test_alarm_triggers_sound_and_popup() -> None:
    controller, player = _controller()
    status = controller.update(ALARM)
    assert status.popup_should_show
    assert player.playing
    assert "Vacuum1" in status.reason


def test_acknowledge_frees_the_screen_and_stops_the_sound() -> None:
    """The warning covers the OSAI screen and must clear on the click."""
    controller, player = _controller()
    controller.update(ALARM)
    controller.acknowledge()
    status = controller.update(ALARM)  # condicao persiste no ciclo seguinte
    assert not status.popup_should_show  # screen freed to operate the machine
    assert not player.playing
    assert status.snoozed


def test_snooze_lasts_five_minutes_then_the_alarm_returns() -> None:
    """The operator needs time to reach the machine - and the warning returns."""
    controller, player = _controller()
    start = datetime(2026, 8, 30, 10, 0, 0)
    controller.update(ALARM, start)
    controller.acknowledge(start)

    # During the snooze: nothing on screen, no sound.
    during = controller.update(ALARM, start + timedelta(minutes=4, seconds=59))
    assert not during.popup_should_show
    assert not player.playing
    assert during.snoozed

    # After five minutes the condition still holds -> it warns again.
    after = controller.update(ALARM, start + timedelta(minutes=5, seconds=1))
    assert after.popup_should_show
    assert player.playing
    assert not after.snoozed


def test_condition_clearing_resets_everything() -> None:
    controller, player = _controller()
    controller.update(ALARM)
    controller.acknowledge()
    status = controller.update(CLEAR)  # bomba religada
    assert not status.popup_should_show
    assert not player.playing
    # A new alarm after the reset plays sound again (silence is not permanent).
    status = controller.update(ALARM)
    assert status.popup_should_show
    assert player.playing


# -- Optional sound (noisy shop / PC with no speakers) --------------------

def _controller_muted_config() -> tuple[AlarmController, FakePlayer]:
    player = FakePlayer()
    return AlarmController(player, Path("alarm.wav"), sound_enabled=False), player


def test_visual_alarm_works_without_sound() -> None:
    controller, player = _controller_muted_config()
    status = controller.update(ALARM)
    assert status.popup_should_show      # o aviso visual continua igual
    assert not player.playing            # mas nada e reproduzido
    assert player.start_calls == 0
    assert not status.sound_enabled      # the UI uses this to hide the button


def test_sound_disabled_never_plays_across_cycles() -> None:
    controller, player = _controller_muted_config()
    for _ in range(5):
        controller.update(ALARM)
    assert player.start_calls == 0


def test_sound_enabled_by_default_still_plays() -> None:
    controller, player = _controller()
    status = controller.update(ALARM)
    assert player.playing
    assert status.sound_enabled


# -- Critical moment: program running (Iso lines field) -------------------

def test_running_with_critical_off_alerts() -> None:
    """Program running with Vacuum1 OFF -> alert."""
    decision = ENGINE.evaluate(_result(PumpState.ON, PumpState.OFF, "4986_P4.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING
    assert "Vacuum1" in decision.reason


def test_running_with_critical_not_visible_is_warning() -> None:
    """Menu scrolled: cannot verify -> alert, never silence."""
    decision = ENGINE.evaluate(
        _result(PumpState.ON, PumpState.NOT_VISIBLE, "4986_P4.CNC", RunPhase.RUNNING)
    )
    assert decision.level is AlertLevel.WARNING
    assert "could not be verified" in decision.reason


def test_running_with_critical_unknown_is_warning() -> None:
    """Visible but unreadable also counts as 'not verified'."""
    decision = ENGINE.evaluate(
        _result(PumpState.ON, PumpState.UNKNOWN, "4986_P4.CNC", RunPhase.RUNNING)
    )
    assert decision.level is AlertLevel.WARNING


def test_running_with_critical_on_is_silent() -> None:
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.ON, "4986_P4.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.NONE  # o critico e so o Vacuum1


def test_standby_stays_silent_even_with_vacuum_off() -> None:
    """An idle machine with the vacuum off is normal - it must not alarm."""
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.OFF, "4986_P4.CNC", RunPhase.IDLE))
    assert decision.level is AlertLevel.NONE


def test_critical_indicator_name_matches_ignoring_spaces() -> None:
    """'Vacuum 1' in config must match 'Vacuum1' read from screen, and back."""
    engine = RuleEngine([], critical_indicator="Vacuum 1")
    decision = engine.evaluate(_result(PumpState.ON, PumpState.OFF, "X.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING


def test_missing_critical_indicator_is_warning_not_silence() -> None:
    """A critical indicator missing from the config must not read as 'all fine'."""
    engine = RuleEngine([], critical_indicator="Vacuum 9")
    decision = engine.evaluate(_result(PumpState.ON, PumpState.ON, "X.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING


# -- the button frees the screen and the action is recorded ---------------
#
# The popup covers the OSAI screen: kept until the condition cleared, it
# stopped the operator from resolving the very condition. The click now
# dismisses it - and the trade-off is the record, because with no popup on
# screen that line is the only proof anyone saw it.

class FakeActionLog:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, object]] = []

    def record(self, when, action: str, reason: str, silenced_until=None) -> bool:  # type: ignore[no-untyped-def]
        self.rows.append((action, reason, silenced_until))
        return True


def _controller_with_log() -> tuple[AlarmController, FakePlayer, FakeActionLog]:
    player, log = FakePlayer(), FakeActionLog()
    return AlarmController(player, Path("alarm.wav"), True, log), player, log


def test_acknowledge_takes_the_popup_off_the_screen() -> None:
    controller, _, _ = _controller_with_log()
    assert controller.update(ALARM).popup_should_show

    controller.acknowledge()
    status = controller.update(ALARM)  # condicao ainda existe no ciclo seguinte

    assert not status.popup_should_show  # screen freed to operate
    assert status.snoozed


def test_action_is_recorded_with_reason_and_snooze_end() -> None:
    controller, _, log = _controller_with_log()
    start = datetime(2026, 8, 30, 10, 0, 0)
    controller.update(ALARM, start)
    controller.acknowledge(start)

    assert len(log.rows) == 1
    action, reason, silenced_until = log.rows[0]
    assert action == "ACKNOWLEDGE"
    assert "Vacuum1" in reason
    assert silenced_until == start + timedelta(minutes=5)


def test_clicking_without_an_active_alarm_records_nothing() -> None:
    controller, _, log = _controller_with_log()
    controller.acknowledge()
    assert log.rows == []


def test_resolving_the_condition_cancels_the_snooze() -> None:
    """Vacuum back on: nothing to silence, and a new alarm warns at once."""
    controller, player, _ = _controller_with_log()
    start = datetime(2026, 8, 30, 10, 0, 0)
    controller.update(ALARM, start)
    controller.acknowledge(start)

    controller.update(CLEAR, start + timedelta(seconds=30))  # operador ligou o vacuo
    status = controller.update(ALARM, start + timedelta(minutes=1))
    assert status.popup_should_show
    assert player.playing


def test_a_new_alarm_after_clearing_shows_again() -> None:
    """Dismissing must not carry over to the next event."""
    controller, _, _ = _controller_with_log()
    controller.update(ALARM)
    controller.acknowledge()
    controller.update(CLEAR)              # condicao cessou
    assert controller.update(ALARM).popup_should_show
