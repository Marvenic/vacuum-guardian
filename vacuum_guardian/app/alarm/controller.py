"""AlarmController: the alarm state machine, decoupled from the UI.

Semantics:
- Alarm fires    -> looping sound plus the warning on screen.
- Single button  -> records the action, stops the sound, clears the warning
                                       and SNOOZES for 5 minutes (see SNOOZE_MINUTES). The
                                       warning covers the OSAI screen: leaving it there kept
                                       the operator from fixing the very condition.
- Condition ends -> everything resets; a new alarm plays sound again.

Why the snooze: without it the warning came back on the next cycle (a second
later) while the operator was still walking to the machine. Five minutes is
enough to act. Monitoring does NOT stop meanwhile - the panel and tray icon
keep showing the real state; only the warning and the sound are held back.

The UI only reads `popup_should_show` and calls acknowledge() - no rule lives
in the graphical layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from ..models import AlarmDecision, AlertLevel
from .sound import SoundPlayer

# ponytail: a constant, not a setting. It becomes a config.json field when
# someone on the shop floor asks for a different delay.
SNOOZE_MINUTES = 5.0


@dataclass(frozen=True)
class AlarmStatus:
    """Snapshot of the alarm state for the UI to render."""

    active: bool
    acknowledged: bool
    reason: str  # ready-made popup text
    sound_enabled: bool = True
    dismissed: bool = False   # the operator clicked: the warning is gone
    snoozed: bool = False     # inside the silence window
    level: AlertLevel = AlertLevel.NONE

    @property
    def popup_should_show(self) -> bool:
        return self.active and not self.dismissed


class AlarmController:
    def __init__(
        self,
        player: SoundPlayer,
        wav_path: Path,
        sound_enabled: bool = True,
        action_log=None,  # AlarmActionLog | None (evita import circular)
        snooze_minutes: float = SNOOZE_MINUTES,
    ) -> None:
        self._player = player
        self._wav_path = wav_path
        # Sound is optional (noisy shop / PC with no speakers). With it off the
        # visual warning is unchanged.
        self._sound_enabled = sound_enabled
        self._action_log = action_log
        self._snooze = timedelta(minutes=snooze_minutes)
        self._active = False
        self._acknowledged = False
        self._reason = ""
        self._dismissed = False
        self._snoozed_until: datetime | None = None

    @property
    def snoozed_until(self) -> datetime | None:
        return self._snoozed_until

    def _is_snoozed(self, now: datetime) -> bool:
        if self._snoozed_until is None:
            return False
        if now >= self._snoozed_until:
            logger.info("Snooze over - watching the screen again")
            self._snoozed_until = None
            return False
        return True

    def update(self, decision: AlarmDecision, now: datetime | None = None) -> AlarmStatus:
        """Processes one cycle's rule-engine decision.

        `now` is injectable so tests need not wait five real minutes.
        """
        now = now or datetime.now()

        if not decision.should_alarm:
            # Condition resolved: clear everything, INCLUDING the snooze. Without
            # this, an operator who switches the vacuum on right after clicking
            # would go five minutes unwatched - the next alarm would come late.
            if self._active or self._snoozed_until is not None:
                logger.info("Alarm condition cleared - alarm ended")
                self._player.stop()
                self._active = False
                self._acknowledged = False
                self._dismissed = False
                self._reason = ""
                self._snoozed_until = None
            return self.status(False)

        if self._is_snoozed(now):
            return self.status(True)

        self._reason = decision.reason
        if not self._active:
            logger.warning("ALARM TRIGGERED ({})", self._reason)
            self._active = True
            self._acknowledged = False
            self._dismissed = False
        if self._sound_enabled:
            self._player.start_loop(self._wav_path)
        return self.status(False)

    def acknowledge(self, now: datetime | None = None) -> None:
        """Single button: records the acknowledgement, mutes and snoozes 5 min.

        Recording is the trade-off for letting the warning disappear: with no
        popup on screen, this line is the only proof that somebody saw it.
        """
        if not self._active:
            return
        now = now or datetime.now()
        self._snoozed_until = now + self._snooze
        self._acknowledged = True
        self._dismissed = True
        self._active = False  # the next cycle re-evaluates after the snooze
        self._player.stop()
        logger.info(
            "Alarm acknowledged by the operator ({}) - silenced until {:%H:%M:%S}",
            self._reason, self._snoozed_until,
        )
        if self._action_log is not None:
            self._action_log.record(now, "ACKNOWLEDGE", self._reason, self._snoozed_until)

    # Old name kept: MainWindow and the popup may still call silence().
    silence = acknowledge

    def status(self, snoozed: bool | None = None) -> AlarmStatus:
        if snoozed is None:
            snoozed = self._snoozed_until is not None
        return AlarmStatus(
            active=self._active,
            acknowledged=self._acknowledged,
            reason=self._reason,
            sound_enabled=self._sound_enabled,
            dismissed=self._dismissed,
            snoozed=snoozed,
            level=AlertLevel.WARNING if self._active else AlertLevel.NONE,
        )
