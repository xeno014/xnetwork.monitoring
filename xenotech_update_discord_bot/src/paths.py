"""Shared paths and timestamp helpers for XenoTech IP Monitor."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

# When packaged with PyInstaller, user data (config/, logs/) lives NEXT TO the
# .exe so it survives restarts; bundled read-only resources live in _MEIPASS.
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_ROOT = PROJECT_ROOT

CONFIG_DIR = PROJECT_ROOT / "config"
DEVICES_CONFIG_PATH = CONFIG_DIR / "devices.json"
SETTINGS_PATH = CONFIG_DIR / "settings.local.json"
SETTINGS_EXAMPLE_PATH = CONFIG_DIR / "settings.example.json"
LOGS_DIR = PROJECT_ROOT / "logs"
ICON_PATH = BUNDLE_ROOT / "assets" / "xenotech.ico"


def now_stamp() -> str:
    """Return local Windows time as YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_user_files() -> None:
    """Create config/logs folders and a devices.json on first run."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if not DEVICES_CONFIG_PATH.exists():
            seed = BUNDLE_ROOT / "config" / "devices.json"
            if FROZEN and seed.is_file():
                shutil.copyfile(seed, DEVICES_CONFIG_PATH)
            else:
                DEVICES_CONFIG_PATH.write_text(
                    '{\n    "devices": []\n}\n', encoding="utf-8"
                )
    except OSError:
        # Read-only location etc. - the app reports config problems itself.
        pass


ensure_user_files()
