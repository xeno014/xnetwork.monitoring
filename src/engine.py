"""Single central monitoring engine (thread-safe).

All tray and console controls talk to this one engine — never start a second
continuous monitoring loop.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from app_logger import log_event
from config_loader import Device, get_enabled_devices, load_devices, load_settings
from discord_notify import send_status_change_notification
from monitor import Status, check_devices
from paths import now_stamp

Listener = Callable[[str, dict[str, Any]], None]


class MonitoringEngine:
    """Owns device list, per-device status, and the continuous check loop."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: list[Device] = []
        self._statuses: dict[str, Status] = {}  # keyed by IP
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._interval = 5
        self._webhook_url = ""
        self._listeners: list[Listener] = []
        self.reload_config()

    # --- configuration -------------------------------------------------

    def reload_config(self) -> None:
        """Reload devices and settings from disk."""
        settings = load_settings()
        devices = get_enabled_devices(load_devices())
        with self._lock:
            self._interval = settings["check_interval_seconds"]
            self._webhook_url = settings["discord_webhook_url"]
            previous_statuses = dict(self._statuses)
            self._devices = devices
            self._statuses = {
                device["ip"]: previous_statuses.get(device["ip"], "UNKNOWN")
                for device in devices
            }
        log_event(f"Configuration loaded: {len(devices)} device(s)")

    def get_devices(self) -> list[Device]:
        with self._lock:
            return list(self._devices)

    def get_statuses(self) -> dict[str, Status]:
        with self._lock:
            return dict(self._statuses)

    def get_interval(self) -> int:
        with self._lock:
            return self._interval

    def is_monitoring(self) -> bool:
        with self._lock:
            return self._running

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event, payload or {})
            except Exception:
                pass

    # --- checks --------------------------------------------------------

    def run_check_cycle(self, *, notify: bool = True) -> list[tuple[Device, Status]]:
        """Check all devices once; optionally Discord-notify on changes."""
        devices = self.get_devices()
        results = check_devices(devices)
        changes: list[tuple[Device, Status, Status]] = []

        with self._lock:
            webhook = self._webhook_url
            for device, new_status in results:
                ip = device["ip"]
                previous = self._statuses.get(ip, "UNKNOWN")
                self._statuses[ip] = new_status
                if previous != new_status:
                    changes.append((device, previous, new_status))

        for device, previous, new_status in changes:
            log_event(
                f"Status change: {device['name']} ({device['ip']}) "
                f"{previous} -> {new_status}"
            )
            self._emit(
                "status_change",
                {
                    "device": device,
                    "previous": previous,
                    "status": new_status,
                    "time": now_stamp(),
                },
            )
            if notify:
                # Notify on real transitions only (unchanged states never reach here).
                send_status_change_notification(
                    webhook,
                    device_name=device["name"],
                    ip=device["ip"],
                    new_status=new_status,
                    previous_status=previous,
                )

        self._emit("check_complete", {"results": results, "time": now_stamp()})
        return results

    # --- continuous monitoring -----------------------------------------

    def start_monitoring(self) -> bool:
        """Start the continuous loop if not already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="XenoTechMonitor",
                daemon=True,
            )
            self._thread.start()
        log_event("Monitoring started")
        self._emit("monitoring_started", {"time": now_stamp()})
        return True

    def stop_monitoring(self) -> bool:
        """Stop the continuous loop."""
        with self._lock:
            if not self._running:
                return False
            self._running = False
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.get_interval() + 3)
        log_event("Monitoring stopped")
        self._emit("monitoring_stopped", {"time": now_stamp()})
        return True

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_check_cycle(notify=True)
            except Exception as exc:
                log_event(f"Monitoring cycle error: {exc}")
            # Wait interval; wake early on stop.
            if self._stop_event.wait(self.get_interval()):
                break


# Process-wide singleton — tray and console share this instance.
ENGINE = MonitoringEngine()
