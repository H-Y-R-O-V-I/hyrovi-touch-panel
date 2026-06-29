from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HomeAssistantResult:
    ok: bool
    source: str
    detail: str
    data: dict[str, Any] | None = None


def get_state(entity_id: str) -> HomeAssistantResult:
    return HomeAssistantResult(
        ok=False,
        source="mock",
        detail=f"Mock state for {entity_id}",
        data={
            "entity_id": entity_id,
            "state": "unknown",
            "attributes": {},
        },
    )


def call_service(domain: str, service: str, data: dict[str, Any]) -> HomeAssistantResult:
    return HomeAssistantResult(
        ok=False,
        source="mock",
        detail=f"Mock call to {domain}.{service}",
        data={
            "domain": domain,
            "service": service,
            "data": data,
        },
    )


def healthcheck() -> HomeAssistantResult:
    return HomeAssistantResult(
        ok=True,
        source="mock",
        detail="Home Assistant is not connected yet. Mock mode is active.",
        data={
            "connected": False,
        },
    )

