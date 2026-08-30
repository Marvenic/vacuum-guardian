"""Testes de responsividade do popup de alarme.

Motivados por falha real na CNC: com o alarme na tela, os botoes nao respondiam
e a janela nao podia ser movida - o operador teve de matar o app pelo
Gerenciador de Tarefas. Causa: show_alarm() e chamado a CADA ciclo enquanto o
alarme dura, e chamava raise_()/activateWindow() todas as vezes. Uma vez por
segundo o app roubava o proprio foco do operador: o clique se perdia entre o
press e o release, e o arrasto da janela era cancelado no meio.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide2")

from app.models import AlertLevel  # noqa: E402
from app.ui.alarm_popup import AlarmPopup  # noqa: E402


@pytest.fixture()
def popup(qt_app):  # type: ignore[no-untyped-def]
    acks: list[str] = []
    widget = AlarmPopup(lambda: acks.append("ack"), lambda: acks.append("silence"))
    widget.calls: list[str] = []  # type: ignore[attr-defined]
    widget.raise_ = lambda: widget.calls.append("raise")  # type: ignore[assignment]
    widget.activateWindow = lambda: widget.calls.append("activate")  # type: ignore[assignment]
    return widget, acks


def _show(widget, level=AlertLevel.CRITICAL, reason="Vacuum 1 is OFF"):  # type: ignore[no-untyped-def]
    widget.show_alarm(reason, "4986_P4.CNC", True, level)


def test_first_show_brings_the_window_to_the_front(popup) -> None:  # type: ignore[no-untyped-def]
    widget, _ = popup
    _show(widget)
    assert widget.calls == ["raise", "activate"]
    assert widget.isVisible()


def test_repeated_cycles_do_not_steal_focus_again(popup) -> None:  # type: ignore[no-untyped-def]
    """O nucleo do bug: 1x por segundo o app roubava o foco de volta."""
    widget, _ = popup
    _show(widget)
    widget.calls.clear()

    for _ in range(10):  # dez ciclos com o alarme ativo
        _show(widget)

    assert widget.calls == [], "popup roubou o foco durante o alarme"
    assert widget.isVisible()


def test_escalation_to_critical_does_bring_it_forward(popup) -> None:  # type: ignore[no-untyped-def]
    """Piorar de laranja para vermelho JUSTIFICA reforcar a presenca."""
    widget, _ = popup
    _show(widget, AlertLevel.WARNING, "could not verify")
    widget.calls.clear()

    _show(widget, AlertLevel.CRITICAL, "Vacuum 1 is OFF")
    assert widget.calls == ["raise", "activate"]


def test_buttons_keep_working_across_cycles(popup) -> None:  # type: ignore[no-untyped-def]
    """Depois de varios ciclos, Acknowledge/Silence ainda tem de agir."""
    widget, acks = popup
    _show(widget)
    for _ in range(5):
        _show(widget)

    widget._mute_button.click()
    assert acks == ["silence"]


def test_pulse_does_not_rebuild_the_stylesheet(popup) -> None:  # type: ignore[no-untyped-def]
    """A pulsacao roda a cada 700 ms; refazer a folha de estilo ali pesava
    na thread da UI justamente durante o alarme."""
    widget, _ = popup
    _show(widget)
    before = widget.styleSheet()

    widget._toggle_shade()
    widget._toggle_shade()

    assert widget.styleSheet() == before  # estilo intacto...
    assert widget.palette().window().color().isValid()  # ...cor vem da paleta


def test_unchanged_text_is_not_rewritten_every_cycle(popup) -> None:  # type: ignore[no-untyped-def]
    widget, _ = popup
    _show(widget)
    text = widget._detail.text()
    _show(widget)
    assert widget._detail.text() == text


def test_reason_change_still_updates_the_text(popup) -> None:  # type: ignore[no-untyped-def]
    widget, _ = popup
    _show(widget, reason="primeiro motivo")
    _show(widget, reason="motivo novo")
    assert "motivo novo" in widget._detail.text()


def test_dismiss_hides_and_stops_the_pulse(popup) -> None:  # type: ignore[no-untyped-def]
    widget, _ = popup
    _show(widget)
    widget.dismiss()
    assert not widget.isVisible()
    assert not widget._pulse.isActive()


# -- os botoes precisam liberar a tela ------------------------------------
#
# Relato do chao de fabrica: "ao clicar em qualquer um dos botoes o alerta nao
# sai da tela para permitir a operacao". O popup cobre a tela do OSAI, entao
# manter o aviso ate a condicao cessar impedia o operador de resolver a
# propria condicao do alarme.

def test_acknowledge_removes_the_alert_from_the_screen(popup) -> None:  # type: ignore[no-untyped-def]
    widget, acks = popup
    _show(widget)
    assert widget.isVisible()

    widget._act(widget._on_acknowledge)

    assert acks == ["ack"]           # a acao foi registrada
    assert not widget.isVisible()    # e a tela foi liberada


def test_silence_removes_the_alert_from_the_screen(popup) -> None:  # type: ignore[no-untyped-def]
    widget, acks = popup
    _show(widget)

    widget._mute_button.click()

    assert acks == ["silence"]
    assert not widget.isVisible()


@pytest.mark.parametrize("level", [AlertLevel.WARNING, AlertLevel.CRITICAL])
def test_both_levels_can_be_dismissed(popup, level) -> None:  # type: ignore[no-untyped-def]
    """Vale para o laranja e para o vermelho - o pedido foi explicito."""
    widget, _ = popup
    _show(widget, level)
    widget._act(widget._on_acknowledge)
    assert not widget.isVisible()


def test_dismissing_stops_the_pulse_timer(popup) -> None:  # type: ignore[no-untyped-def]
    """Escondido e pulsando seria trabalho inutil na thread da UI."""
    widget, _ = popup
    _show(widget)
    widget._act(widget._on_silence)
    assert not widget._pulse.isActive()
