"""Popup de alarme: sempre no topo, ate o operador agir.

O popup nao decide nada: MainWindow o mostra/esconde conforme AlarmStatus, e
os botoes repassam a intencao do operador ao AlarmController.

POR QUE O BOTAO FECHA O AVISO: ele cobre a tela do OSAI. Mantendo-o ali
ate a condicao cessar, o operador ficava impedido de mexer na maquina para
RESOLVER a propria condicao do alarme - o aviso virava o obstaculo. Agora
Acknowledge tira o aviso da frente e a acao vai para
logs/alarm_actions.csv: sem o popup na tela, esse registro e a unica prova de
que alguem viu. Depois do clique o alarme fica silenciado por 5 minutos; o
painel e o icone da bandeja continuam mostrando o estado real nesse periodo.

UM NIVEL SO (laranja). Antes havia vermelho ("esta desligado") e laranja
("nao consegui verificar"); a acao do operador era a mesma nos dois casos -
ir conferir o vacuo -, entao duas telas so somavam ruido. O motivo especifico
continua escrito no corpo do aviso.

UM BOTAO SO: Acknowledge. Ele registra, cala o som e silencia por 5 minutos -
tempo de ir ate a maquina sem o aviso voltando a cada segundo.

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
from PySide2.QtGui import QColor, QCloseEvent, QFont, QGuiApplication, QPalette
from PySide2.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

# Laranja: o unico nivel. (tom claro, tom escuro, cor do texto do botao)
_LIGHT, _DARK, _BUTTON_TEXT = "#e07000", "#8a4500", "#8a4500"
_TITLE = "CHECK THE VACUUM"
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
    def __init__(self, on_acknowledge: Callable[[], None]) -> None:
        super().__init__()
        self._locked = True  # enquanto True, o X da janela e Esc sao ignorados
        # Publico de proposito: MainWindow o substitui ao reconstruir o engine.
        self._on_acknowledge = on_acknowledge

        self.setWindowTitle("ALARM - VACUUM GUARDIAN")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowStaysOnTopHint
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint  # titulo sem botao de fechar
        )

        self._title = QLabel(_TITLE)
        self._title.setFont(QFont("Segoe UI", _TITLE_PT, QFont.Black))
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)

        self._detail = QLabel("")
        self._detail.setFont(QFont("Segoe UI", _DETAIL_PT))
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setWordWrap(True)

        # Lambdas resolvem o atributo NO CLIQUE - permite a MainWindow trocar
        # os callbacks quando o engine e reconstruido (recalibracao).
        # O clique fecha o aviso IMEDIATAMENTE, sem esperar o proximo ciclo
        # (ate 1 s de espera passa a sensacao de botao morto - foi o relato).
        # Quem manda no estado continua sendo o AlarmController; aqui so
        # antecipamos o que ele decidiria no ciclo seguinte.
        ack = QPushButton("Acknowledge")
        ack.clicked.connect(lambda: self._act(self._on_acknowledge))

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(ack)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 56, 56, 56)
        layout.addWidget(self._title)
        layout.addSpacing(12)
        layout.addWidget(self._detail)
        layout.addSpacing(24)
        layout.addLayout(buttons)

        # Pulsacao do fundo: so roda enquanto o popup esta visivel.
        self.setAutoFillBackground(True)  # necessario para a paleta pintar o fundo
        self._bright = True
        self._pulse = QTimer(self)
        self._pulse.setInterval(_PULSE_MS)
        self._pulse.timeout.connect(self._toggle_shade)
        self._apply_button_style()
        self._apply_shade(bright=True)

    # -- aparencia ---------------------------------------------------------

    def _apply_shade(self, bright: bool) -> None:
        """Troca so a cor de fundo - roda a cada 700 ms, tem de ser barato.

        Antes isto chamava setStyleSheet(), que re-polia a arvore inteira de
        widgets duas vezes por segundo. Numa CNC modesta, esse trabalho
        continuo na thread da UI competia justamente com os cliques do
        operador no alarme. A paleta troca a cor sem reprocessar estilo.
        """
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(_LIGHT if bright else _DARK))
        self.setPalette(palette)

    def _apply_button_style(self) -> None:
        """Estilo fixo do botao - definido uma vez, nao a cada pulso.

        Nao define o fundo do QDialog de proposito: quem cuida disso e a
        paleta em _apply_shade. Uma folha de estilo com background-color
        venceria a paleta e mataria a pulsacao.
        """
        self.setStyleSheet(
            "QLabel { color: white; }"
            f"QPushButton {{ background-color: white; color: {_BUTTON_TEXT};"
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

    def show_alarm(self, reason: str, program: str, sound_enabled: bool = True) -> None:
        """Exibe (ou atualiza) o aviso em primeiro plano.

        `sound_enabled` nao muda mais os botoes (ha um so, que serve para os
        dois casos); fica no parametro porque a MainWindow ja o passa e o
        texto do botao pode voltar a depender dele.
        """
        # So mexe nos widgets se o texto realmente mudou: este metodo e
        # chamado a CADA ciclo enquanto o alarme dura.
        detail = "Program: {}\n{}".format(program or "?", reason)
        if detail != self._detail.text():
            self._detail.setText(detail)

        if not self.isVisible():
            self._resize_to_screen()
            self.showNormal()
            self._bright = True
            self._apply_shade(bright=True)
            self._pulse.start()
            # Trazer para a frente APENAS ao aparecer. Chamar raise_ a cada
            # ciclo roubava o foco do proprio operador: o clique no botao se
            # perdia entre press e release. Era o "alarme travado" da CNC.
            self.raise_()
            self.activateWindow()

    def _act(self, callback) -> None:  # type: ignore[no-untyped-def]
        """Repassa a intencao ao controlador e tira o aviso da frente.

        O popup cobre a tela do OSAI: enquanto ele estiver ali o operador nao
        consegue mexer na maquina para resolver a propria condicao do alarme.
        """
        callback()
        self.dismiss()

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
