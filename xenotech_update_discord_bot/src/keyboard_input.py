"""Windows keyboard helpers for console shortcuts.

Ctrl+T = test again
Ctrl+N = add device
Ctrl+C = exit console (KeyboardInterrupt)
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

CTRL_C = 0x03
CTRL_N = 0x0E
CTRL_T = 0x14

# Optional replacement used by the tray-hosted console window.
# Returns "test" | "add", or raises KeyboardInterrupt for Ctrl+C.
_poll_command: Callable[[float], str | None] | None = None


def set_command_poller(poller: Callable[[float], str | None] | None) -> None:
    """Install or clear a custom Ctrl+T / Ctrl+N / Ctrl+C poller."""
    global _poll_command
    _poll_command = poller


def using_custom_input() -> bool:
    """True when the tray console is feeding keyboard commands."""
    return _poll_command is not None


def poll_console_command(timeout: float = 0.05) -> str | None:
    """Wait up to ``timeout`` seconds for Ctrl+T / Ctrl+N / Ctrl+C.

    Returns:
        ``"test"``, ``"add"``, or None if nothing was pressed.

    Raises:
        KeyboardInterrupt: If the user presses Ctrl+C.
    """
    if _poll_command is not None:
        return _poll_command(timeout)

    if sys.platform != "win32":
        raise NotImplementedError(
            "Console Ctrl+T / Ctrl+N handling is implemented for Windows only."
        )

    import msvcrt

    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if msvcrt.kbhit():
            first = msvcrt.getch()
            if first in (b"\x00", b"\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getch()
                continue
            code = first[0]
            if code == CTRL_T:
                return "test"
            if code == CTRL_N:
                return "add"
            if code == CTRL_C:
                raise KeyboardInterrupt
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def wait_for_console_command() -> str:
    """Block until Ctrl+T or Ctrl+N is pressed.

    Returns:
        ``"test"`` for Ctrl+T, ``"add"`` for Ctrl+N.

    Raises:
        KeyboardInterrupt: If the user presses Ctrl+C.
        NotImplementedError: If the platform is not Windows.
    """
    while True:
        command = poll_console_command(0.05)
        if command is not None:
            return command


def wait_for_ctrl_t() -> None:
    """Phase 2 compatible helper: wait specifically for Ctrl+T."""
    while True:
        command = wait_for_console_command()
        if command == "test":
            return
        # Ignore Ctrl+N here for Phase 2 callers.
