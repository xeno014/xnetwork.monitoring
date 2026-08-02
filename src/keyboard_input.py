"""Windows keyboard helpers for STATIC_MODE (Ctrl+T / Ctrl+C).

STATIC_MODE waits for the Ctrl+T chord so the user can re-run a single
check without typing a command word. Implementation uses ``msvcrt`` on
Windows and is intentionally isolated here.

Ctrl+C remains the exit path:
- Console control handler may raise ``KeyboardInterrupt`` during sleep.
- If the console delivers Ctrl+C as byte ``0x03``, that is also treated
  as an exit request.
"""

from __future__ import annotations

import sys
import time

# ASCII control codes produced by Windows console for these chords.
CTRL_C = 0x03
CTRL_T = 0x14


def wait_for_ctrl_t() -> None:
    """Block until the user presses Ctrl+T.

    Raises:
        KeyboardInterrupt: If the user presses Ctrl+C.
        NotImplementedError: If the platform is not Windows.
    """
    if sys.platform != "win32":
        raise NotImplementedError(
            "STATIC_MODE Ctrl+T handling is implemented for Windows only."
        )

    import msvcrt

    while True:
        if msvcrt.kbhit():
            first = msvcrt.getch()
            # Extended / special keys arrive as a two-byte sequence.
            if first in (b"\x00", b"\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getch()
                continue

            code = first[0]
            if code == CTRL_T:
                return
            if code == CTRL_C:
                raise KeyboardInterrupt
            # Ignore all other keys; remain in STATIC_MODE waiting.
        else:
            # Brief pause avoids a busy loop and lets Ctrl+C raise
            # KeyboardInterrupt via the normal console handler.
            time.sleep(0.05)
