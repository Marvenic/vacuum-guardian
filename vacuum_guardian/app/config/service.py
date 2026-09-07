"""Loads and saves AppConfig in config.json.

Hand-written serialisation (no external library): the schema is small and
stable, so we control exactly what reaches the disk. Unknown JSON fields are
ignored and missing ones take the dataclass default, which makes version
upgrades tolerant of older configuration files.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from ..models import AppConfig, IndicatorConfig, Roi, ToggleGeometry


class ConfigService:
    """Sole owner of reading and writing config.json."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        """Reads config.json; returns defaults if missing or corrupted.

        A corrupted config must never stop the monitor from starting - in an
        industrial setting, starting with defaults and logging beats crashing.
        """
        if not self._path.exists():
            logger.info("config.json not found at {} - using defaults", self._path)
            return AppConfig()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return self._from_dict(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Invalid config.json ({}) - using defaults", exc)
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        """Writes the config atomically (to .tmp, then renames)."""
        data = self._to_dict(config)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)
        logger.info("Configuration saved to {}", self._path)

    # -- serialisation -----------------------------------------------------

    @staticmethod
    def _roi_to_dict(roi: Roi | None) -> dict[str, int] | None:
        if roi is None:
            return None
        return {"x": roi.x, "y": roi.y, "width": roi.width, "height": roi.height}

    @staticmethod
    def _roi_from_dict(data: dict[str, int] | None) -> Roi | None:
        if not data:
            return None
        return Roi(
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )

    @staticmethod
    def _toggle_to_dict(toggle: ToggleGeometry | None) -> dict[str, int] | None:
        if toggle is None:
            return None
        return {
            "dx": toggle.dx,
            "dy": toggle.dy,
            "width": toggle.width,
            "height": toggle.height,
        }

    @staticmethod
    def _toggle_from_dict(data: dict[str, int] | None) -> ToggleGeometry | None:
        if not data:
            return None
        return ToggleGeometry(
            dx=int(data["dx"]),
            dy=int(data["dy"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )

    def _to_dict(self, c: AppConfig) -> dict[str, object]:
        return {
            "window_title_hint": c.window_title_hint,
            "capture_interval_s": c.capture_interval_s,
            "trigger_programs": c.trigger_programs,
            "template_threshold": c.template_threshold,
            "indicators": [
                {
                    "name": ind.name,
                    "roi": self._roi_to_dict(ind.roi),
                    "toggle": self._toggle_to_dict(ind.toggle),
                }
                for ind in c.indicators
            ],
            "program_roi": self._roi_to_dict(c.program_roi),
            "iso_roi": self._roi_to_dict(c.iso_roi),
            "close_doors_keyword": c.close_doors_keyword,
            "alarm_wav": c.alarm_wav,
            "alarm_sound_enabled": c.alarm_sound_enabled,
            "alarm_snooze_minutes": c.alarm_snooze_minutes,
            "critical_indicator": c.critical_indicator,
            "label_threshold": c.label_threshold,
            "guide_language": c.guide_language,
            "telemetry_enabled": c.telemetry_enabled,
            "telemetry_prompted": c.telemetry_prompted,
            "telemetry_url": c.telemetry_url,
            "install_id": c.install_id,
            "operator_company": c.operator_company,
            "operator_name": c.operator_name,
            "operator_email": c.operator_email,
            "operator_phone": c.operator_phone,
        }

    def _from_dict(self, raw: dict[str, object]) -> AppConfig:
        defaults = AppConfig()
        raw_indicators = raw.get("indicators")
        if isinstance(raw_indicators, list) and raw_indicators:
            indicators = [
                IndicatorConfig(
                    name=str(item["name"]),
                    roi=self._roi_from_dict(item.get("roi")),
                    toggle=self._toggle_from_dict(item.get("toggle")),
                )
                for item in raw_indicators
            ]
        else:
            indicators = defaults.indicators
        return AppConfig(
            window_title_hint=str(raw.get("window_title_hint", defaults.window_title_hint)),
            capture_interval_s=float(raw.get("capture_interval_s", defaults.capture_interval_s)),  # type: ignore[arg-type]
            trigger_programs=[str(p).upper() for p in raw.get("trigger_programs", defaults.trigger_programs)],  # type: ignore[union-attr]
            template_threshold=float(raw.get("template_threshold", defaults.template_threshold)),  # type: ignore[arg-type]
            indicators=indicators,
            program_roi=self._roi_from_dict(raw.get("program_roi")),  # type: ignore[arg-type]
            iso_roi=self._roi_from_dict(raw.get("iso_roi")),  # type: ignore[arg-type]
            close_doors_keyword=str(
                raw.get("close_doors_keyword", defaults.close_doors_keyword)
            ),
            alarm_wav=str(raw.get("alarm_wav", defaults.alarm_wav)),
            alarm_sound_enabled=bool(raw.get("alarm_sound_enabled", defaults.alarm_sound_enabled)),
            alarm_snooze_minutes=float(raw.get("alarm_snooze_minutes", defaults.alarm_snooze_minutes)),  # type: ignore[arg-type]
            critical_indicator=str(raw.get("critical_indicator", defaults.critical_indicator)),
            label_threshold=float(raw.get("label_threshold", defaults.label_threshold)),  # type: ignore[arg-type]
            guide_language=str(raw.get("guide_language", defaults.guide_language)),
            telemetry_enabled=bool(raw.get("telemetry_enabled", defaults.telemetry_enabled)),
            telemetry_prompted=bool(raw.get("telemetry_prompted", defaults.telemetry_prompted)),
            telemetry_url=str(raw.get("telemetry_url", defaults.telemetry_url)),
            install_id=str(raw.get("install_id", defaults.install_id)),
            operator_company=str(raw.get("operator_company", defaults.operator_company)),
            operator_name=str(raw.get("operator_name", defaults.operator_name)),
            operator_email=str(raw.get("operator_email", defaults.operator_email)),
            operator_phone=str(raw.get("operator_phone", defaults.operator_phone)),
        )
