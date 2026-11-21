"""Draws the Couch icon (purple polka dots, Gyro's steel ball, gold horseshoe) -> web/icon.png + icon.ico.
Run once:  python make_icon.py"""
import math
import os
import struct

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
import pygame.gfxdraw as gfx

S = 1024  # draw big, shrink at the end for smooth edges
img = pygame.Surface((S, S), pygame.SRCALPHA)

# purple rounded square with lavender dots
bg = pygame.Surface((S, S), pygame.SRCALPHA)
for y in range(S):
    t = y / S
    pygame.draw.line(bg, (int(150 - 90 * t), int(100 - 70 * t), int(220 - 120 * t)), (0, y), (S, y))
for gy in range(-1, 6):
    for gx in range(-1, 6):
        gfx.filled_circle(bg, gx * 200 + 100, gy * 200 + 100, 62, (225, 208, 255, 110))
mask = pygame.Surface((S, S), pygame.SRCALPHA)
pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, S, S), border_radius=220)
bg.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
img.blit(bg, (0, 0))

# gold horseshoe behind the ball
cx, cy = S // 2, S // 2 + 30
path = [(cx - 320, cy - 330 + i * 4) for i in range(96)]                      # left arm, down
path += [(cx - 320 * math.cos(a / 90 * math.pi), cy + 50 + 320 * math.sin(a / 90 * math.pi)) for a in range(91)]  # U bottom
path += [(cx + 320, cy + 50 - i * 4) for i in range(96)]                       # right arm, up
for w, col in ((120, (150, 100, 20)), (92, (242, 184, 68)), (26, (255, 225, 154))):
    for x, y in path:  # a chain of dots gives a clean thick stroke
        gfx.filled_circle(img, int(x), int(y), w // 2, col)

# Gyro's steel ball (web/steelball.png, made by make_steelball.py)
R = 250
here = os.path.dirname(os.path.abspath(__file__))
img.blit(pygame.transform.smoothscale(pygame.image.load(os.path.join(here, "web", "steelball.png")), (2 * R, 2 * R)), (cx - R, cy - R - 40))

# Johnny-cyan star, top right
pts = [(S * 0.79 + 95 * math.cos(math.pi / 2 + i * math.pi / 5) * (1 if i % 2 == 0 else .45),
        S * 0.2 - 95 * math.sin(math.pi / 2 + i * math.pi / 5) * (1 if i % 2 == 0 else .45)) for i in range(10)]
gfx.filled_polygon(img, pts, (94, 200, 239))
gfx.aapolygon(img, pts, (255, 255, 255))

small = pygame.transform.smoothscale(img, (256, 256))
png = os.path.join(here, "web", "icon.png")
pygame.image.save(small, png)
data = open(png, "rb").read()
# .ico = 6-byte header + one 16-byte entry pointing at the PNG bytes (Windows Vista+ reads PNG inside .ico)
with open(os.path.join(here, "icon.ico"), "wb") as f:
    f.write(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22) + data)
print("wrote", png, "and icon.ico")
