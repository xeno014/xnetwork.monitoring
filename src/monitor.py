"""Basic IP reachability monitoring engine (Phase 2)."""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime

from config_loader import Device

# Default timeout for a single ping attempt (milliseconds on Windows).
PING_TIMEOUT_MS = 2000


def is_reachable(ip: str, timeout_ms: int = PING_TIMEOUT_MS) -> bool:
    """Check whether an IPv4 address responds to a single ping.

    Uses the system ``ping`` command so no third-party packages are required.
    On Windows: ``ping -n 1 -w <timeout_ms> <ip>``.

    Args:
        ip: IPv4 address to check.
        timeout_ms: Per-ping timeout in milliseconds.

    Returns:
        True if the host appears reachable, False otherwise.
        Errors (timeouts, missing ping, etc.) are treated as unreachable
        so the monitoring loop keeps running.
    """
    if sys.platform == "win32":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        # Prevent a console window flash when spawned from some hosts.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        # Linux/macOS: -c count, -W timeout in seconds.
        timeout_sec = max(1, (timeout_ms + 999) // 1000)
        command = ["ping", "-c", "1", "-W", str(timeout_sec), ip]
        creationflags = 0

    # Extra margin so subprocess.wait does not hang if ping misbehaves.
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


def _status_label(online: bool) -> str:
    return "ONLINE" if online else "OFFLINE"


def check_devices(devices: list[Device]) -> list[tuple[Device, bool]]:
    """Ping each device once and return (device, reachable) pairs."""
    results: list[tuple[Device, bool]] = []
    for device in devices:
        reachable = is_reachable(device["ip"])
        results.append((device, reachable))
    return results


def display_check_results(results: list[tuple[Device, bool]]) -> None:
    """Print one monitoring cycle with timestamps and aligned columns."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    name_width = max((len(device["name"]) for device, _ in results), default=4)
    ip_width = max((len(device["ip"]) for device, _ in results), default=7)

    for device, reachable in results:
        print(
            f"[{timestamp}] "
            f"{device['name']:<{name_width}}  "
            f"{device['ip']:<{ip_width}}  "
            f"{_status_label(reachable)}"
        )


def run_one_check(devices: list[Device]) -> None:
    """Run a single monitoring cycle and print ONLINE/OFFLINE results."""
    results = check_devices(devices)
    display_check_results(results)


def _print_static_prompt() -> None:
    """Show the STATIC_MODE completion message and key hints."""
    print()
    print("Static check complete.")
    print()
    print("Press:")
    print("[Ctrl+T] Test again")
    print("[Ctrl+C] Exit")
    print()


def run_static_mode(devices: list[Device]) -> None:
    """Run STATIC_MODE: one check now, then wait for Ctrl+T / Ctrl+C.

    Each Ctrl+T performs exactly one new monitoring cycle.
    Ctrl+C exits (raises KeyboardInterrupt).

    Args:
        devices: Enabled devices to monitor (already filtered).

    Raises:
        KeyboardInterrupt: When the user presses Ctrl+C.
    """
    from keyboard_input import wait_for_ctrl_t

    run_one_check(devices)
    _print_static_prompt()

    while True:
        wait_for_ctrl_t()
        run_one_check(devices)
        _print_static_prompt()


def run_monitoring_loop(devices: list[Device], interval_seconds: int) -> None:
    """CONTINUE_MODE: continuously check reachability until interrupted.

    Args:
        devices: Enabled devices to monitor (already filtered).
        interval_seconds: Seconds to wait between full check cycles.

    Raises:
        KeyboardInterrupt: When the user presses Ctrl+C.
    """
    while True:
        run_one_check(devices)
        print()
        time.sleep(interval_seconds)
