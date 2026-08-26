"""Modelos de dados centrais (sem dependencia de UI ou de servicos)."""

from .core import (
    AlarmDecision,
    AlertLevel,
    AppConfig,
    DetectionResult,
    IndicatorConfig,
    IndicatorReading,
    PumpState,
    Roi,
    ToggleGeometry,
)

__all__ = [
    "AlarmDecision",
    "AlertLevel",
    "AppConfig",
    "DetectionResult",
    "IndicatorConfig",
    "IndicatorReading",
    "PumpState",
    "Roi",
    "ToggleGeometry",
]
