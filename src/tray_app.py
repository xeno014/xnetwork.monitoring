"""Windows system tray application for XenoTech IP Monitor.

Tray, console, and monitoring share one process and one ``ENGINE`` instance.

Console lifecycle (Phase 3 fix):
  NOT_CREATED → create once
  VISIBLE     → shown in taskbar
  HIDDEN      → hidden, removed from taskbar, process/tray/engine keep running

Closing the console (X / Ctrl+C / Q) only HIDES it.
Only tray Exit destroys the console and terminates the app.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from app_logger import log_event
from config_loader import load_settings
from console_ui import run_console_session
from engine import ENGINE
from paths import now_stamp
from startup import (
    disable_windows_startup,
    enable_windows_startup,
    is_windows_startup_enabled,
)

# ---------------------------------------------------------------------------
# Console state
# ---------------------------------------------------------------------------

NOT_CREATED = "not_created"
VISIBLE = "visible"
HIDDEN = "hidden"

_console_lock = threading.RLock()
_console_state = NOT_CREATED
_console_thread: threading.Thread | None = None
_console_stop = threading.Event()  # asks UI session to leave its input loop
_console_hwnd = 0
_stdio_handles: list[object] = []
_saved_stdio: tuple[object, object, object] | None = None
_old_wndproc = None
_wndproc_ref = None  # keep ctypes callback alive

# Win32 constants
WM_CLOSE = 0x0010
WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060
SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
MB_ICONERROR = 0x00000010
MB_ICONWARNING = 0x00000030
MB_YESNO = 0x00000004
MB_SETFOREGROUND = 0x00010000
MB_TASKMODAL = 0x00002000
IDYES = 6

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


def _user32():
    return ctypes.windll.user32


def _kernel32():
    return ctypes.windll.kernel32


def _set_window_long(hwnd: int, index: int, value: int) -> int:
    user32 = _user32()
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        return int(user32.SetWindowLongPtrW(hwnd, index, value))
    return int(user32.SetWindowLongW(hwnd, index, value))


def _get_window_long(hwnd: int, index: int) -> int:
    user32 = _user32()
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        return int(user32.GetWindowLongPtrW(hwnd, index))
    return int(user32.GetWindowLongW(hwnd, index))


def _create_icon():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), color=(15, 23, 42))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(34, 197, 94))
    draw.rectangle((28, 20, 36, 44), fill=(15, 23, 42))
    draw.ellipse((26, 46, 38, 54), fill=(15, 23, 42))
    return image


def _null_stream(mode: str):
    return open(os.devnull, mode, encoding="utf-8", errors="replace")  # noqa: SIM115


def _close_stdio_handles() -> None:
    global _stdio_handles
    for handle in list(_stdio_handles):
        try:
            handle.close()  # type: ignore[union-attr]
        except Exception:
            pass
    _stdio_handles = []


def _restore_quiet_stdio() -> None:
    global _saved_stdio
    _close_stdio_handles()
    if _saved_stdio is not None:
        sys.stdin, sys.stdout, sys.stderr = _saved_stdio  # type: ignore[assignment]
        _saved_stdio = None
    else:
        sys.stdin = _null_stream("r")
        sys.stdout = _null_stream("w")
        sys.stderr = _null_stream("w")


def _apply_taskbar_presence(hwnd: int, *, show_in_taskbar: bool) -> None:
    """Toggle console taskbar button via toolwindow/appwindow styles."""
    if not hwnd:
        return
    style = _get_window_long(hwnd, GWL_EXSTYLE)
    if show_in_taskbar:
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    else:
        style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    _set_window_long(hwnd, GWL_EXSTYLE, style)


def _console_wndproc(hwnd, msg, wparam, lparam):
    """Intercept console X button — hide instead of destroying the process."""
    global _old_wndproc
    if msg == WM_CLOSE:
        hide_console()
        return 0
    if msg == WM_SYSCOMMAND and (int(wparam) & 0xFFF0) == SC_CLOSE:
        hide_console()
        return 0
    if _old_wndproc:
        return int(
            _user32().CallWindowProcW(_old_wndproc, hwnd, msg, wparam, lparam)
        )
    return int(_user32().DefWindowProcW(hwnd, msg, wparam, lparam))


def _subclass_console_window(hwnd: int) -> None:
    """Install a WndProc that turns X into hide_console()."""
    global _old_wndproc, _wndproc_ref
    if not hwnd or _old_wndproc is not None:
        return
    _wndproc_ref = WNDPROC(_console_wndproc)
    _old_wndproc = _set_window_long(hwnd, GWLP_WNDPROC, ctypes.cast(_wndproc_ref, ctypes.c_void_p).value)


def _unblock_console_input() -> None:
    """Wake a blocked console UI read without destroying CONIN$."""
    if sys.platform != "win32":
        return
    try:
        handle = _kernel32().GetStdHandle(-10)
        if handle and handle != wintypes.HANDLE(-1).value:
            _kernel32().CancelIoEx(handle, None)
    except Exception:
        pass


def _ensure_console_created() -> bool:
    """Allocate the single process console exactly once."""
    global _console_hwnd, _saved_stdio, _stdio_handles, _console_state
    if sys.platform != "win32":
        return False

    # Already created and still alive.
    if (
        _console_state != NOT_CREATED
        and _console_hwnd
        and _user32().IsWindow(_console_hwnd)
    ):
        return True

    # Detach from any inherited console (e.g. launched from a terminal) so
    # AllocConsole creates a dedicated window owned by this process.
    existing = int(_kernel32().GetConsoleWindow() or 0)
    if existing:
        try:
            _kernel32().FreeConsole()
        except Exception:
            pass

    if not _kernel32().AllocConsole():
        return False

    _kernel32().SetConsoleTitleW("XenoTech IP Monitor")
    _saved_stdio = (sys.stdin, sys.stdout, sys.stderr)
    _stdio_handles = []
    stdin_f = open("CONIN$", "r", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    stdout_f = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    stderr_f = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    _stdio_handles.extend([stdin_f, stdout_f, stderr_f])
    sys.stdin, sys.stdout, sys.stderr = stdin_f, stdout_f, stderr_f

    hwnd = int(_kernel32().GetConsoleWindow() or 0)
    _console_hwnd = hwnd
    if hwnd:
        _subclass_console_window(hwnd)
        # Start hidden from taskbar until we explicitly show.
        _apply_taskbar_presence(hwnd, show_in_taskbar=False)
        _user32().ShowWindow(hwnd, SW_HIDE)
        _console_state = HIDDEN
    return bool(hwnd)


def hide_console() -> None:
    """Hide the console and remove its taskbar entry. Tray/engine keep running."""
    global _console_state, _console_hwnd
    with _console_lock:
        hwnd = _console_hwnd or int(_kernel32().GetConsoleWindow() or 0)
        if not hwnd:
            _console_state = NOT_CREATED
            return

        _console_stop.set()
        _unblock_console_input()

        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

        _apply_taskbar_presence(hwnd, show_in_taskbar=False)
        _user32().ShowWindow(hwnd, SW_HIDE)
        _console_state = HIDDEN
        _console_hwnd = hwnd
        log_event(f"Console hidden at {now_stamp()} (tray/monitoring still running)")


def show_console() -> bool:
    """Show/restore the single console and place it in the taskbar."""
    global _console_state, _console_hwnd
    with _console_lock:
        if not _ensure_console_created():
            return False
        hwnd = _console_hwnd or int(_kernel32().GetConsoleWindow() or 0)
        if not hwnd:
            return False
        _console_hwnd = hwnd
        _apply_taskbar_presence(hwnd, show_in_taskbar=True)
        _user32().ShowWindow(hwnd, SW_RESTORE)
        _user32().ShowWindow(hwnd, SW_SHOW)
        _user32().SetForegroundWindow(hwnd)
        _console_state = VISIBLE
        return True


def destroy_console() -> None:
    """Truly destroy the console (tray Exit / process shutdown only)."""
    global _console_state, _console_hwnd, _old_wndproc, _wndproc_ref
    with _console_lock:
        _console_stop.set()
        _unblock_console_input()
        hwnd = _console_hwnd or int(_kernel32().GetConsoleWindow() or 0)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        _close_stdio_handles()
        try:
            _kernel32().FreeConsole()
        except Exception:
            pass
        if hwnd:
            try:
                _user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        _restore_quiet_stdio()
        _console_hwnd = 0
        _old_wndproc = None
        _wndproc_ref = None
        _console_state = NOT_CREATED
        log_event(f"Console destroyed at {now_stamp()}")


def _ctrl_handler(ctrl_type: int) -> bool:
    """Ctrl+C / Break / Console X signal → hide console only."""
    # 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE
    if ctrl_type in (0, 1, 2):
        hide_console()
        return True
    return False


def _install_ctrl_handler() -> None:
    if sys.platform != "win32":
        return
    handler = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)(_ctrl_handler)
    _install_ctrl_handler._handler = handler  # type: ignore[attr-defined]
    _kernel32().SetConsoleCtrlHandler(handler, True)


def _start_console_ui_session() -> None:
    """Run (or restart) the console menu UI on the shared console."""
    global _console_thread

    if _console_thread is not None and _console_thread.is_alive():
        return

    _console_stop.clear()

    def runner() -> None:
        try:
            _install_ctrl_handler()
            print()
            print("XenoTech IP Monitor console ready.")
            print("Background monitoring is independent of this window.")
            print("Close (X), Ctrl+C, or Q hides this console — tray keeps running.")
            print()
            run_console_session(stop_event=_console_stop)
        except Exception as exc:
            log_event(f"Console session error: {exc}")
        finally:
            # UI session ended — hide console if still visible, never kill tray.
            if _console_state == VISIBLE:
                hide_console()
            log_event(f"Console UI session ended at {now_stamp()}")

    _console_thread = threading.Thread(
        target=runner,
        name="XenoTechConsoleUI",
        daemon=True,
    )
    _console_thread.start()


def open_console_window() -> None:
    """Single-instance console: create / show / focus — never duplicate."""
    with _console_lock:
        state = _console_state
        thread_alive = _console_thread is not None and _console_thread.is_alive()

        if state == VISIBLE:
            show_console()
            need_ui = not thread_alive
        elif state == HIDDEN:
            show_console()
            need_ui = True
            log_event(f"Console restored at {now_stamp()}")
        else:
            if not show_console():
                log_event("Failed to create console window")
                return
            need_ui = True
            log_event(f"Console created at {now_stamp()}")

    if need_ui:
        _start_console_ui_session()


# ---------------------------------------------------------------------------
# Dialogs — Devices (OK fix). Add Device preserved exactly.
# ---------------------------------------------------------------------------

def _message_box(title: str, text: str, flags: int) -> int:
    """Show a Win32 message box (call only from a non-pystray worker thread)."""
    return int(
        ctypes.windll.user32.MessageBoxW(
            None,
            text,
            title,
            flags | MB_SETFOREGROUND | MB_TASKMODAL,
        )
    )


def show_devices_dialog() -> None:
    """Show configured devices + status. OK must close cleanly."""
    devices = ENGINE.get_devices()
    statuses = ENGINE.get_statuses()
    lines = []
    for index, device in enumerate(devices, start=1):
        status = statuses.get(device["ip"], "UNKNOWN")
        lines.append(f"{index}. {device['name']}\n   {device['ip']}\n   {status}")
    text = "\n\n".join(lines) if lines else "No devices configured."

    # NEVER call MessageBox from the pystray menu callback thread — it
    # deadlocks with the tray message loop and OK appears broken.
    def deferred() -> None:
        time.sleep(0.25)
        _message_box("Configured Devices", text, MB_OK | MB_ICONINFORMATION)

    threading.Thread(target=deferred, name="XenoTechDevices", daemon=True).start()


def show_add_device_dialog() -> None:
    """Tray Add Device using Win32 prompts (no tkinter / pystray deadlock)."""

    def deferred() -> None:
        time.sleep(0.25)
        from device_manager import DeviceValidationError, add_device, validate_new_device

        name = _ask_string("Add Device", "Device name:")
        if name is None:
            return
        ip = _ask_string("Add Device", "IP address:")
        if ip is None:
            return

        try:
            proposed = validate_new_device(name, ip)
        except (DeviceValidationError, FileNotFoundError, ValueError, OSError) as exc:
            _message_box("ERROR", f"{exc}\n\nNo changes were made.", MB_OK | MB_ICONERROR)
            return

        answer = _message_box(
            "VERIFY NEW DEVICE",
            f"Device Name : {proposed['name']}\n"
            f"IP Address  : {proposed['ip']}\n\n"
            "Create this device?",
            MB_YESNO | MB_ICONWARNING,
        )
        if answer != IDYES:
            _message_box(
                "Cancelled",
                "Device creation cancelled.\nNo changes were made.",
                MB_OK | MB_ICONINFORMATION,
            )
            return

        try:
            created = add_device(proposed["name"], proposed["ip"])
        except (DeviceValidationError, FileNotFoundError, ValueError, OSError) as exc:
            _message_box(
                "ERROR",
                f"{exc}\n\nOriginal configuration was preserved.",
                MB_OK | MB_ICONERROR,
            )
            return

        _message_box(
            "Success",
            "Device created successfully.\n\n"
            f"Device Name : {created['name']}\n"
            f"IP Address  : {created['ip']}\n\n"
            "The device has been added to monitoring.",
            MB_OK | MB_ICONINFORMATION,
        )

    threading.Thread(target=deferred, name="XenoTechAddDevice", daemon=True).start()


def _ask_string(title: str, prompt: str) -> str | None:
    """Ask for a string using VB InputBox via PowerShell (Windows)."""
    if sys.platform != "win32":
        return None

    import subprocess

    safe_title = title.replace("'", "''")
    safe_prompt = prompt.replace("'", "''")
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"$r = [Microsoft.VisualBasic.Interaction]::InputBox("
        f"'{safe_prompt}','{safe_title}',''); "
        # Distinguish Cancel (returns empty) by also checking dialog result is hard;
        # empty string is treated as cancel for our prompts.
        "Write-Output $r"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if result.returncode != 0:
            return None
        value = (result.stdout or "").rstrip("\r\n")
        if value == "":
            return None
        return value
    except Exception:
        return None


def _status_text(_: object = None) -> str:
    state = "RUNNING" if ENGINE.is_monitoring() else "STOPPED"
    count = len(ENGINE.get_devices())
    return f"Status: {state} | Devices: {count}"


def run_tray_app() -> None:
    """Start the system tray UI (blocking on the main thread)."""
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: pystray. Install with:\n"
            "  pip install pystray Pillow"
        ) from exc

    settings = load_settings()
    log_event(f"Tray application starting at {now_stamp()}")

    if settings["start_monitoring_on_launch"] and not ENGINE.is_monitoring():
        ENGINE.start_monitoring()

    icon_image = _create_icon()

    def on_devices(icon: object, item: object) -> None:
        _ = icon, item
        show_devices_dialog()

    def on_add_device(icon: object, item: object) -> None:
        _ = icon, item
        show_add_device_dialog()

    def on_start(icon: object, item: object) -> None:
        _ = item
        ENGINE.start_monitoring()
        icon.title = _status_text()  # type: ignore[attr-defined]

    def on_stop(icon: object, item: object) -> None:
        _ = item
        ENGINE.stop_monitoring()
        icon.title = _status_text()  # type: ignore[attr-defined]

    def on_static(icon: object, item: object) -> None:
        _ = icon, item
        try:
            ENGINE.run_check_cycle(notify=True)
            log_event("Tray: Static Check completed")
        except Exception as exc:
            log_event(f"Tray static check failed: {exc}")

    def on_scanner(icon: object, item: object) -> None:
        _ = icon, item
        open_console_window()

    def on_open_console(icon: object, item: object) -> None:
        _ = icon, item
        open_console_window()

    def on_enable_startup(icon: object, item: object) -> None:
        _ = icon, item
        enable_windows_startup()

    def on_disable_startup(icon: object, item: object) -> None:
        _ = icon, item
        disable_windows_startup()

    def on_exit(icon: object, item: object) -> None:
        _ = item
        log_event(f"Tray Exit requested at {now_stamp()}")
        # Full shutdown — only path that destroys console + stops engine.
        destroy_console()
        ENGINE.stop_monitoring()
        icon.stop()

    menu = pystray.Menu(
        Item(_status_text, None, enabled=False),
        Item("Devices", on_devices),
        Item("Add Device", on_add_device),
        Item("Start Monitoring", on_start),
        Item("Stop Monitoring", on_stop),
        Item("Static Check", on_static),
        Item("IP Scanner", on_scanner),
        Item("Open Console", on_open_console),
        pystray.Menu.SEPARATOR,
        Item(
            "Enable Windows Startup",
            on_enable_startup,
            checked=lambda item: is_windows_startup_enabled(),
            visible=lambda item: not is_windows_startup_enabled(),
        ),
        Item(
            "Disable Windows Startup",
            on_disable_startup,
            visible=lambda item: is_windows_startup_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        Item("Exit", on_exit),
    )

    icon = pystray.Icon(
        "XenoTechIPMonitor",
        icon_image,
        "XenoTech IP Monitor",
        menu,
    )
    icon.default_action = on_open_console

    try:
        icon.run()
    finally:
        destroy_console()
        ENGINE.stop_monitoring()
        log_event(f"Tray application stopped at {now_stamp()}")
