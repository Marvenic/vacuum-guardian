"""Reproducao do som de alarme.

winsound com SND_ASYNC|SND_LOOP toca o WAV em loop sem bloquear a thread -
exatamente o requisito 6 ("tocar WAV continuamente"). A interface SoundPlayer
permite substituir por um fake nos testes (nao queremos testes barulhentos).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loguru import logger


class SoundPlayer(Protocol):
    """Contrato minimo do reprodutor de som do alarme."""

    def start_loop(self, wav_path: Path) -> None:
        """Inicia o WAV em loop (nao bloqueante). Chamadas repetidas sao inofensivas."""
        ...

    def stop(self) -> None:
        """Para o som imediatamente."""
        ...


class WinSoundPlayer:
    """SoundPlayer real, baseado em winsound (stdlib do Windows)."""

    def __init__(self) -> None:
        self._playing = False

    def start_loop(self, wav_path: Path) -> None:
        if self._playing:
            return  # ja esta tocando; reiniciar causaria "gaguejar"
        import winsound

        try:
            winsound.PlaySound(
                str(wav_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            self._playing = True
        except RuntimeError as exc:
            # WAV ausente/corrompido: cai para o som de exclamacao do sistema,
            # em loop nao ha - mas um alarme degradado e melhor que silencio.
            logger.error("Failed to play {} ({}) - falling back to the system sound", wav_path, exc)
            winsound.MessageBeep(winsound.MB_ICONHAND)

    def stop(self) -> None:
        if not self._playing:
            return
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
        self._playing = False
