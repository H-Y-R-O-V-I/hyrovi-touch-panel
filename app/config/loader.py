from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "home_assistant_url": "",
    "home_assistant_token": "",
    "refresh_interval": 5,
    "fullscreen": False,
    "screen_width": 800,
    "screen_height": 480,
    "entities": {
        "main_light": "light.wohnzimmer",
        "temperature": "sensor.wohnzimmer_temperature",
        "humidity": "sensor.wohnzimmer_humidity",
    },
}


@dataclass
class AppConfig:
    home_assistant_url: str = ""
    home_assistant_token: str = ""
    refresh_interval: int = 5
    fullscreen: bool = False
    screen_width: int = 800
    screen_height: int = 480
    entities: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            home_assistant_url=str(data.get("home_assistant_url", "")),
            home_assistant_token=str(data.get("home_assistant_token", "")),
            refresh_interval=int(data.get("refresh_interval", 5)),
            fullscreen=bool(data.get("fullscreen", False)),
            screen_width=int(data.get("screen_width", 800)),
            screen_height=int(data.get("screen_height", 480)),
            entities=dict(data.get("entities", {})),
        )


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> AppConfig:
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file must contain a mapping: {path}")
        data = loaded

    merged = _merge_dicts(DEFAULTS, data)
    return AppConfig.from_dict(merged)

