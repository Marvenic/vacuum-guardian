"""Janela de calibracao: assistente passo a passo sobre um frame do OSAI.

A versao anterior mostrava sete botoes de uma vez, em duas fileiras de modos
diferentes ("Fixed position" e "Scroll-proof"), e nada indicava a ordem. Era
o operador que precisava saber a sequencia - e nao sabia. Agora:

- o CalibrationGuide conduz: um passo por vez, com UM botao de acao;
- esta janela apenas EXECUTA a acao pedida (recorta, mede, grava o PNG);
- os botoes antigos continuam existindo em "Advanced", recolhidos, para os
  casos de posicao fixa e para quem precisar refazer algo fora de ordem.

A outra fonte de confusao era ter de FECHAR e REABRIR a janela para capturar
as amostras ON/OFF, porque o frame era congelado na abertura. Agora a janela
se esconde por um instante e tira uma foto nova (`_grab_frame`), entao o
operador liga/desliga o vacuo e captura sem sair daqui.

Dois modos de calibrar um indicador:
1. BUSCA POR ROTULO (o que o assistente ensina): guarda a imagem do texto e a
   posicao do toggle RELATIVA a ele, entao sobrevive a rolagem do menu.
2. POSICAO FIXA (legado, em "Advanced"): ROI + templates ON/OFF.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from PySide2.QtCore import QPoint, QRect, Qt
from PySide2.QtGui import QImage, QMouseEvent, QPixmap
from PySide2.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import AppConfig, Roi, ToggleGeometry
from .calibration_guide import (
    ACT_DIALOG,
    ACT_PROGRAM,
    REQ_LABEL,
    REQ_OFF,
    REQ_ON,
    REQ_TOGGLE,
    CalibrationGuide,
)

_PROGRAM_TARGET = "Program name"
_DIALOG_TARGET = "Confirmation dialogs (area)"

# Tempo que a janela fica escondida antes de fotografar a tela. Precisa ser
# suficiente para o Windows redesenhar o que estava por baixo.
_HIDE_BEFORE_GRAB_S = 0.45
# Espera entre as duas tentativas de captura (ver _refresh_frame).
_RETRY_WAIT_S = 0.25


class _FrameLabel(QLabel):
    """QLabel com selecao por rubber-band; guarda o retangulo em coords do widget."""

    def __init__(self) -> None:
        super().__init__()
        self._band = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = QPoint()
        self.selection: QRect | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Qt5: QMouseEvent.pos() (QPoint). No Qt6 seria event.position().toPoint().
        self._origin = event.pos()
        self._band.setGeometry(QRect(self._origin, self._origin))
        self._band.show()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._band.isVisible():
            self._band.setGeometry(QRect(self._origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.selection = self._band.geometry()

    def clear_selection(self) -> None:
        self.selection = None
        self._band.hide()


class RoiSelectorDialog(QDialog):
    """Assistente de calibracao sobre um frame capturado do OSAI."""

    def __init__(
        self,
        frame_bgr: np.ndarray,
        config: AppConfig,
        templates_dir: Path,
        on_language_changed: Callable[[str], None] | None = None,
        grab_frame: Callable[[], np.ndarray] | None = None,
    ) -> None:
        super().__init__()
        self._frame = frame_bgr
        self._config = config
        self._templates_dir = templates_dir
        self._grab_frame = grab_frame
        self.changed = False  # MainWindow reconstroi o engine se True

        self.setWindowTitle("Calibration - Vacuum Guardian")

        self._label = _FrameLabel()
        self._scale = 1.0
        self._show_frame(frame_bgr)

        scroll = QScrollArea()
        scroll.setWidget(self._label)

        self._target = QComboBox()
        self._target.addItem(_PROGRAM_TARGET)
        self._target.addItem(_DIALOG_TARGET)
        for ind in config.indicators:
            self._target.addItem(ind.name)
        self._select_target(config.critical_indicator)

        refresh = QPushButton("Refresh screenshot")
        refresh.setToolTip("Hides this window for a moment and takes a new picture")
        refresh.clicked.connect(self._refresh_frame)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(QLabel("Target:"))
        top.addWidget(self._target, 1)
        top.addWidget(refresh)
        top.addWidget(done)

        # Modo legado, recolhido: presente para quem precisa, fora do caminho
        # de quem esta apenas seguindo o assistente.
        self._advanced = QWidget()
        actions = QGridLayout(self._advanced)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(QLabel("<b>Fixed position</b>"), 0, 0)
        actions.addWidget(self._button("Save ROI for target", self._save_roi), 0, 1)
        actions.addWidget(self._button("Crop = ON template", lambda: self._save_template("on")), 0, 2)
        actions.addWidget(self._button("Crop = OFF template", lambda: self._save_template("off")), 0, 3)
        actions.addWidget(QLabel("<b>Scroll-proof</b>"), 1, 0)
        actions.addWidget(self._button("Set label", self._save_label), 1, 1)
        actions.addWidget(self._button("Set toggle area", self._save_toggle_area), 1, 2)
        samples = QHBoxLayout()
        samples.addWidget(self._button("ON sample", lambda: self._capture_sample("on")))
        samples.addWidget(self._button("OFF sample", lambda: self._capture_sample("off")))
        actions.addLayout(samples, 1, 3)
        self._advanced.setVisible(False)

        advanced_toggle = QCheckBox("Advanced (manual buttons)")
        advanced_toggle.toggled.connect(self._advanced.setVisible)

        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(scroll, 1)
        left.addWidget(advanced_toggle)
        left.addWidget(self._advanced)

        self._guide = CalibrationGuide(
            config, templates_dir, self, on_language_changed, self._run_step
        )
        # Ao mudar de passo, a selecao anterior nao vale mais - deixa-la na tela
        # convidaria a capturar a area errada no passo seguinte.
        self._guide.step_changed.connect(self._label.clear_selection)
        # O combo "Target:" acompanha o passo: o operador ve, sem precisar
        # mexer, qual indicador esta sendo calibrado agora.
        self._guide.step_changed.connect(self._follow_guide_target)
        self._follow_guide_target()

        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addWidget(self._guide)
        self.resize(1280, 780)

    # -- infraestrutura ----------------------------------------------------

    @staticmethod
    def _button(text: str, slot) -> QPushButton:  # type: ignore[no-untyped-def]
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _follow_guide_target(self) -> None:
        """Sincroniza o combo com o indicador do passo atual do assistente."""
        guide = getattr(self, "_guide", None)
        if guide is None:
            return
        name = guide.current_step().indicator
        if name:
            self._select_target(name)

    def _select_target(self, name: str) -> None:
        index = self._target.findText(name)
        if index >= 0:
            self._target.setCurrentIndex(index)

    def _show_frame(self, frame_bgr: np.ndarray) -> None:
        """Exibe o frame escalado para caber na tela, guardando a escala usada."""
        self._frame = frame_bgr
        height, width = frame_bgr.shape[:2]
        self._scale = min(1.0, 1200 / width, 800 / height)
        display = (
            cv2.resize(frame_bgr, None, fx=self._scale, fy=self._scale)
            if self._scale < 1.0
            else frame_bgr
        )
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888
        ).copy()  # copy(): o buffer numpy sai de escopo, o QImage nao pode apontar para ele
        self._label.setPixmap(QPixmap.fromImage(image))
        self._label.setFixedSize(rgb.shape[1], rgb.shape[0])
        self._label.clear_selection()

    def _refresh_frame(self) -> bool:
        """Esconde a janela, fotografa a tela de novo e reaparece.

        Sem isso o operador precisaria fechar e reabrir a calibracao a cada
        amostra ON/OFF - a maior fonte de confusao do fluxo anterior.
        """
        if self._grab_frame is None:
            return False
        # MINIMIZAR, nunca hide(): esta janela roda dentro de exec_(), e
        # hide() encerra o loop modal na hora. O exec_() retornava no meio da
        # captura, o Done nunca era processado e sobrava um dialogo visivel e
        # ainda modal - com o Qt mantendo a janela principal DESABILITADA no
        # Windows. Era esse o "congelou e nao deixa nem fechar".
        # Minimizar tira a janela da foto sem mexer no estado modal.
        self.showMinimized()
        QApplication.processEvents()
        time.sleep(_HIDE_BEFORE_GRAB_S)
        frame, error = None, ""
        # Duas tentativas: a primeira falha costuma ser um handle GDI morto
        # (esconder/reexibir a janela invalida o contexto), e o ScreenCapture
        # recria o grabber por baixo - a segunda entao passa.
        for attempt in (1, 2):
            try:
                frame = self._grab_frame()
                break
            except Exception as exc:  # captura nunca pode derrubar a calibracao
                logger.exception("Screenshot attempt {} failed", attempt)
                error = str(exc)
                time.sleep(_RETRY_WAIT_S)
        self.showNormal()  # par do showMinimized acima
        self.raise_()
        self.activateWindow()
        if frame is None:
            # O detalhe tecnico vai para "Show details": o operador ve uma frase
            # acionavel, e quem for diagnosticar ainda tem a mensagem do erro.
            box = QMessageBox(
                QMessageBox.Warning,
                "Calibration",
                "Could not take a new screenshot.",
                QMessageBox.Ok,
                self,
            )
            box.setInformativeText(
                "Press the button again, or use 'Refresh screenshot'."
            )
            if error:
                box.setDetailedText(error)
            box.exec_()
            return False
        self._show_frame(frame)
        return True

    # -- ponte com o assistente -------------------------------------------

    def _run_step(self, action: str, indicator: str = "") -> bool:
        """Executa a acao do passo atual. Retorna True se capturou com sucesso.

        `indicator` vem do proprio passo do assistente. Antes usava-se sempre
        o indicador critico: com dois vacuos, o operador seguia instrucoes do
        Vacuum Pump 1 e a captura era gravada no Vacuum 1 - que e a razao de o
        Vacuum Pump 1 continuar "sem leitura" depois de calibrado.
        """
        target = indicator or self._config.critical_indicator
        if action in (REQ_LABEL, REQ_TOGGLE):
            # Passos de desenho: o operador ja arrastou sobre a foto atual.
            self._select_target(target)
            return self._save_label() if action == REQ_LABEL else self._save_toggle_area()
        if action in (REQ_ON, REQ_OFF):
            # Passos de amostra: o estado na tela mudou, entao precisa de foto nova.
            self._select_target(target)
            if not self._refresh_frame():
                return False
            return self._capture_sample("on" if action == REQ_ON else "off")
        if action == ACT_DIALOG:
            self._select_target(_DIALOG_TARGET)
            return self._save_roi()
        if action == ACT_PROGRAM:
            self._select_target(_PROGRAM_TARGET)
            return self._save_roi()
        return False

    def _mark_changed(self) -> None:
        """Marca alteracao e atualiza o progresso mostrado no assistente."""
        self.changed = True
        guide = getattr(self, "_guide", None)
        if guide is not None:
            guide.refresh()

    # -- helpers -----------------------------------------------------------

    def _selected_roi(self) -> Roi | None:
        """Converte a selecao (coords do widget escalado) para pixels reais do frame."""
        sel = self._label.selection
        if sel is None or sel.width() < 3 or sel.height() < 3:
            QMessageBox.warning(self, "Calibration", "Drag a rectangle over the image first.")
            return None
        inv = 1.0 / self._scale
        return Roi(
            x=int(sel.x() * inv),
            y=int(sel.y() * inv),
            width=int(sel.width() * inv),
            height=int(sel.height() * inv),
        )

    def _current_indicator(self):  # type: ignore[no-untyped-def]
        """Indicador selecionado, ou None se o alvo nao for um indicador."""
        target = self._target.currentText()
        if target in (_PROGRAM_TARGET, _DIALOG_TARGET):
            QMessageBox.warning(self, "Calibration", "Select an indicator first.")
            return None
        return next((i for i in self._config.indicators if i.name == target), None)

    def _crop(self, roi: Roi) -> np.ndarray | None:
        crop = self._frame[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
        if crop.size == 0:
            QMessageBox.warning(self, "Calibration", "ROI is outside the frame bounds.")
            return None
        return crop

    def _locate_label(self, slug: str) -> tuple[int, int] | None:
        """Acha o rotulo salvo dentro do frame atual (base do deslocamento do toggle)."""
        path = self._templates_dir / f"{slug}_label.png"
        template = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if template is None:
            QMessageBox.warning(self, "Calibration", "Capture the name first.")
            return None
        if (
            self._frame.shape[0] < template.shape[0]
            or self._frame.shape[1] < template.shape[1]
        ):
            return None
        result = cv2.matchTemplate(self._frame, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < self._config.label_threshold:
            QMessageBox.warning(
                self,
                "Calibration",
                f"The indicator is not visible on this screenshot (score {score:.2f}).\n"
                "Scroll the OSAI menu so it shows, then try again.",
            )
            return None
        return int(location[0]), int(location[1])

    # -- modo posicao fixa (Advanced) --------------------------------------

    def _save_roi(self) -> bool:
        roi = self._selected_roi()
        if roi is None:
            return False
        target = self._target.currentText()
        if target == _PROGRAM_TARGET:
            self._config.program_roi = roi
        elif target == _DIALOG_TARGET:
            self._config.dialog_roi = roi
        else:
            for ind in self._config.indicators:
                if ind.name == target:
                    ind.roi = roi
        self._mark_changed()
        logger.info("ROI for '{}' set: {}", target, roi)
        return True

    def _save_template(self, state: str) -> bool:
        """Recorta a ROI ATUAL do indicador no frame e grava como template on/off."""
        indicator = self._current_indicator()
        if indicator is None:
            return False
        roi = indicator.roi or self._selected_roi()
        if roi is None:
            return False
        crop = self._crop(roi)
        if crop is None:
            return False
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        path = self._templates_dir / f"{indicator.slug}_{state}.png"
        cv2.imwrite(str(path), crop)
        self._mark_changed()
        logger.info("Template saved: {}", path)
        return True

    # -- modo busca por rotulo (assistente) --------------------------------

    def _save_label(self) -> bool:
        """Guarda a imagem do texto do indicador (ex.: 'Vacuum 1')."""
        indicator = self._current_indicator()
        if indicator is None:
            return False
        roi = self._selected_roi()
        if roi is None:
            return False
        crop = self._crop(roi)
        if crop is None:
            return False
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        path = self._templates_dir / f"{indicator.slug}_label.png"
        cv2.imwrite(str(path), crop)
        self._mark_changed()
        logger.info("Label template saved: {} ({})", path, roi)
        return True

    def _save_toggle_area(self) -> bool:
        """Guarda o toggle como deslocamento a partir do rotulo."""
        indicator = self._current_indicator()
        if indicator is None:
            return False
        roi = self._selected_roi()
        if roi is None:
            return False
        origin = self._locate_label(indicator.slug)
        if origin is None:
            return False
        indicator.toggle = ToggleGeometry(
            dx=roi.x - origin[0],
            dy=roi.y - origin[1],
            width=roi.width,
            height=roi.height,
        )
        self._mark_changed()
        logger.info("Toggle geometry for '{}': {}", indicator.name, indicator.toggle)
        return True

    def _capture_sample(self, state: str) -> bool:
        """Amostra de cor do toggle no estado atual (sem arrastar nada).

        Localiza o rotulo no frame e recorta o toggle pela geometria salva -
        assim a amostra sai exatamente da area que sera lida em operacao.
        """
        indicator = self._current_indicator()
        if indicator is None:
            return False
        if indicator.toggle is None:
            QMessageBox.warning(self, "Calibration", "Capture the ON/OFF button first.")
            return False
        origin = self._locate_label(indicator.slug)
        if origin is None:
            return False
        roi = Roi(
            x=origin[0] + indicator.toggle.dx,
            y=origin[1] + indicator.toggle.dy,
            width=indicator.toggle.width,
            height=indicator.toggle.height,
        )
        crop = self._crop(roi)
        if crop is None:
            return False
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        path = self._templates_dir / f"{indicator.slug}_toggle_{state}.png"
        cv2.imwrite(str(path), crop)
        self._mark_changed()
        logger.info("Toggle {} sample saved: {}", state.upper(), path)
        return True
