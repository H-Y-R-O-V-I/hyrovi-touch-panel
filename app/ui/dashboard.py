from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
from typing import Callable

import pygame

from app.config.loader import AppConfig
from app.ha.client import HomeAssistantClient
from app.runtime import current_release_dir, read_release_metadata
from app.ui.components import clamp, panel, rounded_rect, text, wrap_text
from app.ui.models import DashboardPageConfig, DashboardTileConfig, TileState
from app.ui.theme import BASE_HEIGHT, BASE_WIDTH, CONTENT_BOTTOM, CONTENT_TOP, HEADER_HEIGHT, NAV_HEIGHT, Theme


THEME = Theme()
STATE_LABELS = {
    "on": "Ein",
    "off": "Aus",
    "unavailable": "Nicht verfügbar",
    "unknown": "Unbekannt",
}


@dataclass(slots=True)
class PanelSnapshot:
    ha_state: str = "Offline"
    light_state: str = "Unbekannt"
    temperature: str = "--"
    humidity: str = "--"
    release: str = "unknown"
    connected: bool = False
    light_on: bool = False
    temperature_value: float = 21.8
    humidity_value: float = 46.0
    last_successful_fetch: str = "Noch keiner"
    error: str = ""


@dataclass(slots=True)
class HitTarget:
    label: str
    rect: pygame.Rect
    action: Callable[[], None]
    active: bool = False
    target_id: str = ""


@dataclass(slots=True)
class TouchPress:
    source: str
    pointer_id: int | None
    started_at: float
    start_pos: tuple[int, int]
    target: HitTarget | None
    blocked: bool = False
    consumed: bool = False


class DashboardApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = HomeAssistantClient.from_config(config)
        self.screen: pygame.Surface | None = None
        self.running = True
        self.page_index = 0
        self.page_order = self._page_order()
        self.snapshot = PanelSnapshot()
        self.tile_states: dict[str, TileState] = {}
        self.entity_cache: dict[str, dict[str, object]] = {}
        self.last_refresh = 0.0
        self.fonts: dict[str, pygame.font.Font] = {}
        self.targets: list[HitTarget] = []
        self.active_press: TouchPress | None = None
        self.input_enabled_at = 0.0
        self.last_action_at = 0.0
        self.tap_move_threshold = 28
        self.tap_debounce_seconds = 0.28
        self._page_lookup = {page.id: page for page in self.config.dashboard.pages if page.id}
        if "home" in self.page_order:
            self.page_index = self.page_order.index("home")

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
        self.fonts["title"] = pygame.font.SysFont("DejaVu Sans", max(22, base + 10), bold=True)
        self.fonts["header"] = pygame.font.SysFont("DejaVu Sans", max(18, base + 5), bold=True)
        self.fonts["body"] = pygame.font.SysFont("DejaVu Sans", max(15, base))
        self.fonts["small"] = pygame.font.SysFont("DejaVu Sans", max(13, base - 4))
        self.fonts["button"] = pygame.font.SysFont("DejaVu Sans", max(17, base + 1), bold=True)

    def _page_order(self) -> list[str]:
        pages = [
            page
            for page in self.config.dashboard.pages
            if page.id and page.visible
        ]
        pages.sort(key=lambda page: (int(getattr(page, "order", 0)), page.id))
        return [page.id for page in pages]

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
        pos = self._event_position(event)
        if pos is None:
            return
        now = time.monotonic()
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
        if press is None or press.consumed:
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
        start_target = press.target
        current_target = self._hit_target(pos)
        delta_x = pos[0] - press.start_pos[0]
        delta_y = pos[1] - press.start_pos[1]
        self.active_press = None

        if press.blocked or now < self.input_enabled_at:
            return
        if current_target is None or start_target is None:
            return
        if current_target.target_id != start_target.target_id:
            return
        if abs(delta_x) > self.tap_move_threshold or abs(delta_y) > self.tap_move_threshold:
            return
        if now - self.last_action_at < self.tap_debounce_seconds:
            return

        self.last_action_at = now
        press.consumed = True
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
        now = time.monotonic()
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

        if not self.client.enabled:
            self._refresh_mock(force=force)
            return

        if not ha.ok:
            return

        entity_ids = self._dashboard_entity_ids()
        errors: list[str] = []
        for entity_id in entity_ids:
            result = self.client.get_state(entity_id)
            if not result.ok or not isinstance(result.data, dict):
                errors.append(result.detail)
                continue
            self.entity_cache[entity_id] = result.data
            self.tile_states[entity_id] = self._tile_state_for_entity(entity_id, result.data)

        self._update_summary_states()
        if errors:
            self.snapshot.error = "; ".join(dict.fromkeys(errors))
        else:
            self.snapshot.error = ""
            self.snapshot.last_successful_fetch = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    def _refresh_mock(self, force: bool = False) -> None:
        if force:
            self.snapshot.light_state = "Aus"
        else:
            self.snapshot.light_on = not self.snapshot.light_on
            self.snapshot.temperature_value = round(max(18.0, min(27.0, self.snapshot.temperature_value + 0.1)), 1)
            self.snapshot.humidity_value = round(max(30.0, min(66.0, self.snapshot.humidity_value + 0.1)), 1)
        self.snapshot.light_state = "Ein" if self.snapshot.light_on else "Aus"
        self.snapshot.temperature = f"{self.snapshot.temperature_value:.1f} °C"
        self.snapshot.humidity = f"{self.snapshot.humidity_value:.1f} %"

    def _update_summary_states(self) -> None:
        light_id = self.config.entities.main_light
        temp_id = self.config.entities.temperature
        humidity_id = self.config.entities.humidity

        light_state = self.entity_cache.get(light_id, {})
        temp_state = self.entity_cache.get(temp_id, {})
        humidity_state = self.entity_cache.get(humidity_id, {})

        self.snapshot.light_state = self._state_label(light_state)
        self.snapshot.light_on = self._is_on(light_state)
        self.snapshot.temperature = self._format_value(temp_state, "temperature")
        self.snapshot.humidity = self._format_value(humidity_state, "humidity")

    def _dashboard_entity_ids(self) -> list[str]:
        seen: set[str] = set()
        entity_ids: list[str] = []
        for page in self._effective_pages():
            for tile in page.tiles:
                entity_id = tile.entity_id.strip()
                if not entity_id or entity_id in seen:
                    continue
                seen.add(entity_id)
                entity_ids.append(entity_id)
        return entity_ids

    def _state_label(self, payload: dict[str, object] | None) -> str:
        if not payload:
            return "Unbekannt"
        state = str(payload.get("state", "unknown")).lower()
        if state in STATE_LABELS:
            return STATE_LABELS[state]
        return str(payload.get("state", "unknown"))

    def _is_on(self, payload: dict[str, object] | None) -> bool:
        if not payload:
            return False
        return str(payload.get("state", "")).lower() == "on"

    def _format_value(self, payload: dict[str, object] | None, kind: str) -> str:
        if not payload:
            return "--"
        state = str(payload.get("state", "--"))
        lowered = state.lower()
        if lowered == "unavailable":
            return "Nicht verfügbar"
        if lowered == "unknown":
            return "Unbekannt"
        attributes = payload.get("attributes", {})
        unit = "°C" if kind == "temperature" else "%"
        if isinstance(attributes, dict):
            unit = str(attributes.get("unit_of_measurement", unit))
        return f"{state} {unit}".strip()

    def _render(self) -> None:
        assert self.screen is not None
        width, height = self.screen.get_size()
        scale = self._scale()
        offset_x = int((width - BASE_WIDTH * scale) / 2)
        offset_y = int((height - BASE_HEIGHT * scale) / 2)
        self.targets = []

        self.screen.fill(THEME.bg)
        self._draw_background(scale, offset_x, offset_y)
        self._draw_header(scale, offset_x, offset_y)
        if self.snapshot.error:
            self._draw_banner(scale, offset_x, offset_y, self.snapshot.error)
        self._draw_page(scale, offset_x, offset_y)
        self._draw_navigation(scale, offset_x, offset_y)
        pygame.display.flip()

    def _draw_background(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        width = int(BASE_WIDTH * scale)
        height = int(BASE_HEIGHT * scale)
        glow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.circle(glow, THEME.bg_glow_a, (int(width * 0.18), int(height * 0.18)), int(140 * scale))
        pygame.draw.circle(glow, THEME.bg_glow_b, (int(width * 0.84), int(height * 0.2)), int(120 * scale))
        self.screen.blit(glow, (offset_x, offset_y))

    def _draw_header(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        rect = self._rect(0, 0, BASE_WIDTH, HEADER_HEIGHT, scale, offset_x, offset_y)
        rounded_rect(self.screen, rect, THEME.header, 20)
        pygame.draw.rect(self.screen, THEME.header_border, rect, width=2, border_radius=20)
        text(self.screen, self._font("title"), "Hyrovi Touch Panel", rect.x + self._scale_value(20, scale), rect.y + self._scale_value(12, scale), THEME.text)
        page_label = self._current_page().label if self._current_page() else "Dashboard"
        text(self.screen, self._font("small"), page_label, rect.x + self._scale_value(22, scale), rect.y + self._scale_value(42, scale), THEME.text_muted)
        clock = datetime.now().strftime("%H:%M")
        surf = self._font("title").render(clock, True, THEME.text)
        self.screen.blit(surf, (rect.right - surf.get_width() - self._scale_value(20, scale), rect.y + self._scale_value(14, scale)))

    def _draw_banner(self, scale: float, offset_x: int, offset_y: int, message: str) -> None:
        rect = self._rect(24, 78, 752, 54, scale, offset_x, offset_y)
        panel(self.screen, rect, THEME.warn, 18)
        self._draw_multiline(message, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(12, scale), "small", THEME.text)

    def _draw_page(self, scale: float, offset_x: int, offset_y: int) -> None:
        page = self._current_page()
        if page is None:
            return
        title_rect = self._rect(24, 94, 752, 34, scale, offset_x, offset_y)
        text(self.screen, self._font("header"), page.label, title_rect.x, title_rect.y, THEME.text)
        cards = self._page_cards(page)
        rects = self._card_layout(len(cards), scale, offset_x, offset_y)
        for tile, rect in zip(cards, rects):
            self._draw_tile(tile, rect, scale)

    def _draw_navigation(self, scale: float, offset_x: int, offset_y: int) -> None:
        nav_top = BASE_HEIGHT - NAV_HEIGHT
        nav_ids = self.page_order
        if not nav_ids:
            return
        width = BASE_WIDTH / max(1, len(nav_ids))
        for index, page_id in enumerate(nav_ids):
            page = self._page_lookup.get(page_id) or DashboardPageConfig(id=page_id, label=page_id.title(), tiles=[])
            rect = self._rect(index * width + 8, nav_top + 10, width - 16, 52, scale, offset_x, offset_y)
            self.targets.append(HitTarget(page.label, rect, lambda page_id=page_id: self._set_page(page_id), active=self._current_page_id() == page_id, target_id=f"nav:{page_id}"))
            self._button(rect, page.label, accent=self._current_page_id() == page_id)

    def _draw_tile(self, tile: DashboardTileConfig, rect: pygame.Rect, scale: float) -> None:
        state = self._tile_state(tile)
        fill = state.fill or THEME.off_fill
        border = state.border or THEME.header_border
        text_color = state.text or THEME.text
        secondary = state.secondary_text or THEME.text_muted
        rounded_rect(self.screen, rect, fill, 18)
        pygame.draw.rect(self.screen, border, rect, width=2, border_radius=18)
        self._draw_multiline(state.friendly_name or tile.label or tile.id, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(12, scale), "header", text_color)
        value = state.state
        self._draw_multiline(value, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(42, scale), "body", text_color)
        if state.info:
            self._draw_multiline(state.info, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(74, scale), "small", secondary)
        if state.error:
            self._draw_multiline(state.error, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(74, scale), "small", THEME.bad)
        action_label = state.action_label or self._action_label(tile)
        if action_label:
            badge = pygame.Rect(rect.right - self._scale_value(120, scale), rect.bottom - self._scale_value(42, scale), self._scale_value(104, scale), self._scale_value(28, scale))
            rounded_rect(self.screen, badge, THEME.action_fill, 12)
            self._draw_multiline(action_label, badge.x + self._scale_value(10, scale), badge.y + self._scale_value(4, scale), "small", THEME.text)
        action = self._tile_action(tile)
        if action is not None and state.is_available and not state.busy and not state.locked:
            self.targets.append(HitTarget(tile.label or tile.id, rect, action, active=state.is_on, target_id=tile.id))

    def _button(self, rect: pygame.Rect, label: str, accent: bool = False) -> None:
        fill = THEME.panel_alt if not accent else THEME.accent
        border = THEME.header_border if not accent else THEME.accent_bright
        rounded_rect(self.screen, rect, fill, 16)
        pygame.draw.rect(self.screen, border, rect, width=2, border_radius=16)
        surf = self._font("button").render(label, True, THEME.text)
        self.screen.blit(surf, (rect.centerx - surf.get_width() / 2, rect.centery - surf.get_height() / 2))

    def _draw_multiline(self, value: str, x: int, y: int, font_key: str, color: tuple[int, int, int]) -> None:
        assert self.screen is not None
        font = self._font(font_key)
        max_width = max(12, int((self.screen.get_width() - x - 24) / max(1, font.size("x")[0])))
        line_y = y
        for line in wrap_text(value, width=max_width):
            surf = font.render(line, True, color)
            self.screen.blit(surf, (x, line_y))
            line_y += surf.get_height() + 2

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

    def _current_page(self) -> DashboardPageConfig | None:
        if not self.page_order:
            return None
        page_id = self._current_page_id()
        return self._page_lookup.get(page_id)

    def _current_page_id(self) -> str:
        if not self.page_order:
            return "home"
        self.page_index = clamp(self.page_index, 0, len(self.page_order) - 1)
        return self.page_order[self.page_index]

    def _set_page(self, page_id: str) -> None:
        if page_id not in self.page_order:
            return
        self.page_index = self.page_order.index(page_id)

    def _hit_target(self, pos: tuple[int, int]) -> HitTarget | None:
        for target in reversed(self.targets):
            if target.rect.collidepoint(pos):
                return target
        return None

    def _effective_pages(self) -> list[DashboardPageConfig]:
        pages = [page for page in self.config.dashboard.pages if page.visible]
        pages.sort(key=lambda page: (int(getattr(page, "order", 0)), page.id))
        return pages

    def _page_cards(self, page: DashboardPageConfig) -> list[DashboardTileConfig]:
        tiles = [tile for tile in page.tiles if tile.visible]
        tiles.sort(key=lambda tile: (int(getattr(tile, "order", 0)), tile.id))
        return tiles

    def _tile_state(self, tile: DashboardTileConfig) -> TileState:
        if tile.id == "ha_status":
            return TileState(entity_id="", state=self.snapshot.ha_state, info=self.snapshot.error or "Live-Status", friendly_name="Home Assistant", domain="system", action_label="Aktualisieren", fill=THEME.sensor_fill, border=THEME.sensor_border, text=THEME.text, secondary_text=THEME.text_muted)
        if tile.id == "release":
            return TileState(entity_id="", state=self.snapshot.release, friendly_name="Release", domain="system", fill=THEME.sensor_fill, border=THEME.sensor_border, text=THEME.text, secondary_text=THEME.text_muted)
        if tile.id == "last_fetch":
            return TileState(entity_id="", state=self.snapshot.last_successful_fetch, friendly_name="Letzter Abruf", domain="system", fill=THEME.sensor_fill, border=THEME.sensor_border, text=THEME.text, secondary_text=THEME.text_muted)
        if tile.entity_id:
            payload = self.entity_cache.get(tile.entity_id, {})
            return self._tile_state_for_entity(tile.entity_id, payload, tile=tile)
        return TileState(entity_id=tile.entity_id, state="--", friendly_name=tile.label or tile.id, domain=tile.type, info=tile.info, fill=THEME.off_fill, border=THEME.header_border, text=THEME.text, secondary_text=THEME.text_muted)

    def _tile_state_for_entity(self, entity_id: str, payload: dict[str, object], tile: DashboardTileConfig | None = None) -> TileState:
        state = str(payload.get("state", "unknown"))
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        attributes = payload.get("attributes", {})
        friendly_name = tile.label if tile and tile.label else ""
        info = tile.info if tile else ""
        if isinstance(attributes, dict):
            friendly_name = friendly_name or str(attributes.get("friendly_name", ""))
            if not info:
                info = str(attributes.get("unit_of_measurement", ""))
        if not friendly_name:
            friendly_name = entity_id
        action_label = self._action_label(tile, state=state, domain=domain)
        locked = state.lower() in {"unknown", "unavailable", ""}
        palette_state = TileState(
            entity_id=entity_id,
            state=state,
            friendly_name=friendly_name,
            domain=domain,
            info=info,
            busy=False,
            locked=locked,
            action_label=action_label,
        )
        fill, border, text_color, secondary = self._tile_palette(tile, palette_state)
        return TileState(
            entity_id=entity_id,
            state=self._state_label(payload),
            friendly_name=friendly_name,
            domain=domain,
            info=info,
            busy=False,
            locked=locked,
            action_label=action_label,
            fill=fill,
            border=border,
            text=text_color,
            secondary_text=secondary,
        )

    def _action_label(self, tile: DashboardTileConfig | None, *, state: str = "", domain: str = "") -> str:
        if tile is None:
            return ""
        action = (tile.action or "").lower()
        if action in {"none", ""}:
            return ""
        if action == "refresh":
            return "Nur lesen"
        if action == "toggle":
            if state.lower() == "on":
                return "Ausschalten"
            if state.lower() == "off":
                return "Einschalten"
            if domain in {"light", "switch", "input_boolean"}:
                return "Schalten"
            return ""
        if action == "trigger":
            return "Starten"
        if action == "on":
            return "Einschalten"
        if action == "off":
            return "Ausschalten"
        return action.title()

    def _tile_action(self, tile: DashboardTileConfig) -> Callable[[], None] | None:
        action = (tile.action or "").lower()
        if action == "refresh":
            return self._force_refresh
        if not tile.entity_id:
            return None
        if action in {"", "toggle"}:
            return lambda tile=tile: self._toggle_entity(tile.entity_id)
        if action == "on":
            return lambda tile=tile: self._turn_on_entity(tile.entity_id)
        if action == "off":
            return lambda tile=tile: self._turn_off_entity(tile.entity_id)
        if action == "trigger":
            return lambda tile=tile: self._trigger_entity(tile.entity_id)
        if action == "scene":
            return lambda tile=tile: self._turn_on_scene(tile.entity_id)
        return None

    def _tile_palette(self, tile: DashboardTileConfig, state: TileState) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
        domain = state.domain or (tile.entity_id.split(".", 1)[0] if "." in tile.entity_id else tile.type)
        lowered = state.state.lower()
        if state.busy:
            return THEME.busy_fill, THEME.accent_bright, THEME.text, THEME.text_muted
        if lowered == "unavailable":
            return THEME.off_fill, THEME.unavailable_border, THEME.text, THEME.text_muted
        if lowered == "unknown":
            return THEME.off_fill, THEME.unknown_border, THEME.text, THEME.text_muted
        if lowered == "on":
            if domain == "light":
                return THEME.light_on_fill, THEME.light_on_fill, THEME.text_dark, THEME.text_dark
            if domain == "switch":
                return THEME.switch_on_fill, THEME.switch_on_fill, THEME.text, THEME.text
            if domain == "input_boolean":
                return THEME.boolean_on_fill, THEME.boolean_on_fill, THEME.text_dark, THEME.text_dark
            if domain in {"script", "automation", "scene"} or tile.type in {"script", "automation", "scene", "action"}:
                return THEME.action_fill, THEME.action_fill, THEME.text, THEME.text_muted
        if tile.type in {"sensor", "binary_sensor"} or domain in {"sensor", "binary_sensor"}:
            return THEME.sensor_fill, THEME.sensor_border, THEME.text, THEME.text_muted
        if tile.type in {"script", "automation", "scene"} or domain in {"script", "automation", "scene"}:
            return THEME.action_fill, THEME.sensor_border, THEME.text, THEME.text_muted
        return THEME.off_fill, THEME.header_border, THEME.text, THEME.text_muted

    def _turn_on_entity(self, entity_id: str) -> None:
        self._actuate_entity(entity_id, "turn_on")

    def _turn_off_entity(self, entity_id: str) -> None:
        self._actuate_entity(entity_id, "turn_off")

    def _trigger_entity(self, entity_id: str) -> None:
        self._actuate_entity(entity_id, "trigger")

    def _turn_on_scene(self, entity_id: str) -> None:
        self._actuate_entity(entity_id, "scene")

    def _toggle_entity(self, entity_id: str) -> None:
        if not self.client.enabled:
            current = self.tile_states.get(entity_id)
            if current is None:
                return
            current.state = "Ein" if current.is_on else "Aus"
            return
        current = self.client.get_state(entity_id)
        if not current.ok or not isinstance(current.data, dict):
            self.snapshot.error = current.detail
            return
        state = str(current.data.get("state", "")).lower()
        domain = self.client.entity_domain(entity_id)
        if domain not in {"light", "switch", "input_boolean"}:
            self.snapshot.error = f"Kann {entity_id} nicht schalten: Domain {domain or 'unbekannt'}."
            return
        if state == "on":
            result = self.client.turn_off(entity_id)
        elif state == "off":
            result = self.client.turn_on(entity_id)
        else:
            self.snapshot.error = f"Kann {entity_id} nicht schalten: Zustand {state or 'unbekannt'}."
            return
        self._apply_action_result(entity_id, result, expected=None)

    def _actuate_entity(self, entity_id: str, mode: str) -> None:
        if not self.client.enabled:
            self.snapshot.error = "Home Assistant ist nicht konfiguriert."
            return
        current = self.client.get_state(entity_id)
        if not current.ok or not isinstance(current.data, dict):
            self.snapshot.error = current.detail
            return
        state = str(current.data.get("state", "")).lower()
        if mode == "turn_on":
            result = self.client.turn_on(entity_id)
        elif mode == "turn_off":
            result = self.client.turn_off(entity_id)
        elif mode == "trigger":
            result = self.client.trigger(entity_id)
        elif mode == "scene":
            result = self.client.turn_on_scene(entity_id)
        else:
            self.snapshot.error = f"Unbekannte Aktion für {entity_id}."
            return
        self._apply_action_result(entity_id, result, expected=None, before_state=state)

    def _apply_action_result(self, entity_id: str, result, expected: str | None, before_state: str | None = None) -> None:
        if not result.ok:
            self.snapshot.error = result.detail
            return
        refreshed = self.client.get_state(entity_id)
        if not refreshed.ok or not isinstance(refreshed.data, dict):
            self.snapshot.error = refreshed.detail if not refreshed.ok else f"Konnte Zustand von {entity_id} nicht lesen."
            return
        refreshed_state = str(refreshed.data.get("state", "")).lower()
        if before_state is not None and refreshed_state == before_state:
            self.snapshot.error = f"Entity {entity_id} hat sich nach der Aktion nicht verändert."
            return
        self.entity_cache[entity_id] = refreshed.data
        self.tile_states[entity_id] = self._tile_state_for_entity(entity_id, refreshed.data)
        self._update_summary_states()
        self.snapshot.error = ""
        self.snapshot.last_successful_fetch = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        if before_state is not None and str(refreshed.data.get("state", "")).lower() == before_state:
            return

    def _force_refresh(self) -> None:
        self._refresh(force=True)

    def _card_layout(self, count: int, scale: float, offset_x: int, offset_y: int) -> list[pygame.Rect]:
        if count <= 0:
            return []
        cols = 2 if count > 1 else 1
        gap = self._scale_value(14, scale)
        left = offset_x + self._scale_value(24, scale)
        top = offset_y + self._scale_value(CONTENT_TOP, scale)
        available_width = self._scale_value(BASE_WIDTH - 48, scale)
        available_height = self._scale_value(BASE_HEIGHT - CONTENT_TOP - CONTENT_BOTTOM, scale)
        card_width = (available_width - gap * (cols - 1)) // cols
        rows = (count + cols - 1) // cols
        card_height = max(self._scale_value(92, scale), (available_height - gap * (rows - 1)) // max(1, rows))
        rects: list[pygame.Rect] = []
        for index in range(count):
            row = index // cols
            col = index % cols
            x = left + col * (card_width + gap)
            y = top + row * (card_height + gap)
            rects.append(pygame.Rect(x, y, card_width, card_height))
        return rects
