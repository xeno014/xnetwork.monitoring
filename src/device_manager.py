"""Add-device flow: validate, confirm, final-validate, atomic save."""

from __future__ import annotations

import ipaddress

from app_logger import log_event
from config_loader import (
    Device,
    DEVICES_CONFIG_PATH,
    load_devices,
    save_devices,
    validate_devices_payload,
    devices_to_payload,
)
from engine import ENGINE
from paths import now_stamp


class DeviceValidationError(ValueError):
    """Raised when a proposed device fails validation."""


def validate_new_device(name: str, ip: str, existing: list[Device] | None = None) -> Device:
    """Validate a proposed device against current configuration."""
    clean_name = (name or "").strip()
    clean_ip = (ip or "").strip()

    if not clean_name:
        raise DeviceValidationError("Device name cannot be empty.")
    if not clean_ip:
        raise DeviceValidationError("IP address cannot be empty.")

    try:
        ipaddress.IPv4Address(clean_ip)
    except ipaddress.AddressValueError as exc:
        raise DeviceValidationError("IP address must be a valid IPv4 address.") from exc

    if existing is None:
        existing = load_devices()

    for device in existing:
        if device["name"].casefold() == clean_name.casefold():
            raise DeviceValidationError(
                f'A device named "{clean_name}" already exists.'
            )
        if device["ip"] == clean_ip:
            raise DeviceValidationError(
                f"A device with IP address {clean_ip} already exists."
            )

    # Ensure the merged config would remain valid.
    proposed = list(existing) + [
        Device(name=clean_name, ip=clean_ip, enabled=True)
    ]
    validate_devices_payload(devices_to_payload(proposed))

    return Device(name=clean_name, ip=clean_ip, enabled=True)


def add_device(name: str, ip: str) -> Device:
    """Final-validate and atomically persist a new device, then reload engine."""
    existing = load_devices()
    new_device = validate_new_device(name, ip, existing)
    # Final validation immediately before write.
    updated = existing + [new_device]
    validate_devices_payload(devices_to_payload(updated))
    save_devices(updated, DEVICES_CONFIG_PATH)
    ENGINE.reload_config()
    log_event(
        f"Device created: {new_device['name']} ({new_device['ip']}) at {now_stamp()}"
    )
    return new_device
