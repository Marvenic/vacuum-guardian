"""Resolucao de caminhos de recursos (funciona em dev e congelado).

O PyInstaller extrai os arquivos empacotados para uma pasta temporaria
apontada por sys._MEIPASS; ja os arquivos GRAVAVEIS (config.json, logs)
devem ficar junto ao .exe, nao no temporario que some ao fechar.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Caminho de um recurso somente-leitura empacotado (assets/...)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parents[2] / relative


def user_data_path() -> Path:
    """Pasta gravavel: ao lado do .exe (congelado) ou raiz do projeto (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]
