"""Localizacao da janela do OSAI e captura de frames."""

from .window_locator import WindowLocator, WindowRect
from .screen_capture import ScreenCapture

__all__ = ["WindowLocator", "WindowRect", "ScreenCapture"]
