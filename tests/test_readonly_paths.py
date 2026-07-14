from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
import yaml

from app.admin.web import create_app
from app.config.loader import AdminConfig, AppConfig, EntityConfig, HomeAssistantConfig, TouchConfig, UIConfig, UpdateConfig
from app.doctor import run_doctor
from app.ui.dashboard import DashboardApp


class ReadOnlyPathTests(unittest.TestCase):
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

    def _config(self) -> AppConfig:
        return AppConfig(
            home_assistant=HomeAssistantConfig(url="http://homeassistant.local:8123", token="token"),
            ui=UIConfig(fullscreen=False, screen_width=800, screen_height=480, hide_cursor=True, refresh_interval=1.0),
            touch=TouchConfig(mode="pygame", enable_gestures=True),
            updates=UpdateConfig(),
            entities=EntityConfig(main_light="switch.lampe_wohnzimmer", temperature="sensor.temp", humidity="sensor.humidity"),
            admin=AdminConfig(),
        )

    def _config_file(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "home_assistant": {
                        "url": "http://homeassistant.local:8123",
                        "token": "secret",
                    },
                    "entities": {
                        "main_light": "switch.lampe_wohnzimmer",
                        "temperature": "sensor.temp",
                        "humidity": "sensor.humidity",
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0])
    @patch("app.ha.client.requests.request")
    def test_dashboard_refresh_uses_only_get_requests(self, mock_request, _monotonic) -> None:
        mock_request.side_effect = [
            self._response(200, {"message": "ok"}),
            self._response(200, {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.temp", "state": "21.4", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.humidity", "state": "48", "attributes": {}}),
        ]
        app = DashboardApp(self._config())
        app.screen = SimpleNamespace(get_size=lambda: (800, 480))

        app._refresh(force=True)

        self.assertEqual(mock_request.call_count, 4)
        self.assertTrue(all(call.args[0] == "GET" for call in mock_request.call_args_list))

    @patch("app.doctor._run_py_compile", return_value=(True, "Python syntax check passed."))
    @patch("app.doctor._python_files", return_value=[])
    @patch("app.doctor.read_release_metadata")
    @patch("app.doctor.current_release_dir")
    @patch("app.doctor.requests.get")
    @patch("app.ha.client.requests.request")
    @patch("app.doctor.subprocess.run")
    def test_doctor_uses_only_get_requests(self, mock_subprocess, mock_request, mock_get, mock_current_release, mock_read_metadata, _python_files, _compile) -> None:
        mock_current_release.return_value = Path("/tmp/release")
        mock_read_metadata.return_value = MagicMock(version="test")
        mock_subprocess.return_value = subprocess.CompletedProcess(args=["libinput"], returncode=0, stdout="", stderr="")
        mock_get.return_value = self._response(200, {"message": "ok"})
        mock_request.side_effect = [
            self._response(200, {"message": "ok"}),
            self._response(200, {"message": "ok"}),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "home_assistant": {"url": "http://homeassistant.local:8123", "token": "secret"},
                        "entities": {
                            "main_light": "switch.lampe_wohnzimmer",
                            "temperature": "sensor.temp",
                            "humidity": "sensor.humidity",
                        },
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            report = run_doctor(config_path)

        self.assertIsNotNone(report)
        self.assertTrue(all(call.args[0] == "GET" for call in mock_request.call_args_list))

    @patch("app.ha.client.requests.request")
    def test_admin_home_assistant_test_uses_only_get_requests(self, mock_request) -> None:
        mock_request.side_effect = [
            self._response(200, [
                {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {"friendly_name": "Wohnzimmer"}},
            ]),
            self._response(200, {"message": "ok"}),
            self._response(200, [
                {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {"friendly_name": "Wohnzimmer"}},
            ]),
            self._response(200, {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.temp", "state": "21.4", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.humidity", "state": "48", "attributes": {}}),
            self._response(200, {"entity_id": "switch.lampe_wohnzimmer", "state": "off", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.temp", "state": "21.4", "attributes": {}}),
            self._response(200, {"entity_id": "sensor.humidity", "state": "48", "attributes": {}}),
        ]
        app = create_app(self._config_file())
        client = app.test_client()
        response = client.get("/home-assistant/test")

        self.assertEqual(response.status_code, 200)
        self.assertIn("API", response.get_data(as_text=True))
        self.assertGreaterEqual(mock_request.call_count, 6)
        self.assertTrue(all(call.args[0] == "GET" for call in mock_request.call_args_list))


if __name__ == "__main__":
    unittest.main()
