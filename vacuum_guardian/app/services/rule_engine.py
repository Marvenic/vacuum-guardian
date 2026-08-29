"""Rule Engine: decide SE ha alerta e QUAL a severidade.

Regra principal (momento critico):
    Depois que o operador confirma MATERIAL THICKNESS e EXCEEDING MATERIAL,
    a pedra pode se mover. A partir dai o indicador critico ("Vacuum 1")
    precisa estar comprovadamente ON:

        ON                      -> nada
        OFF                     -> CRITICAL (vermelho)
        NOT_VISIBLE / UNKNOWN   -> WARNING  (laranja)

    O terceiro caso e a decisao de projeto mais importante aqui: o menu do
    OSAI rola, entao o "Vacuum 1" pode simplesmente nao estar na tela. Ficar
    calado seria fingir que esta tudo bem sem ter verificado nada - por isso
    "nao consegui verificar" tambem alerta, so que em nivel menor.

Regra secundaria (legado): nome do programa casa com trigger_programs E
algum indicador esta OFF -> CRITICAL. Continua util para instalacoes cujos
programas tenham nomes descritivos.

Puro de proposito (sem I/O, sem estado): entrada DetectionResult, saida
AlarmDecision. Isso o torna trivialmente testavel e desacoplado da UI.
"""

from __future__ import annotations

from ..models import AlarmDecision, AlertLevel, DetectionResult, PumpState, RunPhase


class RuleEngine:
    def __init__(
        self,
        trigger_programs: list[str],
        critical_indicator: str = "Vacuum 1",
    ) -> None:
        # Normaliza uma vez; comparacao e sempre em maiusculas.
        self._triggers = [t.upper() for t in trigger_programs if t.strip()]
        self._critical = critical_indicator.strip()

    @property
    def critical_indicator(self) -> str:
        return self._critical

    def is_monitored_program(self, program_name: str) -> bool:
        """True se qualquer palavra-gatilho aparece no nome do programa."""
        name = program_name.upper()
        return bool(name) and any(t in name for t in self._triggers)

    def _critical_reading(self, result: DetectionResult):
        """Leitura do indicador critico; casa nome exato e, se falhar, sem espacos."""
        reading = result.indicators.get(self._critical)
        if reading is not None:
            return reading
        wanted = self._critical.lower().replace(" ", "")
        for name, value in result.indicators.items():
            if name.lower().replace(" ", "") == wanted:
                return value
        return None

    def evaluate(self, result: DetectionResult) -> AlarmDecision:
        monitored = self.is_monitored_program(result.program_name)
        offending = tuple(
            name for name, r in result.indicators.items() if r.state is PumpState.OFF
        )
        unknown = tuple(
            name for name, r in result.indicators.items()
            if not r.state.is_verifiable
        )

        level = AlertLevel.NONE
        reason = ""

        # -- regra do campo Iso lines --------------------------------------
        # CLOSE THE DOORS = ainda da tempo de ligar o vacuo: aviso laranja.
        # Texto mudou depois disso = o programa ja esta cortando: vermelho.
        if result.run_phase is RunPhase.DOORS:
            reading = self._critical_reading(result)
            state = reading.state if reading is not None else PumpState.NOT_VISIBLE
            if state is not PumpState.ON:
                level = AlertLevel.WARNING
                reason = (
                    f"CLOSE THE DOORS: turn {self._critical} ON before starting."
                    if state is PumpState.OFF
                    else f"CLOSE THE DOORS: could not verify {self._critical}. Check it."
                )
        elif result.run_phase is RunPhase.RUNNING:
            reading = self._critical_reading(result)
            state = reading.state if reading is not None else PumpState.NOT_VISIBLE
            if state is PumpState.OFF:
                level = AlertLevel.CRITICAL
                reason = f"Program started with {self._critical} OFF - STOP THE MACHINE."
            elif not state.is_verifiable:
                level = AlertLevel.WARNING
                reason = f"Program running and {self._critical} could not be verified."

        # -- regra secundaria (legado) -------------------------------------
        if monitored and offending and level is not AlertLevel.CRITICAL:
            level = AlertLevel.CRITICAL
            reason = "OFF: " + ", ".join(offending)

        return AlarmDecision(
            is_monitored_program=monitored,
            offending=offending,
            unknown=unknown,
            level=level,
            reason=reason,
        )
