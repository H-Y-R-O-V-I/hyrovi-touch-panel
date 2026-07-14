from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pygame

from app.ui.components import panel, rounded_rect, text, wrap_text
from app.ui.models import DashboardPageConfig
from app.ui.theme import BASE_HEIGHT, BASE_WIDTH, CONTENT_BOTTOM, CONTENT_TOP, HEADER_HEIGHT, NAV_HEIGHT, Theme

if TYPE_CHECKING:
    from app.ui.dashboard import DashboardApp


THEME = Theme()


class DashboardRenderer:
    def __init__(self, app: "DashboardApp") -> None:
        self.app = app

    def render(self, present: bool = True) -> None:
        assert self.app.screen is not None
        width, height = self.app.screen.get_size()
        scale = self.app._scale()
        offset_x = int((width - BASE_WIDTH * scale) / 2)
        offset_y = int((height - BASE_HEIGHT * scale) / 2)
        self.app.targets = []

        self.app.screen.fill(THEME.bg)
        self._draw_background(scale, offset_x, offset_y)
        self._draw_header(scale, offset_x, offset_y)
        if self.app.snapshot.error:
            self._draw_banner(scale, offset_x, offset_y, self.app.snapshot.error)
        self._draw_page(scale, offset_x, offset_y)
        self._draw_navigation(scale, offset_x, offset_y)
        if present:
            pygame.display.flip()

    def _draw_background(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.app.screen is not None
        width = int(BASE_WIDTH * scale)
        height = int(BASE_HEIGHT * scale)
        glow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.circle(glow, THEME.bg_glow_a, (int(width * 0.18), int(height * 0.18)), int(140 * scale))
        pygame.draw.circle(glow, THEME.bg_glow_b, (int(width * 0.84), int(height * 0.2)), int(120 * scale))
        self.app.screen.blit(glow, (offset_x, offset_y))

    def _draw_header(self, scale: float, offset_x: int, offset_y: int) -> None:
        assert self.app.screen is not None
        rect = self.app._rect(0, 0, BASE_WIDTH, HEADER_HEIGHT, scale, offset_x, offset_y)
        rounded_rect(self.app.screen, rect, THEME.header, 20)
        pygame.draw.rect(self.app.screen, THEME.header_border, rect, width=2, border_radius=20)
        text(self.app.screen, self.app._font("title"), "Hyrovi Touch Panel", rect.x + self.app._scale_value(20, scale), rect.y + self.app._scale_value(12, scale), THEME.text)
        page_label = self.app._current_page().label if self.app._current_page() else "Dashboard"
        text(self.app.screen, self.app._font("small"), page_label, rect.x + self.app._scale_value(22, scale), rect.y + self.app._scale_value(42, scale), THEME.text_muted)
        clock = datetime.now().strftime("%H:%M")
        surf = self.app._font("title").render(clock, True, THEME.text)
        self.app.screen.blit(surf, (rect.right - surf.get_width() - self.app._scale_value(20, scale), rect.y + self.app._scale_value(14, scale)))

    def _draw_banner(self, scale: float, offset_x: int, offset_y: int, message: str) -> None:
        rect = self.app._rect(24, 78, 752, 54, scale, offset_x, offset_y)
        panel(self.app.screen, rect, THEME.warn, 18)
        self._draw_multiline(message, rect.x + self.app._scale_value(16, scale), rect.y + self.app._scale_value(12, scale), "small", THEME.text)

    def _draw_page(self, scale: float, offset_x: int, offset_y: int) -> None:
        page = self.app._current_page()
        if page is None:
            return
        title_rect = self.app._rect(24, 94, 752, 34, scale, offset_x, offset_y)
        text(self.app.screen, self.app._font("header"), page.label, title_rect.x, title_rect.y, THEME.text)
        cards = self.app._page_cards(page)
        rects = self.app._card_layout(len(cards), scale, offset_x, offset_y)
        for tile, rect in zip(cards, rects):
            self._draw_tile(tile, rect, scale)

    def _draw_navigation(self, scale: float, offset_x: int, offset_y: int) -> None:
        nav_top = BASE_HEIGHT - NAV_HEIGHT
        nav_ids = self.app.page_order
        if not nav_ids:
            return
        width = BASE_WIDTH / max(1, len(nav_ids))
        for index, page_id in enumerate(nav_ids):
            page = self.app._page_lookup.get(page_id) or self._page_stub(page_id)
            rect = self.app._rect(index * width + 8, nav_top + 10, width - 16, 52, scale, offset_x, offset_y)
            self.app.targets.append(self.app._target(page.label, rect, lambda page_id=page_id: self.app._set_page(page_id), active=self.app._current_page_id() == page_id, target_id=f"nav:{page_id}"))
            self._button(rect, page.label, accent=self.app._current_page_id() == page_id)

    def _draw_tile(self, tile, rect: pygame.Rect, scale: float) -> None:
        state = self.app._tile_state(tile)
        fill = state.fill or THEME.off_fill
        border = state.border or THEME.header_border
        text_color = state.text or THEME.text
        secondary = state.secondary_text or THEME.text_muted
        rounded_rect(self.app.screen, rect, fill, 18)
        pygame.draw.rect(self.app.screen, border, rect, width=2, border_radius=18)
        self._draw_multiline(state.friendly_name or tile.label or tile.id, rect.x + self.app._scale_value(16, scale), rect.y + self.app._scale_value(12, scale), "header", text_color)
        value = state.state
        self._draw_multiline(value, rect.x + self.app._scale_value(16, scale), rect.y + self.app._scale_value(42, scale), "body", text_color)
        if state.info:
            self._draw_multiline(state.info, rect.x + self.app._scale_value(16, scale), rect.y + self.app._scale_value(74, scale), "small", secondary)
        if state.error:
            self._draw_multiline(state.error, rect.x + self.app._scale_value(16, scale), rect.y + self.app._scale_value(74, scale), "small", THEME.bad)
        action_label = state.action_label or self.app._action_label(tile)
        if action_label:
            badge = pygame.Rect(rect.right - self.app._scale_value(120, scale), rect.bottom - self.app._scale_value(42, scale), self.app._scale_value(104, scale), self.app._scale_value(28, scale))
            rounded_rect(self.app.screen, badge, THEME.action_fill, 12)
            self._draw_multiline(action_label, badge.x + self.app._scale_value(10, scale), badge.y + self.app._scale_value(4, scale), "small", THEME.text)
        action = self.app._tile_action(tile)
        if action is not None and state.is_available and not state.busy and not state.locked:
            self.app.targets.append(self.app._target(tile.label or tile.id, rect, action, active=state.is_on, target_id=tile.id))

    def _button(self, rect: pygame.Rect, label: str, accent: bool = False) -> None:
        fill = THEME.panel_alt if not accent else THEME.accent
        border = THEME.header_border if not accent else THEME.accent_bright
        rounded_rect(self.app.screen, rect, fill, 16)
        pygame.draw.rect(self.app.screen, border, rect, width=2, border_radius=16)
        surf = self.app._font("button").render(label, True, THEME.text)
        self.app.screen.blit(surf, (rect.centerx - surf.get_width() / 2, rect.centery - surf.get_height() / 2))

    def _draw_multiline(self, value: str, x: int, y: int, font_key: str, color: tuple[int, int, int]) -> None:
        assert self.app.screen is not None
        font = self.app._font(font_key)
        max_width = max(12, int((self.app.screen.get_width() - x - 24) / max(1, font.size("x")[0])))
        line_y = y
        for line in wrap_text(value, width=max_width):
            surf = font.render(line, True, color)
            self.app.screen.blit(surf, (x, line_y))
            line_y += surf.get_height() + 2

    def _page_stub(self, page_id: str) -> DashboardPageConfig:
        return DashboardPageConfig(id=page_id, label=page_id.title(), tiles=[])
