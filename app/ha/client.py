from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import requests

from app.config.loader import AppConfig, HomeAssistantUrlError, normalize_home_assistant_url


@dataclass(slots=True)
class HomeAssistantResult:
    ok: bool
    source: str
    detail: str
    data: Any | None = None
    status_code: int | None = None


class HomeAssistantClient:
    def __init__(self, url: str, token: str, timeout: float = 4.0) -> None:
        self.url = url.strip()
        self.token = token.strip()
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: AppConfig) -> "HomeAssistantClient":
        return cls(config.home_assistant.url, config.home_assistant.token)

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def _base_url(self) -> str:
        return normalize_home_assistant_url(self.url)

    def _api_url(self, suffix: str = "", *, trailing_slash: bool = False) -> str:
        base = self._base_url()
        if suffix:
            return f"{base}/api/{suffix.lstrip('/')}"
        return f"{base}/api/" if trailing_slash else f"{base}/api"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, suffix: str = "", *, json: dict[str, Any] | None = None, trailing_slash: bool = False) -> HomeAssistantResult:
        try:
            url = self._api_url(suffix, trailing_slash=trailing_slash)
        except HomeAssistantUrlError as exc:
            return HomeAssistantResult(ok=False, source="config", detail=f"Invalid Home Assistant URL: {exc}")

        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(),
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else None
            if status == 401:
                detail = "Home Assistant authentication failed (401 Unauthorized)."
            elif status == 404:
                detail = "Home Assistant resource not found (404 Not Found)."
            else:
                detail = f"Home Assistant returned HTTP {status if status is not None else 'error'}."
            return HomeAssistantResult(ok=False, source="ha", detail=detail, status_code=status)
        except requests.Timeout:
            return HomeAssistantResult(ok=False, source="ha", detail="Timeout while contacting Home Assistant.")
        except requests.ConnectionError as exc:
            message = str(exc).lower()
            if any(marker in message for marker in ("name or service not known", "temporary failure in name resolution", "nodename nor servname provided", "failed to resolve", "dns")):
                detail = "DNS error while resolving the Home Assistant host."
            else:
                detail = f"Connection error while contacting Home Assistant: {exc}"
            return HomeAssistantResult(ok=False, source="ha", detail=detail)
        except requests.InvalidURL as exc:
            return HomeAssistantResult(ok=False, source="config", detail=f"Invalid Home Assistant URL: {exc}")
        except requests.RequestException as exc:
            return HomeAssistantResult(ok=False, source="ha", detail=f"Home Assistant request failed: {exc}")

        payload: Any | None = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text

        return HomeAssistantResult(ok=True, source="ha", detail="ok", data=payload, status_code=response.status_code)

    def healthcheck(self) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=True,
                source="mock",
                detail="Home Assistant not configured. Mock mode is active.",
                data={"connected": False},
            )
        return self._request("GET", trailing_slash=True)

    def get_state(self, entity_id: str) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=False,
                source="mock",
                detail=f"Mock state for {entity_id}",
                data={"entity_id": entity_id, "state": "unknown", "attributes": {}},
            )
        result = self._request("GET", f"states/{entity_id}")
        if not result.ok and result.status_code == 404:
            result.detail = f"Entity not found: {entity_id}"
        return result

    def list_states(self) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(ok=False, source="mock", detail="Home Assistant not configured.", data=[])
        return self._request("GET", "states")

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> HomeAssistantResult:
        if not self.enabled:
            return HomeAssistantResult(
                ok=False,
                source="mock",
                detail=f"Mock call to {domain}.{service}",
                data={"domain": domain, "service": service, "data": data},
            )
        return self._request("POST", f"services/{domain}/{service}", json=data)

    @staticmethod
    def _entity_domain(entity_id: str) -> str:
        domain, _, _object_id = entity_id.partition(".")
        return domain.strip().lower()

    def _refresh_state_until(self, entity_id: str, expected_state: str, *, attempts: int = 5, delay: float = 0.25) -> HomeAssistantResult:
        latest = self.get_state(entity_id)
        if latest.ok and str((latest.data or {}).get("state", "")).lower() == expected_state:
            return latest

        for _ in range(attempts - 1):
            time.sleep(delay)
            latest = self.get_state(entity_id)
            if latest.ok and str((latest.data or {}).get("state", "")).lower() == expected_state:
                return latest
        return latest

    def toggle_light(self, entity_id: str) -> HomeAssistantResult:
        if not self.enabled:
            current = self.get_state(entity_id)
            if not current.ok:
                return current
            state = str((current.data or {}).get("state", "unknown")).lower()
            return HomeAssistantResult(
                ok=False,
                source="mock",
                detail=f"Mock toggle for {entity_id}",
                data={"entity_id": entity_id, "state": state},
            )

        current = self.get_state(entity_id)
        if not current.ok:
            return current

        state = str((current.data or {}).get("state", "")).lower()
        domain = self._entity_domain(entity_id)
        if domain not in {"light", "switch"}:
            return HomeAssistantResult(
                ok=False,
                source="config",
                detail=f"Cannot toggle {entity_id}: unsupported domain '{domain or 'unknown'}'.",
                data=current.data,
            )
        if state == "on":
            service = "turn_off"
            expected_state = "off"
        elif state == "off":
            service = "turn_on"
            expected_state = "on"
        elif state in {"unknown", "unavailable", ""}:
            service = "turn_on"
            expected_state = "on"
        else:
            return HomeAssistantResult(
                ok=False,
                source="ha",
                detail=f"Cannot toggle {entity_id}: current state is {state or 'unknown' }.",
                data=current.data,
            )

        service_result = self.call_service(domain, service, {"entity_id": entity_id})
        refreshed = self._refresh_state_until(entity_id, expected_state)
        if refreshed.ok and str((refreshed.data or {}).get("state", "")).lower() == expected_state:
            return refreshed
        if not service_result.ok and refreshed.ok:
            return refreshed
        if not service_result.ok:
            return service_result
        return HomeAssistantResult(
            ok=False,
            source="ha",
            detail=f"Entity {entity_id} did not reach {expected_state} after {domain}.{service}.",
            data=refreshed.data if refreshed.ok else current.data,
            status_code=refreshed.status_code if refreshed.status_code is not None else service_result.status_code,
        )
