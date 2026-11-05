"""Generate mathdraw/assets/icon.png + icon.ico (replace with your own artwork if you like)."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "mathdraw", "assets")
S = 1024


def make():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=(18, 24, 33, 255))
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    for k in range(1, 8):
        v = 40 + k * (S - 80) / 8
        g.line((v, 110, v, S - 110), fill=(255, 255, 255, 34), width=6)
        g.line((110, v, S - 110, v), fill=(255, 255, 255, 34), width=6)
    g.line((140, S / 2 + 90, S - 140, S / 2 + 90), fill=(255, 255, 255, 110), width=12)
    img.alpha_composite(layer)
    # the curve: a smooth damped wave, drawn with a glow
    pts = []
    for i in range(400):
        t = i / 399
        x = 150 + t * (S - 300)
        y = S / 2 + 90 - 260 * math.sin(2.4 * math.pi * t) * math.exp(-1.1 * t) - 120 * t
        pts.append((x, y))
    def stroke(draw, r, fill):  # stamp discs: smooth thick line without PIL's jagged joins
        for x, y in pts:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    stroke(ImageDraw.Draw(glow), 36, (0, 229, 255, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
    line = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    stroke(ImageDraw.Draw(line), 21, (0, 229, 255, 255))
    img.alpha_composite(line)
    d = ImageDraw.Draw(img)
    # fingertip
    fx, fy = pts[-1]
    d.ellipse((fx - 62, fy - 62, fx + 62, fy + 62), fill=(255, 210, 63, 255))
    d.ellipse((fx - 30, fy - 30, fx + 30, fy + 30), fill=(18, 24, 33, 255))
    return img


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    im = make()
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    im.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icons written to", OUT)
