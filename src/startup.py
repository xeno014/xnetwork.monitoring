"""Windows startup registration (per-user, no admin required)."""

from __future__ import annotations

import sys
from pathlib import Path

from app_logger import log_event
from paths import PROJECT_ROOT

APP_RUN_NAME = "XenoTechIPMonitor"


def _pythonw_path() -> Path:
    python = Path(sys.executable)
    if python.name.lower() == "python.exe":
        candidate = python.with_name("pythonw.exe")
        if candidate.is_file():
            return candidate
    return python


def _launch_command() -> str:
    script = PROJECT_ROOT / "src" / "main.py"
    return f'"{_pythonw_path()}" "{script}" --tray'


def enable_windows_startup() -> bool:
    """Register the app in HKCU Run for current-user startup."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        with key:
            winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        log_event("Windows startup enabled (HKCU Run)")
        return True
    except OSError as exc:
        log_event(f"Failed to enable Windows startup: {exc}")
        return False


def disable_windows_startup() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        with key:
            try:
                winreg.DeleteValue(key, APP_RUN_NAME)
            except FileNotFoundError:
                pass
        log_event("Windows startup disabled")
        return True
    except OSError as exc:
        log_event(f"Failed to disable Windows startup: {exc}")
        return False


def is_windows_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        with key:
            winreg.QueryValueEx(key, APP_RUN_NAME)
        return True
    except OSError:
        return False
