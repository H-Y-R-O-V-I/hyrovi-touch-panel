from __future__ import annotations

import pygame


def run_touch_test(screen_size: tuple[int, int], fullscreen: bool = True) -> int:
    pygame.init()
    screen = pygame.display.set_mode(screen_size, pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE)
    pygame.display.set_caption("Hyrovi Touch Test")
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont("DejaVu Sans", 28, bold=True)
    small = pygame.font.SysFont("DejaVu Sans", 18)
    clock = pygame.time.Clock()
    running = True
    last_pos = (0, 0)
    taps = 0

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                taps += 1
                if event.type == pygame.MOUSEBUTTONDOWN:
                    last_pos = event.pos
                else:
                    last_pos = (int(event.x * screen.get_width()), int(event.y * screen.get_height()))
            elif event.type == pygame.MOUSEMOTION:
                last_pos = event.pos

        screen.fill((10, 14, 18))
        pygame.draw.rect(screen, (38, 52, 64), (24, 24, screen.get_width() - 48, screen.get_height() - 48), border_radius=24)
        title = font.render("Touch-Test", True, (240, 244, 248))
        screen.blit(title, (40, 40))
        lines = [
            f"Taps: {taps}",
            f"Last position: {last_pos[0]} / {last_pos[1]}",
            "Tap, swipe or press ESC to close.",
        ]
        y = 100
        for line in lines:
            surf = small.render(line, True, (210, 220, 232))
            screen.blit(surf, (40, y))
            y += 32
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return 0


def run_display_test(screen_size: tuple[int, int], fullscreen: bool = True) -> int:
    pygame.init()
    screen = pygame.display.set_mode(screen_size, pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE)
    pygame.display.set_caption("Hyrovi Display Test")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        width, height = screen.get_size()
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, (180, 30, 30), (0, 0, width // 3, height // 3))
        pygame.draw.rect(screen, (30, 180, 30), (width // 3, 0, width // 3, height // 3))
        pygame.draw.rect(screen, (30, 30, 180), (2 * width // 3, 0, width - 2 * width // 3, height // 3))
        pygame.draw.rect(screen, (220, 220, 220), (0, height // 3, width, 32))
        pygame.display.flip()
        clock.tick(20)

    pygame.quit()
    return 0
