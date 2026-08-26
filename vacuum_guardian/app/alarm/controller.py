"""AlarmController: maquina de estados do alarme, desacoplada da UI.

Semantica:
- Alarme dispara -> som em loop + popup deve aparecer.
- "Silenciar"    -> para o som; popup CONTINUA visivel enquanto a condicao
                    persistir (o popup nunca some sozinho com alarme ativo).
- "Reconhecer"   -> registra ciencia do operador no log e para o som; popup
                    tambem continua enquanto a condicao persistir.
- Condicao cessa -> som para, popup pode fechar, silencio/reconhecimento
                    sao resetados (um NOVO alarme volta a tocar som).
- ESCALADA       -> se um alerta laranja (WARNING) virar vermelho (CRITICAL),
                    o silencio e cancelado e o som volta: a situacao piorou e
                    o operador precisa saber, mesmo tendo silenciado antes.

A UI apenas consulta `popup_should_show` e chama acknowledge()/silence() -
nenhuma regra vive na camada grafica.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..models import AlarmDecision, AlertLevel
from .sound import SoundPlayer


@dataclass(frozen=True)
class AlarmStatus:
    """Fotografia do estado do alarme para a UI exibir."""

    active: bool
    muted: bool
    acknowledged: bool
    reason: str  # texto pronto para o popup
    sound_enabled: bool = True  # False esconde o botao "Silence" no popup
    level: AlertLevel = AlertLevel.NONE

    @property
    def popup_should_show(self) -> bool:
        return self.active

    @property
    def is_critical(self) -> bool:
        return self.level is AlertLevel.CRITICAL


class AlarmController:
    def __init__(self, player: SoundPlayer, wav_path: Path, sound_enabled: bool = True) -> None:
        self._player = player
        self._wav_path = wav_path
        # Som opcional (fabrica barulhenta / PC sem alto-falante). Com ele
        # desligado o popup continua identico - o alerta visual nunca depende
        # do audio.
        self._sound_enabled = sound_enabled
        self._active = False
        self._muted = False
        self._acknowledged = False
        self._reason = ""
        self._level = AlertLevel.NONE

    @property
    def level(self) -> AlertLevel:
        return self._level

    def update(self, decision: AlarmDecision) -> AlarmStatus:
        """Processa a decisao do Rule Engine de um ciclo. Chamado pelo loop de monitoramento."""
        if decision.should_alarm:
            self._reason = decision.reason
            escalated = decision.level is AlertLevel.CRITICAL and self._level is AlertLevel.WARNING
            if not self._active:
                # Transicao inativo -> ativo: novo alarme sempre comeca com som.
                logger.warning("ALARM TRIGGERED [{}] ({})", decision.level.name, self._reason)
                self._active = True
                self._muted = False
                self._acknowledged = False
            elif escalated:
                # Laranja -> vermelho: reabre o canal sonoro mesmo se silenciado.
                logger.warning("ALARM ESCALATED to CRITICAL ({})", self._reason)
                self._muted = False
                self._acknowledged = False
            self._level = decision.level
            if self._sound_enabled and not self._muted:
                self._player.start_loop(self._wav_path)
        elif self._active:
            # Condicao cessou: encerra tudo e rearma para o proximo evento.
            logger.info("Alarm condition cleared - alarm ended")
            self._player.stop()
            self._active = False
            self._muted = False
            self._acknowledged = False
            self._reason = ""
            self._level = AlertLevel.NONE
        return self.status()

    def silence(self) -> None:
        """Botao 'Silenciar': para o som; popup permanece enquanto a condicao durar."""
        if not self._active:
            return
        logger.info("Alarm silenced by the operator")
        self._muted = True
        self._player.stop()

    def acknowledge(self) -> None:
        """Botao 'Reconhecer': registra ciencia do operador (e tambem silencia)."""
        if not self._active:
            return
        logger.info("Alarm acknowledged by the operator")
        self._acknowledged = True
        self._muted = True
        self._player.stop()

    def status(self) -> AlarmStatus:
        return AlarmStatus(
            active=self._active,
            muted=self._muted,
            acknowledged=self._acknowledged,
            reason=self._reason,
            sound_enabled=self._sound_enabled,
            level=self._level,
        )
