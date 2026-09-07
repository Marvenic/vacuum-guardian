"""Resource path resolution (works in development and when frozen).

PyInstaller extracts bundled files to a temporary folder pointed to by
sys._MEIPASS; WRITABLE files (config.json, logs) must instead sit beside
the .exe, not in the temporary folder that vanishes on exit.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Path of a bundled read-only resource (assets/...)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parents[2] / relative


def user_data_path() -> Path:
    """Writable folder: beside the .exe when frozen, project root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]
