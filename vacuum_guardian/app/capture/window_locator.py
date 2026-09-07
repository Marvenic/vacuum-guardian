"""Locates the OSAI window through the native Windows API (ctypes/user32).

ctypes instead of pywin32 to avoid a dependency: all we need is EnumWindows
plus GetWindowText and GetWindowRect. The search is by title substring
(case-insensitive), configurable through config.json ("window_title_hint"),
because the exact OSAI window title varies between installations.

"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

from loguru import logger

_user32 = ctypes.windll.user32

_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


# A minimised window sits at (-32000, -32000) WITH positive width and
# height, and IsWindowVisible still returns True. Measured here:
#   NORMAL     IsWindowVisible=True IsIconic=False rect=(1654,858) 532x388
#   MINIMISED IsWindowVisible=True IsIconic=True  rect=(-32000,-32000) 391x61
# Without checking IsIconic the app "found" a minimised OSAI and captured an
# off-screen region: useless frame, empty OCR, alarm never fired.
_OFFSCREEN = -20000


@dataclass(frozen=True)
class WindowCandidate:
    """An enumerated window, before deciding whether it is usable."""

    title: str
    left: int
    top: int
    width: int
    height: int
    minimized: bool

    @property
    def usable(self) -> bool:
        """Can it be captured? It must be restored and on screen."""
        return (
            not self.minimized
            and self.width > 0
            and self.height > 0
            and self.left > _OFFSCREEN
            and self.top > _OFFSCREEN
        )


@dataclass(frozen=True)
class WindowRect:
    """Absolute rectangle (screen coordinates) of a window that was found."""

    left: int
    top: int
    width: int
    height: int
    title: str


class WindowLocator:
    """Finds the window whose title contains the configured hint."""

    def __init__(self, title_hint: str) -> None:
        self._hint = title_hint.lower()

    def find(self) -> WindowRect | None:
        """Returns the rectangle of the best window matching the hint.

        None if nothing is usable - the caller decides the fallback (capturing
        the whole monitor, for instance).
        """
        return choose_window(self._enumerate(), self._hint)

    def _enumerate(self) -> list[WindowCandidate]:
        """Lists titled windows, without judging whether they are usable."""
        candidates: list[WindowCandidate] = []

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True  # keep enumerating
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            rect = wt.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            candidates.append(
                WindowCandidate(
                    title=buffer.value,
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                    minimized=bool(_user32.IsIconic(hwnd)),
                )
            )
            return True

        _user32.EnumWindows(_EnumWindowsProc(_callback), 0)
        return candidates


def choose_window(candidates: list[WindowCandidate], hint: str) -> WindowRect | None:
    """Picks which matching window to capture.

    Two decisions that came from real failures on the CNC:

    - MINIMISED is no good. Windows still reports IsWindowVisible=True and
      returns an off-screen rectangle; capturing there yields a useless frame
      and the app appeared to "find" OSAI while reading nothing.
    - The LARGEST wins, not the first. The hint "OSAI" also matches service
      windows such as "OSAI BootController", which are small; the operating
      screen fills the monitor.
    """
    wanted = hint.lower()
    matching = [c for c in candidates if wanted in c.title.lower()]
    usable = [c for c in matching if c.usable]

    if not usable:
        if matching:
            # Telling "does not exist" apart from "exists but is minimised" saves
            # the operator from looking for the fault in the wrong place.
            logger.warning(
                "Window '{}' found but not usable (minimised or off-screen): {}",
                hint, ", ".join(sorted({c.title for c in matching})),
            )
        else:
            logger.debug("No window with a title containing '{}'", hint)
        return None

    best = max(usable, key=lambda c: c.width * c.height)
    if len(usable) > 1:
        logger.debug(
            "{} windows match '{}' - using the largest: '{}'",
            len(usable), hint, best.title,
        )
    return WindowRect(best.left, best.top, best.width, best.height, best.title)
