"""Testes da camada de visao com imagens sinteticas (sem depender do OSAI)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.detection import DetectionService
from app.detection.service import build_matchers
from app.models import IndicatorConfig, PumpState, Roi
from app.vision import TemplateMatcher


def _make_indicator(color: tuple[int, int, int]) -> np.ndarray:
    """Gera um 'indicador' sintetico 40x40: circulo colorido sobre fundo cinza."""
    img = np.full((40, 40, 3), 60, dtype=np.uint8)
    cv2.circle(img, (20, 20), 12, color, -1)
    return img


@pytest.fixture()
def templates_dir(tmp_path: Path) -> Path:
    """Templates sinteticos para dois indicadores (vacuum_pump e vacuum1)."""
    for slug in ("vacuum_pump", "vacuum1"):
        cv2.imwrite(str(tmp_path / f"{slug}_on.png"), _make_indicator((0, 255, 0)))
        cv2.imwrite(str(tmp_path / f"{slug}_off.png"), _make_indicator((0, 0, 255)))
    return tmp_path


def _matcher(templates_dir: Path, slug: str = "vacuum_pump") -> TemplateMatcher:
    return TemplateMatcher(
        on_path=templates_dir / f"{slug}_on.png",
        off_path=templates_dir / f"{slug}_off.png",
        threshold=0.8,
    )


class FakeReader:
    """TextReader de teste - devolve um texto fixo."""

    def __init__(self, text: str = "SINK_CUTOUT_01") -> None:
        self.text = text

    def read_text(self, roi_bgr: np.ndarray) -> str:
        return self.text


def test_matcher_detects_on_state(templates_dir: Path) -> None:
    matcher = _matcher(templates_dir)
    assert matcher.ready
    result = matcher.match(_make_indicator((0, 255, 0)))
    assert result.state is PumpState.ON
    assert result.confidence >= 0.8


def test_matcher_detects_off_state(templates_dir: Path) -> None:
    result = _matcher(templates_dir).match(_make_indicator((0, 0, 255)))
    assert result.state is PumpState.OFF


def test_matcher_unknown_when_nothing_matches(templates_dir: Path) -> None:
    noise = np.random.default_rng(42).integers(0, 255, (40, 40, 3), dtype=np.uint8)
    result = _matcher(templates_dir).match(noise)
    assert result.state is PumpState.UNKNOWN


def test_matcher_unknown_without_templates(tmp_path: Path) -> None:
    matcher = TemplateMatcher(tmp_path / "x_on.png", tmp_path / "x_off.png", threshold=0.8)
    assert not matcher.ready
    result = matcher.match(_make_indicator((0, 255, 0)))
    assert result.state is PumpState.UNKNOWN


def _service(templates_dir: Path, indicators: list[IndicatorConfig], program_roi: Roi | None) -> DetectionService:
    return DetectionService(
        matchers=build_matchers(templates_dir, 0.8, indicators),
        reader=FakeReader(),
        indicators=indicators,
        program_roi=program_roi,
    )


def test_detection_service_reads_two_indicators(templates_dir: Path) -> None:
    # Frame com Vacuum Pump ON (verde) e Vacuum1 OFF (vermelho).
    frame = np.full((200, 200, 3), 60, dtype=np.uint8)
    frame[10:50, 10:50] = _make_indicator((0, 255, 0))
    frame[60:100, 10:50] = _make_indicator((0, 0, 255))

    indicators = [
        IndicatorConfig("Vacuum Pump", Roi(10, 10, 40, 40)),
        IndicatorConfig("Vacuum1", Roi(10, 60, 40, 40)),
    ]
    result = _service(templates_dir, indicators, Roi(0, 150, 200, 30)).detect(frame)

    assert result.indicators["Vacuum Pump"].state is PumpState.ON
    assert result.indicators["Vacuum1"].state is PumpState.OFF
    assert result.program_name == "SINK_CUTOUT_01"
    assert result.elapsed_ms > 0


def test_detection_service_handles_missing_rois(templates_dir: Path) -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    indicators = [IndicatorConfig("Vacuum Pump"), IndicatorConfig("Vacuum1")]
    result = _service(templates_dir, indicators, None).detect(frame)
    assert all(r.state is PumpState.UNKNOWN for r in result.indicators.values())
    assert result.program_name == ""


def test_detection_service_roi_out_of_bounds(templates_dir: Path) -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    indicators = [IndicatorConfig("Vacuum Pump", Roi(90, 90, 40, 40))]
    result = _service(templates_dir, indicators, None).detect(frame)
    assert result.indicators["Vacuum Pump"].state is PumpState.UNKNOWN


def test_windows_ocr_reads_rendered_text() -> None:
    """Teste de integracao com a engine real do Windows; pula se indisponivel."""
    try:
        from app.vision import WindowsOcrReader

        reader = WindowsOcrReader()
    except Exception as exc:  # sem pacote de idioma / fora do Windows
        pytest.skip(f"Windows OCR indisponivel: {exc}")

    img = np.full((60, 400, 3), 255, dtype=np.uint8)
    cv2.putText(img, "SINK CUTOUT 01", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    text = reader.read_text(img)
    assert "SINK" in text.upper()
