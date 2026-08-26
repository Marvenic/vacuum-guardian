"""Utilitarios de plataforma (autostart, caminhos)."""

from .autostart import AutoStart
from .paths import resource_path, user_data_path

__all__ = ["AutoStart", "resource_path", "user_data_path"]
