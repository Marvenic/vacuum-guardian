"""Dataclasses e enums centrais do Vacuum Guardian.

Estes tipos sao a "linguagem comum" entre captura, visao, regras e UI.
Nenhum deles conhece OpenCV, Qt ou mss - apenas dados puros, o que mantem
as camadas desacopladas (Dependency Inversion) e faceis de testar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PumpState(Enum):
    """Estado detectado de um indicador (toggle) na tela do OSAI."""

    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"  # visivel, mas leitura inconclusiva
    # O menu de softkeys do OSAI tem rolagem: o indicador pode simplesmente
    # nao estar na tela. Isso e diferente de "li e nao entendi" - por isso
    # tem estado proprio, para a mensagem ao operador poder ser especifica.
    NOT_VISIBLE = "NOT_VISIBLE"

    @property
    def is_verifiable(self) -> bool:
        """True apenas quando o estado foi realmente comprovado (ON ou OFF)."""
        return self in (PumpState.ON, PumpState.OFF)


class AlertLevel(Enum):
    """Ha alerta ou nao.

    Existiam dois niveis (laranja "nao verifiquei" e vermelho "esta
    desligado"). Na pratica a acao do operador era a mesma - conferir o vacuo
    - e duas telas diferentes so somavam ruido. Ficou um: laranja.
    """

    NONE = 0
    WARNING = 1


class RunPhase(Enum):
    """Onde o operador esta na largada de um programa, lido no campo Iso lines.

    Em stand-by o campo mostra codigo irrelevante. Ao carregar o arquivo o
    OSAI pede CLOSE THE DOORS - e o aviso de que o corte vai comecar. Quando
    esse texto sai e o conteudo muda, o programa esta rodando de fato.
    """

    IDLE = "IDLE"        # stand-by
    DOORS = "DOORS"      # "CLOSE THE DOORS" na tela: hora de conferir o vacuo
    RUNNING = "RUNNING"  # texto mudou depois do aviso: programa em execucao


@dataclass(frozen=True)
class Roi:
    """Regiao de interesse em pixels, relativa ao canto superior-esquerdo da JANELA do OSAI.

    Guardar coordenadas relativas a janela (e nao a tela) permite que a janela
    seja movida sem invalidar a configuracao.
    """

    x: int
    y: int
    width: int
    height: int

    def is_valid(self) -> bool:
        """ROI precisa ter area positiva para ser usavel."""
        return self.width > 0 and self.height > 0 and self.x >= 0 and self.y >= 0


@dataclass(frozen=True)
class ToggleGeometry:
    """Onde fica o toggle (pill ON/OFF) EM RELACAO ao rotulo do indicador.

    O rotulo e localizado por template matching em qualquer ponto da tela
    (o menu rola), entao a posicao do toggle so pode ser expressa como um
    deslocamento a partir do rotulo encontrado - nunca como coordenada fixa.
    """

    dx: int
    dy: int
    width: int
    height: int

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0


@dataclass
class IndicatorConfig:
    """Um toggle da tela do OSAI que precisa estar ON durante programas monitorados.

    O requisito atual exige dois: "Vacuum Pump 1" e "Vacuum 1" (nomes exatos
    como aparecem na tela do OSAI). Modelar como lista permite acrescentar
    outros apenas editando o config.json, sem mudanca de codigo.
    """

    name: str
    roi: Roi | None = None  # definido na calibracao (modo posicao fixa)
    # Modo "busca por rotulo" (tolerante a rolagem do menu): quando definido,
    # tem prioridade sobre a ROI fixa.
    toggle: ToggleGeometry | None = None

    @property
    def slug(self) -> str:
        """Identificador para nomes de arquivo de template (ex.: 'vacuum_pump_1')."""
        return self.name.strip().lower().replace(" ", "_")


@dataclass(frozen=True)
class IndicatorReading:
    """Leitura de um indicador em um ciclo de deteccao."""

    state: PumpState
    confidence: float  # score do template matching (0.0 se UNKNOWN)


@dataclass(frozen=True)
class DetectionResult:
    """Resultado de um ciclo completo de deteccao (indicadores + programa)."""

    indicators: dict[str, IndicatorReading]  # chave = nome do indicador
    program_name: str
    timestamp: datetime
    elapsed_ms: float  # tempo total de processamento do ciclo
    run_phase: RunPhase = RunPhase.IDLE  # lido no campo Iso lines


@dataclass(frozen=True)
class AlarmDecision:
    """Saida do Rule Engine para um DetectionResult."""

    is_monitored_program: bool
    offending: tuple[str, ...]  # indicadores confirmados OFF
    unknown: tuple[str, ...]    # indicadores que nao puderam ser lidos
    level: AlertLevel = AlertLevel.NONE
    reason: str = ""  # texto pronto para o popup, montado pelo Rule Engine

    @property
    def should_alarm(self) -> bool:
        """Qualquer nivel diferente de NONE exibe o popup."""
        return self.level is not AlertLevel.NONE


@dataclass
class AppConfig:
    """Configuracao persistida em config.json.

    Mutavel de proposito: a tela de configuracoes edita esta instancia e pede
    ao ConfigService para salvar.
    """

    window_title_hint: str = "OSAI"  # substring do titulo da janela a capturar
    capture_interval_s: float = 1.0  # intervalo entre ciclos de deteccao
    trigger_programs: list[str] = field(default_factory=lambda: ["SINK", "CUTOUT", "BOWL"])
    template_threshold: float = 0.80  # score minimo do template matching
    indicators: list[IndicatorConfig] = field(
        default_factory=lambda: [IndicatorConfig("Vacuum Pump 1"), IndicatorConfig("Vacuum 1")]
    )
    program_roi: Roi | None = None
    alarm_wav: str = ""  # vazio = assets/alarm.wav
    # Som opcional: fabricas sao barulhentas e o PC da CNC pode nao ter
    # alto-falante. Com o som desligado, o alerta visual (popup pulsante)
    # e o unico canal - por isso ele precisa ser forte por si so.
    alarm_sound_enabled: bool = True
    # Depois que o operador clica, o alerta fica quieto por este tempo.
    # 20 min cobre um programa simples; um sink cutout leva 20-35 min. Sem
    # isso o aviso reaparecia a cada troca de severidade (laranja <-> vermelho)
    # e o operador nao conseguia trabalhar.
    alarm_snooze_minutes: float = 20.0

    # -- momento critico (armar/desarmar) ---------------------------------
    # O ponto de risco e lido no campo "Iso lines" do OSAI (ver RunPhase):
    # mais confiavel que o nome do programa, porque todos se chamam
    # <numero>.CNC.
    # Indicador que DEVE estar ON no momento critico. "Vacuum 1" e o mais
    # importante: sem ele a pedra nao esta presa.
    critical_indicator: str = "Vacuum 1"
    # Campo "Iso lines" (canto inferior esquerdo do OSAI): e onde aparece o
    # pedido CLOSE THE DOORS antes do corte. None = recurso desligado.
    iso_roi: Roi | None = None
    close_doors_keyword: str = "CLOSE THE DOOR"  # sem o S: casa singular e plural
    label_threshold: float = 0.75  # score minimo para dar o rotulo como encontrado
    # Idioma do guia de calibracao ("en"/"pt"). E o unico texto bilingue do
    # app: o operador alterna no proprio painel e a escolha fica gravada.
    guide_language: str = "en"
