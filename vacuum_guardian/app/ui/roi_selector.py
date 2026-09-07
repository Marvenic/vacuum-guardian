"""Calibration window: a step-by-step wizard over a frame of the OSAI screen.

The previous version showed seven buttons at once, in two rows of different
modes ("Fixed position" and "Scroll-proof"), with nothing to say in which
order. The operator had to know the sequence - and did not. Now:

- CalibrationGuide leads: one step at a time, with ONE action button;
- this window only EXECUTES the requested action (crop, measure, write PNG);
- the old buttons still exist under "Advanced", collapsed, for fixed-position
  cases and for redoing something out of order.

The other source of confusion was having to CLOSE and REOPEN the window to
capture the ON/OFF samples, because the frame was frozen on opening. Now the
window steps aside for a moment and takes a fresh picture (`_grab_frame`), so
the operator toggles the vacuum and captures without leaving.

Two ways to calibrate an indicator:
1. LABEL SEARCH (what the wizard teaches): stores the image of the text and
   the toggle position RELATIVE to it, so it survives menu scrolling.
2. FIXED POSITION (legacy, under "Advanced"): ROI + ON/OFF templates.
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
    ACT_PROGRAM,
    REQ_ISO,
    REQ_LABEL,
    REQ_OFF,
    REQ_ON,
    REQ_TOGGLE,
    CalibrationGuide,
)

_PROGRAM_TARGET = "Program name"
_ISO_TARGET = "Iso lines (area)"

# How long the window stays out of the way before the screenshot. Long
# enough for Windows to repaint whatever was underneath.
_HIDE_BEFORE_GRAB_S = 0.45
# Wait between the two capture attempts (see _refresh_frame).
_RETRY_WAIT_S = 0.25


class _FrameLabel(QLabel):
    """QLabel with rubber-band selection; keeps the rect in widget coordinates."""

    def __init__(self) -> None:
        super().__init__()
        self._band = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = QPoint()
        self.selection: QRect | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Qt5: QMouseEvent.pos() (QPoint). On Qt6 it would be event.position().
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
    """Calibration wizard over a captured frame of the OSAI screen."""

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
        self.changed = False  # MainWindow rebuilds the engine when True

        self.setWindowTitle("Calibration - Vacuum Guardian")

        self._label = _FrameLabel()
        self._scale = 1.0
        self._show_frame(frame_bgr)

        scroll = QScrollArea()
        scroll.setWidget(self._label)

        self._target = QComboBox()
        self._target.addItem(_PROGRAM_TARGET)
        self._target.addItem(_ISO_TARGET)
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

        # Legacy mode, collapsed: there for those who need it, out of the way
        # of anyone simply following the wizard.
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
        # On a step change the previous selection is stale - leaving it on screen
        # would invite capturing the wrong area on the next step.
        self._guide.step_changed.connect(self._label.clear_selection)
        # The "Target:" combo follows the step, so the operator can see which
        # indicator is being calibrated without touching anything.
        self._guide.step_changed.connect(self._follow_guide_target)
        self._follow_guide_target()

        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addWidget(self._guide)
        self.resize(1280, 780)

    # -- infrastructure ----------------------------------------------------

    @staticmethod
    def _button(text: str, slot) -> QPushButton:  # type: ignore[no-untyped-def]
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _follow_guide_target(self) -> None:
        """Keeps the combo in sync with the current wizard step's indicator."""
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
        """Shows the frame scaled to fit, remembering the scale that was used."""
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
        """Steps the window aside, takes a fresh screenshot and comes back.

        Without this the operator would have to close and reopen calibration for
        every ON/OFF sample - the biggest confusion in the previous flow.
        """
        if self._grab_frame is None:
            return False
        # MINIMISE, never hide(): this window runs inside exec_(), and hiding a
        # hide() encerra o loop modal na hora. O exec_() retornava no meio da
        # captura, o Done nunca era processado e sobrava um dialogo visivel e
        # with the main window left DISABLED by Windows. That was the "it froze
        # and will not even close" report.
        # Minimising takes the window out of the shot without touching modality.
        self.showMinimized()
        QApplication.processEvents()
        time.sleep(_HIDE_BEFORE_GRAB_S)
        frame, error = None, ""
        # Two attempts: the first failure is usually a dead GDI handle (hiding
        # and reshowing the window invalidates the context), and ScreenCapture
        # recreates the grabber underneath - so the second attempt works.
        for attempt in (1, 2):
            try:
                frame = self._grab_frame()
                break
            except Exception as exc:  # capture must never break calibration
                logger.exception("Screenshot attempt {} failed", attempt)
                error = str(exc)
                time.sleep(_RETRY_WAIT_S)
        self.showNormal()  # par do showMinimized acima
        self.raise_()
        self.activateWindow()
        if frame is None:
            # The technical detail goes to "Show details": the operator sees one
            # actionable sentence, and a technician still gets the error text.
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

    # -- bridge to the wizard ---------------------------------------------

    def _run_step(self, action: str, indicator: str = "") -> bool:
        """Runs the current step's action. True when the capture succeeded.

        `indicator` comes from the wizard step itself. It used to always use the
        critical indicator: with two vacuums, the operator followed instructions
        for Vacuum Pump 1 while the capture was written to Vacuum 1 - which is
        why Vacuum Pump 1 stayed unreadable after being calibrated.
        """
        target = indicator or self._config.critical_indicator
        if action in (REQ_LABEL, REQ_TOGGLE):
            # Drawing steps: the operator has already dragged over the picture.
            self._select_target(target)
            return self._save_label() if action == REQ_LABEL else self._save_toggle_area()
        if action in (REQ_ON, REQ_OFF):
            # Sample steps: the screen state changed, so a fresh picture is needed.
            self._select_target(target)
            if not self._refresh_frame():
                return False
            return self._capture_sample("on" if action == REQ_ON else "off")
        if action == REQ_ISO:
            self._select_target(_ISO_TARGET)
            return self._save_roi()
        if action == ACT_PROGRAM:
            self._select_target(_PROGRAM_TARGET)
            return self._save_roi()
        return False

    def _mark_changed(self) -> None:
        """Marks a change and refreshes the progress shown in the wizard."""
        self.changed = True
        guide = getattr(self, "_guide", None)
        if guide is not None:
            guide.refresh()

    # -- helpers -----------------------------------------------------------

    def _selected_roi(self) -> Roi | None:
        """Converts the selection (scaled widget coords) to real frame pixels."""
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
        """The selected indicator, or None when the target is not an indicator."""
        target = self._target.currentText()
        if target in (_PROGRAM_TARGET, _ISO_TARGET):
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
        """Finds the stored label in the current frame (base for the toggle offset)."""
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

    # -- fixed-position mode (Advanced) ------------------------------------

    def _save_roi(self) -> bool:
        roi = self._selected_roi()
        if roi is None:
            return False
        target = self._target.currentText()
        if target == _PROGRAM_TARGET:
            self._config.program_roi = roi
        elif target == _ISO_TARGET:
            self._config.iso_roi = roi
        else:
            for ind in self._config.indicators:
                if ind.name == target:
                    ind.roi = roi
        self._mark_changed()
        logger.info("ROI for '{}' set: {}", target, roi)
        return True

    def _save_template(self, state: str) -> bool:
        """Crops the indicator's CURRENT ROI and stores it as an on/off template."""
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

    # -- label-search mode (the wizard) ------------------------------------

    def _save_label(self) -> bool:
        """Stores the image of the indicator's text (e.g. 'Vacuum 1')."""
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
        """Stores the toggle as an offset from the label."""
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
        """Colour sample of the toggle in its current state (no dragging).

        It locates the label in the frame and crops the toggle by the stored
        geometry, so the sample comes from exactly the area read in operation.
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
