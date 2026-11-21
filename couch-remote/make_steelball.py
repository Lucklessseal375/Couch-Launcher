"""Cuts the steel ball out of its white background -> web/steelball.png (transparent, 256 px).
Run:  python make_steelball.py <picture of the ball>"""
import os
import sys

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
import pygame.gfxdraw as gfx

src = pygame.image.load(sys.argv[1])
w, h = src.get_size()
# the ball's edge: the outermost pixels that aren't near-white
xs, ys = [], []
for y in range(0, h, 2):
    for x in range(0, w, 2):
        r, g, b, a = src.get_at((x, y))
        if a > 128 and r + g + b < 600:  # visible and not white
            xs.append(x)
            ys.append(y)
# centre = average dark pixel, radius from the dark area (stray specks barely move either)
cx, cy = sum(xs) // len(xs), sum(ys) // len(ys)
R = int((len(xs) * 4 / 3.14159) ** 0.5) - 4  # each sample stands for 2x2 pixels; -4 trims the white rim

out = pygame.Surface((2 * R, 2 * R), pygame.SRCALPHA)
out.blit(src, (0, 0), (cx - R, cy - R, 2 * R, 2 * R))
mask = pygame.Surface((2 * R, 2 * R), pygame.SRCALPHA)
gfx.filled_circle(mask, R, R, R - 1, (255, 255, 255, 255))
gfx.aacircle(mask, R, R, R - 1, (255, 255, 255, 255))
out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "steelball.png")
pygame.image.save(pygame.transform.smoothscale(out, (256, 256)), dst)
print("wrote", dst, "from circle", (cx, cy, R))
