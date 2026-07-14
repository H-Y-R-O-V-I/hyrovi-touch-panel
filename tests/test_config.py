from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import yaml

from app.config.loader import HomeAssistantUrlError, load_config, normalize_home_assistant_url


class ConfigTests(unittest.TestCase):
    def test_valid_url_is_preserved(self) -> None:
        self.assertEqual(
            normalize_home_assistant_url("http://homeassistant.local:8123"),
            "http://homeassistant.local:8123",
        )

    def test_trailing_slash_is_removed(self) -> None:
        self.assertEqual(
            normalize_home_assistant_url("https://homeassistant.example.com/"),
            "https://homeassistant.example.com",
        )

    def test_broken_triple_slash_url_is_repaired(self) -> None:
        self.assertEqual(
            normalize_home_assistant_url("http:///homeassistant.local:8123"),
            "http://homeassistant.local:8123",
        )

    def test_url_without_host_is_rejected(self) -> None:
        with self.assertRaises(HomeAssistantUrlError):
            normalize_home_assistant_url("http:///")

    def test_load_config_repairs_salvageable_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "home_assistant": {
                            "url": "http:///homeassistant.local:8123",
                            "token": "secret",
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.home_assistant.url, "http://homeassistant.local:8123")
            self.assertEqual(config.home_assistant.token, "secret")

    def test_existing_dashboard_is_not_extended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "dashboard": {
                            "pages": [
                                {
                                    "id": "home",
                                    "label": "Home",
                                    "visible": True,
                                    "order": 0,
                                    "tiles": [
                                        {
                                            "id": "lamp",
                                            "type": "entity",
                                            "page": "home",
                                            "entity_id": "switch.lampe_wohnzimmer",
                                            "label": "Lampe Wohnzimmer",
                                            "action": "toggle",
                                            "visible": True,
                                            "order": 0,
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(len(config.dashboard.pages), 1)
            self.assertEqual(config.dashboard.pages[0].id, "home")
            self.assertEqual(len(config.dashboard.pages[0].tiles), 1)
            self.assertEqual(config.dashboard.pages[0].tiles[0].id, "lamp")

    def test_missing_dashboard_uses_fallback_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "entities": {
                            "main_light": "switch.lampe_wohnzimmer",
                            "temperature": "sensor.temp",
                            "humidity": "sensor.humidity",
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertGreaterEqual(len(config.dashboard.pages), 1)
            self.assertEqual(config.dashboard.pages[0].id, "home")


if __name__ == "__main__":
    unittest.main()
