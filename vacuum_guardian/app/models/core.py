"""Core dataclasses and enums for Vacuum Guardian.

These types are the shared language between capture, vision, rules and UI.
None of them knows OpenCV, Qt or mss - plain data only, which keeps the
layers decoupled and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PumpState(Enum):
    """Detected state of one indicator (toggle) on the OSAI screen."""

    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"  # on screen, but the reading was inconclusive
    # The OSAI softkey menu scrolls, so the indicator may simply not be on
    # screen. That is different from "read it and could not tell", so it
    # gets its own state and the operator gets a specific message.
    NOT_VISIBLE = "NOT_VISIBLE"

    @property
    def is_verifiable(self) -> bool:
        """True only when the state was actually proven (ON or OFF)."""
        return self in (PumpState.ON, PumpState.OFF)


class AlertLevel(Enum):
    """Whether there is an alert.

    There used to be two levels (orange "could not verify" and red "it is
    off"). In practice the operator's next move was the same - go and check
    the vacuum - so two different screens only added noise. One is left.
    """

    NONE = 0
    WARNING = 1


class RunPhase(Enum):
    """Where the operator is in the start of a program, read from Iso lines.

    On stand-by the field shows irrelevant code. Once the file is loaded OSAI
    asks to CLOSE THE DOORS - the sign that cutting is about to start. When
    that text goes away and the content changes, the program is really running.
    """

    IDLE = "IDLE"        # stand-by
    DOORS = "DOORS"      # "CLOSE THE DOORS" on screen: time to check the vacuum
    RUNNING = "RUNNING"  # text changed after the warning: program running


@dataclass(frozen=True)
class Roi:
    """Region of interest in pixels, relative to the top-left of the OSAI WINDOW.

    Storing coordinates relative to the window (not the screen) means the window
    can be moved without invalidating the calibration.
    """

    x: int
    y: int
    width: int
    height: int

    def is_valid(self) -> bool:
        """A ROI needs a positive area to be usable."""
        return self.width > 0 and self.height > 0 and self.x >= 0 and self.y >= 0


@dataclass(frozen=True)
class ToggleGeometry:
    """Where the ON/OFF pill sits RELATIVE to the indicator label.

    The label is located by template matching anywhere on screen (the menu
    scrolls), so the toggle position can only be expressed as an offset from
    the label that was found - never as a fixed coordinate.
    """

    dx: int
    dy: int
    width: int
    height: int

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass
class IndicatorConfig:
    """A toggle on the OSAI screen that must be ON while a program runs.

    The current requirement lists two: "Vacuum Pump 1" and "Vacuum 1" (exact
    names as shown on the OSAI screen). Modelling them as a list allows adding
    more by editing config.json alone, with no code change.
    """

    name: str
    roi: Roi | None = None  # set during calibration (fixed-position mode)
    # Label-search mode (survives menu scrolling): when set, it takes
    # precedence over the fixed ROI.
    toggle: ToggleGeometry | None = None

    @property
    def slug(self) -> str:
        """Identifier used in template file names (e.g. 'vacuum_pump_1')."""
        return self.name.strip().lower().replace(" ", "_")


@dataclass(frozen=True)
class IndicatorReading:
    """One indicator reading from a detection cycle."""

    state: PumpState
    confidence: float  # template matching score (0.0 when UNKNOWN)


@dataclass(frozen=True)
class DetectionResult:
    """Result of a full detection cycle (indicators + program)."""

    indicators: dict[str, IndicatorReading]  # key = indicator name
    program_name: str
    timestamp: datetime
    elapsed_ms: float  # total processing time of the cycle
    run_phase: RunPhase = RunPhase.IDLE  # read from the Iso lines field


@dataclass(frozen=True)
class AlarmDecision:
    """Rule engine output for one DetectionResult."""

    is_monitored_program: bool
    offending: tuple[str, ...]  # indicators proven OFF
    unknown: tuple[str, ...]    # indicators that could not be read
    level: AlertLevel = AlertLevel.NONE
    reason: str = ""  # ready-made popup text, built by the rule engine

    @property
    def should_alarm(self) -> bool:
        """Any level other than NONE shows the popup."""
        return self.level is not AlertLevel.NONE


@dataclass
class AppConfig:
    """Configuration persisted in config.json.

    Mutable on purpose: the settings screen edits this instance and asks
    ConfigService to save it.
    """

    window_title_hint: str = "OSAI"  # substring of the window title to capture
    capture_interval_s: float = 1.0  # delay between detection cycles
    trigger_programs: list[str] = field(default_factory=lambda: ["SINK", "CUTOUT", "BOWL"])
    template_threshold: float = 0.80  # minimum template matching score
    indicators: list[IndicatorConfig] = field(
        default_factory=lambda: [IndicatorConfig("Vacuum Pump 1"), IndicatorConfig("Vacuum 1")]
    )
    program_roi: Roi | None = None
    alarm_wav: str = ""  # empty = assets/alarm.wav
    # Sound is optional: shops are noisy and the CNC PC may have no
    # speakers. With sound off the visual alert (a pulsing popup) is the
    # only channel - which is why it has to stand on its own.
    alarm_sound_enabled: bool = True
    # After the operator clicks, the alert stays quiet for this long.
    # 20 min covers a simple program; a sink cutout takes 20-35 min. Without
    # it the warning came back seconds later and the operator could not
    # get any work done.
    alarm_snooze_minutes: float = 20.0

    # -- the critical moment ---------------------------------------------
    # The risk window is read from the OSAI "Iso lines" field (see RunPhase):
    # more reliable than the program name, because every program is called
    # <number>.CNC.
    # The indicator that MUST be ON at the critical moment. "Vacuum 1" is
    # the important one: without it the stone is not held down.
    critical_indicator: str = "Vacuum 1"
    # The "Iso lines" field (bottom left of the OSAI screen): where the
    # CLOSE THE DOORS request appears before cutting. None = feature off.
    iso_roi: Roi | None = None
    close_doors_keyword: str = "CLOSE THE DOOR"  # no final S: matches both forms
    label_threshold: float = 0.75  # minimum score to call the label found
    # Language of the calibration guide ("en"/"pt"). It is the only bilingual
    # text in the app: the operator switches it and the choice is stored.
    guide_language: str = "en"

    # -- usage report (opt-in) --------------------------------------------
    # Off by default. The app asks ONCE, showing what would be sent;
    # `telemetry_prompted` keeps it from asking again on every start.
    # With no URL nothing is sent, even if consent was given.
    telemetry_enabled: bool = False
    telemetry_prompted: bool = False
    telemetry_url: str = ""
    install_id: str = ""  # random uuid, created on first run
    # OPTIONAL operator card. Empty = only the anonymous counters are sent.
    operator_company: str = ""
    operator_name: str = ""
    operator_email: str = ""
    operator_phone: str = ""
