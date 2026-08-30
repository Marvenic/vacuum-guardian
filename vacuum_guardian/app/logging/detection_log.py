"""Trilha de auditoria em CSV (requisito 8).

Por que um CSV separado do log do loguru:
- o .log e para diagnostico humano; o CSV e para analise (Excel, Power BI);
- colunas estaveis permitem correlacionar alarmes com turnos/programas.

Estrategia de escrita: apenas MUDANCAS de estado (ou eventos de alarme) sao
gravadas. Registrar todos os ciclos geraria ~86 mil linhas/dia a 1 Hz, sem
ganho de informacao. Assim o arquivo continua legivel e o disco saudavel em
operacao continua.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..models import AlarmDecision, DetectionResult


class DetectionLog:
    """Escreve uma linha por transicao de estado detectada."""

    # Colunas novas entram sempre NO FIM: planilhas e relatorios ja feitos
    # sobre arquivos antigos continuam apontando para as mesmas posicoes.
    _HEADER = [
        "date",
        "time",
        "program",
        "monitored_program",
        "indicators",
        "alarm",
        "elapsed_ms",
        "level",
        "phase",
    ]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._last_signature: str | None = None
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Cria o arquivo com cabecalho na primeira execucao."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:  # disco cheio/permissao: nunca derrubar o monitor
            logger.error("Could not prepare {}: {}", self._path, exc)

    @staticmethod
    def _signature(result: DetectionResult, decision: AlarmDecision) -> str:
        """Identidade do estado atual; muda => vale a pena gravar uma linha."""
        states = ",".join(f"{k}={v.state.value}" for k, v in sorted(result.indicators.items()))
        return f"{result.program_name}|{states}|{decision.level.name}|{result.run_phase.value}"

    def record(self, result: DetectionResult, decision: AlarmDecision) -> bool:
        """Grava se o estado mudou desde a ultima linha. Retorna True se gravou."""
        signature = self._signature(result, decision)
        if signature == self._last_signature:
            return False
        self._last_signature = signature

        row = [
            f"{result.timestamp:%Y-%m-%d}",
            f"{result.timestamp:%H:%M:%S}",
            result.program_name,
            "YES" if decision.is_monitored_program else "NO",
            " ".join(f"{k}={v.state.value}" for k, v in sorted(result.indicators.items())),
            "YES" if decision.should_alarm else "NO",
            f"{result.elapsed_ms:.1f}",
            decision.level.name,
            result.run_phase.value,
        ]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the CSV audit trail: {}", exc)
            return False
        return True


class OverrideLog:
    """Registra quando o operador iniciou o programa mesmo sem o vacuo ligado.

    Arquivo proprio (e nao uma coluna no detections.csv) porque o publico e
    outro: o gerente quer uma lista curta de "ignorou o aviso e cortou assim
    mesmo", com data e hora, sem ter de filtrar milhares de linhas.

    Uma linha por evento: a transicao CLOSE THE DOORS -> programa rodando com
    o vacuo fora do estado ON.
    """

    _HEADER = ["date", "time", "program", "indicator", "state_at_start"]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensure_header()

    def _ensure_header(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:
            logger.error("Could not prepare {}: {}", self._path, exc)

    def record(self, when: datetime, program: str, indicator: str, state: str) -> bool:
        """Grava um override. Retorna True se conseguiu gravar."""
        row = [
            f"{when:%Y-%m-%d}",
            f"{when:%H:%M:%S}",
            program,
            indicator,
            state,
        ]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the override log: {}", exc)
            return False
        logger.warning(
            "OVERRIDE: program started with {} = {} (recorded for the manager)",
            indicator, state,
        )
        return True


class AlarmActionLog:
    """Registra o que o operador fez quando o alarme apareceu.

    Arquivo proprio porque a pergunta e especifica e frequente: "o alarme
    tocou, alguem viu?". Uma linha por clique, com a severidade e o motivo
    que estavam na tela naquele instante - depois de dispensado, o popup sai
    e essa e a unica prova de que o aviso foi visto.
    """

    _HEADER = ["date", "time", "action", "level", "reason"]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensure_header()

    def _ensure_header(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists() or self._path.stat().st_size == 0:
                with self._path.open("w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle, delimiter=";").writerow(self._HEADER)
        except OSError as exc:
            logger.error("Could not prepare {}: {}", self._path, exc)

    def record(self, when: datetime, action: str, level: str, reason: str) -> bool:
        """Grava uma acao do operador. Retorna True se conseguiu gravar."""
        row = [f"{when:%Y-%m-%d}", f"{when:%H:%M:%S}", action, level, reason]
        try:
            with self._path.open("a", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle, delimiter=";").writerow(row)
        except OSError as exc:
            logger.error("Failed to write the alarm action log: {}", exc)
            return False
        return True
