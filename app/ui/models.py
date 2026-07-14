from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class DashboardTileConfig:
    id: str
    type: str
    entity_id: str = ""
    label: str = ""
    action: str = "toggle"
    icon: str = ""
    info: str = ""
    order: int = 0


@dataclass(slots=True)
class DashboardPageConfig:
    id: str
    label: str
    tiles: list[DashboardTileConfig] = field(default_factory=list)


@dataclass(slots=True)
class DashboardConfig:
    pages: list[DashboardPageConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TileState:
    entity_id: str
    state: str = "unknown"
    friendly_name: str = ""
    domain: str = ""
    info: str = ""
    error: str = ""
    busy: bool = False
    locked: bool = False
    action_label: str = ""

    @property
    def is_available(self) -> bool:
        return self.state.lower() not in {"unknown", "unavailable"}

    @property
    def is_on(self) -> bool:
        return self.state.lower() == "on"

