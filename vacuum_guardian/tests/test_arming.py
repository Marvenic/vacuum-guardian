"""Testes da deteccao do momento critico (as duas confirmacoes do OSAI).

Sequencia real na maquina:
    MATERIAL THICKNESS -> EXCEEDING MATERIAL -> (confirmadas) -> a pedra move
"""

from __future__ import annotations

from app.detection import ArmingDetector, ArmingState


def _run(detector: ArmingDetector, *frames: str) -> bool:
    armed = False
    for text in frames:
        armed = detector.update(text)
    return armed


def test_full_sequence_arms_only_after_both_are_confirmed() -> None:
    detector = ArmingDetector()
    assert not detector.update("Production manager 4986_P4.CNC")
    assert not detector.update("MATERIAL THICKNESS 20.000000")  # 1a janela aberta
    assert not detector.update("EXCEEDINGMATERIAL 0.000000")    # 2a janela aberta
    # As duas sumiram = confirmadas: agora sim.
    assert detector.update("Production manager 4986_P4.CNC")
    assert detector.state is ArmingState.ARMED


def test_dialogs_still_open_never_arm() -> None:
    """Enquanto a janela esta na tela a maquina ainda nao cortou."""
    detector = ArmingDetector()
    assert not _run(
        detector,
        "MATERIAL THICKNESS",
        "MATERIAL THICKNESS",
        "EXCEEDINGMATERIAL",
        "EXCEEDINGMATERIAL",
    )


def test_exceeding_without_thickness_does_not_arm() -> None:
    """Texto solto nao pode armar - so a sequencia completa conta."""
    detector = ArmingDetector()
    assert not _run(detector, "EXCEEDINGMATERIAL", "algo diferente")


def test_new_job_disarms_previous_run() -> None:
    """A 1a janela reaparecendo significa novo trabalho: desarma o anterior."""
    detector = ArmingDetector()
    _run(detector, "MATERIAL THICKNESS", "EXCEEDINGMATERIAL", "rodando")
    assert detector.armed
    assert not detector.update("MATERIAL THICKNESS 30.000000")
    assert detector.state is ArmingState.THICKNESS


def test_stays_armed_while_cutting() -> None:
    """Sem sinal confiavel de 'corte terminou', o guardiao continua vigiando."""
    detector = ArmingDetector()
    _run(detector, "MATERIAL THICKNESS", "EXCEEDINGMATERIAL")
    for _ in range(10):
        assert detector.update("Production manager - cortando")


def test_disarm_is_explicit() -> None:
    detector = ArmingDetector()
    _run(detector, "MATERIAL THICKNESS", "EXCEEDINGMATERIAL", "rodando")
    detector.disarm()
    assert not detector.armed
    assert detector.state is ArmingState.IDLE


def test_keywords_are_case_insensitive() -> None:
    detector = ArmingDetector()
    assert not detector.update("Material Thickness")
    assert not detector.update("ExceedingMaterial")
    assert detector.update("rodando")


def test_ocr_noise_around_keywords_still_matches() -> None:
    """OCR real vem com lixo em volta; a busca e por substring de proposito."""
    detector = ArmingDetector()
    detector.update("Asset Input - IP.192.168.139.1 MATERIAL THICKNESS 20.000000 OK Cancel")
    detector.update("Asset Input EXCEEDINGMATERIAL 0.000000 OK Cancel (ESC)")
    assert detector.update("Production manager")
