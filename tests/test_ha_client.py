from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from app.ha.client import HomeAssistantClient


class HomeAssistantClientTests(unittest.TestCase):
    def _response(self, status_code: int = 200, payload=None, text: str = ""):
        response = MagicMock()
        response.status_code = status_code
        response.content = b"yes" if payload is not None or text else b""
        response.json = MagicMock(return_value=payload)
        response.text = text
        response.ok = 200 <= status_code < 300
        if status_code >= 400:
            error = requests.HTTPError(response=response)
            response.raise_for_status = MagicMock(side_effect=error)
        else:
            response.raise_for_status = MagicMock(return_value=None)
        return response

    def test_api_url_has_no_triple_slash(self) -> None:
        client = HomeAssistantClient("http://homeassistant.local:8123/", "token")
        self.assertEqual(client._api_url("states/light.test"), "http://homeassistant.local:8123/api/states/light.test")
        self.assertEqual(client._api_url(trailing_slash=True), "http://homeassistant.local:8123/api/")

    @patch("app.ha.client.requests.request")
    def test_healthcheck_success(self, mock_request) -> None:
        mock_request.return_value = self._response(200, {"message": "ok"})
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.healthcheck()
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "ha")
        self.assertEqual(result.data, {"message": "ok"})

    @patch("app.ha.client.requests.request")
    def test_healthcheck_401(self, mock_request) -> None:
        mock_request.return_value = self._response(401, {"message": "nope"})
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.healthcheck()
        self.assertFalse(result.ok)
        self.assertIn("401 Unauthorized", result.detail)

    @patch("app.ha.client.requests.request")
    def test_healthcheck_timeout(self, mock_request) -> None:
        mock_request.side_effect = requests.Timeout()
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.healthcheck()
        self.assertFalse(result.ok)
        self.assertIn("Timeout", result.detail)

    @patch("app.ha.client.requests.request")
    def test_healthcheck_dns_error(self, mock_request) -> None:
        mock_request.side_effect = requests.ConnectionError("Name or service not known")
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.healthcheck()
        self.assertFalse(result.ok)
        self.assertIn("DNS error", result.detail)

    @patch("app.ha.client.requests.request")
    def test_get_state_404_is_entity_not_found(self, mock_request) -> None:
        mock_request.return_value = self._response(404, {"message": "missing"})
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.get_state("light.missing")
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "Entity not found: light.missing")

    @patch("app.ha.client.requests.request")
    def test_toggle_light_turns_on_and_refreshes_state(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(200, {"result": "ok"}),
            self._response(200, {"entity_id": "light.test", "state": "on", "attributes": {}}),
        ]
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.toggle_light("light.test")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["state"], "on")
        self.assertEqual(mock_request.call_count, 3)

    @patch("app.ha.client.requests.request")
    def test_toggle_switch_uses_switch_domain(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"result": "ok"}),
            self._response(200, {"entity_id": "switch.test", "state": "on", "attributes": {}}),
        ]
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.toggle_light("switch.test")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["state"], "on")
        self.assertEqual(mock_request.call_args_list[1].args[1], "http://homeassistant.local:8123/api/services/switch/turn_on")

    @patch("app.ha.client.requests.request")
    def test_service_error_keeps_result_failed(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(500, {"message": "boom"}),
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "light.test", "state": "off", "attributes": {}}),
        ]
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.toggle_light("light.test")
        self.assertFalse(result.ok)
        self.assertIn("HTTP 500", result.detail)
        self.assertEqual(mock_request.call_count, 7)

    @patch("app.ha.client.requests.request")
    def test_service_error_but_state_changes_is_success(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(500, {"message": "boom"}),
            self._response(200, {"entity_id": "switch.test", "state": "on", "attributes": {}}),
        ]
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.toggle_light("switch.test")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["state"], "on")

    @patch("app.ha.client.requests.request")
    def test_service_success_but_state_does_not_change_is_failure(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"result": "ok"}),
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "switch.test", "state": "off", "attributes": {}}),
        ]
        client = HomeAssistantClient("http://homeassistant.local:8123", "token")
        result = client.toggle_light("switch.test")
        self.assertFalse(result.ok)
        self.assertIn("did not reach on", result.detail)


if __name__ == "__main__":
    unittest.main()
