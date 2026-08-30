"""Testes da escolha da janela do OSAI.

Motivados por falha real na CNC: ao reiniciar, o app "nao detectava" a tela do
OSAI. Medido nesta maquina, uma janela MINIMIZADA reporta:

    IsWindowVisible=True  IsIconic=True  rect=(-32000,-32000) 391x61

ou seja, passava no filtro antigo (visivel + largura/altura positivas). O app
capturava uma regiao fora da tela, o OCR nao lia nada e nenhum alarme - nem o
laranja - chegava a disparar.
"""

from __future__ import annotations

from app.capture.window_locator import WindowCandidate, choose_window


def _window(title: str, left=100, top=100, width=1920, height=1080, minimized=False):  # type: ignore[no-untyped-def]
    return WindowCandidate(title, left, top, width, height, minimized)


def test_picks_the_matching_window() -> None:
    chosen = choose_window([_window("Bloco de notas"), _window("CMS - OSAI")], "osai")
    assert chosen is not None
    assert chosen.title == "CMS - OSAI"


def test_hint_is_case_insensitive() -> None:
    assert choose_window([_window("cms - osai")], "OSAI") is not None


def test_no_match_returns_none() -> None:
    assert choose_window([_window("Bloco de notas")], "osai") is None


def test_minimized_window_is_refused(caplog) -> None:  # type: ignore[no-untyped-def]
    """O bug: minimizada tem rect fora da tela, capturar ali nao le nada."""
    candidates = [_window("OSAI", left=-32000, top=-32000, width=391, height=61, minimized=True)]
    assert choose_window(candidates, "osai") is None


def test_offscreen_window_is_refused_even_if_not_flagged() -> None:
    """Cinto e suspensorio: coordenada fora da tela basta para recusar."""
    candidates = [_window("OSAI", left=-32000, top=-32000, width=391, height=61)]
    assert choose_window(candidates, "osai") is None


def test_zero_sized_window_is_refused() -> None:
    assert choose_window([_window("OSAI", width=0, height=0)], "osai") is None


def test_largest_match_wins_over_service_windows() -> None:
    """'OSAI BootController' casa com o mesmo hint e e pequena.

    A tela de operacao ocupa o monitor; pegar "a primeira" ja fez o app
    calibrar sobre uma janela de servico e capturar uma barra preta.
    """
    candidates = [
        _window("OSAI BootController", width=400, height=200),
        _window("CMS Production - OSAI", width=1920, height=1080),
    ]
    chosen = choose_window(candidates, "osai")
    assert chosen is not None
    assert chosen.title == "CMS Production - OSAI"


def test_minimized_main_window_does_not_shadow_a_usable_one() -> None:
    """Havendo uma utilizavel, a minimizada nao pode roubar a escolha."""
    candidates = [
        _window("OSAI", left=-32000, top=-32000, width=3000, height=3000, minimized=True),
        _window("CMS - OSAI", width=1280, height=1024),
    ]
    chosen = choose_window(candidates, "osai")
    assert chosen is not None
    assert chosen.title == "CMS - OSAI"


def test_background_window_is_still_usable() -> None:
    """Estar atras de outra janela nao impede a captura - so minimizada impede."""
    chosen = choose_window([_window("CMS - OSAI", left=0, top=0)], "osai")
    assert chosen is not None
    assert (chosen.left, chosen.top, chosen.width, chosen.height) == (0, 0, 1920, 1080)


# -- gatilho nao calibrado (falha silenciosa) ------------------------------

def test_engine_reports_when_the_trigger_is_not_calibrated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Sem a area Iso lines nao existe gatilho: o app roda e NUNCA alarma.

    Falhar em silencio num app de seguranca e o pior comportamento possivel -
    o operador acha que esta protegido. O engine tem de sinalizar.
    """
    from app.models import AppConfig, Roi
    from app.services.monitor import MonitorEngine

    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    sem_gatilho = MonitorEngine(AppConfig(iso_roi=None), tmp_path)
    assert sem_gatilho.trigger_ready is False
    sem_gatilho.close()

    com_gatilho = MonitorEngine(AppConfig(iso_roi=Roi(10, 10, 200, 60)), tmp_path)
    assert com_gatilho.trigger_ready is True
    com_gatilho.close()
