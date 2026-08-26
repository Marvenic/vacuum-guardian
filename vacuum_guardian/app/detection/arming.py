"""Detecta o MOMENTO CRITICO a partir das confirmacoes do OSAI.

Contexto de chao de fabrica: todos os programas se chamam <numero>.CNC, entao
o nome nao diz se aquele trabalho exige vacuo, nem se ja comecou. O que marca
o inicio real do risco e a sequencia de duas janelas azuis que o operador
precisa confirmar antes do corte:

    MATERIAL THICKNESS  ->  EXCEEDING MATERIAL  ->  (a pedra se move)

Enquanto elas estao na tela a maquina ainda esta parada. Quando a SEGUNDA
desaparece (confirmada), entra o periodo em que o vacuo precisa estar ligado:
e ai que o guardiao "arma".

Desarmar: quando a sequencia recomeca (novo trabalho) ou explicitamente pelo
operador. Sem sinal confiavel de "corte terminou" na tela, preferimos
continuar armado - falso alarme incomoda, falta de alarme machuca.
"""

from __future__ import annotations

from enum import Enum

from loguru import logger


class ArmingState(Enum):
    IDLE = "IDLE"                    # nada acontecendo
    THICKNESS = "THICKNESS"          # 1a janela na tela
    EXCEEDING = "EXCEEDING"          # 2a janela na tela
    ARMED = "ARMED"                  # ambas confirmadas: pedra pode se mover


class ArmingDetector:
    """Acompanha a sequencia das duas confirmacoes via texto lido da tela."""

    def __init__(self, thickness_keyword: str = "THICKNESS",
                 exceeding_keyword: str = "EXCEEDING") -> None:
        self._thickness = thickness_keyword.upper()
        self._exceeding = exceeding_keyword.upper()
        self._state = ArmingState.IDLE

    @property
    def state(self) -> ArmingState:
        return self._state

    @property
    def armed(self) -> bool:
        return self._state is ArmingState.ARMED

    def _to(self, state: ArmingState) -> None:
        if state is not self._state:
            logger.info("Arming: {} -> {}", self._state.value, state.value)
            self._state = state

    def update(self, screen_text: str) -> bool:
        """Processa o texto da tela de um ciclo. Retorna se esta armado."""
        text = (screen_text or "").upper()
        has_thickness = self._thickness in text
        has_exceeding = self._exceeding in text

        if has_thickness:
            # A 1a janela reaparecendo significa NOVO trabalho: reinicia o
            # ciclo (e desarma um armamento anterior que tenha ficado ativo).
            self._to(ArmingState.THICKNESS)
        elif has_exceeding and self._state in (ArmingState.THICKNESS, ArmingState.EXCEEDING):
            self._to(ArmingState.EXCEEDING)
        elif self._state is ArmingState.EXCEEDING and not has_exceeding:
            # A 2a janela sumiu = o operador confirmou. Comeca o risco.
            self._to(ArmingState.ARMED)
        return self.armed

    def disarm(self) -> None:
        """Encerra o periodo critico (ex.: operador reconheceu o alarme)."""
        self._to(ArmingState.IDLE)
