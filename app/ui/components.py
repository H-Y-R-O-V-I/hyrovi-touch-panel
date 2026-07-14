from __future__ import annotations

import textwrap
from dataclasses import dataclass

import pygame


@dataclass(slots=True)
class TextBlock:
    lines: list[str]


def rounded_rect(surface: pygame.Surface, rect: pygame.Rect, color: tuple[int, int, int], radius: int) -> None:
    pygame.draw.rect(surface, color, rect, border_radius=radius)


def panel(surface: pygame.Surface, rect: pygame.Rect, accent: tuple[int, int, int] | None = None, radius: int = 18) -> None:
    rounded_rect(surface, rect, (20, 28, 38), radius)
    pygame.draw.rect(surface, accent or (52, 66, 80), rect, width=2, border_radius=radius)


def text(surface: pygame.Surface, font: pygame.font.Font, value: str, x: int, y: int, color: tuple[int, int, int]) -> pygame.Rect:
    surf = font.render(value, True, color)
    rect = surf.get_rect(topleft=(x, y))
    surface.blit(surf, rect)
    return rect


def wrap_text(value: str, width: int) -> list[str]:
    if not value:
        return [""]
    return textwrap.wrap(value, width=width) or [value]


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))

