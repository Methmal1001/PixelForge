"""Locally drawn placeholder artwork for the sample design.

Drawn with Pillow primitives only. It is NOT AI output and makes no network calls.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from models.design import TextElement


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def create_sample_background(width: int = 1080, height: int = 1080) -> Image.Image:
    """A cinematic black-and-blue product backdrop with a phone silhouette."""
    w, h = width, height
    ramp = Image.linear_gradient("L").resize((w, h))
    canvas = ImageOps.colorize(ramp, black="#0B0F24", mid="#070A18", white="#03040A").convert("RGBA")

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((int(w * 0.48), int(h * 0.05), int(w * 1.1), int(h * 0.7)), fill=(70, 110, 255, 150))
    draw.ellipse((int(w * 0.6), int(h * 0.45), int(w * 1.05), int(h * 0.95)), fill=(124, 92, 255, 120))
    draw.ellipse((int(-w * 0.2), int(h * 0.75), int(w * 0.35), int(h * 1.2)), fill=(40, 70, 200, 80))
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(w * 0.08)))

    # light beams
    beams = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(beams)
    for i, alpha in enumerate((38, 26, 18)):
        x = int(w * (0.62 + i * 0.09))
        bdraw.polygon([(x, 0), (x + int(w * 0.05), 0), (x - int(w * 0.18), h), (x - int(w * 0.26), h)],
                      fill=(150, 180, 255, alpha))
    canvas = Image.alpha_composite(canvas, beams.filter(ImageFilter.GaussianBlur(w * 0.012)))

    # phone mock-up
    pw = int(w * 0.27)
    ph = min(int(pw * 2.05), int(h * 0.66))
    px, py = int(w * 0.62), int(h * 0.17)
    radius = int(pw * 0.16)

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (px + 12, py + 30, px + pw + 12, py + ph + 30), radius, fill=(0, 0, 0, 200)
    )
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(w * 0.03)))

    body = Image.new("RGBA", (pw, ph), (12, 14, 22, 255))
    ImageDraw.Draw(body).rounded_rectangle((0, 0, pw - 1, ph - 1), radius, outline=(92, 104, 150, 255), width=3)
    inset = max(6, int(pw * 0.045))
    screen_size = (pw - inset * 2, ph - inset * 2)
    screen_ramp = Image.linear_gradient("L").rotate(35, expand=False).resize(screen_size)
    screen = ImageOps.colorize(screen_ramp, black="#5B3DF5", mid="#2C5BFF", white="#0B1435").convert("RGBA")
    body.paste(screen, (inset, inset), _rounded_mask(screen_size, int(radius * 0.8)))
    notch_w = int(pw * 0.28)
    ImageDraw.Draw(body).rounded_rectangle(
        ((pw - notch_w) // 2, inset + 10, (pw + notch_w) // 2, inset + 10 + int(pw * 0.06)),
        int(pw * 0.03), fill=(8, 9, 14, 255),
    )
    canvas.paste(body, (px, py), _rounded_mask((pw, ph), radius))

    # reflective floor line
    floor = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fy = py + ph + int(h * 0.05)
    ImageDraw.Draw(floor).ellipse((int(w * 0.5), fy - 6, int(w * 1.0), fy + 6), fill=(120, 150, 255, 160))
    canvas = Image.alpha_composite(canvas, floor.filter(ImageFilter.GaussianBlur(8)))

    # sparkles
    sparkle = ImageDraw.Draw(canvas)
    for fx, fy2, r in ((0.55, 0.12, 3), (0.93, 0.3, 2), (0.5, 0.55, 2), (0.96, 0.8, 3), (0.44, 0.9, 2)):
        cx, cy = int(w * fx), int(h * fy2)
        sparkle.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(220, 230, 255, 220))

    return canvas.convert("RGB")


def create_sample_design(width: int = 1080, height: int = 1080) -> tuple[Image.Image, list[TextElement]]:
    """Return a placeholder background plus editable text layers."""
    w, h = width, height
    texts = [
        TextElement("NEW ARRIVALS", x=w * 0.075, y=h * 0.2, font_size=round(h * 0.028),
                    color="#A99BFF", bold=True),
        TextElement("Mega\nSmartphone\nSale", x=w * 0.07, y=h * 0.25, font_size=round(h * 0.082),
                    color="#FFFFFF", bold=True),
        TextElement("Up to 40% off flagship phones\nThis weekend only · Colombo", x=w * 0.075, y=h * 0.6,
                    font_size=round(h * 0.03), color="#C9CEE0", bold=False),
        TextElement("Shop now  →", x=w * 0.075, y=h * 0.76, font_size=round(h * 0.034),
                    color="#7FB2FF", bold=True),
    ]
    return create_sample_background(w, h), texts
