from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    bg: tuple[int, int, int] = (11, 14, 18)
    bg_glow_a: tuple[int, int, int, int] = (28, 78, 128, 44)
    bg_glow_b: tuple[int, int, int, int] = (24, 120, 92, 28)
    header: tuple[int, int, int] = (19, 25, 34)
    header_border: tuple[int, int, int] = (42, 54, 68)
    panel: tuple[int, int, int] = (20, 28, 38)
    panel_alt: tuple[int, int, int] = (26, 35, 46)
    card: tuple[int, int, int] = (24, 32, 42)
    off_fill: tuple[int, int, int] = (23, 31, 41)
    light_on_fill: tuple[int, int, int] = (198, 141, 48)
    switch_on_fill: tuple[int, int, int] = (52, 141, 198)
    boolean_on_fill: tuple[int, int, int] = (72, 186, 124)
    sensor_fill: tuple[int, int, int] = (30, 37, 48)
    action_fill: tuple[int, int, int] = (58, 75, 110)
    busy_fill: tuple[int, int, int] = (76, 99, 151)
    unavailable_border: tuple[int, int, int] = (214, 72, 72)
    unknown_border: tuple[int, int, int] = (222, 146, 68)
    sensor_border: tuple[int, int, int] = (74, 96, 118)
    text: tuple[int, int, int] = (238, 243, 248)
    text_dark: tuple[int, int, int] = (16, 20, 25)
    text_muted: tuple[int, int, int] = (156, 171, 186)
    ok: tuple[int, int, int] = (79, 212, 138)
    warn: tuple[int, int, int] = (245, 169, 61)
    bad: tuple[int, int, int] = (244, 104, 104)
    accent: tuple[int, int, int] = (94, 164, 255)
    accent_bright: tuple[int, int, int] = (116, 186, 255)
    busy: tuple[int, int, int] = (108, 151, 220)


BASE_WIDTH = 800
BASE_HEIGHT = 480
HEADER_HEIGHT = 72
NAV_HEIGHT = 72
CONTENT_TOP = 84
CONTENT_BOTTOM = 92
