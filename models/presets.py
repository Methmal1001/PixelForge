"""Social-media canvas size presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SizePreset:
    key: str
    name: str
    width: int
    height: int
    ratio: str

    @property
    def label(self) -> str:
        return f"{self.name} · {self.width} × {self.height}"


SIZE_PRESETS: tuple[SizePreset, ...] = (
    SizePreset("square", "Square Post", 1080, 1080, "1:1"),
    SizePreset("portrait", "Portrait Post", 1080, 1350, "4:5"),
    SizePreset("story", "Story", 1080, 1920, "9:16"),
    SizePreset("landscape", "Landscape Banner", 1920, 1080, "16:9"),
)


def find_preset(key: str) -> SizePreset | None:
    return next((p for p in SIZE_PRESETS if p.key == key), None)
