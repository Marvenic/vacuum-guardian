"""Teste de ponta a ponta do assistente de calibracao.

Vale mais que testar cada botao isolado: percorre os quatro passos na ordem em
que o operador os ve e, no fim, monta o IndicatorFinder com os arquivos
gerados. Se o assistente produzir algo que o detector nao consegue usar, o
teste falha - que e exatamente o modo de falha que apareceu na fabrica.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide2")

from PySide2.QtCore import QRect  # noqa: E402
from PySide2.QtWidgets import QMessageBox  # noqa: E402

from app.models import AppConfig, IndicatorConfig, PumpState  # noqa: E402
from app.ui.calibration_guide import (  # noqa: E402
    REQ_LABEL,
    REQ_OFF,
    REQ_ON,
    REQ_TOGGLE,
)
from app.ui.roi_selector import RoiSelectorDialog  # noqa: E402
from app.detection.service import build_finders  # noqa: E402
from app.vision.finder import IndicatorFinder  # noqa: E402

# Linha sintetica: [rotulo 60x14][espaco 10][toggle 40x14] em (20, row_y).
_LABEL_W, _LABEL_H = 60, 14
_TOGGLE_W, _TOGGLE_H = 40, 14
_ROW_X, _GAP = 20, 10
_BLUE = (200, 90, 20)
_WHITE = (245, 245, 245)


def _label_image() -> np.ndarray:
    label = np.full((_LABEL_H, _LABEL_W, 3), 230, np.uint8)
    cv2.putText(label, "Vacuum 1", (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (40, 40, 40), 1)
    return label


def _toggle_image(on: bool) -> np.ndarray:
    if on:
        toggle = np.full((_TOGGLE_H, _TOGGLE_W, 3), _BLUE, np.uint8)
        cv2.circle(toggle, (_TOGGLE_W - 7, _TOGGLE_H // 2), 5, _WHITE, -1)
    else:
        toggle = np.full((_TOGGLE_H, _TOGGLE_W, 3), _WHITE, np.uint8)
        cv2.circle(toggle, (7, _TOGGLE_H // 2), 5, _BLUE, -1)
    return toggle


def _screen(row_y: int, on: bool) -> np.ndarray:
    """Frame pequeno de proposito: mantem a escala em 1.0 e simplifica as coords."""
    screen = np.full((300, 400, 3), 250, np.uint8)
    cv2.rectangle(screen, (0, 0), (399, 40), (210, 210, 210), -1)
    screen[row_y : row_y + _LABEL_H, _ROW_X : _ROW_X + _LABEL_W] = _label_image()
    x = _ROW_X + _LABEL_W + _GAP
    screen[row_y : row_y + _TOGGLE_H, x : x + _TOGGLE_W] = _toggle_image(on)
    return screen


@pytest.fixture(autouse=True)
def _no_modal_boxes(monkeypatch):  # type: ignore[no-untyped-def]
    """Caixas modais travam (ou derrubam) a suite headless.

    Elas sao o comportamento certo do produto - o operador precisa ver o
    aviso -, entao apenas as silenciamos no teste em vez de remove-las.
    """
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))


@pytest.fixture()
def setup(qt_app, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Dialogo com um 'monitor' controlavel: o teste decide o que a foto mostra."""
    config = AppConfig(
        indicators=[IndicatorConfig("Vacuum Pump 1"), IndicatorConfig("Vacuum 1")],
        critical_indicator="Vacuum 1",
    )
    screen = {"frame": _screen(80, on=True)}
    dialog = RoiSelectorDialog(
        screen["frame"], config, tmp_path, None, lambda: screen["frame"]
    )
    return dialog, config, tmp_path, screen


def _drag(dialog: RoiSelectorDialog, x: int, y: int, w: int, h: int) -> None:
    """Simula o arrasto do operador sobre a imagem (escala 1.0 neste frame)."""
    dialog._label.selection = QRect(x, y, w, h)


def test_wizard_starts_on_the_first_step(setup) -> None:  # type: ignore[no-untyped-def]
    dialog, _, _, _ = setup
    # Comeca pelo PRIMEIRO indicador da lista, nao pelo critico.
    assert dialog._guide.current_step().anchor == "label@vacuum_pump_1"


def test_full_calibration_produces_a_working_detector(setup) -> None:  # type: ignore[no-untyped-def]
    """O que importa: no fim, o detector le ON e OFF corretamente."""
    dialog, config, templates, screen = setup
    row_y = 80

    _drag(dialog, _ROW_X, row_y, _LABEL_W, _LABEL_H)
    assert dialog._run_step(REQ_LABEL)
    assert (templates / "vacuum_1_label.png").exists()

    _drag(dialog, _ROW_X + _LABEL_W + _GAP, row_y, _TOGGLE_W, _TOGGLE_H)
    assert dialog._run_step(REQ_TOGGLE)
    assert config.indicators[1].toggle is not None

    screen["frame"] = _screen(row_y, on=True)
    assert dialog._run_step(REQ_ON)
    screen["frame"] = _screen(row_y, on=False)
    assert dialog._run_step(REQ_OFF)

    finder = IndicatorFinder(
        templates / "vacuum_1_label.png",
        config.indicators[1].toggle,
        config.label_threshold,
        templates / "vacuum_1_toggle_on.png",
        templates / "vacuum_1_toggle_off.png",
    )
    assert finder.ready
    # E funciona com o menu rolado para outra altura - o objetivo do modo.
    assert finder.read(_screen(200, on=True)).state is PumpState.ON
    assert finder.read(_screen(200, on=False)).state is PumpState.OFF


def test_toggle_geometry_is_relative_to_the_label(setup) -> None:  # type: ignore[no-untyped-def]
    """Deslocamento, nao coordenada fixa - senao a rolagem quebraria tudo."""
    dialog, config, _, _ = setup
    row_y = 80
    _drag(dialog, _ROW_X, row_y, _LABEL_W, _LABEL_H)
    dialog._run_step(REQ_LABEL)
    _drag(dialog, _ROW_X + _LABEL_W + _GAP, row_y, _TOGGLE_W, _TOGGLE_H)
    dialog._run_step(REQ_TOGGLE)

    toggle = config.indicators[1].toggle
    assert toggle is not None
    assert toggle.dx == _LABEL_W + _GAP
    assert toggle.dy == 0


def test_capture_without_a_drag_fails_and_does_not_advance(setup) -> None:  # type: ignore[no-untyped-def]
    """Sem retangulo nao ha captura - e o assistente nao pode fingir progresso."""
    dialog, _, _, _ = setup
    dialog._label.clear_selection()
    step_before = dialog._guide.current_step().anchor
    assert not dialog._run_step(REQ_LABEL)
    assert dialog._guide.current_step().anchor == step_before


def test_sample_before_toggle_area_is_refused(setup) -> None:  # type: ignore[no-untyped-def]
    """Fora de ordem nao pode gerar amostra de uma area que ninguem definiu."""
    dialog, _, templates, _ = setup
    _drag(dialog, _ROW_X, 80, _LABEL_W, _LABEL_H)
    dialog._run_step(REQ_LABEL)
    assert not dialog._run_step(REQ_ON)
    assert not (templates / "vacuum_1_toggle_on.png").exists()


def test_successful_capture_advances_the_wizard(setup) -> None:  # type: ignore[no-untyped-def]
    """A acao roda pelo assistente: sucesso avanca sozinho para o proximo passo."""
    dialog, _, _, _ = setup
    _drag(dialog, _ROW_X, 80, _LABEL_W, _LABEL_H)
    # Comeca pelo PRIMEIRO indicador da lista, nao pelo critico.
    assert dialog._guide.current_step().anchor == "label@vacuum_pump_1"
    dialog._guide._run_action()
    assert dialog._guide.current_step().anchor == "toggle@vacuum_pump_1"


def test_calibration_marks_the_dialog_as_changed(setup) -> None:  # type: ignore[no-untyped-def]
    """MainWindow so salva e reinicia o monitor se `changed` for True."""
    dialog, _, _, _ = setup
    assert not dialog.changed
    _drag(dialog, _ROW_X, 80, _LABEL_W, _LABEL_H)
    dialog._run_step(REQ_LABEL)
    assert dialog.changed


# -- dois indicadores ------------------------------------------------------
#
# Regressao do chao de fabrica: o assistente mandava capturar o Vacuum Pump 1,
# mas gravava tudo no indicador critico (Vacuum 1). O Vacuum Pump 1 ficava sem
# rotulo e sem amostras, e o painel dizia que nao conseguia ler o estado dele.


def _two_row_screen(pump_on: bool, vacuum_on: bool) -> np.ndarray:
    """Tela com DUAS linhas: 'Vacuum Pump 1' em cima, 'Vacuum 1' embaixo."""
    screen = np.full((300, 400, 3), 250, np.uint8)
    cv2.rectangle(screen, (0, 0), (399, 40), (210, 210, 210), -1)
    for row_y, text, is_on in ((80, "Pump 1", pump_on), (140, "Vacuum 1", vacuum_on)):
        label = np.full((_LABEL_H, _LABEL_W, 3), 230, np.uint8)
        cv2.putText(label, text, (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (40, 40, 40), 1)
        screen[row_y : row_y + _LABEL_H, _ROW_X : _ROW_X + _LABEL_W] = label
        x = _ROW_X + _LABEL_W + _GAP
        screen[row_y : row_y + _TOGGLE_H, x : x + _TOGGLE_W] = _toggle_image(is_on)
    return screen


@pytest.fixture()
def two_indicators(qt_app, tmp_path: Path):  # type: ignore[no-untyped-def]
    config = AppConfig(
        indicators=[IndicatorConfig("Vacuum Pump 1"), IndicatorConfig("Vacuum 1")],
        critical_indicator="Vacuum 1",
    )
    screen = {"frame": _two_row_screen(pump_on=True, vacuum_on=True)}
    dialog = RoiSelectorDialog(
        screen["frame"], config, tmp_path, None, lambda: screen["frame"]
    )
    return dialog, config, tmp_path, screen


def _calibrate(dialog, screen, indicator: str, row_y: int, on_frame, off_frame) -> None:
    """Roda os quatro passos de um indicador, como o assistente faz."""
    _drag(dialog, _ROW_X, row_y, _LABEL_W, _LABEL_H)
    assert dialog._run_step(REQ_LABEL, indicator)
    _drag(dialog, _ROW_X + _LABEL_W + _GAP, row_y, _TOGGLE_W, _TOGGLE_H)
    assert dialog._run_step(REQ_TOGGLE, indicator)
    screen["frame"] = on_frame
    assert dialog._run_step(REQ_ON, indicator)
    screen["frame"] = off_frame
    assert dialog._run_step(REQ_OFF, indicator)


def test_each_indicator_gets_its_own_files(two_indicators) -> None:  # type: ignore[no-untyped-def]
    """O bug: capturar o Vacuum Pump 1 gravava nos arquivos do Vacuum 1."""
    dialog, config, templates, screen = two_indicators

    _calibrate(
        dialog, screen, "Vacuum Pump 1", 80,
        _two_row_screen(pump_on=True, vacuum_on=True),
        _two_row_screen(pump_on=False, vacuum_on=True),
    )

    assert (templates / "vacuum_pump_1_label.png").exists()
    assert (templates / "vacuum_pump_1_toggle_on.png").exists()
    assert (templates / "vacuum_pump_1_toggle_off.png").exists()
    assert config.indicators[0].toggle is not None
    # E nada pode ter vazado para o indicador critico.
    assert not (templates / "vacuum_1_label.png").exists()
    assert config.indicators[1].toggle is None


def test_both_indicators_end_up_readable(two_indicators) -> None:  # type: ignore[no-untyped-def]
    """O que o operador vai conferir no painel: os DOIS passam a ser lidos."""
    dialog, config, templates, screen = two_indicators

    _calibrate(
        dialog, screen, "Vacuum Pump 1", 80,
        _two_row_screen(pump_on=True, vacuum_on=True),
        _two_row_screen(pump_on=False, vacuum_on=True),
    )
    _calibrate(
        dialog, screen, "Vacuum 1", 140,
        _two_row_screen(pump_on=True, vacuum_on=True),
        _two_row_screen(pump_on=True, vacuum_on=False),
    )

    finders = build_finders(templates, config)
    assert set(finders) == {"Vacuum Pump 1", "Vacuum 1"}

    frame = _two_row_screen(pump_on=True, vacuum_on=False)
    assert finders["Vacuum Pump 1"].read(frame).state is PumpState.ON
    assert finders["Vacuum 1"].read(frame).state is PumpState.OFF

    frame = _two_row_screen(pump_on=False, vacuum_on=True)
    assert finders["Vacuum Pump 1"].read(frame).state is PumpState.OFF
    assert finders["Vacuum 1"].read(frame).state is PumpState.ON


def test_wizard_walks_both_indicators_in_order(two_indicators) -> None:  # type: ignore[no-untyped-def]
    """O roteiro comeca pelo Vacuum Pump 1 e so depois vai ao Vacuum 1."""
    dialog, _, _, _ = two_indicators
    anchors = [s.anchor for s in dialog._guide._steps if s.indicator]
    assert anchors.index("label@vacuum_pump_1") < anchors.index("label@vacuum_1")
    # E o passo atual manda no combo do topo, sem o operador ter de trocar.
    assert dialog._guide.current_step().indicator == "Vacuum Pump 1"
    assert dialog._target.currentText() == "Vacuum Pump 1"


# -- estado modal (o "congelou e nao deixa nem fechar") --------------------

def test_refresh_screenshot_does_not_end_the_modal_loop(setup) -> None:  # type: ignore[no-untyped-def]
    """Capturar uma foto nova nao pode encerrar o exec_() da calibracao.

    Bug real na CNC: `_refresh_frame` usava hide(), e hide() num dialogo dentro
    de exec_() encerra o loop modal na hora. O exec_() retornava no meio da
    captura, o clique em Done nunca era processado, e sobrava um dialogo ainda
    modal - com o Qt mantendo a janela principal DESABILITADA no Windows: nao
    aceitava clique, nao movia, nao fechava.
    """
    from PySide2.QtCore import QTimer
    from PySide2.QtWidgets import QApplication

    dialog, _, _, _ = setup
    order: list[str] = []

    def refresh() -> None:
        order.append("refresh")
        dialog._refresh_frame()

    def done() -> None:
        order.append("done")
        dialog.accept()

    QTimer.singleShot(50, refresh)
    QTimer.singleShot(1200, done)
    dialog.exec_()
    order.append("exec_returned")

    # O Done TEM de acontecer antes do exec_() devolver o controle.
    assert order == ["refresh", "done", "exec_returned"]
    assert not dialog.isVisible()
    assert QApplication.activeModalWidget() is None  # nada de modal pendurado


# -- roteamento por indicador ---------------------------------------------

def test_target_combo_matches_the_opening_step(setup) -> None:  # type: ignore[no-untyped-def]
    """O alvo tem de refletir o indicador do passo, ja na abertura.

    Ficava preso no indicador critico ("Vacuum 1") enquanto o assistente
    mostrava instrucoes do "Vacuum Pump 1" - convite a calibrar o errado.
    """
    dialog, _, _, _ = setup
    assert dialog._guide.current_step().indicator == "Vacuum Pump 1"
    assert dialog._target.currentText() == "Vacuum Pump 1"


def test_wizard_writes_files_for_the_step_indicator(setup) -> None:  # type: ignore[no-untyped-def]
    """Seguindo o assistente pelo botao verde, o Vacuum Pump 1 tem de ficar
    calibrado NELE - nao no Vacuum 1."""
    dialog, config, templates, screen = setup
    row_y = 80

    _drag(dialog, _ROW_X, row_y, _LABEL_W, _LABEL_H)
    dialog._guide._run_action()                       # 1. nome
    _drag(dialog, _ROW_X + _LABEL_W + _GAP, row_y, _TOGGLE_W, _TOGGLE_H)
    dialog._guide._run_action()                       # 2. botao ON/OFF
    screen["frame"] = _screen(row_y, on=True)
    dialog._guide._run_action()                       # 3. amostra ON
    screen["frame"] = _screen(row_y, on=False)
    dialog._guide._run_action()                       # 4. amostra OFF

    for name in ("vacuum_pump_1_label.png", "vacuum_pump_1_toggle_on.png",
                 "vacuum_pump_1_toggle_off.png"):
        assert (templates / name).exists(), f"faltou {name}"
    assert config.indicators[0].toggle is not None, "geometria foi para o indicador errado"
    assert not (templates / "vacuum_1_label.png").exists(), "gravou no Vacuum 1 por engano"


def test_calibrated_indicator_is_actually_read(setup) -> None:  # type: ignore[no-untyped-def]
    """Prova o sintoma relatado: depois de calibrado nao pode ficar 'UNREADABLE'."""
    dialog, config, templates, screen = setup
    row_y = 80
    _drag(dialog, _ROW_X, row_y, _LABEL_W, _LABEL_H)
    dialog._guide._run_action()
    _drag(dialog, _ROW_X + _LABEL_W + _GAP, row_y, _TOGGLE_W, _TOGGLE_H)
    dialog._guide._run_action()
    screen["frame"] = _screen(row_y, on=True)
    dialog._guide._run_action()
    screen["frame"] = _screen(row_y, on=False)
    dialog._guide._run_action()

    finders = build_finders(templates, config)
    assert "Vacuum Pump 1" in finders, "nenhum leitor criado para o indicador calibrado"
    assert finders["Vacuum Pump 1"].read(_screen(row_y, on=True)).state is PumpState.ON
    assert finders["Vacuum Pump 1"].read(_screen(row_y, on=False)).state is PumpState.OFF
