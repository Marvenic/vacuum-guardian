"""Detecta a largada de um programa lendo o campo "Iso lines" do OSAI.

Contexto de chao de fabrica: todos os programas se chamam <numero>.CNC, entao
o nome nao diz se aquele trabalho ja comecou. Quem conta isso e o campo
"Iso lines" (canto inferior esquerdo), que o proprio OSAI atualiza conforme a
execucao.

    stand-by  -> codigo irrelevante
    carregou  -> "CLOSE THE DOORS"      -> hora de conferir o vacuo
    iniciou   -> o texto muda           -> a pedra pode se mover

A versao anterior armava pelas janelas MATERIAL THICKNESS / EXCEEDING
MATERIAL. Foi removida: o campo Iso lines cobre o mesmo momento com leitura
mais confiavel, e sem precisar de OCR na tela inteira.
"""

from __future__ import annotations

from loguru import logger

from ..models import RunPhase


class IsoLineWatcher:
    """Le o campo "Iso lines" e diz em que fase da largada o operador esta.

    Mais confiavel que o nome do programa (todos sao <numero>.CNC) e mais
    direto que as janelas de confirmacao: o proprio OSAI escreve CLOSE THE
    DOORS ali antes de liberar o corte.

        stand-by  -> texto qualquer, sem relevancia          -> IDLE
        carregou  -> "CLOSE THE DOORS"                       -> DOORS
        iniciou   -> o texto muda (viraram linhas de codigo) -> RUNNING

    Sair de DOORS direto para RUNNING e a evidencia de que o operador seguiu
    em frente: se o vacuo nao estava ligado, ele ignorou o aviso.
    """

    def __init__(self, keyword: str = "CLOSE THE DOOR") -> None:
        self._keyword = keyword.upper()
        self._phase = RunPhase.IDLE
        self._doors_text = ""  # texto exato visto no aviso, para detectar mudanca

    @property
    def phase(self) -> RunPhase:
        return self._phase

    def _to(self, phase: RunPhase) -> None:
        if phase is not self._phase:
            logger.info("Iso lines: {} -> {}", self._phase.value, phase.value)
            self._phase = phase

    def update(self, iso_text: str) -> RunPhase:
        """Processa o texto do campo Iso lines de um ciclo."""
        text = (iso_text or "").upper().strip()

        if self._keyword in text:
            self._doors_text = text
            self._to(RunPhase.DOORS)
        elif self._phase is RunPhase.DOORS and text and text != self._doors_text:
            # O aviso saiu e entrou outro conteudo: o programa comecou.
            self._to(RunPhase.RUNNING)
        elif self._phase is RunPhase.RUNNING and not text:
            # ponytail: tela vazia = voltou ao stand-by. Sem sinal explicito de
            # "terminou", so o campo esvaziar encerra o ciclo.
            self._to(RunPhase.IDLE)
        return self._phase

    def reset(self) -> None:
        self._to(RunPhase.IDLE)
        self._doors_text = ""
