"""
Generate windows/oak_camera.ico for the portable executable.
=============================================================
Run once, then commit the result. The continuous integration build needs no
Pillow this way.

    python tools/make_icon.py
"""
import os
import sys

from PIL import Image, ImageDraw

# Windows picks the closest size from the icon, so supply the usual set.
SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "windows", "oak_camera.ico")


def draw(size: int) -> Image.Image:
    """Draw a camera aperture at one size. Matches the tray icon artwork."""
    scale  = 4                      # draw large, then downsample for clean edges
    big    = size * scale
    image  = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d      = ImageDraw.Draw(image)

    margin = max(1, int(big * 0.06))
    ring   = max(1, int(big * 0.05))
    centre = big / 2

    # Dark body with a white ring reads on a light and a dark taskbar.
    d.ellipse([margin, margin, big - margin, big - margin],
              fill=(24, 28, 34, 255), outline=(255, 255, 255, 255), width=ring)

    radius = centre - margin - int(big * 0.13)
    d.ellipse([centre - radius, centre - radius, centre + radius, centre + radius],
              outline=(0, 200, 90, 255), width=max(1, int(big * 0.065)))

    pupil = int(big * 0.10)
    d.ellipse([centre - pupil, centre - pupil, centre + pupil, centre + pupil],
              fill=(0, 200, 90, 255))

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames = [draw(s) for s in SIZES]
    frames[-1].save(OUT, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes, sizes {list(SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
