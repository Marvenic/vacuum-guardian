"""Alarm sound playback.

winsound with SND_ASYNC|SND_LOOP plays the WAV on loop without blocking the
thread. The SoundPlayer interface allows a fake in tests (nobody wants a
noisy test suite).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loguru import logger


class SoundPlayer(Protocol):
    """Minimum contract for the alarm sound player."""

    def start_loop(self, wav_path: Path) -> None:
        """Starts the WAV on loop (non-blocking). Repeat calls are harmless."""
        ...

    def stop(self) -> None:
        """Stops the sound immediately."""
        ...


class WinSoundPlayer:
    """Real SoundPlayer, backed by winsound (Windows stdlib)."""

    def __init__(self) -> None:
        self._playing = False

    def start_loop(self, wav_path: Path) -> None:
        if self._playing:
            return  # already playing; restarting would make it stutter
        import winsound

        try:
            winsound.PlaySound(
                str(wav_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            self._playing = True
        except RuntimeError as exc:
            # Missing or broken WAV: fall back to the system sound. There is
            # no loop then, but a degraded alarm beats silence.
            logger.error("Failed to play {} ({}) - falling back to the system sound", wav_path, exc)
            winsound.MessageBeep(winsound.MB_ICONHAND)

    def stop(self) -> None:
        if not self._playing:
            return
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
        self._playing = False
