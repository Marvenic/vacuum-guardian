"""AlarmController: maquina de estados do alarme, desacoplada da UI.

Semantica:
- Alarme dispara -> som em loop + aviso na tela.
- Botao unico    -> registra a acao, para o som, tira o aviso da frente e
                    SILENCIA por 5 minutos (ver SNOOZE_MINUTES). O aviso cobre
                    a tela do OSAI: mantendo-o ali o operador ficava impedido
                    de mexer na maquina para resolver a propria condicao.
- Condicao cessa -> tudo reseta; um novo alarme volta a tocar som.

Por que a soneca: sem ela o aviso reaparecia no ciclo seguinte (1 s depois),
enquanto o operador ainda estava indo ate a maquina. Os 5 minutos dao tempo de
agir. O monitoramento NAO para nesse periodo - o painel e o icone da bandeja
continuam mostrando o estado real; so o aviso e o som ficam suspensos.

A UI apenas consulta `popup_should_show` e chama acknowledge() - nenhuma regra
vive na camada grafica.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from ..models import AlarmDecision, AlertLevel
from .sound import SoundPlayer

# ponytail: constante, nao configuracao. Vira campo do config.json quando
# alguem do chao de fabrica pedir outro tempo.
SNOOZE_MINUTES = 5.0


@dataclass(frozen=True)
class AlarmStatus:
    """Fotografia do estado do alarme para a UI exibir."""

    active: bool
    acknowledged: bool
    reason: str  # texto pronto para o popup
    sound_enabled: bool = True
    dismissed: bool = False   # operador clicou: o aviso sai da tela
    snoozed: bool = False     # dentro da janela de silencio
    level: AlertLevel = AlertLevel.NONE

    @property
    def popup_should_show(self) -> bool:
        return self.active and not self.dismissed


class AlarmController:
    def __init__(
        self,
        player: SoundPlayer,
        wav_path: Path,
        sound_enabled: bool = True,
        action_log=None,  # AlarmActionLog | None (evita import circular)
        snooze_minutes: float = SNOOZE_MINUTES,
    ) -> None:
        self._player = player
        self._wav_path = wav_path
        # Som opcional (fabrica barulhenta / PC sem alto-falante). Com ele
        # desligado o aviso visual continua identico.
        self._sound_enabled = sound_enabled
        self._action_log = action_log
        self._snooze = timedelta(minutes=snooze_minutes)
        self._active = False
        self._acknowledged = False
        self._reason = ""
        self._dismissed = False
        self._snoozed_until: datetime | None = None

    @property
    def snoozed_until(self) -> datetime | None:
        return self._snoozed_until

    def _is_snoozed(self, now: datetime) -> bool:
        if self._snoozed_until is None:
            return False
        if now >= self._snoozed_until:
            logger.info("Snooze over - watching the screen again")
            self._snoozed_until = None
            return False
        return True

    def update(self, decision: AlarmDecision, now: datetime | None = None) -> AlarmStatus:
        """Processa a decisao do Rule Engine de um ciclo.

        `now` e injetavel para o teste nao precisar esperar 5 minutos.
        """
        now = now or datetime.now()

        if not decision.should_alarm:
            # Condicao resolvida: zera tudo, INCLUSIVE a soneca. Sem isto, o
            # operador que liga o vacuo logo apos o clique ficaria 5 minutos
            # sem vigilancia - o alarme seguinte so apareceria depois.
            if self._active or self._snoozed_until is not None:
                logger.info("Alarm condition cleared - alarm ended")
                self._player.stop()
                self._active = False
                self._acknowledged = False
                self._dismissed = False
                self._reason = ""
                self._snoozed_until = None
            return self.status(False)

        if self._is_snoozed(now):
            return self.status(True)

        self._reason = decision.reason
        if not self._active:
            logger.warning("ALARM TRIGGERED ({})", self._reason)
            self._active = True
            self._acknowledged = False
            self._dismissed = False
        if self._sound_enabled:
            self._player.start_loop(self._wav_path)
        return self.status(False)

    def acknowledge(self, now: datetime | None = None) -> None:
        """Botao unico: registra a ciencia, cala o som e silencia por 5 min.

        O registro e a contrapartida de deixar o aviso sumir: sem o popup na
        tela, essa linha e a unica prova de que alguem viu o alarme.
        """
        if not self._active:
            return
        now = now or datetime.now()
        self._snoozed_until = now + self._snooze
        self._acknowledged = True
        self._dismissed = True
        self._active = False  # o ciclo seguinte reavalia do zero, apos a soneca
        self._player.stop()
        logger.info(
            "Alarm acknowledged by the operator ({}) - silenced until {:%H:%M:%S}",
            self._reason, self._snoozed_until,
        )
        if self._action_log is not None:
            self._action_log.record(now, "ACKNOWLEDGE", self._reason, self._snoozed_until)

    # Nome antigo mantido: MainWindow e o popup ainda podem chamar silence().
    silence = acknowledge

    def status(self, snoozed: bool | None = None) -> AlarmStatus:
        if snoozed is None:
            snoozed = self._snoozed_until is not None
        return AlarmStatus(
            active=self._active,
            acknowledged=self._acknowledged,
            reason=self._reason,
            sound_enabled=self._sound_enabled,
            dismissed=self._dismissed,
            snoozed=snoozed,
            level=AlertLevel.WARNING if self._active else AlertLevel.NONE,
        )
