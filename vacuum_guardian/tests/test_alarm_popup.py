"""Responsiveness tests for the alarm popup.

Motivated by a real CNC failure: with the alarm on screen the buttons did not
respond and the window could not be moved - the operator had to kill the app
from Task Manager. Cause: show_alarm() is called on EVERY cycle while the
alarm lasts, and it called raise_()/activateWindow() every time. Once a
second the app stole focus from the operator: the click was lost between
press and release, and dragging the window was cancelled halfway.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide2")

from app.ui.alarm_popup import AlarmPopup  # noqa: E402


@pytest.fixture()
def popup(qt_app):  # type: ignore[no-untyped-def]
    acks: list[str] = []
    widget = AlarmPopup(lambda: acks.append("ack"))
    widget.calls: list[str] = []  # type: ignore[attr-defined]
    widget.raise_ = lambda: widget.calls.append("raise")  # type: ignore[assignment]
    widget.activateWindow = lambda: widget.calls.append("activate")  # type: ignore[assignment]
    return widget, acks


def _show(widget, reason="Vacuum 1 is OFF"):  # type: ignore[no-untyped-def]
    widget.show_alarm(reason, "4986_P4.CNC", True)


def test_first_show_brings_the_window_to_the_front(popup) -> None:  # type: ignore[no-untyped-def]
    widget, _ = popup
    _show(widget)
    assert widget.calls == ["raise", "activate"]
    assert widget.isVisible()


def test_repeated_cycles_do_not_steal_focus_again(popup) -> None:  # type: ignore[no-untyped-def]
    """The core of the bug: once a second the app stole focus back."""
    widget, _ = popup
    _show(widget)
    widget.calls.clear()

    for _ in range(10):  # dez ciclos com o alarme ativo
        _show(widget)

    assert widget.calls == [], "popup roubou o foco durante o alarme"
    assert widget.isVisible()


def test_new_reason_does_not_steal_focus_either(popup) -> None:  # type: ignore[no-untyped-def]
    """With one level, nothing justifies stealing focus after the first show."""
    widget, _ = popup
    _show(widget, "could not verify")
    widget.calls.clear()

    _show(widget, "Vacuum 1 is OFF")
    assert widget.calls == []


def test_button_keeps_working_across_cycles(popup) -> None:  # type: ignore[no-untyped-def]
    """After several cycles, Acknowledge must still act."""
    widget, acks = popup
    _show(widget)
    for _ in range(5):
        _show(widget)

    widget._act(widget._on_acknowledge)
    assert acks == ["ack"]


def test_pulse_does_not_rebuild_the_stylesheet(popup) -> None:  # type: ignore[no-untyped-def]
    """The pulse runs every 700 ms; rebuilding the stylesheet there weighed
    on the UI thread exactly during the alarm."""
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
# Shop-floor report: "clicking either button does not take the alert off the
# screen so the machine can be operated". The popup covers the OSAI screen,
# so keeping it until the condition cleared stopped the operator from
# resolving the very condition being alarmed.

def test_acknowledge_removes_the_alert_from_the_screen(popup) -> None:  # type: ignore[no-untyped-def]
    widget, acks = popup
    _show(widget)
    assert widget.isVisible()

    widget._act(widget._on_acknowledge)

    assert acks == ["ack"]           # a acao foi registrada
    assert not widget.isVisible()    # e a tela foi liberada


def test_only_one_button_is_offered(popup) -> None:  # type: ignore[no-untyped-def]
    """Two buttons with the same practical effect only forced a choice."""
    from PySide2.QtWidgets import QPushButton

    widget, _ = popup
    labels = [b.text() for b in widget.findChildren(QPushButton)]
    assert labels == ["Acknowledge"]


def test_the_alert_can_always_be_dismissed(popup) -> None:  # type: ignore[no-untyped-def]
    """The operator needs the OSAI screen free to resolve the condition."""
    widget, _ = popup
    _show(widget)
    widget._act(widget._on_acknowledge)
    assert not widget.isVisible()


def test_dismissing_stops_the_pulse_timer(popup) -> None:  # type: ignore[no-untyped-def]
    """Hidden and pulsing would be wasted work on the UI thread."""
    widget, _ = popup
    _show(widget)
    widget._act(widget._on_acknowledge)
    assert not widget._pulse.isActive()
