"""Starting automatically with Windows (through the Startup folder).

Why the Startup folder and not the alternatives:
- Registry (HKCU\\...\\Run): works, but writing to the Registry is a classic
  antivirus heuristic trigger and is invisible to the operator;
- Task Scheduler: more powerful (it can run before login) but needs
  administrator rights, rare on a shop-floor PC;
- Startup folder: no privilege, visible and removable by the user.

The .lnk shortcut is created via WScript.Shell (COM), present on every Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

from .paths import resource_path

_SHORTCUT_NAME = "Vacuum Guardian.lnk"


def _vbs_string(value: str) -> str:
    """Turns text into a VBScript literal (inner quotes are doubled).

    Needed because the shortcut arguments must be quoted to survive spaces in
    the path - without escaping, VBScript sees an unterminated string and
    fails to compile.
    """
    return '"' + value.replace('"', '""') + '"'


class AutoStart:
    """Enables or disables starting the app with Windows."""

    def __init__(self, name: str = _SHORTCUT_NAME) -> None:
        self._name = name

    @property
    def shortcut_path(self) -> Path:
        """Path of the shortcut.

        Read on every access (not in __init__) so it honours changes to APPDATA -
        which is also what lets tests run without touching the real folder.
        """
        return (
            Path(os.environ["APPDATA"])
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / self._name
        )

    @staticmethod
    def _target() -> tuple[str, str, str]:
        """Returns (executable, arguments, working directory).

        Frozen (PyInstaller): the .exe itself, with no arguments.
        Development: pythonw.exe (no console) plus the path to main.py.
        """
        if getattr(sys, "frozen", False):
            exe = sys.executable
            return exe, "", str(Path(exe).parent)
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else sys.executable)
        main_py = Path(sys.argv[0]).resolve()
        return exe, f'"{main_py}"', str(main_py.parent)

    def is_enabled(self) -> bool:
        return self.shortcut_path.exists()

    def enable(self) -> bool:
        """Creates the shortcut in the Startup folder. True on success."""
        target, arguments, working_dir = self._target()
        shortcut = self.shortcut_path
        icon = resource_path("assets/icon.ico")

        # A few lines of VBScript is the most portable way to create a .lnk
        # without an extra dependency (pywin32/winshell).
        lines = [
            'Set s = CreateObject("WScript.Shell")',
            f"Set lnk = s.CreateShortcut({_vbs_string(str(shortcut))})",
            f"lnk.TargetPath = {_vbs_string(target)}",
            f"lnk.Arguments = {_vbs_string(arguments)}",
            f"lnk.WorkingDirectory = {_vbs_string(working_dir)}",
            'lnk.Description = "Vacuum Guardian - vacuum monitoring"',
        ]
        if icon.exists():
            lines.append(f"lnk.IconLocation = {_vbs_string(str(icon))}")
        lines.append("lnk.Save")

        vbs = Path(os.environ["TEMP"]) / "vg_autostart.vbs"
        try:
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            # cscript expects ANSI/UTF-16; utf-8 breaks on accented paths.
            vbs.write_text("\n".join(lines) + "\n", encoding="mbcs")
            subprocess.run(
                ["cscript.exe", "//Nologo", str(vbs)],
                check=True, capture_output=True, timeout=20,
            )
            logger.info("Automatic startup enabled: {}", shortcut)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("Failed to enable automatic startup: {}", exc)
            return False
        finally:
            vbs.unlink(missing_ok=True)

    def disable(self) -> bool:
        """Removes the shortcut from the Startup folder."""
        try:
            self.shortcut_path.unlink(missing_ok=True)
            logger.info("Automatic startup disabled")
            return True
        except OSError as exc:
            logger.error("Failed to disable automatic startup: {}", exc)
            return False

    def set_enabled(self, enabled: bool) -> bool:
        return self.enable() if enabled else self.disable()
