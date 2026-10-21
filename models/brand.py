"""Optional brand details the user can attach to an AI generation request."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()\-./]{5,}$")

# Font sizes are expressed for a 1080 px wide canvas and scaled to the real canvas.
REFERENCE_WIDTH = 1080

TEXT_MODES = {
    "layers": "Editable text layers (recommended)",
    "ai": "Draw text inside the AI image",
}

COLOR_THEMES: dict[str, tuple[str, tuple[str, ...]]] = {
    "auto": ("Let the AI choose", ()),
    "violet": ("Violet & indigo", ("#7C5CFF", "#4F7CFF", "#0D0E13")),
    "ocean": ("Ocean blue", ("#0B3D91", "#1E88E5", "#E3F2FD")),
    "sunset": ("Sunset orange", ("#FF6B35", "#F7C59F", "#2E294E")),
    "forest": ("Forest green", ("#1B4332", "#52B788", "#F1FAEE")),
    "luxury": ("Black & gold", ("#0A0A0A", "#C9A227", "#F5E6C4")),
    "mono": ("Monochrome", ("#111111", "#777777", "#FFFFFF")),
    "pastel": ("Soft pastel", ("#F8C8DC", "#B8E0D2", "#FFF5E1")),
    "custom": ("Custom colours", ()),
}


@dataclass(frozen=True)
class BrandField:
    text: str = ""
    size: int = 40          # px on a 1080 px wide canvas
    color: str = "#FFFFFF"

    @property
    def filled(self) -> bool:
        return bool(self.text.strip())


def split_values(text: str) -> list[str]:
    """Split "a, b; c" or one-per-line input into clean values."""
    return [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]


@dataclass(frozen=True)
class BrandDetails:
    company: BrandField = field(default_factory=lambda: BrandField(size=86, color="#FFFFFF"))
    description: BrandField = field(default_factory=lambda: BrandField(size=40, color="#FFFFFF"))
    phones: BrandField = field(default_factory=lambda: BrandField(size=30, color="#FFFFFF"))
    emails: BrandField = field(default_factory=lambda: BrandField(size=30, color="#FFFFFF"))
    theme: str = "auto"
    custom_colors: tuple[str, ...] = ("#7C5CFF", "#4F7CFF")
    text_mode: str = "layers"

    def fields(self) -> list[tuple[str, BrandField]]:
        return [("company", self.company), ("description", self.description),
                ("phones", self.phones), ("emails", self.emails)]

    @property
    def has_text(self) -> bool:
        return any(f.filled for _key, f in self.fields())

    @property
    def is_empty(self) -> bool:
        return not self.has_text and self.theme == "auto"

    def theme_colors(self) -> tuple[str, ...]:
        if self.theme == "custom":
            return self.custom_colors
        return COLOR_THEMES.get(self.theme, ("", ()))[1]

    def validate(self) -> None:
        for email in split_values(self.emails.text):
            if not EMAIL_PATTERN.match(email):
                raise ValueError(f"“{email}” does not look like a valid email address.")
        for phone in split_values(self.phones.text):
            if not PHONE_PATTERN.match(phone):
                raise ValueError(f"“{phone}” does not look like a valid phone number.")
        for key, item in self.fields():
            if not 8 <= item.size <= 400:
                raise ValueError(f"The {key} font size must be between 8 and 400 px.")

    # ------------------------------------------------------------------ prompt text

    def prompt_section(self) -> str:
        """Lines appended to the AI prompt describing the brand and how to treat its text."""
        if self.is_empty:
            return ""
        lines = ["", "Brand details:"]
        if self.company.filled:
            lines.append(f"- Company name: {self.company.text.strip()}")
        if self.description.filled:
            lines.append(f"- About the business: {self.description.text.strip()}")
        colors = self.theme_colors()
        if colors:
            name = COLOR_THEMES.get(self.theme, ("Custom", ()))[0]
            lines.append(f"- Colour theme ({name.lower()}): use {', '.join(colors)} as the main palette.")
        if not self.has_text:
            return "\n".join(lines)

        if self.text_mode == "layers":
            lines.append(
                "IMPORTANT: do NOT render any text, letters, numbers or logos in the image. Leave clean, "
                "uncluttered space at the top for the company name and at the bottom for contact details; "
                "the text will be added afterwards as separate layers.")
            return "\n".join(lines)

        lines.append("Render the following text clearly, spelled exactly as written:")
        labels = {"company": "Company name (largest, headline)", "description": "Tagline / description",
                  "phones": "Phone", "emails": "Email"}
        for key, item in self.fields():
            if item.filled:
                value = ", ".join(split_values(item.text)) if key in ("phones", "emails") else item.text.strip()
                lines.append(f"- {labels[key]}: “{value}” — about {item.size}px tall on a {REFERENCE_WIDTH}px "
                             f"wide canvas, colour {item.color}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ persistence

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BrandDetails:
        if not isinstance(data, dict):
            return cls()
        default = cls()
        values = {}
        for key, item in default.fields():
            raw = data.get(key) or {}
            values[key] = BrandField(
                text=str(raw.get("text", "")),
                size=int(raw.get("size", item.size)) if str(raw.get("size", "")).isdigit() else item.size,
                color=str(raw.get("color", item.color)),
            )
        theme = data.get("theme", "auto")
        mode = data.get("text_mode", "layers")
        custom = tuple(data.get("custom_colors") or default.custom_colors)[:2]
        return cls(**values, theme=theme if theme in COLOR_THEMES else "auto",
                   custom_colors=custom, text_mode=mode if mode in TEXT_MODES else "layers")
