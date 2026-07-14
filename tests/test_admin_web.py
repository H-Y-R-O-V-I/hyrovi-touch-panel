from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.admin.web import (
    create_app,
    _dashboard_apply_preview_form,
    _dashboard_update_from_form,
    _dashboard_validate,
    _merge_home_assistant_config,
)
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

    @patch("app.admin.web.run_doctor")
    def test_health_endpoint_returns_json_without_token(self, mock_run_doctor) -> None:
        mock_report = mock_run_doctor.return_value
        mock_report.ok = True
        mock_report.to_dict.return_value = {"checks": []}
        config_path = self._config_file()
        app = create_app(config_path)
        client = app.test_client()

        response = client.get("/health")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('"ok": true', body)
        self.assertNotIn("super-secret-token", body)

    @patch("app.admin.web.HomeAssistantClient.list_states", return_value=HomeAssistantResult(ok=True, source="ha", detail="ok", data=[]))
    def test_dashboard_page_does_not_expose_token(self, _list_states) -> None:
        config_path = self._config_file()
        app = create_app(config_path)
        client = app.test_client()

        response = client.get("/dashboard")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("super-secret-token", body)
        self.assertIn("Karte bearbeiten", body)
        self.assertIn("Seiten", body)
        self.assertIn('name="tile_id"', body)
        self.assertIn('Neue Karten-ID', body)

    def test_dashboard_validation_rejects_duplicate_entity_on_same_page(self) -> None:
        errors = _dashboard_validate(
            {
                "pages": [
                    {
                        "id": "home",
                        "label": "Home",
                        "tiles": [
                            {"id": "a", "type": "entity", "entity_id": "switch.lampe_wohnzimmer", "action": "toggle"},
                            {"id": "b", "type": "entity", "entity_id": "switch.lampe_wohnzimmer", "action": "toggle"},
                        ],
                    }
                ]
            }
        )
        self.assertTrue(any("Duplicate entity" in error for error in errors))

    def test_dashboard_validation_allows_same_entity_on_different_pages(self) -> None:
        errors = _dashboard_validate(
            {
                "pages": [
                    {
                        "id": "home",
                        "label": "Home",
                        "tiles": [
                            {"id": "a", "type": "entity", "entity_id": "switch.lampe_wohnzimmer", "action": "toggle"},
                        ],
                    },
                    {
                        "id": "switches",
                        "label": "Schalter",
                        "tiles": [
                            {"id": "b", "type": "entity", "entity_id": "switch.lampe_wohnzimmer", "action": "toggle"},
                        ],
                    },
                ]
            }
        )
        self.assertFalse(any("Duplicate entity" in error for error in errors))

    def test_dashboard_update_supports_new_tile_id_dropdown(self) -> None:
        data = {
            "dashboard": {
                "pages": [
                    {
                        "id": "home",
                        "label": "Home",
                        "tiles": [],
                    }
                ]
            }
        }
        ok, detail, updated = _dashboard_update_from_form(
            data,
            {
                "dashboard_action": "save_tile",
                "page_id": "home",
                "tile_id": "__new__",
                "new_tile_id": "living_room_light",
                "entity_id": "switch.lampe_wohnzimmer",
                "type": "entity",
                "action": "toggle",
                "label": "Lampe Wohnzimmer",
                "icon": "",
                "info": "",
                "accent": "",
                "order": "0",
            },
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "Dashboard updated.")
        self.assertEqual(updated["dashboard"]["pages"][0]["tiles"][0]["id"], "living_room_light")

    def test_dashboard_preview_form_applies_unsaved_tile_changes(self) -> None:
        data = {
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
                                "page": "home",
                                "type": "entity",
                                "entity_id": "switch.lampe_wohnzimmer",
                                "label": "Lampe",
                                "action": "toggle",
                                "icon": "",
                                "info": "",
                                "order": 0,
                                "visible": True,
                                "accent": "",
                                "show_on_home": False,
                            }
                        ],
                    }
                ]
            }
        }
        ok, detail, draft, preview_page_id, preview_entity_id, preview_state = _dashboard_apply_preview_form(
            data,
            {
                "page_id": "home",
                "page_label": "Wohnzimmer",
                "page_order": "2",
                "page_visible": "on",
                "tile_id": "lamp",
                "entity_id": "switch.lampe_wohnzimmer",
                "type": "entity",
                "action": "toggle",
                "label": "Wohnzimmerlampe",
                "icon": "",
                "info": "",
                "accent": "#ffcc00",
                "order": "1",
                "visible": "on",
                "show_on_home": "on",
                "preview_page_id": "home",
                "preview_entity_id": "switch.lampe_wohnzimmer",
                "preview_state": "off",
            },
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "Preview updated.")
        self.assertEqual(preview_page_id, "home")
        self.assertEqual(preview_entity_id, "switch.lampe_wohnzimmer")
        self.assertEqual(preview_state, "off")
        self.assertEqual(draft["dashboard"]["pages"][0]["label"], "Wohnzimmer")
        self.assertEqual(draft["dashboard"]["pages"][0]["tiles"][0]["label"], "Wohnzimmerlampe")

    @patch("app.admin.web._render_dashboard_preview_png", return_value=(True, "Preview rendered.", b"PNGDATA"))
    def test_dashboard_preview_endpoint_returns_png(self, _mock_preview) -> None:
        config_path = self._config_file()
        app = create_app(config_path)
        client = app.test_client()

        response = client.post(
            "/dashboard/preview",
            data={
                "page_id": "home",
                "preview_page_id": "home",
                "preview_entity_id": "switch.lampe_wohnzimmer",
                "preview_state": "live",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertEqual(response.get_data(), b"PNGDATA")


if __name__ == "__main__":
    unittest.main()
