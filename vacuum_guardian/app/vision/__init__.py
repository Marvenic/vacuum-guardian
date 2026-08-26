"""Algoritmos de visao computacional (template matching, busca por rotulo e OCR)."""

from .template_matcher import TemplateMatcher, TemplateMatch
from .finder import IndicatorFinder, FinderResult, blue_fraction
from .ocr import TextReader, WindowsOcrReader

__all__ = [
    "TemplateMatcher",
    "TemplateMatch",
    "IndicatorFinder",
    "FinderResult",
    "blue_fraction",
    "TextReader",
    "WindowsOcrReader",
]
