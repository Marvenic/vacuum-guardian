"""The popup itself must not corrupt the screen reading.

Real CNC failure: the warning appeared, the operator clicked, and the app
showed it again straight after. The popup covers the OSAI screen, so the OCR
of the "Iso lines" field read the warning's own pixels. The text stopped
"CLOSE THE DOORS", o watcher concluia "o programa comecou" (DOORS -> RUNNING)
and, with the vacuum not ON, the rule escalated.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.models import AppConfig, Roi, RunPhase
from app.services.monitor import MonitorEngine


class _Locator:
    def find(self):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture()
def engine(tmp_path: Path, monkeypatch):  # type: ignore[no-untyped-def]
    """A real engine, but with capture and OCR driven by the test."""
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    config = AppConfig(iso_roi=Roi(100, 900, 300, 60))
    engine = MonitorEngine(config, tmp_path)

    frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(engine._capture, "grab", lambda: (frame, None))

    texts = {"iso": "CLOSE THE DOORS"}
    monkeypatch.setattr(
        engine._detection, "_reader", type("R", (), {"read_text": lambda self, roi: texts["iso"]})()
    )
    yield engine, texts
    engine.close()


def test_phase_follows_the_iso_field_when_nothing_covers_it(engine) -> None:  # type: ignore[no-untyped-def]
    eng, texts = engine
    assert eng.run_cycle().result.run_phase is RunPhase.DOORS

    texts["iso"] = "G1 X1575 Y90"  # o programa comecou de verdade
    assert eng.run_cycle().result.run_phase is RunPhase.RUNNING


def test_popup_over_the_iso_field_freezes_the_phase(engine) -> None:  # type: ignore[no-untyped-def]
    """The core of the bug: an alert plus a click must not escalate on its own."""
    eng, texts = engine
    assert eng.run_cycle().result.run_phase is RunPhase.DOORS

    # The alarm popup centred, covering the Iso lines ROI.
    eng.set_occlusion((0, 800, 1920, 280))
    texts["iso"] = "VACUUM IS OFF!"  # o que o OCR leria do proprio aviso

    for _ in range(5):
        assert eng.run_cycle().result.run_phase is RunPhase.DOORS


def test_phase_resumes_after_the_popup_leaves_the_screen(engine) -> None:  # type: ignore[no-untyped-def]
    eng, texts = engine
    eng.run_cycle()
    eng.set_occlusion((0, 800, 1920, 280))
    texts["iso"] = "VACUUM IS OFF!"
    eng.run_cycle()

    eng.set_occlusion(None)          # operador dispensou o aviso
    texts["iso"] = "G1 X1575 Y90"    # e o programa comecou mesmo
    assert eng.run_cycle().result.run_phase is RunPhase.RUNNING


def test_popup_elsewhere_on_the_screen_does_not_freeze(engine) -> None:  # type: ignore[no-untyped-def]
    """It only freezes if it covers the ROI - a window in a corner must not blind it."""
    eng, texts = engine
    eng.run_cycle()
    eng.set_occlusion((0, 0, 200, 100))  # canto superior esquerdo, longe da ROI

    texts["iso"] = "G1 X1575 Y90"
    assert eng.run_cycle().result.run_phase is RunPhase.RUNNING


def test_no_occlusion_reported_means_normal_reading(engine) -> None:  # type: ignore[no-untyped-def]
    eng, texts = engine
    eng.set_occlusion(None)
    assert eng.run_cycle().result.run_phase is RunPhase.DOORS
