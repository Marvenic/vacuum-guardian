"""Configuracao central do loguru e trilha de auditoria."""

from .detection_log import DetectionLog, OverrideLog
from .setup import setup_logging

__all__ = ["DetectionLog", "OverrideLog", "setup_logging"]
