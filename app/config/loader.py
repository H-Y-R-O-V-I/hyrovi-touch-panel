from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "home_assistant": {
        "url": "http://homeassistant.local:8123",
        "token": "",
    },
    "ui": {
        "fullscreen": True,
        "screen_width": 800,
        "screen_height": 480,
        "hide_cursor": True,
        "refresh_interval": 1.0,
    },
    "touch": {
        "mode": "pygame",
        "enable_gestures": True,
    },
    "updates": {
        "enabled": True,
        "github_repo": "H-Y-R-O-V-I/hyrovi-touch-panel",
        "channel": "stable",
        "check_on_boot": True,
        "boot_delay_seconds": 60,
        "auto_update": True,
        "rollback_on_failed_healthcheck": True,
    },
    "entities": {
        "main_light": "light.ikea_of_sweden_ormanas_led_strip",
        "temperature": "sensor.tesla_wall_connector_mcu_temperatur",
        "humidity": "sensor.solaredge_speicherniveau",
    },
    "admin": {
        "pin": "",
    },
}


@dataclass(slots=True)
class HomeAssistantConfig:
    url: str = ""
    token: str = ""


@dataclass(slots=True)
class UIConfig:
    fullscreen: bool = True
    screen_width: int = 800
    screen_height: int = 480
    hide_cursor: bool = True
    refresh_interval: float = 1.0


@dataclass(slots=True)
class TouchConfig:
    mode: str = "pygame"
    enable_gestures: bool = True


@dataclass(slots=True)
class UpdateConfig:
    enabled: bool = True
    github_repo: str = "H-Y-R-O-V-I/hyrovi-touch-panel"
    channel: str = "stable"
    check_on_boot: bool = True
    boot_delay_seconds: int = 60
    auto_update: bool = True
    rollback_on_failed_healthcheck: bool = True


@dataclass(slots=True)
class EntityConfig:
    main_light: str = "light.extended_color_light_3"
    temperature: str = "sensor.wohnzimmer_temperatur"
    humidity: str = "sensor.wohnzimmer_luftfeuchtigkeit"


@dataclass(slots=True)
class AdminConfig:
    pin: str = ""


@dataclass(slots=True)
class AppConfig:
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    touch: TouchConfig = field(default_factory=TouchConfig)
    updates: UpdateConfig = field(default_factory=UpdateConfig)
    entities: EntityConfig = field(default_factory=EntityConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    source_path: Path | None = None
    exists: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ha_enabled(self) -> bool:
        return bool(self.home_assistant.url.strip() and self.home_assistant.token.strip())

    @property
    def display_size(self) -> tuple[int, int]:
        return self.ui.screen_width, self.ui.screen_height


class HomeAssistantUrlError(ValueError):
    pass


def normalize_home_assistant_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise HomeAssistantUrlError("Home Assistant URL is empty.")

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise HomeAssistantUrlError("Home Assistant URL must start with http:// or https://.")
    if parsed.query or parsed.fragment:
        raise HomeAssistantUrlError("Home Assistant URL must not contain query parameters or fragments.")

    host = parsed.netloc.strip()
    path = parsed.path or ""

    if not host:
        candidate = path.lstrip("/")
        if not candidate or "/" in candidate:
            raise HomeAssistantUrlError(
                "Home Assistant URL must include a host, for example http://homeassistant.local:8123."
            )
        host = candidate
    elif path and set(path) != {"/"}:
        raise HomeAssistantUrlError(
            "Home Assistant URL must not contain a path. Use the base host and optional port only."
        )

    if not host:
        raise HomeAssistantUrlError(
            "Home Assistant URL must include a host, for example http://homeassistant.local:8123."
        )

    return urlunsplit((parsed.scheme, host, "", "", ""))


def _normalize_optional_home_assistant_url(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    try:
        return normalize_home_assistant_url(stripped)
    except HomeAssistantUrlError:
        return value


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return loaded


def read_config_data(path: Path) -> dict[str, Any]:
    return _load_yaml(path)


def dump_config_data(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def load_config(path: Path) -> AppConfig:
    exists = path.exists()
    loaded = _load_yaml(path)
    if isinstance(loaded.get("home_assistant"), dict):
        loaded = dict(loaded)
        loaded["home_assistant"] = dict(loaded["home_assistant"])
        loaded["home_assistant"]["url"] = _normalize_optional_home_assistant_url(
            loaded["home_assistant"].get("url", "")
        )
    merged = _merge_dicts(DEFAULT_CONFIG, loaded)
    merged_home_assistant = dict(_section(merged, "home_assistant"))
    merged_home_assistant["url"] = _normalize_optional_home_assistant_url(merged_home_assistant.get("url", ""))
    merged["home_assistant"] = merged_home_assistant

    return AppConfig(
        home_assistant=HomeAssistantConfig(**_section(merged, "home_assistant")),
        ui=UIConfig(**_section(merged, "ui")),
        touch=TouchConfig(**_section(merged, "touch")),
        updates=UpdateConfig(**_section(merged, "updates")),
        entities=EntityConfig(**_section(merged, "entities")),
        admin=AdminConfig(**_section(merged, "admin")),
        source_path=path,
        exists=exists,
        raw=merged,
    )
