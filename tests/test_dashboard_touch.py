from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import pygame

from app.config.loader import AdminConfig, AppConfig, EntityConfig, HomeAssistantConfig, TouchConfig, UIConfig, UpdateConfig
from app.ui.dashboard import DashboardApp, HitTarget
from app.ui.models import DashboardConfig, DashboardPageConfig, DashboardTileConfig


class DashboardTouchTests(unittest.TestCase):
    def _config(self) -> AppConfig:
        return AppConfig(
            home_assistant=HomeAssistantConfig(url="http://homeassistant.local:8123", token="token"),
            ui=UIConfig(fullscreen=False, screen_width=800, screen_height=480, hide_cursor=True, refresh_interval=1.0),
            touch=TouchConfig(mode="pygame", enable_gestures=True),
            updates=UpdateConfig(),
            entities=EntityConfig(main_light="switch.lampe_wohnzimmer", temperature="sensor.temp", humidity="sensor.humidity"),
            dashboard=DashboardConfig(
                pages=[
                    DashboardPageConfig(
                        id="home",
                        label="Home",
                        visible=True,
                        order=0,
                        tiles=[
                            DashboardTileConfig(
                                id="lamp",
                                page="home",
                                type="entity",
                                entity_id="switch.lampe_wohnzimmer",
                                label="Lampe Wohnzimmer",
                                action="toggle",
                                order=0,
                            )
                        ],
                    )
                ]
            ),
            admin=AdminConfig(),
        )

    def _app_with_button(self):
        app = DashboardApp(self._config())
        app.screen = SimpleNamespace(get_size=lambda: (800, 480))
        action = MagicMock()
        app.targets = [HitTarget(label="Lamp", rect=pygame.Rect(100, 100, 200, 100), action=action)]
        app.input_enabled_at = 0.0
        app.last_action_at = -10.0
        return app, action

    def _mouse(self, event_type: int, pos: tuple[int, int]) -> pygame.event.Event:
        return pygame.event.Event(event_type, {"pos": pos, "button": 1})

    def _finger(self, event_type: int, pos: tuple[int, int], finger_id: int = 7) -> pygame.event.Event:
        return pygame.event.Event(event_type, {"x": pos[0] / 800, "y": pos[1] / 480, "finger_id": finger_id})

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0])
    def test_mousedown_alone_does_not_fire(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (120, 120)))
        self.assertIsNotNone(app.active_press)
        action.assert_not_called()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.2])
    def test_fingerdown_and_up_on_same_button_fire_once(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._finger(pygame.FINGERDOWN, (120, 120)))
        app._touch_end(self._finger(pygame.FINGERUP, (124, 124)))
        action.assert_called_once()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.1])
    def test_start_guard_ignores_stale_touch(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app.input_enabled_at = 20.0
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (120, 120)))
        app._touch_end(self._mouse(pygame.MOUSEBUTTONUP, (120, 120)))
        action.assert_not_called()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.15])
    def test_swipe_does_not_fire(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (120, 120)))
        app._touch_end(self._mouse(pygame.MOUSEBUTTONUP, (320, 210)))
        action.assert_not_called()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.2])
    def test_down_outside_up_inside_does_not_fire(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (20, 20)))
        app._touch_end(self._mouse(pygame.MOUSEBUTTONUP, (120, 120)))
        action.assert_not_called()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.1, 10.2])
    def test_duplicate_finger_and_mouse_events_fire_once(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._finger(pygame.FINGERDOWN, (120, 120), finger_id=1))
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (120, 120)))
        app._touch_end(self._finger(pygame.FINGERUP, (120, 120), finger_id=1))
        app._touch_end(self._mouse(pygame.MOUSEBUTTONUP, (120, 120)))
        action.assert_called_once()

    @patch("app.ui.dashboard.time.monotonic", side_effect=[10.0, 10.2])
    def test_button_up_within_same_button_fires_once(self, _monotonic) -> None:
        app, action = self._app_with_button()
        app._touch_start(self._mouse(pygame.MOUSEBUTTONDOWN, (120, 120)))
        app._touch_end(self._mouse(pygame.MOUSEBUTTONUP, (140, 130)))
        action.assert_called_once()

    def test_configured_page_is_not_extended_with_defaults(self) -> None:
        app = DashboardApp(self._config())
        page = app._effective_pages()[0]
        cards = app._page_cards(page)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].id, "lamp")

    def test_on_state_uses_full_fill_palette(self) -> None:
        app = DashboardApp(self._config())
        tile = DashboardTileConfig(id="lamp", page="home", type="entity", entity_id="switch.lampe_wohnzimmer", label="Lampe Wohnzimmer", action="toggle")
        state = app._tile_state_for_entity(
            "switch.lampe_wohnzimmer",
            {"entity_id": "switch.lampe_wohnzimmer", "state": "on", "attributes": {}},
            tile=tile,
        )
        self.assertIsInstance(state.fill, tuple)
        self.assertIsInstance(state.border, tuple)
        self.assertEqual(len(state.fill), 3)
        self.assertEqual(len(state.border), 3)

    def test_on_state_without_tile_metadata_does_not_crash(self) -> None:
        app = DashboardApp(self._config())
        state = app._tile_state_for_entity(
            "switch.lampe_wohnzimmer",
            {"entity_id": "switch.lampe_wohnzimmer", "state": "on", "attributes": {}},
        )
        self.assertEqual(state.state, "Ein")
        self.assertIsInstance(state.fill, tuple)
        self.assertEqual(len(state.fill), 3)


if __name__ == "__main__":
    unittest.main()
