"""Simple file logger for Phase 3 events."""

from __future__ import annotations

import threading
from pathlib import Path

from paths import LOGS_DIR, now_stamp

_lock = threading.Lock()
_log_path: Path | None = None


def _ensure_log_path() -> Path:
    global _log_path
    if _log_path is None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _log_path = LOGS_DIR / "monitor.log"
    return _log_path


def log_event(message: str) -> None:
    """Append a timestamped line to the local monitor log."""
    line = f"[{now_stamp()}] {message}\n"
    try:
        path = _ensure_log_path()
        with _lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        # Logging must never crash the application.
        pass
