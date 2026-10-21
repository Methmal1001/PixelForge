"""Persisted user preferences (stored per user by QSettings)."""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings

from models.brand import BrandDetails

from app_info import ORGANIZATION
from ui.styles import DEFAULT_THEME_MODE, THEME_MODES

_THEME_KEY = "appearance/theme"


def _settings() -> QSettings:
    return QSettings(ORGANIZATION, "AI Studio")


def load_theme_mode() -> str:
    mode = _settings().value(_THEME_KEY, DEFAULT_THEME_MODE)
    return mode if mode in THEME_MODES else DEFAULT_THEME_MODE


_BRAND_KEY = "generation/brand"


def load_brand() -> BrandDetails:
    raw = _settings().value(_BRAND_KEY, "")
    try:
        return BrandDetails.from_dict(json.loads(raw)) if raw else BrandDetails()
    except (TypeError, ValueError):
        return BrandDetails()


def save_brand(brand: BrandDetails) -> None:
    settings = _settings()
    settings.setValue(_BRAND_KEY, json.dumps(brand.to_dict()))
    settings.sync()


def save_theme_mode(mode: str) -> None:
    if mode in THEME_MODES:
        settings = _settings()
        settings.setValue(_THEME_KEY, mode)
        settings.sync()
