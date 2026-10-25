# -*- coding: utf-8 -*-
"""README hero: a 3:1 wide feature banner."""
from PIL import Image, ImageDraw, ImageFont

W, H = 2100, 700
OUT = "/Users/hejie/ZCodeProject/nxnative-romfs-archive/frontend/screenshots/hero-features-en.png"

F_HEI = "/Library/Fonts/4080_方正超粗黑_GBK.ttf"
F_MED = "/Library/Fonts/SourceHanSansCN-Medium.ttf"
def hei(s): return ImageFont.truetype(F_HEI, s)
def med(s): return ImageFont.truetype(F_MED, s)

GREEN = (52, 199, 89)
YELLOW = (255, 214, 10)
GREY = (170, 180, 190)
CARD = (34, 41, 48)
CARD_EDGE = (58, 68, 78)


def vgrad(size, top, bottom):
    w, h = size
    base = Image.new("RGB", size)
    d = ImageDraw.Draw(base)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t)))
    return base


im = vgrad((W, H), (26, 32, 38), (15, 20, 24)).convert("RGBA")
d = ImageDraw.Draw(im, "RGBA")

for cx, cy, r, a in [(50, 40, 120, 20), (W - 60, 60, 90, 16), (40, H - 40, 90, 14), (W - 50, H - 50, 120, 18)]:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, a), width=3)

# ---- left column ----
LX = 86
d.text((LX, 96), "Switch games", font=hei(84), fill="white")
d.text((LX, 196), "on your iPhone", font=hei(84), fill=YELLOW)
d.text((LX + 4, 308), "Not an emulator. No terminal.", font=med(38), fill=(206, 214, 222))
d.text((LX + 4, 358), "A macOS app does the whole build in a few clicks", font=med(34), fill=GREY)

stats = [("58", "game profiles", GREEN), ("3", "verified on iPhone", YELLOW), ("300k", "files → 127 shards", GREEN)]
y0 = 470
for i, (num, label, color) in enumerate(stats):
    x = LX + i * 268
    d.text((x, y0), num, font=hei(66), fill=color)
    d.text((x + 2, y0 + 82), label, font=med(27), fill=(196, 206, 214))

# ---- right column: 2x2 cards ----
RX = 900
CW = W - 90 - RX
CH = 132
GAP = 20
cards = [
    ("01", "One-click build", "Pick your files, press build — no terminal"),
    ("02", "RomFS archive", "300k files into 127 shards — 16 GB installs"),
    ("03", "Resumable builds", "A stopped build continues where it left off"),
    ("04", "Self-installing", "Fetches the repository and updates itself"),
]
top = (H - (len(cards) * CH + (len(cards) - 1) * GAP)) // 2
for i, (num, title, desc) in enumerate(cards):
    x = RX
    y = top + i * (CH + GAP)
    d.rounded_rectangle([x, y, x + CW, y + CH], radius=20, fill=CARD, outline=CARD_EDGE, width=2)
    d.text((x + 28, y + 22), num, font=hei(42), fill=GREEN)
    d.text((x + 104, y + 16), title, font=hei(34), fill="white")
    d.text((x + 104, y + 66), desc, font=med(25), fill=GREY)

im.convert("RGB").save(OUT, optimize=True)
print("saved", OUT, Image.open(OUT).size, "ratio", round(W / H, 2))
