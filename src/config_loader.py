"""Load and validate device / settings configuration; safe atomic writes."""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from pathlib import Path
from typing import TypedDict

from paths import DEVICES_CONFIG_PATH, SETTINGS_PATH



class Device(TypedDict):
    """Shape of a single device entry in devices.json."""

    name: str
    ip: str
    enabled: bool


class AppSettings(TypedDict):
    discord_webhook_url: str
    check_interval_seconds: int
    scanner_duration_seconds: int
    start_monitoring_on_launch: bool


DEFAULT_SETTINGS: AppSettings = {
    "discord_webhook_url": "",
    "check_interval_seconds": 5,
    "scanner_duration_seconds": 60,
    "start_monitoring_on_launch": True,
}


def _validate_device(device: object, index: int) -> Device:
    """Validate one device object and return it as a Device TypedDict."""
    if not isinstance(device, dict):
        raise ValueError(f"Device at index {index} must be an object.")

    for field in ("name", "ip"):
        if field not in device:
            raise ValueError(
                f'Device at index {index} is missing required field "{field}".'
            )

    name = device["name"]
    ip = device["ip"]
    # Phase 3 configs omit enabled; default True. Phase 1/2 may still include it.
    enabled = device.get("enabled", True)

    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f'Device at index {index}: "name" must be a non-empty string.'
        )

    if not isinstance(ip, str):
        raise ValueError(f'Device at index {index}: "ip" must be a string.')

    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError as exc:
        raise ValueError(
            f'Device at index {index}: "ip" must be a valid IPv4 address.'
        ) from exc

    if not isinstance(enabled, bool):
        raise ValueError(
            f'Device at index {index}: "enabled" must be a boolean when present.'
        )

    return Device(name=name.strip(), ip=ip.strip(), enabled=enabled)


def validate_devices_payload(data: object) -> list[Device]:
    """Validate a full devices JSON payload and return the device list."""
    if not isinstance(data, dict) or "devices" not in data:
        raise ValueError('Config must contain a top-level "devices" key.')

    devices = data["devices"]
    if not isinstance(devices, list):
        raise ValueError('"devices" must be a list.')

    validated = [_validate_device(device, index) for index, device in enumerate(devices)]

    names = [d["name"].casefold() for d in validated]
    ips = [d["ip"] for d in validated]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate device names are not allowed.")
    if len(ips) != len(set(ips)):
        raise ValueError("Duplicate device IP addresses are not allowed.")

    return validated


def load_devices(config_path: Path = DEVICES_CONFIG_PATH) -> list[Device]:
    """Load and validate the devices list from a JSON config file."""
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    return validate_devices_payload(data)


def get_enabled_devices(devices: list[Device]) -> list[Device]:
    """Return only devices marked as enabled (Phase 1/2 compatibility)."""
    return [device for device in devices if device["enabled"]]


def devices_to_payload(devices: list[Device]) -> dict[str, list[dict[str, str]]]:
    """Build the on-disk JSON structure (name + ip only)."""
    return {
        "devices": [
            {"name": device["name"], "ip": device["ip"]} for device in devices
        ]
    }


def atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON via temp file + replace to avoid corrupting the original."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=4) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def save_devices(devices: list[Device], config_path: Path = DEVICES_CONFIG_PATH) -> None:
    """Validate and atomically save the device list."""
    payload = devices_to_payload(devices)
    validate_devices_payload(payload)
    atomic_write_json(config_path, payload)


def load_settings(settings_path: Path = SETTINGS_PATH) -> AppSettings:
    """Load optional local settings; missing file yields safe defaults."""
    settings: AppSettings = dict(DEFAULT_SETTINGS)  # type: ignore[assignment]
    if not settings_path.is_file():
        return settings

    try:
        with settings_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return settings

    if not isinstance(data, dict):
        return settings

    url = data.get("discord_webhook_url", "")
    if isinstance(url, str):
        settings["discord_webhook_url"] = url.strip()

    interval = data.get("check_interval_seconds", settings["check_interval_seconds"])
    if isinstance(interval, int) and interval > 0:
        settings["check_interval_seconds"] = interval

    duration = data.get(
        "scanner_duration_seconds", settings["scanner_duration_seconds"]
    )
    if isinstance(duration, int) and duration > 0:
        settings["scanner_duration_seconds"] = duration

    start = data.get(
        "start_monitoring_on_launch", settings["start_monitoring_on_launch"]
    )
    if isinstance(start, bool):
        settings["start_monitoring_on_launch"] = start

    return settings


# Keep Phase 1/2 path constant name available.
__all__ = [
    "Device",
    "AppSettings",
    "DEVICES_CONFIG_PATH",
    "load_devices",
    "get_enabled_devices",
    "validate_devices_payload",
    "devices_to_payload",
    "atomic_write_json",
    "save_devices",
    "load_settings",
    "DEFAULT_SETTINGS",
]
