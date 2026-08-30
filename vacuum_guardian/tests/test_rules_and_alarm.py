"""Testes do Rule Engine e da maquina de estados do alarme."""

from __future__ import annotations

from datetime import datetime
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
    True, ("Vacuum1",), (), level=AlertLevel.CRITICAL, reason="OFF: Vacuum1"
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


def test_silence_stops_sound_and_frees_the_screen() -> None:
    """Requisito revisado: o aviso cobre a tela do OSAI e precisa sair no clique."""
    controller, player = _controller()
    controller.update(ALARM)
    controller.silence()
    status = controller.update(ALARM)  # condicao persiste no ciclo seguinte
    assert not status.popup_should_show  # tela liberada para operar a maquina
    assert status.active                 # o alarme segue ativo por dentro
    assert not player.playing


def test_acknowledge_logs_mutes_and_frees_the_screen() -> None:
    controller, player = _controller()
    controller.update(ALARM)
    controller.acknowledge()
    status = controller.update(ALARM)
    assert status.acknowledged
    assert not status.popup_should_show
    assert not player.playing


def test_condition_clearing_resets_everything() -> None:
    controller, player = _controller()
    controller.update(ALARM)
    controller.silence()
    status = controller.update(CLEAR)  # bomba religada
    assert not status.popup_should_show
    assert not player.playing
    # Novo alarme depois do reset volta a tocar som (silencio nao e permanente).
    status = controller.update(ALARM)
    assert status.popup_should_show
    assert player.playing


# -- Som opcional (fabrica barulhenta / PC sem alto-falante) ---------------

def _controller_muted_config() -> tuple[AlarmController, FakePlayer]:
    player = FakePlayer()
    return AlarmController(player, Path("alarm.wav"), sound_enabled=False), player


def test_visual_alarm_works_without_sound() -> None:
    controller, player = _controller_muted_config()
    status = controller.update(ALARM)
    assert status.popup_should_show      # o aviso visual continua igual
    assert not player.playing            # mas nada e reproduzido
    assert player.start_calls == 0
    assert not status.sound_enabled      # UI usa isso para esconder "Silence"


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


# -- Momento critico: programa rodando (campo Iso lines) -------------------

def test_running_with_critical_off_is_critical() -> None:
    """Programa rodando e Vacuum1 OFF -> vermelho."""
    decision = ENGINE.evaluate(_result(PumpState.ON, PumpState.OFF, "4986_P4.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.CRITICAL
    assert "Vacuum1" in decision.reason


def test_running_with_critical_not_visible_is_warning() -> None:
    """Menu rolado: nao da para verificar -> laranja, nunca silencio."""
    decision = ENGINE.evaluate(
        _result(PumpState.ON, PumpState.NOT_VISIBLE, "4986_P4.CNC", RunPhase.RUNNING)
    )
    assert decision.level is AlertLevel.WARNING
    assert "could not be verified" in decision.reason


def test_running_with_critical_unknown_is_warning() -> None:
    """Visivel mas ilegivel tambem e 'nao verificado'."""
    decision = ENGINE.evaluate(
        _result(PumpState.ON, PumpState.UNKNOWN, "4986_P4.CNC", RunPhase.RUNNING)
    )
    assert decision.level is AlertLevel.WARNING


def test_running_with_critical_on_is_silent() -> None:
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.ON, "4986_P4.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.NONE  # o critico e so o Vacuum1


def test_standby_stays_silent_even_with_vacuum_off() -> None:
    """Maquina parada com vacuo desligado e normal - nao pode alarmar."""
    decision = ENGINE.evaluate(_result(PumpState.OFF, PumpState.OFF, "4986_P4.CNC", RunPhase.IDLE))
    assert decision.level is AlertLevel.NONE


def test_critical_indicator_name_matches_ignoring_spaces() -> None:
    """'Vacuum 1' no config deve casar com 'Vacuum1' lido da tela (e vice-versa)."""
    engine = RuleEngine([], critical_indicator="Vacuum 1")
    decision = engine.evaluate(_result(PumpState.ON, PumpState.OFF, "X.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.CRITICAL


def test_missing_critical_indicator_is_warning_not_silence() -> None:
    """Indicador critico ausente da config nao pode virar 'tudo certo'."""
    engine = RuleEngine([], critical_indicator="Vacuum 9")
    decision = engine.evaluate(_result(PumpState.ON, PumpState.ON, "X.CNC", RunPhase.RUNNING))
    assert decision.level is AlertLevel.WARNING


# -- Escalada laranja -> vermelho ------------------------------------------

def test_escalation_from_warning_to_critical_unmutes() -> None:
    """Silenciou o laranja; se virar vermelho, o som precisa voltar."""
    controller, player = _controller()
    controller.update(WARN)
    controller.silence()
    assert not player.playing

    status = controller.update(ALARM)  # a situacao piorou
    assert status.level is AlertLevel.CRITICAL
    assert player.playing
    assert not status.muted


def test_no_unmute_while_level_stays_the_same() -> None:
    """Silencio precisa valer enquanto a severidade nao mudar."""
    controller, player = _controller()
    controller.update(WARN)
    controller.silence()
    controller.update(WARN)
    assert not player.playing


# -- botoes liberam a tela e a acao fica registrada ------------------------
#
# O popup cobre a tela do OSAI: mantido ate a condicao cessar, impedia o
# operador de resolver a propria condicao do alarme. Agora o clique dispensa
# o aviso - e a contrapartida e o registro, porque sem o popup na tela essa
# linha e a unica prova de que alguem viu.

class FakeActionLog:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def record(self, when, action: str, level: str, reason: str) -> bool:  # type: ignore[no-untyped-def]
        self.rows.append((action, level, reason))
        return True


def _controller_with_log() -> tuple[AlarmController, FakePlayer, FakeActionLog]:
    player, log = FakePlayer(), FakeActionLog()
    return AlarmController(player, Path("alarm.wav"), True, log), player, log


def test_acknowledge_takes_the_popup_off_the_screen() -> None:
    controller, _, _ = _controller_with_log()
    assert controller.update(ALARM).popup_should_show

    controller.acknowledge()
    status = controller.update(ALARM)  # condicao ainda existe no ciclo seguinte

    assert not status.popup_should_show  # tela liberada para operar
    assert status.active                 # mas o alarme continua ativo por dentro
    assert status.dismissed


def test_silence_also_takes_the_popup_off_the_screen() -> None:
    controller, player, _ = _controller_with_log()
    controller.update(ALARM)
    controller.silence()
    status = controller.update(ALARM)
    assert not status.popup_should_show
    assert not player.playing


@pytest.mark.parametrize("decision", [ALARM, WARN])
def test_both_levels_can_be_dismissed(decision) -> None:  # type: ignore[no-untyped-def]
    controller, _, _ = _controller_with_log()
    controller.update(decision)
    controller.acknowledge()
    assert not controller.update(decision).popup_should_show


def test_action_is_recorded_with_level_and_reason() -> None:
    controller, _, log = _controller_with_log()
    controller.update(ALARM)
    controller.acknowledge()

    assert len(log.rows) == 1
    action, level, reason = log.rows[0]
    assert action == "ACKNOWLEDGE"
    assert level == "CRITICAL"
    assert "Vacuum1" in reason


def test_silence_is_recorded_as_its_own_action() -> None:
    controller, _, log = _controller_with_log()
    controller.update(WARN)
    controller.silence()
    assert log.rows[0][0] == "SILENCE"
    assert log.rows[0][1] == "WARNING"


def test_clicking_without_an_active_alarm_records_nothing() -> None:
    controller, _, log = _controller_with_log()
    controller.acknowledge()
    assert log.rows == []


def test_escalation_brings_a_dismissed_alert_back() -> None:
    """Dispensou o laranja; virando vermelho, o aviso TEM de voltar."""
    controller, _, _ = _controller_with_log()
    controller.update(WARN)
    controller.acknowledge()
    assert not controller.update(WARN).popup_should_show

    status = controller.update(ALARM)  # a situacao piorou
    assert status.popup_should_show
    assert not status.dismissed


def test_a_new_alarm_after_clearing_shows_again() -> None:
    """Dispensar nao pode valer para o proximo evento."""
    controller, _, _ = _controller_with_log()
    controller.update(ALARM)
    controller.acknowledge()
    controller.update(CLEAR)              # condicao cessou
    assert controller.update(ALARM).popup_should_show
