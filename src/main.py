"""XenoTech Network Monitor — Phase 2: Basic IP Monitoring Engine."""

from __future__ import annotations

import sys

from config_loader import get_enabled_devices, load_devices
from monitor import run_monitoring_loop, run_static_mode

# Seconds between each full monitoring cycle in CONTINUE_MODE.
CHECK_INTERVAL = 5

# User-facing aliases → canonical mode name.
MODE_ALIASES = {
    "continue": "continue",
    "1": "continue",
    "static": "static",
    "2": "static",
}


def normalize_mode(raw: str) -> str | None:
    """Map a user mode string to ``continue`` or ``static``.

    Accepts case-insensitive names and numeric shortcuts ``1`` / ``2``.
    Returns None when the value is not recognized.
    """
    key = raw.strip().lower()
    return MODE_ALIASES.get(key)


def prompt_mode(argv: list[str]) -> str | None:
    """Resolve monitoring mode from CLI args or an interactive prompt.

    Interactive invalid input is rejected with a clear message and the
    user is asked again. Ctrl+C / EOF during the prompt exits cleanly
    via KeyboardInterrupt / EOFError to the caller.
    """
    if len(argv) > 1:
        mode = normalize_mode(argv[1])
        if mode is not None:
            return mode
        print(
            f'Unknown mode "{argv[1]}". '
            'Use "continue"/"1" or "static"/"2".',
            file=sys.stderr,
        )
        # Fall through to interactive selection so the user can recover.
        print()

    print("Select monitoring mode:")
    print(
        f"  1 / continue  - Automatic checks every {CHECK_INTERVAL} seconds"
    )
    print("  2 / static    - One check now; Ctrl+T to test again")
    print()

    while True:
        raw = input("Mode: ").strip()
        mode = normalize_mode(raw)
        if mode is not None:
            return mode
        print(
            f'Unknown mode "{raw}". '
            'Please enter "continue"/"1" or "static"/"2".'
        )
        print()


def display_banner(mode: str, device_count: int) -> None:
    """Print the Phase 2 startup banner for the selected mode."""
    print("XenoTech Network Monitor")
    print("========================")
    print(f"Mode: {mode.upper()}")
    print()
    if mode == "continue":
        print(f"Monitoring {device_count} device(s)...")
        print()


def main(argv: list[str] | None = None) -> int:
    """Load enabled devices and start the selected monitoring mode."""
    if argv is None:
        argv = sys.argv

    try:
        devices = load_devices()
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    enabled = get_enabled_devices(devices)
    if not enabled:
        print("No enabled devices found in configuration.", file=sys.stderr)
        print('Set "enabled": true for at least one device in config/devices.json.')
        return 1

    try:
        mode = prompt_mode(argv)
    except (EOFError, KeyboardInterrupt):
        print()
        print("Stopping XenoTech Network Monitor...")
        print("Monitor stopped.")
        return 0

    if mode is None:
        return 1

    display_banner(mode, len(enabled))

    try:
        if mode == "static":
            run_static_mode(enabled)
        else:
            run_monitoring_loop(enabled, CHECK_INTERVAL)
    except KeyboardInterrupt:
        print()
        print("Stopping XenoTech Network Monitor...")
        print("Monitor stopped.")
        return 0
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
