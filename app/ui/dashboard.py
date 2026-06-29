from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pygame

from app.config.loader import AppConfig
from app.ha.client import healthcheck


BASE_WIDTH = 800
BASE_HEIGHT = 480
NAV_HEIGHT = 72
HEADER_HEIGHT = 72
PADDING = 20


@dataclass
class MockSnapshot:
    ha_connected: str = "Mock"
    living_room_light: str = "Mock"
    temperature: str = "Mock"
    humidity: str = "Mock"
    pi_status: str = "Mock"
    light_is_on: bool = False
    temperature_value: float = 21.8
    humidity_value: float = 46.0


@dataclass
class HitTarget:
    label: str
    rect: pygame.Rect
    action: Callable[[], None]
    active: bool = False


class DashboardApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.screen: pygame.Surface | None = None
        self.running = True
        self.page = "home"
        self.snapshot = MockSnapshot()
        self.last_mock_update = 0.0
        self.last_clock_text = ""
        self.fonts: dict[str, pygame.font.Font] = {}
        self.targets: list[HitTarget] = []

    def run(self) -> int:
        pygame.init()
        pygame.font.init()
        self._setup_display()
        self._build_fonts()
        self._refresh_snapshot(force=True)

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
        if self.config.fullscreen:
            flags |= pygame.FULLSCREEN
        else:
            flags |= pygame.RESIZABLE

        self.screen = pygame.display.set_mode(
            (self.config.screen_width, self.config.screen_height),
            flags,
        )
        pygame.display.set_caption("Hyrovi Touch Panel")

    def _build_fonts(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        base = max(14, int(self._scale_value(18)))
        self.fonts["title"] = pygame.font.SysFont("DejaVu Sans", max(18, base + 8), bold=True)
        self.fonts["header"] = pygame.font.SysFont("DejaVu Sans", max(16, base + 2), bold=True)
        self.fonts["body"] = pygame.font.SysFont("DejaVu Sans", max(14, base))
        self.fonts["small"] = pygame.font.SysFont("DejaVu Sans", max(12, base - 4))
        self.fonts["button"] = pygame.font.SysFont("DejaVu Sans", max(16, base + 1), bold=True)

    def _handle_events(self) -> None:
        assert self.screen is not None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.type == pygame.VIDEORESIZE and not self.config.fullscreen:
                self.screen = pygame.display.set_mode(event.size, pygame.SCALED | pygame.RESIZABLE)
                self._build_fonts()
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                self._handle_pointer_down(event)

    def _handle_pointer_down(self, event: pygame.event.Event) -> None:
        pos = self._event_position(event)
        if pos is None:
            return
        for target in reversed(self.targets):
            if target.rect.collidepoint(pos):
                target.action()
                return

    def _event_position(self, event: pygame.event.Event) -> tuple[int, int] | None:
        assert self.screen is not None
        if event.type == pygame.MOUSEBUTTONDOWN:
            return event.pos
        if event.type == pygame.FINGERDOWN:
            width, height = self.screen.get_size()
            x = int(event.x * width)
            y = int(event.y * height)
            return (x, y)
        return None

    def _tick(self) -> None:
        now = pygame.time.get_ticks() / 1000.0
        if now - self.last_mock_update >= max(1, int(self.config.refresh_interval)):
            self._refresh_snapshot()
            self.last_mock_update = now

    def _refresh_snapshot(self, force: bool = False) -> None:
        jitter = 0.0 if force else random.uniform(-0.15, 0.15)
        self.snapshot.temperature_value = round(
            max(18.0, min(26.5, self.snapshot.temperature_value + jitter)),
            1,
        )
        humidity_delta = 0.0 if force else random.uniform(-0.3, 0.3)
        self.snapshot.humidity_value = round(
            max(30.0, min(65.0, self.snapshot.humidity_value + humidity_delta)),
            1,
        )
        self.snapshot.temperature = f"{self.snapshot.temperature_value:.1f} C"
        self.snapshot.humidity = f"{self.snapshot.humidity_value:.1f} %"
        self.snapshot.living_room_light = "An" if self.snapshot.light_is_on else "Aus"

    def _render(self) -> None:
        assert self.screen is not None
        width, height = self.screen.get_size()
        scale = self._scale()
        offset_x = int((width - BASE_WIDTH * scale) / 2)
        offset_y = int((height - BASE_HEIGHT * scale) / 2)

        self.targets = []
        self.screen.fill((12, 16, 22))
        self._draw_background_glow(scale, offset_x, offset_y)
        self._draw_header(scale, offset_x, offset_y)
        self._draw_page(scale, offset_x, offset_y)
        self._draw_navigation(scale, offset_x, offset_y)
        pygame.display.flip()

    def _draw_background_glow(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        width = int(BASE_WIDTH * scale)
        height = int(BASE_HEIGHT * scale)
        glow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.circle(glow, (34, 80, 120, 50), (int(width * 0.18), int(height * 0.18)), int(140 * scale))
        pygame.draw.circle(glow, (20, 110, 90, 40), (int(width * 0.82), int(height * 0.24)), int(120 * scale))
        self.screen.blit(glow, (offset_x, offset_y))

    def _draw_header(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        header_rect = self._rect(0, 0, BASE_WIDTH, HEADER_HEIGHT, scale, offset_x, offset_y)
        self._rounded_rect(self.screen, header_rect, (17, 24, 33), 18)

        title = self._font("title").render("Hyrovi Touch Panel", True, (240, 245, 250))
        self.screen.blit(title, (header_rect.x + self._scale_value(22, scale), header_rect.y + self._scale_value(14, scale)))

        clock_text = datetime.now().strftime("%H:%M")
        if clock_text != self.last_clock_text:
            self.last_clock_text = clock_text
        clock_surface = self._font("title").render(clock_text, True, (210, 225, 240))
        clock_x = header_rect.right - clock_surface.get_width() - self._scale_value(24, scale)
        clock_y = header_rect.y + self._scale_value(14, scale)
        self.screen.blit(clock_surface, (clock_x, clock_y))

    def _draw_page(self, scale: float, offset_x: int, offset_y: int) -> None:
        if self.page == "home":
            self._draw_home(scale, offset_x, offset_y)
        elif self.page == "lights":
            self._draw_lights(scale, offset_x, offset_y)
        else:
            self._draw_system(scale, offset_x, offset_y)

    def _draw_home(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        self._draw_page_title("Home", scale, offset_x, offset_y)
        card_w = 352
        card_h = 90
        gap = 18
        start_x = 24
        start_y = 114

        cards = [
            ("HA verbunden", self.snapshot.ha_connected, (57, 110, 168)),
            ("Wohnzimmer Licht", self.snapshot.living_room_light, (53, 124, 92)),
            ("Temperatur", self.snapshot.temperature, (163, 111, 48)),
            ("Pi Status", self.snapshot.pi_status, (98, 95, 184)),
        ]

        for index, (label, value, accent) in enumerate(cards):
            col = index % 2
            row = index // 2
            rect = self._rect(
                start_x + col * (card_w + gap),
                start_y + row * (card_h + gap),
                card_w,
                card_h,
                scale,
                offset_x,
                offset_y,
            )
            self._status_card(label, value, accent, rect, scale)

        quick_actions_y = 318
        quick_actions = [
            ("Lichter", "lights", lambda: self._set_page("lights")),
            ("System", "system", lambda: self._set_page("system")),
            ("Aktualisieren", "refresh", self._force_refresh),
        ]
        for index, (label, page_key, action) in enumerate(quick_actions):
            rect = self._rect(
                24 + index * 246,
                quick_actions_y,
                228,
                66,
                scale,
                offset_x,
                offset_y,
            )
            self._touch_button(label, rect, scale, action, accent=page_key == self.page)

    def _draw_lights(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        self._draw_page_title("Lichter", scale, offset_x, offset_y)

        info_rect = self._rect(24, 118, 752, 108, scale, offset_x, offset_y)
        self._panel(info_rect)
        self._write_text("Wohnzimmer", info_rect.x + self._scale_value(18, scale), info_rect.y + self._scale_value(14, scale), "header")
        self._write_text(
            f"Status: {self.snapshot.living_room_light}",
            info_rect.x + self._scale_value(18, scale),
            info_rect.y + self._scale_value(44, scale),
            "body",
            color=(220, 230, 240),
        )
        self._write_text(
            "Spater kann hier ein Home-Assistant-Service call direkt aufgerufen werden.",
            info_rect.x + self._scale_value(18, scale),
            info_rect.y + self._scale_value(72, scale),
            "small",
            color=(165, 175, 185),
        )

        toggle_label = "Wohnzimmer ausschalten" if self.snapshot.light_is_on else "Wohnzimmer einschalten"
        toggle_rect = self._rect(24, 250, 420, 88, scale, offset_x, offset_y)
        self._touch_button(toggle_label, toggle_rect, scale, self._toggle_light, accent=True)

        back_rect = self._rect(464, 250, 312, 88, scale, offset_x, offset_y)
        self._touch_button("Zuruck zu Home", back_rect, scale, lambda: self._set_page("home"))

        state_rect = self._rect(24, 356, 752, 74, scale, offset_x, offset_y)
        self._status_card("Mock Device", "Nur lokale Vorschau", (70, 95, 120), state_rect, scale)

    def _draw_system(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        self._draw_page_title("System", scale, offset_x, offset_y)
        sys_rect = self._rect(24, 116, 752, 280, scale, offset_x, offset_y)
        self._panel(sys_rect)

        lines = [
            ("App-Modus", "Mock Dashboard"),
            ("Fullscreen", "Ja" if self.config.fullscreen else "Nein"),
            ("Screen", f"{self.config.screen_width} x {self.config.screen_height}"),
            ("Refresh", f"{self.config.refresh_interval} s"),
            ("HA Healthcheck", healthcheck().detail),
        ]

        y = sys_rect.y + self._scale_value(16, scale)
        for label, value in lines:
            self._write_text(label, sys_rect.x + self._scale_value(18, scale), y, "small", color=(150, 165, 180))
            self._write_text(value, sys_rect.x + self._scale_value(180, scale), y, "body", color=(230, 235, 240))
            y += self._scale_value(42, scale)

        back_rect = self._rect(24, 416, 752, 52, scale, offset_x, offset_y)
        self._touch_button("Zuruck zu Home", back_rect, scale, lambda: self._set_page("home"))

    def _draw_page_title(self, title: str, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.screen is not None
        surf = self._font("title").render(title, True, (235, 240, 245))
        self.screen.blit(surf, (offset_x + self._scale_value(24, scale), offset_y + self._scale_value(92, scale)))

    def _draw_navigation(self, scale: float, offset_x: int, offset_y: int) -> None:
        nav_top = BASE_HEIGHT - NAV_HEIGHT
        item_width = 800 / 3
        items = [
            ("Home", "home"),
            ("Lichter", "lights"),
            ("System", "system"),
        ]
        for index, (label, page) in enumerate(items):
            rect = self._rect(
                index * item_width + 8,
                nav_top + 10,
                item_width - 16,
                52,
                scale,
                offset_x,
                offset_y,
            )
            self._touch_button(label, rect, scale, lambda page=page: self._set_page(page), accent=self.page == page)

    def _status_card(
        self,
        label: str,
        value: str,
        accent: tuple[int, int, int],
        rect: pygame.Rect,
        scale: float,
    ) -> None:
        assert self.screen is not None
        self._panel(rect, accent)
        self._write_text(label, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(12, scale), "small", color=(155, 170, 180))
        self._write_text(value, rect.x + self._scale_value(16, scale), rect.y + self._scale_value(38, scale), "header", color=(245, 248, 250))

    def _touch_button(
        self,
        label: str,
        rect: pygame.Rect,
        scale: float,
        action: Callable[[], None],
        accent: bool = False,
    ) -> None:
        assert self.screen is not None
        self.targets.append(HitTarget(label=label, rect=rect, action=action, active=accent))
        fill = (34, 42, 52) if not accent else (51, 93, 140)
        border = (78, 96, 115) if not accent else (110, 160, 210)
        text_color = (232, 238, 244)
        self._rounded_rect(self.screen, rect, fill, 16)
        pygame.draw.rect(self.screen, border, rect, width=max(1, int(self._scale_value(2, scale))), border_radius=max(8, int(self._scale_value(16, scale))))
        text = self._font("button").render(label, True, text_color)
        self.screen.blit(
            text,
            (
                rect.centerx - text.get_width() / 2,
                rect.centery - text.get_height() / 2,
            ),
        )

    def _panel(self, rect: pygame.Rect, accent: tuple[int, int, int] | None = None) -> None:
        assert self.screen is not None
        self._rounded_rect(self.screen, rect, (20, 28, 38), 18)
        border_color = accent or (52, 66, 80)
        pygame.draw.rect(self.screen, border_color, rect, width=2, border_radius=18)

    def _write_text(
        self,
        text: str,
        x: int,
        y: int,
        font_key: str,
        color: tuple[int, int, int] = (238, 242, 245),
    ) -> None:
        assert self.screen is not None
        surface = self._font(font_key).render(text, True, color)
        self.screen.blit(surface, (x, y))

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

    def _rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        scale: float,
        offset_x: int,
        offset_y: int,
    ) -> pygame.Rect:
        return pygame.Rect(
            offset_x + self._scale_value(x, scale),
            offset_y + self._scale_value(y, scale),
            self._scale_value(w, scale),
            self._scale_value(h, scale),
        )

    def _set_page(self, page: str) -> None:
        self.page = page

    def _toggle_light(self) -> None:
        self.snapshot.light_is_on = not self.snapshot.light_is_on
        self.snapshot.living_room_light = "An" if self.snapshot.light_is_on else "Aus"

    def _force_refresh(self) -> None:
        self._refresh_snapshot(force=True)
