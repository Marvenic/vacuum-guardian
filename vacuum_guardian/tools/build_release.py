r"""Builds the complete portable package (executable + guide + ZIP).

It exists so releases are reproducible: PyInstaller alone does not copy the
operator guide nor zip the result, and doing that by hand already produced
an incomplete package.

Usage:  .venv\Scripts\python tools/build_release.py
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
    """Aborts early if the app is running.

    A running VacuumGuardian.exe holds the log file open and makes PyInstaller
    fail while cleaning dist/ - with a traceback that does not explain the
    cause. Better to detect it here and say what to do.
    """
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq VacuumGuardian.exe"],
        capture_output=True, text=True, check=False,
    )
    if "VacuumGuardian.exe" in result.stdout:
        raise SystemExit(
            "ERROR: VacuumGuardian.exe is running and locks the build files. "
            "Close it (tray -> Exit) or run: taskkill /F /IM VacuumGuardian.exe"
        )


def main() -> int:
    ensure_not_running()
    print("[1/4] Cleaning previous builds…")
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)

    print("[2/4] Building the icon…")
    run(sys.executable, str(ROOT / "tools" / "build_icon.py"))

    print("[3/4] Packaging with PyInstaller…")
    run(sys.executable, "-m", "PyInstaller", "vacuum_guardian.spec", "--noconfirm")

    print("[4/4] Copying the guide and zipping…")
    shutil.copy2(GUIDE, DIST / GUIDE.name)
    archive = shutil.make_archive(str(ZIP_BASE), "zip", root_dir=DIST.parent, base_dir=DIST.name)

    size_mb = Path(archive).stat().st_size / (1024 * 1024)
    print(f"\nPackage ready: {archive} ({size_mb:.0f} MB)")
    print(f"Portable folder: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
