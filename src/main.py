"""XenoTech IP Monitor — Phase 3 entry point.

Modes:
  python src/main.py              → Windows system tray (default on Windows)
  python src/main.py --tray       → Force tray mode
  python src/main.py --console    → Interactive console menu
  python src/main.py continue|1   → Phase 2-compatible CONTINUE (foreground)
  python src/main.py static|2     → Phase 2-compatible STATIC
  python src/main.py scanner|3    → IP Scanner
  python src/main.py add|4        → Add Device
"""

from __future__ import annotations

import sys

from app_logger import log_event
from config_loader import get_enabled_devices, load_devices, load_settings
from engine import ENGINE
from paths import now_stamp


MODE_ALIASES = {
    "continue": "continue",
    "1": "continue",
    "static": "static",
    "2": "static",
    "scanner": "scanner",
    "ip scanner": "scanner",
    "3": "scanner",
    "add": "add",
    "add device": "add",
    "4": "add",
    "console": "console",
    "tray": "tray",
}


def normalize_mode(raw: str) -> str | None:
    return MODE_ALIASES.get(raw.strip().lower())


def bootstrap_engine() -> int:
    """Load configuration into the shared engine. Returns exit code on failure."""
    try:
        devices = load_devices()
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        log_event(f"Configuration error: {exc}")
        return 1

    enabled = get_enabled_devices(devices)
    if not enabled:
        print("No devices found in configuration.", file=sys.stderr)
        return 1

    ENGINE.reload_config()
    return 0


def run_legacy_or_menu(argv: list[str]) -> int:
    """Console / Phase 2 compatible paths."""
    from console_ui import (
        run_add_device_flow,
        run_console_session,
        run_ip_scanner_ui,
        run_monitoring_loop,
        run_static_mode,
    )

    mode: str | None = None
    if len(argv) > 1:
        arg = argv[1].strip().lower()
        if arg in {"--console", "console"}:
            mode = "console"
        elif arg in {"--tray", "tray"}:
            mode = "tray"
        else:
            mode = normalize_mode(arg)
            if mode is None:
                print(
                    f'Unknown mode "{argv[1]}". '
                    "Use continue/1, static/2, scanner/3, add/4, --console, or --tray.",
                    file=sys.stderr,
                )
                return 1

    if mode == "tray":
        from tray_app import run_tray_app

        run_tray_app()
        return 0

    if mode in {None, "console"}:
        try:
            run_console_session()
        except KeyboardInterrupt:
            print()
            print("Stopping XenoTech Network Monitor...")
            print("Monitor stopped.")
        return 0

    devices = ENGINE.get_devices()
    settings = load_settings()
    interval = settings["check_interval_seconds"]

    print("XenoTech Network Monitor")
    print("========================")
    print(f"Mode: {mode.upper()}")
    print()

    try:
        if mode == "continue":
            run_monitoring_loop(devices, interval)
        elif mode == "static":
            run_static_mode(devices)
        elif mode == "scanner":
            run_ip_scanner_ui()
        elif mode == "add":
            run_add_device_flow()
    except KeyboardInterrupt:
        print()
        print("Stopping XenoTech Network Monitor...")
        print("Monitor stopped.")
        return 0
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    log_event(f"Application startup at {now_stamp()}")
    code = bootstrap_engine()
    if code != 0:
        return code

    # Default on Windows with no args: tray mode (no lingering console required).
    if len(argv) == 1 and sys.platform == "win32":
        try:
            from tray_app import run_tray_app

            run_tray_app()
            log_event(f"Application shutdown at {now_stamp()}")
            return 0
        except SystemExit as exc:
            # Fall back to console if tray deps missing.
            print(str(exc), file=sys.stderr)
            print("Falling back to console mode...", file=sys.stderr)

    result = run_legacy_or_menu(argv)
    log_event(f"Application shutdown at {now_stamp()}")
    return result


if __name__ == "__main__":
    sys.exit(main())
