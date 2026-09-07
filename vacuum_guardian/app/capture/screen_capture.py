"""Frame capture with mss.

mss is the fastest pure-Python way to grab a screen region on Windows (it
uses the GDI API directly). Compared with the alternatives:
- PIL.ImageGrab: slower, with no fine control over region or monitor;
- pygetwindow + pyautogui: more dependencies for the same result.

The frame comes back as a BGR numpy array (OpenCV's layout), ready for the
vision layer with no extra conversion.
"""

from __future__ import annotations

import threading

import numpy as np
from loguru import logger
from mss import mss

from .window_locator import WindowLocator, WindowRect


class ScreenCapture:
    """Captures the OSAI window; falls back to the primary monitor if absent."""

    def __init__(self, locator: WindowLocator) -> None:
        self._locator = locator
        # mss uses GDI handles that are only valid on the thread that created
        # them; grab() runs on the monitoring thread (and calibration on the UI
        # thread), so we keep one mss instance PER THREAD via threading.local.
        self._local = threading.local()
        self._warned_fallback = False

    @property
    def _sct(self) -> mss:
        if not hasattr(self._local, "sct"):
            self._local.sct = mss()
        return self._local.sct

    def grab(self) -> tuple[np.ndarray, WindowRect | None]:
        """Grabs one frame.

        Returns:
            (BGR frame, window rectangle, or None when the full-screen fallback
            was used). The rectangle is returned so the caller can apply the
            window-relative ROIs.
        """
        window = self._locator.find()
        if window is not None:
            region = {
                "left": window.left,
                "top": window.top,
                "width": window.width,
                "height": window.height,
            }
            self._warned_fallback = False
        else:
            # Fallback: the whole primary monitor. Logged only once so the log is
            # not flooded while OSAI is closed.
            if not self._warned_fallback:
                logger.warning("OSAI window not found - capturing the primary monitor")
                self._warned_fallback = True
            region = self._sct.monitors[1]  # [0] = all monitors combined

        shot = self._grab_region(region)
        # np.array (NOT asarray): mss reuses its internal buffer between grabs
        # of the same size. A view would turn into the next capture's pixels -
        # and the calibration screen holds a frame for several seconds while the
        # operator works on the OSAI screen.
        # mss delivers BGRA; the alpha channel is dropped -> BGR (OpenCV).
        # ascontiguousarray: besides COPYING (mss recycles its buffer), it
        # guarantees contiguous memory we own. Slicing BGRA->BGR leaves the array
        # with a broken stride, and OpenCV receiving a non-contiguous view over
        # somebody else's memory was what crashed the process with no
        # traceback ("VacuumGuardian.exe has stopped working").
        frame = np.ascontiguousarray(np.array(shot, dtype=np.uint8)[:, :, :3])
        return frame, window

    def _grab_region(self, region):  # type: ignore[no-untyped-def]
        """Grabs the region, recreating the grabber if the GDI handle died.

        Windows GDI handles are invalidated by ordinary events: hiding and
        reexibir uma janela (o que a calibracao faz a cada amostra), trocar de
        session, changing DPI. Without this second attempt, a transient failure
        left calibration stuck on "Could not take a new screenshot".
        """
        try:
            return self._sct.grab(region)
        except Exception as exc:
            logger.warning("Screen capture failed ({}) - recreating the grabber", exc)
            self._reset()
            return self._sct.grab(region)

    def _reset(self) -> None:
        """Drops this thread's grabber; the next access creates a new one."""
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:  # may already be invalid - closing is best effort
                pass
            del self._local.sct

    def close(self) -> None:
        self._reset()
