"""Inicio automatico com o Windows (via pasta Startup).

Por que a pasta Startup e nao alternativas:
- Registro (HKCU\\...\\Run): funciona, mas escrita em Registro e um gatilho
  classico de heuristica de antivirus e e invisivel ao operador;
- Task Scheduler: mais poderoso (ex.: rodar antes do login), porem exige
  privilegio administrativo, raro em PC de chao de fabrica;
- Pasta Startup: sem privilegio, visivel e removivel pelo proprio usuario.

O atalho .lnk e criado via WScript.Shell (COM), presente em todo Windows.
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
    """Converte um texto em literal VBScript (aspas internas viram duplas).

    Necessario porque os argumentos do atalho precisam ir entre aspas para
    tolerar espacos no caminho - sem escape, o VBScript ve string nao
    terminada e falha na compilacao.
    """
    return '"' + value.replace('"', '""') + '"'


class AutoStart:
    """Habilita/desabilita o inicio automatico do app com o Windows."""

    def __init__(self, name: str = _SHORTCUT_NAME) -> None:
        self._name = name

    @property
    def shortcut_path(self) -> Path:
        """Caminho do atalho.

        Lido a cada acesso (e nao no __init__) para respeitar mudancas de
        APPDATA - o que tambem permite testar sem tocar na pasta real.
        """
        return (
            Path(os.environ["APPDATA"])
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / self._name
        )

    @staticmethod
    def _target() -> tuple[str, str, str]:
        """Retorna (executavel, argumentos, diretorio de trabalho).

        Congelado (PyInstaller): o proprio .exe, sem argumentos.
        Desenvolvimento: pythonw.exe (sem console) + caminho do main.py.
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
        """Cria o atalho na pasta Startup. Retorna True em caso de sucesso."""
        target, arguments, working_dir = self._target()
        shortcut = self.shortcut_path
        icon = resource_path("assets/icon.ico")

        # VBScript de poucas linhas e a forma mais portavel de criar um .lnk
        # sem dependencia extra (pywin32/winshell).
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
            # cscript espera ANSI/UTF-16; utf-8 quebra em caminhos acentuados.
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
        """Remove o atalho da pasta Startup."""
        try:
            self.shortcut_path.unlink(missing_ok=True)
            logger.info("Automatic startup disabled")
            return True
        except OSError as exc:
            logger.error("Failed to disable automatic startup: {}", exc)
            return False

    def set_enabled(self, enabled: bool) -> bool:
        return self.enable() if enabled else self.disable()
