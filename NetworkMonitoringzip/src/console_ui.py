"""Interactive console UI for XenoTech IP Monitor."""

from __future__ import annotations

import sys
import threading
from typing import Callable

from app_logger import log_event
from config_loader import load_settings
from device_manager import DeviceValidationError, add_device, validate_new_device
from engine import ENGINE
from keyboard_input import using_custom_input, wait_for_console_command
from paths import now_stamp
from scanner import run_lan_scan


ExitCallback = Callable[[], None]


def print_main_menu() -> None:
    print("=" * 48)
    print("XenoTech IP Monitor")
    print("=" * 19)
    print()
    print("1. Continue")
    print("2. Static")
    print("3. IP Scanner")
    print("4. Add Device")
    print()
    print("Ctrl + N = Add Device")
    print("Ctrl + T = Test Again")
    print("Ctrl + C = Exit Console")
    print("=" * 23)
    print()


def print_configured_devices() -> None:
    devices = ENGINE.get_devices()
    statuses = ENGINE.get_statuses()
    print("=" * 48)
    print("Configured Devices")
    print("=" * 18)
    print()
    if not devices:
        print("No devices configured.")
    for index, device in enumerate(devices, start=1):
        status = statuses.get(device["ip"], "UNKNOWN")
        print(f"{index}. {device['name']}")
        print(f"   {device['ip']}")
        print(f"   {status}")
        print()
    print()


def print_phase3_static_results() -> None:
    """Run one check and print the Phase 3 STATIC CHECK table."""
    print()
    print("Testing devices...")
    print()
    results = ENGINE.run_check_cycle(notify=True)
    print("# STATIC CHECK")
    print()
    print("## Device                 IP              Status")
    print()
    name_width = max((len(d["name"]) for d, _ in results), default=6)
    ip_width = max((len(d["ip"]) for d, _ in results), default=7)
    for device, status in results:
        print(
            f"{device['name']:<{name_width}}   "
            f"{device['ip']:<{ip_width}}   "
            f"{status}"
        )
    print()
    print(f"Time: {now_stamp()}")
    print()
    print("Press Ctrl + T to test again.")
    print("Press Ctrl + N to add a device.")
    print("Press Ctrl + C to exit console.")
    print()
    log_event(f"Static check completed at {now_stamp()}")


def run_add_device_flow() -> None:
    """Interactive Add Device with validation + confirmation + final save."""
    print()
    print("=" * 40)
    print("ADD NEW DEVICE")
    print("=" * 14)
    print()
    try:
        name = input("Device name: ").strip()
        ip = input("IP address: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("Device creation cancelled.")
        print("No changes were made.")
        log_event("Device creation cancelled")
        return

    try:
        proposed = validate_new_device(name, ip)
    except DeviceValidationError as exc:
        print()
        print("ERROR")
        print()
        print(str(exc))
        print()
        print("No changes were made.")
        log_event(f"Device validation failed: {exc}")
        return
    except (FileNotFoundError, ValueError, OSError) as exc:
        print()
        print("ERROR")
        print()
        print(f"Configuration error: {exc}")
        print()
        print("No changes were made.")
        log_event(f"Device validation config error: {exc}")
        return

    print()
    print("=" * 40)
    print("VERIFY NEW DEVICE")
    print("=" * 17)
    print()
    print(f"Device Name : {proposed['name']}")
    print(f"IP Address  : {proposed['ip']}")
    print()
    print("---")
    print()
    try:
        answer = input("Create this device? [Y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer not in {"y", "yes"}:
        print()
        print("Device creation cancelled.")
        print("No changes were made.")
        log_event("Device creation cancelled by user")
        return

    try:
        created = add_device(proposed["name"], proposed["ip"])
    except DeviceValidationError as exc:
        print()
        print("ERROR")
        print()
        print(str(exc))
        print()
        print("No changes were made.")
        log_event(f"Final device validation failed: {exc}")
        return
    except (FileNotFoundError, ValueError, OSError) as exc:
        print()
        print("ERROR")
        print()
        print(f"Failed to save configuration: {exc}")
        print()
        print("Original configuration was preserved.")
        log_event(f"Device save failed: {exc}")
        return

    print()
    print("Device created successfully.")
    print()
    print(f"Device Name : {created['name']}")
    print(f"IP Address  : {created['ip']}")
    print()
    print("The device has been added to monitoring.")
    print()


def run_ip_scanner_ui() -> None:
    settings = load_settings()
    duration = settings["scanner_duration_seconds"]
    print()
    print("=" * 48)
    print("XenoTech Network Scanner")
    print("=" * 24)
    print()
    print("Scanning local network...")
    print()

    last_lines: list[str] = []

    def on_progress(message: str) -> None:
        if message.startswith("Time remaining:"):
            print(f"\r{message}   ", end="", flush=True)
        else:
            print(message)

    def on_discovery(hit) -> None:
        line = f"{hit.ip:<17}  {hit.mac}"
        last_lines.append(line)

    try:
        hits = run_lan_scan(
            duration,
            on_progress=on_progress,
            on_discovery=on_discovery,
        )
    except Exception as exc:
        print()
        print(f"Scanner failed: {exc}")
        log_event(f"Scanner UI failure: {exc}")
        return

    print()
    print()
    print("## IP Address        MAC Address")
    print()
    for hit in hits:
        print(f"{hit.ip:<17}  {hit.mac}")
    print()
    print("---")
    print()
    print(f"Devices discovered: {len(hits)}")
    print()
    print("Scan complete.")
    print()
    print("Discovered devices are NOT automatically added to monitoring.")
    print("Use option 4 / Ctrl+N to add a device manually.")
    print()


def run_continue_console(stop_event: threading.Event | None = None) -> None:
    """Attach to the shared engine continuous loop and print updates.

    Does not create a second monitoring loop — only listens to ``ENGINE``.
    """
    import queue
    import time

    from keyboard_input import CTRL_C, CTRL_N, CTRL_T

    print()
    print("Mode: CONTINUE")
    print(f"Interval: {ENGINE.get_interval()} seconds")
    print()

    events: queue.Queue = queue.Queue()

    def listener(event: str, payload: dict) -> None:
        if event == "check_complete":
            events.put(payload)

    ENGINE.add_listener(listener)

    if not ENGINE.is_monitoring():
        # Immediate first check, then start the single background loop.
        _print_continue_cycle(ENGINE.run_check_cycle(notify=True))
        ENGINE.start_monitoring()
        print("Monitoring started.")
    else:
        print("Monitoring already running in the background.")
        print("Waiting for the next shared-engine cycle...")
    print("Ctrl+T = force one check now | Ctrl+N = add device | Ctrl+C = close console")
    print("(Closing this view does not stop background monitoring.)")
    print()

    try:
        from keyboard_input import poll_console_command

        while True:
            if stop_event is not None and stop_event.is_set():
                raise KeyboardInterrupt

            while not events.empty():
                payload = events.get_nowait()
                results = payload.get("results") or []
                if results:
                    _print_continue_cycle(results)

            command = poll_console_command(0.05)
            if command == "test":
                print()
                print("Testing devices...")
                _print_continue_cycle(ENGINE.run_check_cycle(notify=True))
            elif command == "add":
                run_add_device_flow()
    except KeyboardInterrupt:
        if stop_event is not None:
            stop_event.set()
        raise
    except KeyboardInterrupt:
        print()
        if stop_event is not None and stop_event.is_set():
            print("Closing console...")
        else:
            print("Returning to menu. Background monitoring remains active.")
        print()
    finally:
        ENGINE.remove_listener(listener)


def _print_continue_cycle(results) -> None:
    stamp = now_stamp()
    for device, status in results:
        print(f"[{stamp}]")
        print(f"{device['name']} - {device['ip']} - {status}")
        print()


def run_static_console(stop_event: threading.Event | None = None) -> None:
    print_phase3_static_results()
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                raise KeyboardInterrupt
            command = wait_for_console_command()
            if command == "test":
                print_phase3_static_results()
            elif command == "add":
                run_add_device_flow()
                print_phase3_static_results()
    except KeyboardInterrupt:
        print()
        if stop_event is not None:
            stop_event.set()
            print("Closing console...")
        else:
            print("Returning to menu.")
        print()

def run_console_session(
    *,
    on_exit_console: ExitCallback | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Run the interactive console menu until the user exits the console.

    Args:
        on_exit_console: Optional callback after the session ends.
        stop_event: When set (e.g. tray Ctrl+C), leave the menu and close.
    """
    log_event(f"Console opened at {now_stamp()}")
    print_main_menu()

    while True:
        if stop_event is not None and stop_event.is_set():
            print()
            print("Closing console...")
            break

        try:
            raw = _read_menu_choice(stop_event)
        except (EOFError, KeyboardInterrupt, OSError):
            print()
            print("Closing console...")
            break

        if raw is None:
            print()
            print("Closing console...")
            break

        raw = raw.strip().lower()
        if raw in {"q", "quit", "exit"}:
            print("Closing console...")
            break
        if raw in {"1", "continue"}:
            try:
                run_continue_console(stop_event=stop_event)
            except KeyboardInterrupt:
                print()
            if stop_event is not None and stop_event.is_set():
                print("Closing console...")
                break
            print_main_menu()
            continue
        if raw in {"2", "static"}:
            try:
                run_static_console(stop_event=stop_event)
            except KeyboardInterrupt:
                print()
            if stop_event is not None and stop_event.is_set():
                print("Closing console...")
                break
            print_main_menu()
            continue
        if raw in {"3", "scanner", "ip scanner"}:
            try:
                run_ip_scanner_ui()
            except KeyboardInterrupt:
                print()
                print("Scanner cancelled.")
            if stop_event is not None and stop_event.is_set():
                print("Closing console...")
                break
            print_main_menu()
            continue
        if raw in {"4", "add", "add device"}:
            try:
                run_add_device_flow()
            except KeyboardInterrupt:
                print()
                print("Device creation cancelled.")
                print("No changes were made.")
            if stop_event is not None and stop_event.is_set():
                print("Closing console...")
                break
            print_main_menu()
            continue
        if raw in {"d", "devices"}:
            print_configured_devices()
            continue

        print('Unknown option. Enter 1, 2, 3, 4, or Q.')
        print()

    log_event(f"Console closed at {now_stamp()}")
    if on_exit_console:
        on_exit_console()


def _read_menu_choice(stop_event: threading.Event | None) -> str | None:
    """Read a menu line; return None when stop_event asks to close."""
    prompt = "Select option [1-4] (or Q to close console): "
    if stop_event is None or sys.platform != "win32" or using_custom_input():
        if stop_event is not None and stop_event.is_set():
            return None
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt, OSError):
            if stop_event is not None:
                stop_event.set()
            return None

    import msvcrt
    import time

    print(prompt, end="", flush=True)
    chars: list[str] = []
    while True:
        if stop_event.is_set():
            return None
        if msvcrt.kbhit():
            raw = msvcrt.getwch()
            if raw in ("\x00", "\xe0"):
                # Consume extended key.
                if msvcrt.kbhit():
                    msvcrt.getwch()
                continue
            if raw in ("\x03",):  # Ctrl+C
                stop_event.set()
                return None
            if raw in ("\r", "\n"):
                print()
                return "".join(chars)
            if raw in ("\b", "\x08"):
                if chars:
                    chars.pop()
                    # Erase last character visually.
                    print("\b \b", end="", flush=True)
                continue
            chars.append(raw)
            print(raw, end="", flush=True)
        else:
            time.sleep(0.05)


# Phase 2 compatibility wrappers used by legacy CLI paths.
def run_static_mode(devices) -> None:
    """Phase 2 STATIC_MODE behavior using the shared engine device list."""
    _ = devices
    run_static_console()


def run_monitoring_loop(devices, interval_seconds: int) -> None:
    """Phase 2 CONTINUE_MODE: foreground-only loop (no background duplicate)."""
    import time

    _ = devices
    interval = interval_seconds or ENGINE.get_interval()
    # Ensure we do not also run the background engine loop.
    if ENGINE.is_monitoring():
        ENGINE.stop_monitoring()

    print(f"Monitoring {len(ENGINE.get_devices())} device(s)...")
    print()
    try:
        while True:
            _print_continue_cycle(ENGINE.run_check_cycle(notify=True))
            time.sleep(interval)
    except KeyboardInterrupt:
        raise
