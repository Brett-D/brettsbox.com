"""Draw the golf PWA icons (PNG for installs and iOS, SVG for browsers). Needs Pillow.

    python golf/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "golf" / "icons"
BG, GREEN, HOLE, FLAG, WHITE = "#0d2619", "#2f8a5c", "#0a1f14", "#f2c14e", "#ffffff"
SCALE = 4  # draw large, then downsample for smooth edges


def draw(size: int, rounded: bool, inset: float) -> Image.Image:
    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    if rounded:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=BG)
    else:
        d.rectangle((0, 0, big, big), fill=BG)

    def p(x: float, y: float) -> tuple[float, float]:
        # Artwork is drawn on a 512 grid, shrunk around the centre by `inset` (for maskable safe zones).
        k = big / 512 * inset
        offset = big * (1 - inset) / 2
        return offset + x * k, offset + y * k

    def box(cx, cy, rx, ry):
        (x0, y0), (x1, y1) = p(cx - rx, cy - ry), p(cx + rx, cy + ry)
        return x0, y0, x1, y1

    d.ellipse(box(256, 372, 176, 64), fill=GREEN)
    d.ellipse(box(300, 372, 28, 10), fill=HOLE)
    d.line([p(300, 372), p(300, 104)], fill=WHITE, width=int(16 * big / 512 * inset))
    d.polygon([p(304, 104), p(304, 204), p(420, 154)], fill=FLAG)
    d.ellipse(box(184, 338, 24, 24), fill=WHITE)
    return image.resize((size, size), Image.LANCZOS)


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="{BG}"/>
  <ellipse cx="256" cy="372" rx="176" ry="64" fill="{GREEN}"/>
  <ellipse cx="300" cy="372" rx="28" ry="10" fill="{HOLE}"/>
  <path d="M300 372V104" stroke="{WHITE}" stroke-width="16" stroke-linecap="round"/>
  <path d="M304 104v100l116-50z" fill="{FLAG}"/>
  <circle cx="184" cy="338" r="24" fill="{WHITE}"/>
</svg>
"""

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, True, 1).save(OUT / "icon-192.png", optimize=True)
    draw(512, True, 1).save(OUT / "icon-512.png", optimize=True)
    draw(512, False, 0.72).save(OUT / "maskable-512.png", optimize=True)
    draw(180, False, 0.9).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    (OUT / "icon.svg").write_text(SVG, encoding="utf-8", newline="\n")
    print(f"Icons written to {OUT}")
