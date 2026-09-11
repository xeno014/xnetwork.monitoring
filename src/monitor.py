"""IP reachability helpers (Windows-compatible ping)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from config_loader import Device

# Default timeout for a single ping attempt (milliseconds on Windows).
PING_TIMEOUT_MS = 2000

Status = str  # UNKNOWN | ONLINE | OFFLINE


def is_reachable(ip: str, timeout_ms: int = PING_TIMEOUT_MS) -> bool:
    """Check whether an IPv4 address responds to a single ping.

    Uses the system ``ping`` command so no third-party packages are required.
    On Windows: ``ping -n 1 -w <timeout_ms> <ip>``.

    Errors (timeouts, missing ping, etc.) are treated as unreachable.
    """
    if sys.platform == "win32":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        timeout_sec = max(1, (timeout_ms + 999) // 1000)
        command = ["ping", "-c", "1", "-W", str(timeout_sec), ip]
        creationflags = 0

    process_timeout = (timeout_ms / 1000.0) + 2.0

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=process_timeout,
            check=False,
            creationflags=creationflags,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def status_from_reachable(reachable: bool) -> Status:
    return "ONLINE" if reachable else "OFFLINE"


def check_devices(devices: list[Device]) -> list[tuple[Device, Status]]:
    """Ping each device once and return (device, status) pairs."""
    results: list[tuple[Device, Status]] = []
    for device in devices:
        try:
            reachable = is_reachable(device["ip"])
            results.append((device, status_from_reachable(reachable)))
        except Exception:
            results.append((device, "UNKNOWN"))
    return results


def display_check_results(results: list[tuple[Device, bool | Status]]) -> None:
    """Print one monitoring cycle (Phase 2 compatible timestamp style)."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    name_width = max((len(device["name"]) for device, _ in results), default=4)
    ip_width = max((len(device["ip"]) for device, _ in results), default=7)

    for device, status in results:
        if isinstance(status, bool):
            label = "ONLINE" if status else "OFFLINE"
        else:
            label = status
        print(
            f"[{timestamp}] "
            f"{device['name']:<{name_width}}  "
            f"{device['ip']:<{ip_width}}  "
            f"{label}"
        )


def run_one_check(devices: list[Device]) -> list[tuple[Device, Status]]:
    """Run a single monitoring cycle and print ONLINE/OFFLINE results."""
    results = check_devices(devices)
    display_check_results(results)
    return results
