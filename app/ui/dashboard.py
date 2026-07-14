from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pygame

from app.config.loader import AppConfig
from app.ha.client import HomeAssistantClient
from app.runtime import current_release_dir, read_release_metadata


BASE_WIDTH = 800
BASE_HEIGHT = 480
NAV_HEIGHT = 72
HEADER_HEIGHT = 72


@dataclass
class PanelSnapshot:
    ha_state: str = "Mock"
    light_state: str = "Mock"
    temperature: str = "--"
    humidity: str = "--"
    release: str = "unknown"
    connected: bool = False
    light_on: bool = False
    temperature_value: float = 21.8
    humidity_value: float = 46.0
    last_successful_fetch: str = "Noch keiner"
    error: str = ""


@dataclass
class HitTarget:
    label: str
    rect: pygame.Rect
    action: Callable[[], None]
    active: bool = False


@dataclass
class TouchPress:
    source: str
    pointer_id: int | None
    started_at: float
    start_pos: tuple[int, int]
    target: HitTarget | None
    blocked: bool = False


class DashboardApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = HomeAssistantClient.from_config(config)
        self.screen: pygame.Surface | None = None
        self.running = True
        self.page = "home"
        self.snapshot = PanelSnapshot()
        self.last_refresh = 0.0
        self.fonts: dict[str, pygame.font.Font] = {}
        self.targets: list[HitTarget] = []
        self.active_press: TouchPress | None = None
        self.input_enabled_at = 0.0
        self.last_action_at = 0.0
        self.tap_move_threshold = 28
        self.tap_debounce_seconds = 0.25

    def run(self) -> int:
        pygame.init()
        pygame.font.init()
        self._setup_display()
        self._load_fonts()
        self.input_enabled_at = time.monotonic() + 2.0
        self._refresh(force=True)

        clock = pygame.time.Clock()
        while self.running:
            self._handle_events()
            self._tick()
            self._render()
            clock.tick(30)

        pygame.quit()
        return 0

    def _setup_display(self) -> None:
        flags = pygame.SCALED
        if self.config.ui.fullscreen:
            flags |= pygame.FULLSCREEN
        else:
            flags |= pygame.RESIZABLE

        self.screen = pygame.display.set_mode(
            (self.config.ui.screen_width, self.config.ui.screen_height),
            flags,
        )
        pygame.display.set_caption("Hyrovi Touch Panel")
        if self.config.ui.hide_cursor:
            pygame.mouse.set_visible(False)
        pygame.event.clear()

    def _load_fonts(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        base = max(14, int(self._scale_value(18)))
        self.fonts["title"] = pygame.font.SysFont("DejaVu Sans", max(20, base + 12), bold=True)
        self.fonts["header"] = pygame.font.SysFont("DejaVu Sans", max(18, base + 6), bold=True)
        self.fonts["body"] = pygame.font.SysFont("DejaVu Sans", max(15, base))
        self.fonts["small"] = pygame.font.SysFont("DejaVu Sans", max(13, base - 4))
        self.fonts["button"] = pygame.font.SysFont("DejaVu Sans", max(18, base + 2), bold=True)

    def _handle_events(self) -> None:
        assert self.screen is not None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.type == pygame.VIDEORESIZE and not self.config.ui.fullscreen:
                self.screen = pygame.display.set_mode(event.size, pygame.SCALED | pygame.RESIZABLE)
                self._load_fonts()
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                self._touch_start(event)
            elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
                self._touch_end(event)

    def _touch_start(self, event: pygame.event.Event) -> None:
        if self.active_press is not None:
            return
        source_info = self._event_source(event)
        if source_info is None:
            return
        source, pointer_id = source_info
        now = time.monotonic()
        pos = self._event_position(event)
        if pos is None:
            return
        target = self._hit_target(pos)
        self.active_press = TouchPress(
            source=source,
            pointer_id=pointer_id,
            started_at=now,
            start_pos=pos,
            target=target,
            blocked=now < self.input_enabled_at,
        )

    def _touch_end(self, event: pygame.event.Event) -> None:
        press = self.active_press
        if press is None:
            return
        source_info = self._event_source(event)
        if source_info is None:
            return
        source, pointer_id = source_info
        if source != press.source or pointer_id != press.pointer_id:
            return
        pos = self._event_position(event)
        if pos is None:
            self.active_press = None
            return
        now = time.monotonic()
        delta_x = pos[0] - press.start_pos[0]
        delta_y = pos[1] - press.start_pos[1]
        distance_x = abs(delta_x)
        distance_y = abs(delta_y)
        self.active_press = None

        if press.blocked or now < self.input_enabled_at:
            return

        if distance_x > 90 and distance_x > distance_y:
            if self.config.touch.enable_gestures:
                self.page = "lights" if delta_x < 0 else "home"
            return
        if distance_y > 120 and distance_y > distance_x:
            if self.config.touch.enable_gestures:
                self.page = "system"
            return

        current_target = self._hit_target(pos)
        if current_target is None or press.target is None:
            return
        if current_target.label != press.target.label or current_target.rect != press.target.rect:
            return
        if distance_x > self.tap_move_threshold or distance_y > self.tap_move_threshold:
            return
        if now - self.last_action_at < self.tap_debounce_seconds:
            return
        self.last_action_at = now
        current_target.action()

    def _event_source(self, event: pygame.event.Event) -> tuple[str, int | None] | None:
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            if getattr(event, "button", 1) != 1:
                return None
            return "mouse", 1
        if event.type in (pygame.FINGERDOWN, pygame.FINGERUP):
            return "finger", int(getattr(event, "finger_id", 0))
        return None

    def _event_position(self, event: pygame.event.Event) -> tuple[int, int] | None:
        assert self.screen is not None
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return event.pos
        if event.type in (pygame.FINGERDOWN, pygame.FINGERUP):
            width, height = self.screen.get_size()
            return (int(event.x * width), int(event.y * height))
        return None

    def _tick(self) -> None:
        now = pygame.time.get_ticks() / 1000.0
        if now - self.last_refresh >= max(0.5, float(self.config.ui.refresh_interval)):
            self._refresh()
            self.last_refresh = now

    def _refresh(self, force: bool = False) -> None:
        release = current_release_dir()
        metadata = read_release_metadata(release) if release else None
        self.snapshot.release = metadata.version if metadata else "unknown"
        if not self.config.exists:
            self.snapshot.error = f"Konfig fehlt: {self.config.source_path}"

        ha = self.client.healthcheck()
        self.snapshot.connected = bool(ha.ok and ha.source == "ha")
        if ha.source == "mock":
            self.snapshot.ha_state = "Mock"
        elif ha.ok:
            self.snapshot.ha_state = "Verbunden"
        else:
            self.snapshot.ha_state = "Offline"
            self.snapshot.error = ha.detail

        if self.client.enabled and ha.ok:
            light = self.client.get_state(self.config.entities.main_light)
            temp = self.client.get_state(self.config.entities.temperature)
            humidity = self.client.get_state(self.config.entities.humidity)
            if light.ok and temp.ok and humidity.ok and isinstance(light.data, dict) and isinstance(temp.data, dict) and isinstance(humidity.data, dict):
                self.snapshot.light_state = self._state_label(light.data)
                self.snapshot.light_on = self._is_on(light.data)
                self.snapshot.temperature = self._format_value(temp.data, "temperature")
                self.snapshot.humidity = self._format_value(humidity.data, "humidity")
                self.snapshot.last_successful_fetch = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                self.snapshot.error = ""
            else:
                details = [result.detail for result in (light, temp, humidity) if not result.ok]
                if details:
                    self.snapshot.error = "; ".join(details)
        elif self.client.enabled and not ha.ok:
            self.snapshot.error = ha.detail
        elif not self.client.enabled:
            if force:
                self.snapshot.light_state = "Aus"
            jitter = 0.0 if force else random.uniform(-0.12, 0.12)
            humidity_delta = 0.0 if force else random.uniform(-0.25, 0.25)
            self.snapshot.temperature_value = round(max(18.0, min(27.0, self.snapshot.temperature_value + jitter)), 1)
            self.snapshot.humidity_value = round(max(30.0, min(66.0, self.snapshot.humidity_value + humidity_delta)), 1)
            self.snapshot.temperature = f"{self.snapshot.temperature_value:.1f} °C"
            self.snapshot.humidity = f"{self.snapshot.humidity_value:.1f} %"
            self.snapshot.light_state = "Ein" if self.snapshot.light_on else "Aus"

    def _state_label(self, payload: dict | None) -> str:
        if not payload:
            return "Unbekannt"
        state = str(payload.get("state", "unknown")).lower()
        if state == "on":
            return "Ein"
        if state == "off":
            return "Aus"
        if state == "unavailable":
            return "Nicht verfügbar"
        if state == "unknown":
            return "Unbekannt"
        return str(payload.get("state", "unknown"))

    def _is_on(self, payload: dict | None) -> bool:
        if not payload:
            return False
        return str(payload.get("state", "")).lower() == "on"

    def _format_value(self, payload: dict | None, kind: str) -> str:
        if not payload:
            return "--"
        state = str(payload.get("state", "--"))
        if state.lower() == "unavailable":
            return "Nicht verfügbar"
        if state.lower() == "unknown":
            return "Unbekannt"
        unit = payload.get("attributes", {}).get("unit_of_measurement", "°C" if kind == "temperature" else "%")
        return f"{state} {unit}".strip()

    def _render(self) -> None:
        assert self.screen is not None
        width, height = self.screen.get_size()
        scale = self._scale()
        offset_x = int((width - BASE_WIDTH * scale) / 2)
        offset_y = int((height - BASE_HEIGHT * scale) / 2)
        self.targets = []

        self.screen.fill((10, 13, 18))
        self._draw_background(scale, offset_x, offset_y)
        self._draw_header(scale, offset_x, offset_y)
        if self.snapshot.error:
            self._draw_error(scale, offset_x, offset_y)
        self._draw_page(scale, offset_x, offset_y)
        self._draw_navigation(scale, offset_x, offset_y)
        pygame.display.flip()

    def _draw_background(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        width = int(BASE_WIDTH * scale)
        height = int(BASE_HEIGHT * scale)
        glow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.circle(glow, (33, 87, 134, 45), (int(width * 0.18), int(height * 0.18)), int(140 * scale))
        pygame.draw.circle(glow, (22, 125, 92, 35), (int(width * 0.84), int(height * 0.2)), int(120 * scale))
        self.screen.blit(glow, (offset_x, offset_y))

    def _draw_header(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        rect = self._rect(0, 0, BASE_WIDTH, HEADER_HEIGHT, scale, offset_x, offset_y)
        self._rounded_rect(self.screen, rect, (18, 24, 33), 20)
        self._draw_text("Hyrovi Touch Panel", rect.x + self._scale_value(20, scale), rect.y + self._scale_value(14, scale), "title")
        clock = datetime.now().strftime("%H:%M")
        surf = self._font("title").render(clock, True, (220, 232, 242))
        self.screen.blit(surf, (rect.right - surf.get_width() - self._scale_value(20, scale), rect.y + self._scale_value(14, scale)))

    def _draw_error(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        rect = self._rect(24, 84, 752, 74, scale, offset_x, offset_y)
        self._panel(rect, (188, 84, 84))
        self._draw_text("Konfiguration oder Home Assistant fehlt", rect.x + self._scale_value(16, scale), rect.y + self._scale_value(10, scale), "header")
        self._draw_text(self.snapshot.error, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(38, scale), "small", (240, 210, 210))

    def _draw_page(self, scale: float, offset_x: int, offset_y: int) -> None:
        if self.page == "home":
            self._draw_home(scale, offset_x, offset_y)
        elif self.page == "lights":
            self._draw_lights(scale, offset_x, offset_y)
        else:
            self._draw_system(scale, offset_x, offset_y)

    def _draw_home(self, scale: float, offset_x: int, offset_y: int) -> None:
        self._draw_page_title("Home", scale, offset_x, offset_y)
        cards = [
            ("Home Assistant", self.snapshot.ha_state, (67, 120, 190)),
            ("Wohnzimmer Licht", self.snapshot.light_state, (56, 140, 96)),
            ("Temperatur", self.snapshot.temperature, (182, 121, 53)),
            ("Luftfeuchte", self.snapshot.humidity, (96, 103, 198)),
        ]
        for index, (label, value, accent) in enumerate(cards):
            col = index % 2
            row = index // 2
            rect = self._rect(24 + col * 380, 116 + row * 98, 356, 82, scale, offset_x, offset_y)
            self._status_card(label, value, accent, rect, scale)
        self._draw_text(f"Letzter erfolgreicher Abruf: {self.snapshot.last_successful_fetch}", offset_x + self._scale_value(24, scale), offset_y + self._scale_value(418, scale), "small", (160, 171, 182))
        self._touch_button("Lichter", self._rect(24, 330, 236, 74, scale, offset_x, offset_y), scale, lambda: self._set_page("lights"), accent=self.page == "lights")
        self._touch_button("System", self._rect(282, 330, 236, 74, scale, offset_x, offset_y), scale, lambda: self._set_page("system"), accent=self.page == "system")
        self._touch_button("Aktualisieren", self._rect(540, 330, 236, 74, scale, offset_x, offset_y), scale, self._force_refresh)

    def _draw_lights(self, scale: float, offset_x: int, offset_y: int) -> None:
        self._draw_page_title("Lichter", scale, offset_x, offset_y)
        info = self._rect(24, 116, 752, 108, scale, offset_x, offset_y)
        self._panel(info)
        self._draw_text("Wohnzimmer", info.x + self._scale_value(18, scale), info.y + self._scale_value(14, scale), "header")
        self._draw_text(f"Status: {self.snapshot.light_state}", info.x + self._scale_value(18, scale), info.y + self._scale_value(44, scale), "body")
        self._draw_text("Große Tap-Flächen und später echte Home-Assistant-Services.", info.x + self._scale_value(18, scale), info.y + self._scale_value(72, scale), "small", (170, 178, 186))
        toggle = "Licht ausschalten" if self.snapshot.light_on else "Licht einschalten"
        self._touch_button(toggle, self._rect(24, 250, 420, 88, scale, offset_x, offset_y), scale, self._toggle_light, accent=True)
        self._touch_button("Zurück", self._rect(464, 250, 312, 88, scale, offset_x, offset_y), scale, lambda: self._set_page("home"))
        self._status_card("Release", self.snapshot.release, (84, 104, 132), self._rect(24, 356, 752, 74, scale, offset_x, offset_y), scale)

    def _draw_system(self, scale: float, offset_x: int, offset_y: int) -> None:
        self._draw_page_title("System", scale, offset_x, offset_y)
        box = self._rect(24, 116, 752, 238, scale, offset_x, offset_y)
        self._panel(box)
        lines = [
            ("Fullscreen", "Ja" if self.config.ui.fullscreen else "Nein"),
            ("Screen", f"{self.config.ui.screen_width} x {self.config.ui.screen_height}"),
            ("Refresh", f"{self.config.ui.refresh_interval:.1f} s"),
            ("Touch", self.config.touch.mode),
            ("Release", self.snapshot.release),
        ]
        y = box.y + self._scale_value(16, scale)
        for label, value in lines:
            self._draw_text(label, box.x + self._scale_value(18, scale), y, "small", (160, 172, 184))
            self._draw_text(value, box.x + self._scale_value(180, scale), y, "body")
            y += self._scale_value(40, scale)
        self._touch_button("Home", self._rect(24, 376, 752, 52, scale, offset_x, offset_y), scale, lambda: self._set_page("home"))

    def _draw_page_title(self, title: str, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        surf = self._font("title").render(title, True, (238, 243, 247))
        self.screen.blit(surf, (offset_x + self._scale_value(24, scale), offset_y + self._scale_value(92, scale)))

    def _draw_navigation(self, scale: float, offset_x: int, offset_y: int) -> None:
        nav_top = BASE_HEIGHT - NAV_HEIGHT
        items = [("Home", "home"), ("Lichter", "lights"), ("System", "system")]
        for index, (label, page) in enumerate(items):
            rect = self._rect(index * (BASE_WIDTH / 3) + 8, nav_top + 10, BASE_WIDTH / 3 - 16, 52, scale, offset_x, offset_y)
            self._touch_button(label, rect, scale, lambda page=page: self._set_page(page), accent=self.page == page)

    def _status_card(self, label: str, value: str, accent: tuple[int, int, int], rect: pygame.Rect, scale: float) -> None:
        self._panel(rect, accent)
        self._draw_text(label, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(12, scale), "small", (160, 171, 182))
        self._draw_text(value, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(36, scale), "header")

    def _touch_button(self, label: str, rect: pygame.Rect, scale: float, action: Callable[[], None], accent: bool = False) -> None:
        assert self.screen is not None
        self.targets.append(HitTarget(label=label, rect=rect, action=action, active=accent))
        fill = (34, 42, 52) if not accent else (51, 98, 150)
        border = (80, 98, 115) if not accent else (112, 168, 220)
        self._rounded_rect(self.screen, rect, fill, 16)
        pygame.draw.rect(self.screen, border, rect, width=max(1, int(self._scale_value(2, scale))), border_radius=max(8, int(self._scale_value(16, scale))))
        text = self._font("button").render(label, True, (235, 240, 244))
        self.screen.blit(text, (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2))

    def _panel(self, rect: pygame.Rect, accent: tuple[int, int, int] | None = None) -> None:
        assert self.screen is not None
        self._rounded_rect(self.screen, rect, (20, 28, 38), 18)
        pygame.draw.rect(self.screen, accent or (52, 66, 80), rect, width=2, border_radius=18)

    def _draw_text(self, text: str, x: int, y: int, font_key: str, color: tuple[int, int, int] = (238, 242, 245)) -> None:
        assert self.screen is not None
        surf = self._font(font_key).render(text, True, color)
        self.screen.blit(surf, (x, y))

    def _rounded_rect(self, surface: pygame.Surface, rect: pygame.Rect, color: tuple[int, int, int], radius: int) -> None:
        pygame.draw.rect(surface, color, rect, border_radius=radius)

    def _font(self, key: str) -> pygame.font.Font:
        return self.fonts[key]

    def _scale(self) -> float:
        assert self.screen is not None
        width, height = self.screen.get_size()
        return min(width / BASE_WIDTH, height / BASE_HEIGHT)

    def _scale_value(self, value: float, scale: float | None = None) -> int:
        if scale is None:
            scale = self._scale()
        return int(round(value * scale))

    def _rect(self, x: float, y: float, w: float, h: float, scale: float, offset_x: int, offset_y: int) -> pygame.Rect:
        return pygame.Rect(
            offset_x + self._scale_value(x, scale),
            offset_y + self._scale_value(y, scale),
            self._scale_value(w, scale),
            self._scale_value(h, scale),
        )

    def _set_page(self, page: str) -> None:
        self.page = page

    def _hit_target(self, pos: tuple[int, int]) -> HitTarget | None:
        for target in reversed(self.targets):
            if target.rect.collidepoint(pos):
                return target
        return None

    def _toggle_light(self) -> None:
        if not self.client.enabled:
            self.snapshot.light_on = not self.snapshot.light_on
            self.snapshot.light_state = "Ein" if self.snapshot.light_on else "Aus"
            return

        result = self.client.toggle_light(self.config.entities.main_light)
        if result.ok and isinstance(result.data, dict):
            self.snapshot.light_state = self._state_label(result.data)
            self.snapshot.light_on = self._is_on(result.data)
            self.snapshot.error = ""
        else:
            self.snapshot.error = result.detail

    def _force_refresh(self) -> None:
        self._refresh(force=True)
