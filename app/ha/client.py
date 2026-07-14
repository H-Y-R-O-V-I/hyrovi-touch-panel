from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from app.config.loader import AppConfig


@dataclass(slots=True)
class HomeAssistantResult:
    ok: bool
    source: str
    detail: str
    data: dict[str, Any] | None = None


class HomeAssistantClient:
    def __init__(self, url: str, token: str, timeout: float = 4.0) -> None:
        self.url = url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: AppConfig) -> "HomeAssistantClient":
        return cls(config.home_assistant.url, config.home_assistant.token)

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def healthcheck(self) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=True,
                source="mock",
                detail="Home Assistant not configured. Mock mode is active.",
                data={"connected": False},
            )

        try:
            response = requests.get(
                urljoin(self.url + "/", "api/"),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return HomeAssistantResult(
                ok=False,
                source="ha",
                detail=f"Home Assistant unreachable: {exc}",
            )

        return HomeAssistantResult(
            ok=True,
            source="ha",
            detail="Home Assistant API reachable.",
            data={"connected": True},
        )

    def get_state(self, entity_id: str) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=False,
                source="mock",
                detail=f"Mock state for {entity_id}",
                data={"entity_id": entity_id, "state": "unknown", "attributes": {}},
            )

        try:
            response = requests.get(
                urljoin(self.url + "/", f"api/states/{entity_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return HomeAssistantResult(ok=False, source="ha", detail=str(exc))

        return HomeAssistantResult(ok=True, source="ha", detail="ok", data=payload)

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=False,
                source="mock",
                detail=f"Mock call to {domain}.{service}",
                data={"domain": domain, "service": service, "data": data},
            )

        try:
            response = requests.post(
                urljoin(self.url + "/", f"api/services/{domain}/{service}"),
                headers=self._headers(),
                json=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
        except requests.RequestException as exc:
            return HomeAssistantResult(ok=False, source="ha", detail=str(exc))

        return HomeAssistantResult(ok=True, source="ha", detail="service called", data=payload)
