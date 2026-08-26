"""Logica de alarme: estado (ativo/silenciado/reconhecido) e reproducao de som."""

from .controller import AlarmController, AlarmStatus
from .sound import SoundPlayer, WinSoundPlayer

__all__ = ["AlarmController", "AlarmStatus", "SoundPlayer", "WinSoundPlayer"]
