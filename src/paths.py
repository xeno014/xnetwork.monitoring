"""Shared paths and timestamp helpers for XenoTech IP Monitor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEVICES_CONFIG_PATH = CONFIG_DIR / "devices.json"
SETTINGS_PATH = CONFIG_DIR / "settings.local.json"
SETTINGS_EXAMPLE_PATH = CONFIG_DIR / "settings.example.json"
LOGS_DIR = PROJECT_ROOT / "logs"


def now_stamp() -> str:
    """Return local Windows time as YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
