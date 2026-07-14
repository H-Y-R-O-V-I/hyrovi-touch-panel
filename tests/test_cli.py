from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

import requests

from app.cli import _ha_actuator_test, _ha_test
from app.ha.client import HomeAssistantResult


class CliReadOnlyTests(unittest.TestCase):
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

    @patch("app.cli.load_config")
    @patch("app.cli.requests.request")
    def test_ha_test_uses_only_get_requests(self, mock_request, mock_load_config) -> None:
        config = MagicMock()
        config.home_assistant.url = "http://homeassistant.local:8123"
        config.home_assistant.token = "token"
        config.entities.main_light = "switch.lampe_wohnzimmer"
        config.entities.temperature = "sensor.temp"
        config.entities.humidity = "sensor.humidity"
        mock_load_config.return_value = config
        mock_request.side_effect = [
            self._response(200, {"message": "ok"}),
            self._response(200, {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.temp", "state": "21.4", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.humidity", "state": "48", "attributes": {}}),
        ]

        result = _ha_test(Namespace(config="/tmp/config.yaml"))

        self.assertEqual(result, 0)
        self.assertEqual(mock_request.call_count, 4)
        self.assertTrue(all(call.args[0] == "GET" for call in mock_request.call_args_list))

    @patch("app.cli._ha_client")
    def test_actuator_test_requires_confirm(self, mock_ha_client) -> None:
        result = _ha_actuator_test(Namespace(entity="switch.lampe_wohnzimmer", confirm=False, config="/tmp/config.yaml"))
        self.assertEqual(result, 2)
        mock_ha_client.assert_not_called()

    @patch("app.cli._ha_client")
    def test_actuator_test_runs_only_with_confirm(self, mock_ha_client) -> None:
        client = MagicMock()
        client.toggle_light.return_value = HomeAssistantResult(ok=True, source="ha", detail="ok", data={"state": "on"})
        mock_ha_client.return_value = (client, MagicMock())

        result = _ha_actuator_test(Namespace(entity="switch.lampe_wohnzimmer", confirm=True, config="/tmp/config.yaml"))

        self.assertEqual(result, 0)
        client.toggle_light.assert_called_once_with("switch.lampe_wohnzimmer")


if __name__ == "__main__":
    unittest.main()
