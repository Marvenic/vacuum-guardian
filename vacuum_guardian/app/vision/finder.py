"""Leitura de um indicador que PODE MUDAR DE LUGAR na tela.

Por que existe: o menu "Favorite Softkey" do OSAI tem rolagem, entao a linha
do "Vacuum 1" nao fica numa posicao fixa - as vezes nem esta visivel. Uma ROI
fixa (TemplateMatcher) leria o toggle de OUTRA funcao apos o operador rolar a
lista, o que seria pior que nao ler nada.

Estrategia em dois passos:
1. ROTULO: procura o texto "Vacuum 1" (imagem-template) em TODO o frame via
   matchTemplate. Isso devolve onde a linha esta agora - ou revela que ela
   nao esta na tela (score abaixo do limiar -> NOT_VISIBLE).
2. TOGGLE: recorta o pill num deslocamento fixo A PARTIR do rotulo achado e
   classifica ON/OFF por COR.

Por que cor e nao template no toggle: os dois estados diferem por area de
azul (ON = pill preenchido; OFF = pill branco com um circulo pequeno). Isso
e um sinal forte e continuo, enquanto template matching entre duas imagens
tao parecidas empata com facilidade - e um empate viraria "ON" (falso
negativo perigoso: diria que ha vacuo quando nao ha).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from ..models import PumpState, ToggleGeometry

# Faixa de azul do tema do OSAI em HSV (OpenCV: H em 0..179).
_BLUE_LOW = np.array([95, 80, 60], dtype=np.uint8)
_BLUE_HIGH = np.array([135, 255, 255], dtype=np.uint8)

# Janela da busca rapida em torno da ultima posicao conhecida do rotulo.
# Vertical generosa: o menu do OSAI rola no eixo Y, entao algumas linhas de
# deslocamento ainda caem dentro da janela e evitam a varredura completa.
_MARGIN_X = 80
_MARGIN_Y = 160

# Usados apenas quando nao ha amostras ON/OFF calibradas.
_DEFAULT_MIDPOINT = 0.40
_DEFAULT_MARGIN = 0.10


def blue_fraction(bgr: np.ndarray) -> float:
    """Fracao [0..1] de pixels azuis do recorte - o sinal que separa ON de OFF."""
    if bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _BLUE_LOW, _BLUE_HIGH)
    return float(np.count_nonzero(mask)) / float(mask.size)


@dataclass(frozen=True)
class FinderResult:
    state: PumpState
    confidence: float   # score do rotulo (0.0 se nao encontrado)
    blue: float = 0.0   # fracao de azul medida no toggle (diagnostico)


class IndicatorFinder:
    """Localiza o rotulo de um indicador e le o toggle ao lado dele."""

    def __init__(
        self,
        label_path: Path,
        toggle: ToggleGeometry | None,
        threshold: float,
        on_sample_path: Path | None = None,
        off_sample_path: Path | None = None,
    ) -> None:
        self._label = self._load(label_path)
        self._toggle = toggle
        self._threshold = threshold
        # Ultima posicao onde o rotulo foi visto (cache da busca rapida).
        self._last: tuple[int, int] | None = None
        # Limiar de cor derivado das AMOSTRAS reais da maquina: mais confiavel
        # que um numero fixo, porque absorve o tema/contraste daquela tela.
        on_sample = self._load(on_sample_path) if on_sample_path else None
        off_sample = self._load(off_sample_path) if off_sample_path else None
        if on_sample is not None and off_sample is not None:
            on_blue = blue_fraction(on_sample)
            off_blue = blue_fraction(off_sample)
            self._midpoint = (on_blue + off_blue) / 2.0
            # Zona morta proporcional a separacao entre os dois estados: se as
            # amostras forem parecidas demais, quase tudo vira UNKNOWN (e o
            # operador e avisado) em vez de gerar leitura errada.
            self._margin = abs(on_blue - off_blue) * 0.15
            self._inverted = on_blue < off_blue  # tema claro/escuro invertido
            logger.info(
                "Toggle colour calibrated: ON={:.2f} OFF={:.2f} midpoint={:.2f}",
                on_blue, off_blue, self._midpoint,
            )
        else:
            self._midpoint = _DEFAULT_MIDPOINT
            self._margin = _DEFAULT_MARGIN
            self._inverted = False

    @property
    def ready(self) -> bool:
        """Precisa do template do rotulo E da geometria do toggle."""
        return self._label is not None and self._toggle is not None and self._toggle.is_valid()

    @staticmethod
    def _load(path: Path | None) -> np.ndarray | None:
        if path is None or not path.exists():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            logger.error("Failed to read image: {}", path)
        return image

    def _classify(self, toggle_bgr: np.ndarray) -> tuple[PumpState, float]:
        blue = blue_fraction(toggle_bgr)
        if abs(blue - self._midpoint) < self._margin:
            return PumpState.UNKNOWN, blue  # ambiguo: nunca chutar
        is_on = blue > self._midpoint
        if self._inverted:
            is_on = not is_on
        return (PumpState.ON if is_on else PumpState.OFF), blue

    @staticmethod
    def _best_match(image: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int]]:
        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        return float(score), (int(location[0]), int(location[1]))

    def _locate(self, frame: np.ndarray) -> tuple[int, int, float] | None:
        """Acha o rotulo, tentando primeiro perto de onde ele estava.

        Varrer 1920x1080 custa ~120 ms POR INDICADOR, POR CICLO - o suficiente
        para estourar o intervalo de captura no PC da CNC e deixar o app
        arrastado depois de calibrado. Entre dois ciclos o item quase nunca sai
        do lugar, entao a busca comeca numa janela ao redor da ultima posicao
        (~10 ms). So quando isso falha e que varre a tela toda, o que preserva
        a tolerancia a rolagem do menu.
        """
        label_h, label_w = self._label.shape[:2]
        frame_h, frame_w = frame.shape[:2]
        if frame_h < label_h or frame_w < label_w:
            return None

        if self._last is not None:
            last_x, last_y = self._last
            x0 = max(0, last_x - _MARGIN_X)
            y0 = max(0, last_y - _MARGIN_Y)
            x1 = min(frame_w, last_x + label_w + _MARGIN_X)
            y1 = min(frame_h, last_y + label_h + _MARGIN_Y)
            if x1 - x0 >= label_w and y1 - y0 >= label_h:
                score, location = self._best_match(frame[y0:y1, x0:x1], self._label)
                if score >= self._threshold:
                    self._last = (x0 + location[0], y0 + location[1])
                    return self._last[0], self._last[1], score

        score, location = self._best_match(frame, self._label)
        if score < self._threshold:
            self._last = None  # sumiu da tela: da proxima vez varre tudo
            return None
        self._last = location
        return location[0], location[1], score

    def read(self, frame: np.ndarray) -> FinderResult:
        """Procura o rotulo na tela e devolve o estado do toggle ao lado dele."""
        if self._label is None or self._toggle is None:
            return FinderResult(PumpState.NOT_VISIBLE, 0.0)

        frame_h, frame_w = frame.shape[:2]
        found = self._locate(frame)
        if found is None:
            # O rotulo nao esta na tela (menu rolado) - estado NAO verificavel.
            return FinderResult(PumpState.NOT_VISIBLE, 0.0)
        located_x, located_y, score = found

        x = located_x + self._toggle.dx
        y = located_y + self._toggle.dy
        if x < 0 or y < 0 or x + self._toggle.width > frame_w or y + self._toggle.height > frame_h:
            return FinderResult(PumpState.NOT_VISIBLE, float(score))

        crop = frame[y : y + self._toggle.height, x : x + self._toggle.width]
        state, blue = self._classify(crop)
        return FinderResult(state, float(score), blue)
