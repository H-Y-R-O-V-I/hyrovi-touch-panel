from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from app.ui.models import DashboardConfig, DashboardPageConfig, DashboardTileConfig


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
        "main_light": "switch.lampe_wohnzimmer",
        "temperature": "sensor.tesla_wall_connector_mcu_temperatur",
        "humidity": "sensor.solaredge_speicherniveau",
    },
    "dashboard": {
        "pages": [],
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
    main_light: str = "switch.lampe_wohnzimmer"
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
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
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


def _normalize_entity_id(value: str) -> str:
    return value.strip()


def _humanize_entity_label(entity_id: str) -> str:
    object_id = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    parts = [part for part in object_id.replace("-", "_").split("_") if part]
    if not parts:
        return entity_id
    return " ".join(part.capitalize() for part in parts)


def _tile(tile_id: str, tile_type: str, entity_id: str, label: str, action: str = "toggle", icon: str = "", info: str = "", order: int = 0) -> dict[str, Any]:
    return {
        "id": tile_id,
        "type": tile_type,
        "entity_id": entity_id,
        "label": label,
        "action": action,
        "icon": icon,
        "info": info,
        "order": order,
    }


def _default_dashboard_pages(entities: dict[str, Any]) -> dict[str, Any]:
    main_light = _normalize_entity_id(str(entities.get("main_light", "")))
    temperature = _normalize_entity_id(str(entities.get("temperature", "")))
    humidity = _normalize_entity_id(str(entities.get("humidity", "")))

    home_tiles: list[dict[str, Any]] = []
    lights_tiles: list[dict[str, Any]] = []
    switches_tiles: list[dict[str, Any]] = []

    if main_light:
        domain = main_light.split(".", 1)[0]
        tile = _tile(
            "main_light",
            "entity",
            main_light,
            _humanize_entity_label(main_light),
            "toggle",
            info="Hauptlicht",
            order=0,
        )
        home_tiles.append(tile)
        if domain in {"light", "switch", "input_boolean"}:
            lights_tiles.append(tile)
        if domain in {"switch", "input_boolean"}:
            switches_tiles.append(tile)
    if temperature:
        home_tiles.append(_tile("temperature", "sensor", temperature, _humanize_entity_label(temperature), "none", info="Temperatur", order=1))
    if humidity:
        home_tiles.append(_tile("humidity", "sensor", humidity, _humanize_entity_label(humidity), "none", info="Luftfeuchte", order=2))

    return {
        "pages": [
            {"id": "home", "label": "Home", "tiles": home_tiles},
            {"id": "lights", "label": "Lampen", "tiles": lights_tiles},
            {"id": "switches", "label": "Schalter", "tiles": switches_tiles},
            {"id": "actions", "label": "Aktionen", "tiles": []},
            {"id": "system", "label": "System", "tiles": []},
        ]
    }


def _normalize_tile(tile: Any, fallback_index: int = 0) -> dict[str, Any]:
    if not isinstance(tile, dict):
        return {}
    return {
        "id": str(tile.get("id") or f"tile_{fallback_index}"),
        "type": str(tile.get("type", "entity")),
        "entity_id": str(tile.get("entity_id", "")),
        "label": str(tile.get("label", "")),
        "action": str(tile.get("action", "toggle")),
        "icon": str(tile.get("icon", "")),
        "info": str(tile.get("info", "")),
        "order": int(tile.get("order", fallback_index) or fallback_index),
    }


def _normalize_dashboard(raw_dashboard: Any, entities: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_dashboard, dict):
        return _default_dashboard_pages(entities)
    pages = raw_dashboard.get("pages", [])
    normalized_pages: list[dict[str, Any]] = []
    if isinstance(pages, list) and pages:
        for page_index, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            page_id = str(page.get("id", f"page_{page_index}")).strip() or f"page_{page_index}"
            label = str(page.get("label", page_id)).strip() or page_id
            tiles = page.get("tiles", [])
            normalized_tiles: list[dict[str, Any]] = []
            if isinstance(tiles, list):
                for tile_index, tile in enumerate(tiles):
                    normalized = _normalize_tile(tile, tile_index)
                    if normalized:
                        normalized_tiles.append(normalized)
            normalized_pages.append({"id": page_id, "label": label, "tiles": normalized_tiles})
    if not normalized_pages:
        return _default_dashboard_pages(entities)
    known_ids = {page["id"] for page in normalized_pages}
    defaults = _default_dashboard_pages(entities)["pages"]
    for page in defaults:
        if page["id"] not in known_ids:
            normalized_pages.append(page)
    return {"pages": normalized_pages}


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
    merged_entities = dict(_section(merged, "entities"))
    merged["dashboard"] = _normalize_dashboard(merged.get("dashboard"), merged_entities)

    return AppConfig(
        home_assistant=HomeAssistantConfig(**_section(merged, "home_assistant")),
        ui=UIConfig(**_section(merged, "ui")),
        touch=TouchConfig(**_section(merged, "touch")),
        updates=UpdateConfig(**_section(merged, "updates")),
        entities=EntityConfig(**_section(merged, "entities")),
        dashboard=DashboardConfig(
            pages=[
                DashboardPageConfig(
                    id=str(page.get("id", "")),
                    label=str(page.get("label", "")),
                    tiles=[
                        DashboardTileConfig(**_normalize_tile(tile, index))
                        for index, tile in enumerate(page.get("tiles", []))
                        if _normalize_tile(tile, index)
                    ],
                )
                for page in merged["dashboard"].get("pages", [])
                if isinstance(page, dict)
            ]
        ),
        admin=AdminConfig(**_section(merged, "admin")),
        source_path=path,
        exists=exists,
        raw=merged,
    )
