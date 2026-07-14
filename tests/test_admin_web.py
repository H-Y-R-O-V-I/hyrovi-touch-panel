from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.admin.web import create_app, _merge_home_assistant_config
from app.ha.client import HomeAssistantResult


class AdminWebTests(unittest.TestCase):
    def _config_file(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "home_assistant": {
                        "url": "http://homeassistant.local:8123",
                        "token": "super-secret-token",
                    },
                    "entities": {
                        "main_light": "light.test",
                        "temperature": "sensor.temp",
                        "humidity": "sensor.humidity",
                    },
                    "admin": {"pin": ""},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    @patch("app.admin.web.HomeAssistantClient.healthcheck", return_value=HomeAssistantResult(ok=True, source="ha", detail="ok"))
    @patch("app.admin.web.HomeAssistantClient.list_states", return_value=HomeAssistantResult(ok=True, source="ha", detail="ok", data=[]))
    @patch("app.admin.web.subprocess.run")
    def test_home_assistant_page_and_status_api_do_not_expose_token(self, mock_run, _list_states, _healthcheck) -> None:
        config_path = self._config_file()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        app = create_app(config_path)
        client = app.test_client()

        html_response = client.get("/home-assistant")
        body = html_response.get_data(as_text=True)
        self.assertEqual(html_response.status_code, 200)
        self.assertNotIn("super-secret-token", body)

        json_response = client.get("/api/home-assistant/status")
        json_body = json_response.get_data(as_text=True)
        self.assertEqual(json_response.status_code, 200)
        self.assertNotIn("super-secret-token", json_body)
        self.assertIn('"token_present": true', json_body)

    def test_blank_token_retains_existing_token(self) -> None:
        current = {
            "home_assistant": {"url": "http://homeassistant.local:8123", "token": "keep-me"},
            "entities": {"main_light": "light.old"},
        }
        ok, detail, merged = _merge_home_assistant_config(current, {"url": "http://homeassistant.local:8123", "token": "", "main_light": "light.new"})
        self.assertTrue(ok)
        self.assertEqual(detail, "Configuration updated.")
        self.assertEqual(merged["home_assistant"]["token"], "keep-me")
        self.assertEqual(merged["entities"]["main_light"], "light.new")


if __name__ == "__main__":
    unittest.main()
