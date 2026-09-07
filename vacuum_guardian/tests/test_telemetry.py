"""Usage reporting: opt-in, minimal, and never in the way.

The rules worth a test are the ones that protect the user: nothing leaves the
machine without consent and without a destination, personal fields are only
sent when typed in, and a failing endpoint cannot disturb the monitor.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.models import AppConfig
from app.services.telemetry import (
    SEND_INTERVAL,
    TelemetryService,
    machine_country,
    new_install_id,
    system_facts,
)


def _service(tmp_path: Path, **kwargs) -> TelemetryService:  # type: ignore[no-untyped-def]
    config = AppConfig(**kwargs)
    return TelemetryService(config, tmp_path)


# -- consent ---------------------------------------------------------------

def test_disabled_by_default(tmp_path: Path) -> None:
    """The default has to be 'sends nothing'."""
    assert not AppConfig().telemetry_enabled
    assert not _service(tmp_path).enabled


def test_consent_without_a_url_still_sends_nothing(tmp_path: Path) -> None:
    """Ticking the box is not enough: with no destination nothing is sent."""
    assert not _service(tmp_path, telemetry_enabled=True).enabled


def test_url_without_consent_sends_nothing(tmp_path: Path) -> None:
    """And having a destination authorises nothing."""
    service = _service(tmp_path, telemetry_url="https://example.invalid/u")
    assert not service.enabled
    assert not service.maybe_send()


def test_enabled_needs_both(tmp_path: Path) -> None:
    service = _service(
        tmp_path, telemetry_enabled=True, telemetry_url="https://example.invalid/u"
    )
    assert service.enabled


# -- report contents -------------------------------------------------------

def test_payload_has_no_personal_data_by_default(tmp_path: Path) -> None:
    payload = _service(tmp_path).payload()
    assert "operator" not in payload
    assert set(payload) == {"install_id", "app_version", "sent_at", "system", "usage"}


def test_operator_card_is_sent_only_when_filled(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        operator_company="Stone Co",
        operator_name="Marcos",
        operator_email="marcos@example.com",
    )
    operator = service.payload()["operator"]
    assert operator == {
        "company": "Stone Co",
        "name": "Marcos",
        "email": "marcos@example.com",
    }  # the empty phone field is not sent


def test_blank_operator_fields_are_dropped(tmp_path: Path) -> None:
    """Whitespace must not count as a filled-in field."""
    service = _service(tmp_path, operator_name="   ")
    assert "operator" not in service.payload()


def test_system_facts_answer_the_questions_that_motivated_this(tmp_path: Path) -> None:
    facts = system_facts()
    assert facts["os"] == "Windows"
    assert facts["os_release"]  # "10" / "11"
    assert "country" in facts   # the region comes from Windows itself
    # And nothing that identifies the machine or the person:
    assert "hostname" not in facts
    assert "user" not in facts


def test_install_id_is_random_not_derived_from_the_machine() -> None:
    assert new_install_id() != new_install_id()
    assert len(new_install_id()) == 32


def test_country_comes_from_windows_without_network() -> None:
    country = machine_country()
    assert isinstance(country, str)
    assert len(country) <= 6  # a short code or empty, never an address


# -- counters --------------------------------------------------------------

def test_osai_minutes_measure_real_use(tmp_path: Path) -> None:
    """The question is 'is the app guarding a machine?', not 'was it installed?'."""
    service = _service(tmp_path)
    for _ in range(120):
        service.note_cycle(osai_found=True)
    for _ in range(60):
        service.note_cycle(osai_found=False)

    usage = service.payload()["usage"]
    assert usage["cycles"] == 180
    assert usage["osai_minutes"] == 2.0


def test_alarms_and_overrides_are_counted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.note_alarm()
    service.note_alarm()
    service.note_override()
    service.note_acknowledge()

    usage = service.payload()["usage"]
    assert (usage["alarms"], usage["overrides"], usage["acknowledges"]) == (2, 1, 1)


# -- send cadence ----------------------------------------------------------

def test_not_due_again_right_after_sending(tmp_path: Path) -> None:
    service = _service(
        tmp_path, telemetry_enabled=True, telemetry_url="https://127.0.0.1:9/none"
    )
    start = datetime(2026, 9, 2, 10, 0, 0)
    assert service.maybe_send(start)
    assert not service.due(start + timedelta(minutes=30))
    assert service.due(start + SEND_INTERVAL)


def test_counters_reset_after_a_send(tmp_path: Path) -> None:
    """Otherwise the same minute of use would be counted in every report."""
    service = _service(
        tmp_path, telemetry_enabled=True, telemetry_url="https://127.0.0.1:9/none"
    )
    service.note_cycle(True)
    service.note_alarm()
    service.maybe_send(datetime(2026, 9, 2, 10, 0, 0))

    usage = service.payload()["usage"]
    assert usage["cycles"] == 0
    assert usage["alarms"] == 0


def test_a_dead_endpoint_never_raises(tmp_path: Path) -> None:
    """A server outage must not disturb a machine cutting stone."""
    service = _service(
        tmp_path, telemetry_enabled=True, telemetry_url="https://127.0.0.1:9/none"
    )
    assert service.maybe_send()  # daemon thread: no exception here
    service.note_cycle(True)     # and the monitor carries on
