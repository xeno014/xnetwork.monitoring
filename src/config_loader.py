"""Load and validate device configuration from JSON."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import TypedDict


# Project root is one level above the src/ directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEVICES_CONFIG_PATH = PROJECT_ROOT / "config" / "devices.json"


class Device(TypedDict):
    """Shape of a single device entry in devices.json."""

    name: str
    ip: str
    enabled: bool


def _validate_device(device: object, index: int) -> Device:
    """Validate one device object and return it as a Device TypedDict."""
    if not isinstance(device, dict):
        raise ValueError(f"Device at index {index} must be an object.")

    for field in ("name", "ip", "enabled"):
        if field not in device:
            raise ValueError(
                f'Device at index {index} is missing required field "{field}".'
            )

    name = device["name"]
    ip = device["ip"]
    enabled = device["enabled"]

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
            f'Device at index {index}: "enabled" must be a boolean.'
        )

    return Device(name=name, ip=ip, enabled=enabled)


def load_devices(config_path: Path = DEVICES_CONFIG_PATH) -> list[Device]:
    """Load and validate the devices list from a JSON config file.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the JSON is invalid or fails basic validation.
        OSError: If the config file cannot be read.
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(data, dict) or "devices" not in data:
        raise ValueError('Config must contain a top-level "devices" key.')

    devices = data["devices"]
    if not isinstance(devices, list):
        raise ValueError('"devices" must be a list.')

    return [_validate_device(device, index) for index, device in enumerate(devices)]


def get_enabled_devices(devices: list[Device]) -> list[Device]:
    """Return only devices marked as enabled."""
    return [device for device in devices if device["enabled"]]
