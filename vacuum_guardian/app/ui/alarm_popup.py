"""Popup de alarme: sempre no topo, impossivel de fechar enquanto a condicao
persistir.

O popup nao decide nada: MainWindow o mostra/esconde conforme AlarmStatus, e
os botoes apenas repassam a intencao do operador ao AlarmController.

DOIS NIVEIS, cores diferentes (requisito do chao de fabrica):
- VERMELHO (CRITICAL): o vacuo esta comprovadamente OFF com o programa
  rodando. Perigo imediato - a pedra pode se soltar.
- LARANJA (WARNING): o indicador nao esta visivel na tela (o menu do OSAI
  rola), entao NAO foi possivel verificar. Nao e a mesma coisa que "esta
  desligado", e por isso nao usa a mesma cor - mas tambem nao pode ficar
  em silencio, porque ninguem conferiu o vacuo.

Por que o fundo PULSA: o som e opcional (fabrica barulhenta, PC da CNC muitas
vezes sem alto-falante). Sem audio, um retangulo estatico se perde na visao
periferica de quem esta olhando para a peca; a alternancia de tom a cada
~700 ms e captada pela visao periferica e devolve a atencao a tela.
O piscar e lento de proposito - piscadas rapidas (>3 Hz) sao desconfortaveis
e podem ser um gatilho fotossensivel.

Todo texto visivel ao operador esta em ingles (idioma de operacao da fabrica).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide2.QtCore import Qt, QTimer
from PySide2.QtGui import QCloseEvent, QFont, QGuiApplication
from PySide2.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..models import AlertLevel

# Paletas por severidade: (tom claro, tom escuro, cor do texto dos botoes).
_PALETTE = {
    AlertLevel.CRITICAL: ("#d10023", "#7a0016", "#b00020"),
    AlertLevel.WARNING: ("#e07000", "#8a4500", "#8a4500"),
}
_TITLES = {
    AlertLevel.CRITICAL: "VACUUM IS OFF!",
    AlertLevel.WARNING: "CANNOT VERIFY VACUUM",
}
_PULSE_MS = 700

# A JANELA e proporcional a tela: o alerta precisa dominar o monitor, seja
# Full HD ou 4K. Nao e tela cheia de proposito - o operador ainda ve o OSAI
# atras e entende o contexto do alarme.
_SCREEN_FRACTION_W = 0.62
_SCREEN_FRACTION_H = 0.52
_MIN_W, _MIN_H = 900, 540

# Ja as FONTES sao fixas em pontos. Ponto tipografico e unidade fisica
# (1/72 pol) e o Qt ja o converte conforme o DPI do monitor: 44pt tem o mesmo
# tamanho fisico em Full HD e em 4K. Escalar pt por pixels contaria a escala
# duas vezes e encolheria o texto em telas de alto DPI.
_TITLE_PT = 44
_DETAIL_PT = 22
_BUTTON_PT = 17


class AlarmPopup(QDialog):
    def __init__(self, on_acknowledge: Callable[[], None], on_silence: Callable[[], None]) -> None:
        super().__init__()
        self._locked = True  # enquanto True, o X da janela e Esc sao ignorados
        # Publicos de proposito: MainWindow os substitui ao reconstruir o engine.
        self._on_acknowledge = on_acknowledge
        self._on_silence = on_silence
        self._level = AlertLevel.CRITICAL

        self.setWindowTitle("ALARM - VACUUM GUARDIAN")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowStaysOnTopHint
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint  # titulo sem botao de fechar
        )

        self._title = QLabel(_TITLES[AlertLevel.CRITICAL])
        self._title.setFont(QFont("Segoe UI", _TITLE_PT, QFont.Black))
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)

        self._detail = QLabel("")
        self._detail.setFont(QFont("Segoe UI", _DETAIL_PT))
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setWordWrap(True)

        # Lambdas resolvem o atributo NO CLIQUE - permite a MainWindow trocar
        # os callbacks quando o engine e reconstruido (recalibracao).
        ack = QPushButton("Acknowledge")
        ack.clicked.connect(lambda: self._on_acknowledge())
        self._mute_button = QPushButton("Silence")
        self._mute_button.clicked.connect(lambda: self._on_silence())

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(ack)
        buttons.addSpacing(16)
        buttons.addWidget(self._mute_button)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 56, 56, 56)
        layout.addWidget(self._title)
        layout.addSpacing(12)
        layout.addWidget(self._detail)
        layout.addSpacing(24)
        layout.addLayout(buttons)

        # Pulsacao do fundo: so roda enquanto o popup esta visivel.
        self._bright = True
        self._pulse = QTimer(self)
        self._pulse.setInterval(_PULSE_MS)
        self._pulse.timeout.connect(self._toggle_shade)
        self._apply_shade(bright=True)

    # -- aparencia ---------------------------------------------------------

    def _apply_shade(self, bright: bool) -> None:
        light, dark, button_text = _PALETTE[self._level]
        background = light if bright else dark
        self.setStyleSheet(
            f"QDialog {{ background-color: {background}; }}"
            "QLabel { color: white; }"
            f"QPushButton {{ background-color: white; color: {button_text};"
            f"  font-weight: bold; padding: 18px 44px;"
            f"  border-radius: 6px; font-size: {_BUTTON_PT}pt; }}"
            "QPushButton:hover { background-color: #ffeedd; }"
        )

    def _resize_to_screen(self) -> None:
        """Dimensiona e centraliza o popup conforme a tela onde ele vai aparecer.

        Recalculado a cada exibicao: o operador pode ter mudado a resolucao ou
        o app pode ter migrado de monitor.
        """
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is None:
            width, height = _MIN_W, _MIN_H
        else:
            width = max(_MIN_W, int(available.width() * _SCREEN_FRACTION_W))
            height = max(_MIN_H, int(available.height() * _SCREEN_FRACTION_H))
            # Nunca maior que a area util (protege telas pequenas).
            width = min(width, available.width())
            height = min(height, available.height())

        self.resize(width, height)
        if available is not None:
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())

    def _toggle_shade(self) -> None:
        self._bright = not self._bright
        self._apply_shade(self._bright)

    # -- ciclo de vida -----------------------------------------------------

    def show_alarm(
        self,
        reason: str,
        program: str,
        sound_enabled: bool = True,
        level: AlertLevel = AlertLevel.CRITICAL,
    ) -> None:
        """Exibe (ou atualiza) o popup em primeiro plano.

        `sound_enabled=False` esconde o botao "Silence": sem som, silenciar
        nao significa nada e so confundiria o operador.
        """
        if level not in _PALETTE:
            level = AlertLevel.CRITICAL
        level_changed = level is not self._level
        self._level = level
        self._title.setText(_TITLES[level])
        self._detail.setText(f"Program: {program or '?'}\n{reason}")
        self._mute_button.setVisible(sound_enabled)
        if not self.isVisible():
            self._resize_to_screen()
            self.showNormal()
            self._bright = True
            self._apply_shade(bright=True)
            self._pulse.start()
        elif level_changed:
            # Escalada laranja -> vermelho com o popup ja aberto: repinta na
            # hora, sem esperar o proximo ciclo da pulsacao.
            self._bright = True
            self._apply_shade(bright=True)
        self.raise_()
        self.activateWindow()

    def dismiss(self) -> None:
        """Chamado pela MainWindow quando a condicao cessa - unico caminho de saida."""
        self._pulse.stop()
        self._locked = False
        self.hide()
        self._locked = True

    # Bloqueia Alt+F4/Esc enquanto o alarme estiver ativo.
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._locked:
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self) -> None:  # Esc
        if not self._locked:
            super().reject()
