"""One-click filter presets. Each preset is simply a set of adjustment values."""

from __future__ import annotations

from dataclasses import replace

from models.design import Adjustments

FILTER_PRESETS: dict[str, tuple[str, Adjustments]] = {
    "none": ("Original", Adjustments()),
    "vivid": ("Vivid", Adjustments(contrast=1.15, saturation=1.4, sharpness=1.3)),
    "warm": ("Warm", Adjustments(warmth=40, saturation=1.1, brightness=1.03)),
    "cool": ("Cool", Adjustments(warmth=-40, tint=-5, contrast=1.05)),
    "vintage": ("Vintage", Adjustments(saturation=0.75, warmth=25, contrast=0.9, shadows=25, vignette=35)),
    "dramatic": ("Dramatic", Adjustments(contrast=1.35, saturation=1.1, highlights=-25, shadows=-20,
                                         vignette=30, sharpness=1.2)),
    "fade": ("Fade", Adjustments(contrast=0.85, saturation=0.85, shadows=35, highlights=-10)),
    "mono": ("Mono", Adjustments(grayscale=True, contrast=1.15)),
    "noir": ("Noir", Adjustments(grayscale=True, contrast=1.45, shadows=-25, vignette=40)),
    "sepia": ("Sepia", Adjustments(sepia=True, contrast=1.05, vignette=20)),
}


def filter_adjustments(key: str) -> Adjustments:
    """The adjustment values for a preset, tagged with the preset name."""
    _name, values = FILTER_PRESETS.get(key, FILTER_PRESETS["none"])
    return replace(values, filter_name=key if key in FILTER_PRESETS else "none")
