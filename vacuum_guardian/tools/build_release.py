r"""Gera o pacote portatil completo (executavel + guia + ZIP).

Existe para que o release seja reprodutivel: o PyInstaller sozinho nao copia
o guia do operador nem compacta o resultado, e refazer isso na mao ja causou
um pacote incompleto.

Uso:  .venv\Scripts\python tools/build_release.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "VacuumGuardian"
GUIDE = ROOT / "docs" / "READ ME - Quick start.txt"
ZIP_BASE = ROOT / "dist" / "VacuumGuardian-portable"


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def ensure_not_running() -> None:
    """Aborta cedo se o app estiver aberto.

    Um VacuumGuardian.exe rodando mantem o arquivo de log aberto e faz o
    PyInstaller falhar ao limpar dist/ - com um traceback que nao explica a
    causa. Melhor detectar aqui e dizer o que fazer.
    """
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq VacuumGuardian.exe"],
        capture_output=True, text=True, check=False,
    )
    if "VacuumGuardian.exe" in result.stdout:
        raise SystemExit(
            "ERRO: VacuumGuardian.exe esta em execucao e trava os arquivos do build. "
            "Feche o app (bandeja -> Exit) ou rode: taskkill /F /IM VacuumGuardian.exe"
        )


def main() -> int:
    ensure_not_running()
    print("[1/4] Limpando builds anteriores…")
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)

    print("[2/4] Gerando o icone…")
    run(sys.executable, str(ROOT / "tools" / "build_icon.py"))

    print("[3/4] Empacotando com o PyInstaller…")
    run(sys.executable, "-m", "PyInstaller", "vacuum_guardian.spec", "--noconfirm")

    print("[4/4] Copiando guia e compactando…")
    shutil.copy2(GUIDE, DIST / GUIDE.name)
    archive = shutil.make_archive(str(ZIP_BASE), "zip", root_dir=DIST.parent, base_dir=DIST.name)

    size_mb = Path(archive).stat().st_size / (1024 * 1024)
    print(f"\nPacote pronto: {archive} ({size_mb:.0f} MB)")
    print(f"Pasta portatil: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
