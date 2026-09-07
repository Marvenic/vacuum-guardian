"""Alarm popup: always on top, until the operator acts.

The popup decides nothing: MainWindow shows and hides it from AlarmStatus,
and the button forwards the operator's intent to the AlarmController.

WHY THE BUTTON CLOSES THE WARNING: it covers the OSAI screen. Keeping it
there until the condition cleared stopped the operator from touching the
machine to FIX the very condition being alarmed - the warning became the
obstacle. Acknowledge now clears it and the action is written to
logs/alarm_actions.csv: with no popup on screen, that record is the only
proof anyone saw it. After the click the alarm is snoozed for 5 minutes;
the panel and tray icon keep showing the real state during that time.

ONE LEVEL ONLY (orange). There used to be red ("it is off") and orange
("could not verify"); the operator's next move was the same either way -
go and check the vacuum - so two screens only added noise. The specific
reason is still written in the body of the warning.

ONE BUTTON: Acknowledge. It records, mutes and snoozes for 5 minutes -
time enough to reach the machine without the warning coming straight back.

Why the background PULSES: sound is optional (noisy shop, CNC PCs often
have no speakers). With no audio a static rectangle is lost in the
peripheral vision of someone looking at the workpiece; a shade change
every ~700 ms is caught peripherally and pulls attention back.
The blink is slow on purpose - fast flashing (>3 Hz) is uncomfortable and
can be a photosensitivity trigger.

All operator-facing text is in English (the language of the shop floor).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QColor, QCloseEvent, QFont, QGuiApplication, QPalette
from PySide2.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

# Orange: the only level. (light shade, dark shade, button text colour)
_LIGHT, _DARK, _BUTTON_TEXT = "#e07000", "#8a4500", "#8a4500"
_TITLE = "CHECK THE VACUUM"
_PULSE_MS = 700

# The WINDOW is proportional to the screen: the alert must dominate the
# monitor, Full HD or 4K. Not full screen on purpose - the operator still
# sees the OSAI screen behind it and keeps the context.
_SCREEN_FRACTION_W = 0.62
_SCREEN_FRACTION_H = 0.52
_MIN_W, _MIN_H = 900, 540

# FONTS, on the other hand, are fixed in points. A point is a physical
# unit (1/72 in) and Qt already scales it by monitor DPI: 44pt is the same
# physical size on Full HD and on 4K. Scaling points by pixels would count
# the scaling twice and shrink the text on high-DPI screens.
_TITLE_PT = 44
_DETAIL_PT = 22
_BUTTON_PT = 17


class AlarmPopup(QDialog):
    def __init__(self, on_acknowledge: Callable[[], None]) -> None:
        super().__init__()
        self._locked = True  # enquanto True, o X da janela e Esc sao ignorados
        # Publico de proposito: MainWindow o substitui ao reconstruir o engine.
        self._on_acknowledge = on_acknowledge

        self.setWindowTitle("ALARM - VACUUM GUARDIAN")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowStaysOnTopHint
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint  # title bar without a close button
        )

        self._title = QLabel(_TITLE)
        self._title.setFont(QFont("Segoe UI", _TITLE_PT, QFont.Black))
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)

        self._detail = QLabel("")
        self._detail.setFont(QFont("Segoe UI", _DETAIL_PT))
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setWordWrap(True)

        # The lambda resolves the attribute AT CLICK TIME, so MainWindow can swap
        # the callback when the engine is rebuilt (recalibration).
        # The click closes the warning IMMEDIATELY, without waiting for the next
        # cycle (up to 1 s of delay feels like a dead button - that was the report).
        # The AlarmController still owns the state; this only anticipates what it
        # would decide on the following cycle.
        ack = QPushButton("Acknowledge")
        ack.clicked.connect(lambda: self._act(self._on_acknowledge))

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(ack)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 56, 56, 56)
        layout.addWidget(self._title)
        layout.addSpacing(12)
        layout.addWidget(self._detail)
        layout.addSpacing(24)
        layout.addLayout(buttons)

        # Background pulse: runs only while the popup is visible.
        self.setAutoFillBackground(True)  # needed for the palette to paint it
        self._bright = True
        self._pulse = QTimer(self)
        self._pulse.setInterval(_PULSE_MS)
        self._pulse.timeout.connect(self._toggle_shade)
        self._apply_button_style()
        self._apply_shade(bright=True)

    # -- aparencia ---------------------------------------------------------

    def _apply_shade(self, bright: bool) -> None:
        """Swaps the background colour only - runs every 700 ms, must be cheap.

        This used to call setStyleSheet(), which re-polished the whole widget
        tree twice a second. On a modest CNC PC that constant work on the UI
        thread competed with the very clicks the operator was making on the
        alarm. The palette changes colour without reprocessing any style.
        """
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(_LIGHT if bright else _DARK))
        self.setPalette(palette)

    def _apply_button_style(self) -> None:
        """Fixed button style - set once, not on every pulse.

        It deliberately does not set the QDialog background: that belongs to
        the palette in _apply_shade. A stylesheet with background-color would
        beat the palette and kill the pulse.
        """
        self.setStyleSheet(
            "QLabel { color: white; }"
            f"QPushButton {{ background-color: white; color: {_BUTTON_TEXT};"
            f"  font-weight: bold; padding: 18px 44px;"
            f"  border-radius: 6px; font-size: {_BUTTON_PT}pt; }}"
            "QPushButton:hover { background-color: #ffeedd; }"
        )

    def _resize_to_screen(self) -> None:
        """Sizes and centres the popup for the screen it will appear on.

        Recomputed on every show: the operator may have changed resolution, or
        the app may have moved to another monitor.
        """
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is None:
            width, height = _MIN_W, _MIN_H
        else:
            width = max(_MIN_W, int(available.width() * _SCREEN_FRACTION_W))
            height = max(_MIN_H, int(available.height() * _SCREEN_FRACTION_H))
            # Never larger than the available area (protects small screens).
            width = min(width, available.width())
            height = min(height, available.height())

        self.resize(width, height)
        if available is not None:
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())

    def _toggle_shade(self) -> None:
        self._bright = not self._bright
        self._apply_shade(self._bright)

    # -- ciclo de vida -----------------------------------------------------

    def show_alarm(self, reason: str, program: str, sound_enabled: bool = True) -> None:
        """Shows (or updates) the warning in the foreground.

        `sound_enabled` no longer changes the buttons (there is only one, and it
        serves both cases); it stays as a parameter because MainWindow already
        passes it and the button text may depend on it again.
        """
        # Only touch the widgets if the text actually changed: this method is
        # called on EVERY cycle while the alarm lasts.
        detail = "Program: {}\n{}".format(program or "?", reason)
        if detail != self._detail.text():
            self._detail.setText(detail)

        if not self.isVisible():
            self._resize_to_screen()
            self.showNormal()
            self._bright = True
            self._apply_shade(bright=True)
            self._pulse.start()
            # Raise to the front ONLY when appearing. Calling raise_ on every cycle
            # stole focus from the operator: the click on the button was lost
            # between press and release. That was the "frozen alarm" on the CNC.
            self.raise_()
            self.activateWindow()

    def _act(self, callback) -> None:  # type: ignore[no-untyped-def]
        """Forwards the intent to the controller and clears the warning.

        The popup covers the OSAI screen: while it is there the operator cannot
        touch the machine to resolve the very condition being alarmed.
        """
        callback()
        self.dismiss()

    def dismiss(self) -> None:
        """Called by MainWindow when the condition clears - the only way out."""
        self._pulse.stop()
        self._locked = False
        self.hide()
        self._locked = True

    # Blocks Alt+F4 and Esc while the alarm is active.
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._locked:
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self) -> None:  # Esc
        if not self._locked:
            super().reject()
