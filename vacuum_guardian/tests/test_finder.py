"""Testes da leitura tolerante a rolagem (IndicatorFinder).

Cenario simulado: uma "tela" onde a linha do indicador aparece em alturas
diferentes (o menu do OSAI rola) e, as vezes, nem aparece.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.models import PumpState, ToggleGeometry
from app.vision.finder import IndicatorFinder, blue_fraction

# Layout sintetico de uma linha: [rotulo 60x14][espaco 10][toggle 40x14]
_LABEL_W, _LABEL_H = 60, 14
_TOGGLE_W, _TOGGLE_H = 40, 14
_GAP = 10
_TOGGLE = ToggleGeometry(dx=_LABEL_W + _GAP, dy=0, width=_TOGGLE_W, height=_TOGGLE_H)

_BLUE = (200, 90, 20)    # BGR: azul do tema OSAI
_WHITE = (245, 245, 245)


def _label_image() -> np.ndarray:
    """Rotulo com textura fixa - o que o matchTemplate vai procurar."""
    label = np.full((_LABEL_H, _LABEL_W, 3), 230, np.uint8)
    cv2.putText(label, "Vacuum 1", (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (40, 40, 40), 1)
    return label


def _toggle_image(on: bool) -> np.ndarray:
    """ON = pill quase todo azul; OFF = branco com um circulo azul pequeno."""
    if on:
        toggle = np.full((_TOGGLE_H, _TOGGLE_W, 3), _BLUE, np.uint8)
        cv2.circle(toggle, (_TOGGLE_W - 7, _TOGGLE_H // 2), 5, _WHITE, -1)
    else:
        toggle = np.full((_TOGGLE_H, _TOGGLE_W, 3), _WHITE, np.uint8)
        cv2.circle(toggle, (7, _TOGGLE_H // 2), 5, _BLUE, -1)
    return toggle


def _screen(row_y: int | None, on: bool = True, height: int = 300, width: int = 400) -> np.ndarray:
    """Tela com a linha em `row_y`; row_y=None simula o item rolado para fora."""
    screen = np.full((height, width, 3), 250, np.uint8)
    # Ruido determinstico para o matchTemplate ter contexto realista.
    cv2.rectangle(screen, (0, 0), (width - 1, 40), (210, 210, 210), -1)
    if row_y is None:
        return screen
    screen[row_y : row_y + _LABEL_H, 20 : 20 + _LABEL_W] = _label_image()
    x = 20 + _TOGGLE.dx
    screen[row_y : row_y + _TOGGLE_H, x : x + _TOGGLE_W] = _toggle_image(on)
    return screen


@pytest.fixture()
def calibrated(tmp_path: Path) -> Path:
    """Grava rotulo e amostras ON/OFF como a calibracao faria."""
    cv2.imwrite(str(tmp_path / "vacuum_1_label.png"), _label_image())
    cv2.imwrite(str(tmp_path / "vacuum_1_toggle_on.png"), _toggle_image(True))
    cv2.imwrite(str(tmp_path / "vacuum_1_toggle_off.png"), _toggle_image(False))
    return tmp_path


def _finder(directory: Path, threshold: float = 0.75) -> IndicatorFinder:
    return IndicatorFinder(
        label_path=directory / "vacuum_1_label.png",
        toggle=_TOGGLE,
        threshold=threshold,
        on_sample_path=directory / "vacuum_1_toggle_on.png",
        off_sample_path=directory / "vacuum_1_toggle_off.png",
    )


# -- classificacao por cor -------------------------------------------------

def test_blue_fraction_separates_on_from_off() -> None:
    assert blue_fraction(_toggle_image(True)) > blue_fraction(_toggle_image(False))


# -- leitura tolerante a rolagem ------------------------------------------

@pytest.mark.parametrize("row_y", [50, 120, 200, 260])
def test_reads_on_at_any_scroll_position(calibrated: Path, row_y: int) -> None:
    """O menu rolou: o estado tem de ser lido do mesmo jeito."""
    result = _finder(calibrated).read(_screen(row_y, on=True))
    assert result.state is PumpState.ON


@pytest.mark.parametrize("row_y", [50, 120, 200, 260])
def test_reads_off_at_any_scroll_position(calibrated: Path, row_y: int) -> None:
    result = _finder(calibrated).read(_screen(row_y, on=False))
    assert result.state is PumpState.OFF


def test_absent_label_is_not_visible_never_on(calibrated: Path) -> None:
    """Item fora da tela: NOT_VISIBLE - jamais 'ON' por omissao."""
    result = _finder(calibrated).read(_screen(None))
    assert result.state is PumpState.NOT_VISIBLE
    assert result.state is not PumpState.ON


def test_missing_label_template_is_not_visible(tmp_path: Path) -> None:
    """Sem calibracao nao se inventa leitura."""
    finder = IndicatorFinder(tmp_path / "ausente.png", _TOGGLE, 0.75)
    assert not finder.ready
    assert finder.read(_screen(100)).state is PumpState.NOT_VISIBLE


def test_toggle_outside_frame_is_not_visible(calibrated: Path) -> None:
    """Rotulo colado na borda direita: o pill cairia fora do frame."""
    screen = np.full((120, 90, 3), 250, np.uint8)
    screen[10 : 10 + _LABEL_H, 20 : 20 + _LABEL_W] = _label_image()
    assert _finder(calibrated).read(screen).state is PumpState.NOT_VISIBLE


def test_works_without_colour_samples(tmp_path: Path) -> None:
    """Sem amostras, cai nos limiares padrao - mas ainda distingue os estados."""
    cv2.imwrite(str(tmp_path / "vacuum_1_label.png"), _label_image())
    finder = IndicatorFinder(tmp_path / "vacuum_1_label.png", _TOGGLE, 0.75)
    assert finder.read(_screen(80, on=True)).state is PumpState.ON
    assert finder.read(_screen(80, on=False)).state is PumpState.OFF


# -- busca rapida (cache da ultima posicao) --------------------------------

def _count_matches(monkeypatch) -> list[tuple[int, int]]:
    """Registra o TAMANHO de cada imagem passada ao matchTemplate."""
    import app.vision.finder as finder_module

    sizes: list[tuple[int, int]] = []
    original = finder_module.cv2.matchTemplate

    def spy(image, template, method):  # type: ignore[no-untyped-def]
        sizes.append((image.shape[1], image.shape[0]))
        return original(image, template, method)

    monkeypatch.setattr(finder_module.cv2, "matchTemplate", spy)
    return sizes


def test_second_read_searches_only_around_the_last_position(calibrated: Path, monkeypatch) -> None:
    """O ganho de desempenho: varrer a tela toda uma vez, depois so a vizinhanca."""
    finder = _finder(calibrated)
    screen = _screen(120, on=True)
    finder.read(screen)  # primeira leitura: varredura completa

    sizes = _count_matches(monkeypatch)
    finder.read(screen)

    assert len(sizes) == 1
    searched_w, searched_h = sizes[0]
    assert searched_w < screen.shape[1] and searched_h < screen.shape[0]


def test_small_scroll_stays_on_the_fast_path(calibrated: Path) -> None:
    """Rolar poucas linhas nao pode custar uma varredura completa."""
    finder = _finder(calibrated)
    finder.read(_screen(120, on=True))
    assert finder.read(_screen(150, on=False)).state is PumpState.OFF


def test_large_scroll_falls_back_to_the_full_search(calibrated: Path) -> None:
    """Fora da janela rapida, ainda tem de encontrar - a rolagem e o motivo do modo."""
    finder = _finder(calibrated)
    finder.read(_screen(50, on=True))
    assert finder.read(_screen(260, on=True)).state is PumpState.ON


def test_cache_is_cleared_when_the_item_disappears(calibrated: Path) -> None:
    """Sumindo da tela, a proxima busca precisa varrer tudo de novo."""
    finder = _finder(calibrated)
    finder.read(_screen(120, on=True))
    assert finder.read(_screen(None)).state is PumpState.NOT_VISIBLE
    assert finder._last is None
    assert finder.read(_screen(240, on=False)).state is PumpState.OFF
