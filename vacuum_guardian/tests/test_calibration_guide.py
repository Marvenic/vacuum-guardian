"""Testes do guia de calibracao embutido.

O valor do guia esta em duas coisas: o roteiro bater com os botoes reais e o
"onde eu parei" refletir o que existe em disco - se ele mentir, o operador se
perde exatamente como se perdia sem guia nenhum.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide2")

from app.models import AppConfig, IndicatorConfig, Roi, ToggleGeometry  # noqa: E402
from app.ui.calibration_guide import (  # noqa: E402
    LANGUAGES,
    REQ_ISO,
    REQ_LABEL,
    REQ_OFF,
    REQ_ON,
    REQ_TOGGLE,
    CalibrationGuide,
    build_steps,
    calibration_status,
    progress_key,
)

_NAMES = ["Vacuum Pump 1", "Vacuum 1"]

_TOGGLE = ToggleGeometry(dx=70, dy=0, width=40, height=14)


def _config(**kwargs) -> AppConfig:  # type: ignore[no-untyped-def]
    config = AppConfig(
        indicators=[IndicatorConfig("Vacuum Pump 1"), IndicatorConfig("Vacuum 1")],
        critical_indicator="Vacuum 1",
    )
    for key, value in kwargs.items():
        setattr(config, key, value)
    return config


def _touch(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(b"x")


# -- roteiro ---------------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_steps_exist_in_both_languages(language: str) -> None:
    steps = build_steps(_NAMES, language)
    assert len(steps) >= 7
    assert all(step.title and step.body for step in steps)


def test_both_languages_share_the_same_skeleton() -> None:
    """Trocar de idioma nao pode mudar a ordem nem o que cada passo produz."""
    english = build_steps(_NAMES, "en")
    portuguese = build_steps(_NAMES, "pt")
    assert [s.anchor for s in english] == [s.anchor for s in portuguese]
    assert [s.requires for s in english] == [s.requires for s in portuguese]


def test_steps_are_in_the_order_the_buttons_must_be_pressed() -> None:
    """Um indicador inteiro por vez, na ordem label -> toggle -> ON -> OFF."""
    order = [s.requires for s in build_steps(_NAMES, "en") if s.requires]
    assert order == [
        progress_key("Vacuum Pump 1", REQ_LABEL),
        progress_key("Vacuum Pump 1", REQ_TOGGLE),
        progress_key("Vacuum Pump 1", REQ_ON),
        progress_key("Vacuum Pump 1", REQ_OFF),
        progress_key("Vacuum 1", REQ_LABEL),
        progress_key("Vacuum 1", REQ_TOGGLE),
        progress_key("Vacuum 1", REQ_ON),
        progress_key("Vacuum 1", REQ_OFF),
        REQ_ISO,  # area do Iso lines, depois dos indicadores
    ]


def test_every_capture_step_knows_its_own_indicator() -> None:
    """A causa do bug: o passo precisa carregar A QUEM ele pertence."""
    for step in build_steps(_NAMES, "en"):
        if step.action in (REQ_LABEL, REQ_TOGGLE, REQ_ON, REQ_OFF):
            assert step.indicator in _NAMES
            assert step.requires == progress_key(step.indicator, step.action)


def test_step_text_names_its_own_indicator() -> None:
    """Passo do Vacuum Pump 1 nao pode falar de Vacuum 1 - era o que confundia."""
    for step in build_steps(_NAMES, "en"):
        if step.indicator == "Vacuum Pump 1":
            text = step.title + step.body
            assert "Vacuum Pump 1" in text
            # "Vacuum 1" so pode aparecer como parte de "Vacuum Pump 1"
            assert "Vacuum 1" not in text.replace("Vacuum Pump 1", "")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_capture_step_has_an_action_button(language: str) -> None:
    """Passo que captura algo precisa de um botao rotulado - senao nao ha o que clicar."""
    from app.ui.calibration_guide import _UI

    labels = _UI[language]["actions"]
    for step in build_steps(_NAMES, language):
        if step.action:
            assert step.action in labels
            assert labels[step.action]


def test_required_steps_all_carry_an_action() -> None:
    """Nao pode existir passo obrigatorio sem forma de conclui-lo pelo assistente."""
    for step in build_steps(_NAMES, "en"):
        if step.requires and step.indicator:
            assert step.requires == progress_key(step.indicator, step.action)
        elif step.requires:
            assert step.action == step.requires  # passos gerais (Iso lines)


def test_sample_steps_do_not_ask_for_a_drag() -> None:
    """As amostras ON/OFF sao automaticas: pedir retangulo confundiria de novo."""
    steps = {s.anchor: s for s in build_steps(_NAMES, "en")}
    assert not steps["on@vacuum_1"].needs_selection
    assert not steps["off@vacuum_1"].needs_selection
    assert steps["label@vacuum_1"].needs_selection
    assert steps["toggle@vacuum_1"].needs_selection


def test_steps_mention_every_configured_indicator() -> None:
    text = " ".join(s.title + s.body for s in build_steps(["Vacuum 9", "Vacuum 8"], "en"))
    assert "Vacuum 9" in text
    assert "Vacuum 8" in text


# -- progresso real --------------------------------------------------------

def test_nothing_calibrated_reports_everything_pending(tmp_path: Path) -> None:
    items, done = calibration_status(_config(), tmp_path)
    assert done == set()
    assert not any(item.done for item in items)


def test_each_artifact_marks_its_own_step(tmp_path: Path) -> None:
    config = _config()
    _touch(tmp_path, "vacuum_1_label.png")
    assert calibration_status(config, tmp_path)[1] == {progress_key("Vacuum 1", REQ_LABEL)}

    config.indicators[1].toggle = _TOGGLE
    assert calibration_status(config, tmp_path)[1] == {
        progress_key("Vacuum 1", REQ_LABEL),
        progress_key("Vacuum 1", REQ_TOGGLE),
    }

    _touch(tmp_path, "vacuum_1_toggle_on.png")
    _touch(tmp_path, "vacuum_1_toggle_off.png")
    assert calibration_status(config, tmp_path)[1] == {
        progress_key("Vacuum 1", key) for key in (REQ_LABEL, REQ_TOGGLE, REQ_ON, REQ_OFF)
    }


def test_progress_is_tracked_per_indicator(tmp_path: Path) -> None:
    """Calibrar o Vacuum Pump 1 conta para ele - e nao marca o Vacuum 1."""
    _touch(tmp_path, "vacuum_pump_1_label.png")
    done = calibration_status(_config(), tmp_path)[1]
    assert done == {progress_key("Vacuum Pump 1", REQ_LABEL)}
    assert progress_key("Vacuum 1", REQ_LABEL) not in done


def test_checklist_covers_every_indicator(tmp_path: Path) -> None:
    """Com dois vacuos o operador precisa ver o progresso dos dois."""
    items, _ = calibration_status(_config(), tmp_path)
    groups = {item.group for item in items if item.group}
    assert groups == {"Vacuum Pump 1", "Vacuum 1"}
    assert len([i for i in items if i.group == "Vacuum Pump 1"]) == 4


def test_optional_items_track_the_optional_rois(tmp_path: Path) -> None:
    config = _config(program_roi=Roi(0, 0, 10, 10))
    items, _ = calibration_status(config, tmp_path)
    optional = [item for item in items if item.optional]
    assert len(optional) == 1
    assert all(item.done for item in optional)


def test_invalid_toggle_does_not_count_as_calibrated(tmp_path: Path) -> None:
    config = _config()
    config.indicators[1].toggle = ToggleGeometry(dx=0, dy=0, width=0, height=0)
    assert progress_key("Vacuum 1", REQ_TOGGLE) not in calibration_status(config, tmp_path)[1]


# -- widget ----------------------------------------------------------------

def test_opens_on_the_first_pending_step(qt_app, tmp_path: Path) -> None:
    """Motivo de existir do painel: retomar de onde o operador parou."""
    config = _config()
    # Vacuum Pump 1 (o primeiro) inteiro pronto; do Vacuum 1 falta a amostra ON.
    for name in (
        "vacuum_pump_1_label.png",
        "vacuum_pump_1_toggle_on.png",
        "vacuum_pump_1_toggle_off.png",
        "vacuum_1_label.png",
    ):
        _touch(tmp_path, name)
    config.indicators[0].toggle = _TOGGLE
    config.indicators[1].toggle = _TOGGLE

    guide = CalibrationGuide(config, tmp_path)
    assert guide._steps[guide._index].anchor == "on@vacuum_1"


def test_opens_on_the_test_step_when_everything_is_done(qt_app, tmp_path: Path) -> None:
    config = _config(iso_roi=Roi(0, 0, 10, 10))
    config.indicators[0].toggle = _TOGGLE
    config.indicators[1].toggle = _TOGGLE
    for slug in ("vacuum_pump_1", "vacuum_1"):
        for suffix in ("_label.png", "_toggle_on.png", "_toggle_off.png"):
            _touch(tmp_path, slug + suffix)

    guide = CalibrationGuide(config, tmp_path)
    assert guide._steps[guide._index].anchor == "test"


def test_language_toggle_keeps_the_current_step(qt_app, tmp_path: Path) -> None:
    guide = CalibrationGuide(_config(), tmp_path)
    guide._go(3)
    anchor = guide._steps[3].anchor

    guide._toggle_language()
    assert guide.language == "pt"
    assert guide._steps[guide._index].anchor == anchor

    guide._toggle_language()
    assert guide.language == "en"
    assert guide._steps[guide._index].anchor == anchor


def test_language_choice_is_reported_for_persistence(qt_app, tmp_path: Path) -> None:
    saved: list[str] = []
    config = _config()
    guide = CalibrationGuide(config, tmp_path, None, saved.append)
    guide._toggle_language()
    assert saved == ["pt"]
    assert config.guide_language == "pt"  # gravado no config que sera salvo


def test_starts_in_the_language_from_config(qt_app, tmp_path: Path) -> None:
    guide = CalibrationGuide(_config(guide_language="pt"), tmp_path)
    assert guide.language == "pt"


def test_unknown_language_in_config_falls_back_to_english(qt_app, tmp_path: Path) -> None:
    guide = CalibrationGuide(_config(guide_language="xx"), tmp_path)
    assert guide.language == "en"


def test_refresh_updates_progress_after_a_capture(qt_app, tmp_path: Path) -> None:
    """Cada botao de calibracao chama refresh(); o checklist tem de acompanhar."""
    config = _config()
    guide = CalibrationGuide(config, tmp_path)
    key = progress_key("Vacuum 1", REQ_LABEL)
    assert key not in calibration_status(config, tmp_path)[1]

    _touch(tmp_path, "vacuum_1_label.png")
    guide.refresh()
    assert key in calibration_status(config, tmp_path)[1]
