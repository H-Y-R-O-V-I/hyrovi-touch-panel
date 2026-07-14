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


if __name__ == "__main__":
    unittest.main()
