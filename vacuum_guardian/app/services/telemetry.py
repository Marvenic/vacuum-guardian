"""Opt-in usage reporting: which Windows versions, which regions, how long
the app actually watches an OSAI screen.

Ground rules, because this ships to other people's machines:

- OFF until the operator says yes. `telemetry_enabled` starts False and the
  app asks once, in plain words, listing what is sent.
- Nothing personal unless typed in. The operator card (company, name, email,
  phone) is optional and separate from the anonymous counters; leave it empty
  and only the counters go out.
- No screen content, no program names, no file paths, no IP geolocation. The
  region comes from Windows' own country setting, so no third party is
  contacted to find out where the machine is.
- Never blocks the monitor. Sending happens in a daemon thread and any
  failure is logged and forgotten - a telemetry outage must not disturb a
  machine guarding a stone cutter.

Transport is a plain HTTPS POST of one JSON document to `telemetry_url`. An
empty URL disables the feature entirely, whatever the checkbox says.
"""

from __future__ import annotations

import ctypes
import json
import locale
import platform
import threading
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from ..models import AppConfig

SEND_INTERVAL = timedelta(hours=1)
_TIMEOUT_S = 10


def machine_country() -> str:
    """ISO country code from Windows' own region setting (e.g. 'NZ').

    GetUserDefaultGeoName is what the Region control panel shows, so it needs
    no network call and no IP database. Falls back to the locale, then to "".
    """
    try:
        buffer = ctypes.create_unicode_buffer(16)
        # 0 asks for the required size; the call fills the buffer otherwise.
        if ctypes.windll.kernel32.GetUserDefaultGeoName(buffer, 16):
            return buffer.value
    except (AttributeError, OSError):
        pass  # older Windows: fall through to the locale
    try:
        tag = locale.getdefaultlocale()[0] or ""
        return tag.split("_")[-1] if "_" in tag else ""
    except ValueError:
        return ""


def system_facts() -> dict[str, object]:
    """The environment half of the report - no personal data in here."""
    release, version, service_pack, _ = platform.win32_ver()
    return {
        "os": "Windows",
        "os_release": release,          # "10", "11"
        "os_build": version,            # "10.0.14393"
        "os_service_pack": service_pack,
        "country": machine_country(),
        "language": (locale.getdefaultlocale()[0] or ""),
        "machine": platform.machine(),  # AMD64
        "python": platform.python_version(),
    }


@dataclass
class UsageCounters:
    """What the app did since the last report. Reset after a successful send."""

    cycles: int = 0
    osai_cycles: int = 0     # cycles where the OSAI window was actually found
    alarms: int = 0
    overrides: int = 0
    acknowledges: int = 0
    session_started: datetime = field(default_factory=datetime.now)

    def as_dict(self, now: datetime) -> dict[str, object]:
        return {
            "cycles": self.cycles,
            # Minutes with the OSAI window on screen is the number that says
            # whether the app is really guarding a machine or just installed.
            "osai_minutes": round(self.osai_cycles / 60.0, 1),
            "uptime_minutes": round((now - self.session_started).total_seconds() / 60.0, 1),
            "alarms": self.alarms,
            "overrides": self.overrides,
            "acknowledges": self.acknowledges,
        }


class TelemetryService:
    """Collects counters and posts them, if and only if the operator agreed."""

    def __init__(self, config: AppConfig, project_root: Path) -> None:
        self._config = config
        self._state_path = project_root / "telemetry.json"
        self.counters = UsageCounters()
        self._last_sent: datetime | None = None

    # -- consent ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Both halves must be true: the operator agreed AND a URL exists."""
        return bool(self._config.telemetry_enabled and self._config.telemetry_url.strip())

    # -- counters ---------------------------------------------------------

    def note_cycle(self, osai_found: bool) -> None:
        self.counters.cycles += 1
        if osai_found:
            self.counters.osai_cycles += 1

    def note_alarm(self) -> None:
        self.counters.alarms += 1

    def note_override(self) -> None:
        self.counters.overrides += 1

    def note_acknowledge(self) -> None:
        self.counters.acknowledges += 1

    # -- payload ----------------------------------------------------------

    def payload(self, now: datetime | None = None) -> dict[str, object]:
        """The exact document that would be sent - shown in the consent dialog.

        Being able to render this is the point: the operator sees the real
        thing, not a description of it.
        """
        now = now or datetime.now()
        data: dict[str, object] = {
            "install_id": self._config.install_id,
            "app_version": _app_version(),
            "sent_at": now.isoformat(timespec="seconds"),
            "system": system_facts(),
            "usage": self.counters.as_dict(now),
        }
        operator = {
            key: value.strip()
            for key, value in (
                ("company", self._config.operator_company),
                ("name", self._config.operator_name),
                ("email", self._config.operator_email),
                ("phone", self._config.operator_phone),
            )
            if value.strip()
        }
        if operator:
            data["operator"] = operator
        return data

    # -- sending ----------------------------------------------------------

    def due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        if not self.enabled:
            return False
        return self._last_sent is None or now - self._last_sent >= SEND_INTERVAL

    def maybe_send(self, now: datetime | None = None) -> bool:
        """Send if enabled and due. Returns whether a send was started."""
        now = now or datetime.now()
        if not self.due(now):
            return False
        self._last_sent = now
        body = json.dumps(self.payload(now)).encode("utf-8")
        url = self._config.telemetry_url.strip()
        # Daemon thread: the monitor loop must not wait on the network, and a
        # pending report must never delay closing the app.
        threading.Thread(
            target=self._post, args=(url, body), name="telemetry", daemon=True
        ).start()
        self.counters = UsageCounters(session_started=self.counters.session_started)
        return True

    @staticmethod
    def _post(url: str, body: bytes) -> None:
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "VacuumGuardian"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                logger.debug("Usage report sent ({})", response.status)
        except Exception as exc:  # network is optional, never fatal
            logger.debug("Usage report not sent: {}", exc)


def new_install_id() -> str:
    """Random id so repeated reports from one PC can be grouped.

    Random on purpose: no hardware serial, no machine name, nothing that ties
    the number back to a person or a company.
    """
    return uuid.uuid4().hex


def _app_version() -> str:
    from .. import __version__

    return __version__
