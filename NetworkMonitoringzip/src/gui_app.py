"""XenoTech IP Monitor - desktop window (Tkinter).

Sits on top of the shared ``ENGINE`` so the GUI never starts a second
monitoring loop. Closing the window hides it to the system tray (when
pystray is available); only tray "Exit" stops monitoring.
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from app_logger import log_event
from config_loader import (
    load_devices,
    load_settings,
    save_devices,
    save_settings,
)
from device_manager import add_device
from discord_bot import DiscordBot
from engine import ENGINE
from netspeed import (
    SpeedTestError,
    agent_speedtest,
    link_speedtest,
    run_internet_speedtest,
    save_result,
)
from paths import ICON_PATH, LOGS_DIR, PROJECT_ROOT, now_stamp
from scanner import run_lan_scan
from startup import (
    disable_windows_startup,
    enable_windows_startup,
    is_windows_startup_enabled,
)

# --- palette -----------------------------------------------------------------
BG = "#0f172a"
CARD = "#1e293b"
HEADER = "#273449"
SELECT = "#334155"
FG = "#e2e8f0"
MUTED = "#94a3b8"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"

STATUS_LABELS = {
    "ONLINE": "\u25cf ONLINE",
    "OFFLINE": "\u25cf OFFLINE",
    "UNKNOWN": "\u25cf UNKNOWN",
}

THIS_PC = "This PC (internet)"

_mutex_handle = None  # keep the single-instance mutex alive


def _acquire_single_instance() -> bool:
    """Return False if another copy of the app is already running."""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\XenoTechIPMonitor")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _make_tray_icon():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), color=(15, 23, 42))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(34, 197, 94))
    draw.rectangle((28, 20, 36, 44), fill=(15, 23, 42))
    draw.ellipse((26, 46, 38, 54), fill=(15, 23, 42))
    return image


def _apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=BG)

    style.configure(".", background=BG, foreground=FG, fieldbackground=CARD,
                    font=("Segoe UI", 10), bordercolor=SELECT, lightcolor=BG,
                    darkcolor=BG, troughcolor=CARD)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
    style.configure("Error.TLabel", foreground=RED)

    style.configure("Card.TFrame", background=CARD)
    style.configure("Card.TLabel", background=CARD, foreground=MUTED)
    style.configure("CardNum.TLabel", background=CARD, foreground=FG,
                    font=("Segoe UI", 24, "bold"))
    style.configure("CardGreen.TLabel", background=CARD, foreground=GREEN,
                    font=("Segoe UI", 24, "bold"))
    style.configure("CardRed.TLabel", background=CARD, foreground=RED,
                    font=("Segoe UI", 24, "bold"))

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 8), background=CARD,
                    foreground=MUTED, borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", HEADER)],
              foreground=[("selected", FG)])

    style.configure("Treeview", background=CARD, fieldbackground=CARD,
                    foreground=FG, rowheight=30, borderwidth=0)
    style.configure("Treeview.Heading", background=HEADER, foreground=FG,
                    relief="flat", padding=(8, 6), font=("Segoe UI", 10, "bold"))
    style.map("Treeview.Heading", background=[("active", SELECT)])
    style.map("Treeview", background=[("selected", SELECT)],
              foreground=[("selected", FG)])

    style.configure("TButton", padding=(14, 7), background=HEADER,
                    foreground=FG, borderwidth=0, focusthickness=0)
    style.map("TButton", background=[("active", SELECT), ("disabled", CARD)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=GREEN, foreground="#052e16",
                    font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", "#16a34a"), ("disabled", CARD)],
              foreground=[("disabled", MUTED)])

    style.configure("TEntry", fieldbackground=CARD, foreground=FG,
                    insertcolor=FG, padding=6)
    style.configure("TSpinbox", fieldbackground=CARD, foreground=FG,
                    insertcolor=FG, arrowcolor=FG, padding=4)
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)],
              indicatorcolor=[("selected", GREEN), ("!selected", CARD)])
    style.configure("TRadiobutton", background=BG, foreground=FG)
    style.map("TRadiobutton", background=[("active", BG)],
              indicatorcolor=[("selected", GREEN), ("!selected", CARD)])
    style.configure("TCombobox", fieldbackground=CARD, background=HEADER,
                    foreground=FG, arrowcolor=FG, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", CARD)],
              foreground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    style.configure("Horizontal.TProgressbar", background=GREEN,
                    troughcolor=CARD, borderwidth=0)


# --- dialogs -------------------------------------------------------------------
class AddDeviceDialog(tk.Toplevel):
    """Modal 'Add Device' form (same validation as the console flow)."""

    def __init__(self, parent: tk.Misc, ip: str = "", on_added=None) -> None:
        super().__init__(parent)
        self._on_added = on_added
        self.title("Add Device")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Device name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(body, textvariable=self.name_var, width=36)
        name_entry.grid(row=1, column=0, sticky="we", pady=(2, 12))

        ttk.Label(body, text="IPv4 address").grid(row=2, column=0, sticky="w")
        self.ip_var = tk.StringVar(value=ip)
        ttk.Entry(body, textvariable=self.ip_var, width=36).grid(
            row=3, column=0, sticky="we", pady=(2, 8))

        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var, style="Error.TLabel",
                  wraplength=300).grid(row=4, column=0, sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="left", padx=(0, 8))
        ttk.Button(buttons, text="Add Device", style="Accent.TButton",
                   command=self._submit).pack(side="left")

        self.bind("<Return>", lambda _e: self._submit())
        self.bind("<Escape>", lambda _e: self.destroy())

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self.grab_set()
        name_entry.focus_set()

    def _submit(self) -> None:
        try:
            device = add_device(self.name_var.get(), self.ip_var.get())
        except (ValueError, OSError) as exc:
            self.error_var.set(str(exc))
            return
        if self._on_added:
            self._on_added(device)
        self.destroy()


# --- main window -----------------------------------------------------------------
class App(tk.Tk):
    def __init__(self, start_minimized: bool = False) -> None:
        super().__init__()
        self.title("XenoTech IP Monitor")
        self.geometry("920x600")
        self.minsize(780, 500)
        try:
            if sys.platform == "win32" and ICON_PATH.is_file():
                self.iconbitmap(str(ICON_PATH))
        except tk.TclError:
            pass
        _apply_theme(self)

        self._events: queue.Queue = queue.Queue()
        self._last_check = "\u2014"
        self._last_change: dict[str, str] = {}
        self._scanning = False
        self._speed_busy = False
        self._speed_names: list[str] = []
        self._tray = None
        self._tray_hint_shown = False
        self.bot = DiscordBot(
            on_status=lambda msg: self._events.put(("bot_status", msg)))

        self._build_header()
        self._build_cards()
        self._build_tabs()

        ENGINE.add_listener(self._on_engine_event)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._refresh_devices()
        self._refresh_monitoring_state()
        self._setup_tray()

        if ENGINE.config_error:
            self._log(f"CONFIG ERROR: {ENGINE.config_error}", "bad")
        settings = load_settings()
        if settings["start_monitoring_on_launch"] and not ENGINE.is_monitoring():
            if ENGINE.get_devices():
                ENGINE.start_monitoring()

        self._restart_bot()

        if start_minimized:
            if self._tray is not None:
                self.withdraw()
            else:
                self.iconify()

        self.after(200, self._drain_events)

    # --- construction ---------------------------------------------------------
    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(20, 16, 20, 4))
        header.pack(fill="x")
        ttk.Label(header, text="XenoTech IP Monitor", style="Title.TLabel").pack(
            side="left")
        self.state_label = tk.Label(header, text="", bg=BG, fg=MUTED,
                                    font=("Segoe UI", 11, "bold"))
        self.state_label.pack(side="right")

    def _build_cards(self) -> None:
        row = ttk.Frame(self, padding=(20, 8, 20, 8))
        row.pack(fill="x")
        self.card_vars: dict[str, tk.StringVar] = {}
        specs = [("total", "Devices", "CardNum.TLabel"),
                 ("online", "Online", "CardGreen.TLabel"),
                 ("offline", "Offline", "CardRed.TLabel"),
                 ("checked", "Last check", "CardNum.TLabel")]
        for index, (key, caption, num_style) in enumerate(specs):
            card = ttk.Frame(row, style="Card.TFrame", padding=(16, 10))
            card.grid(row=0, column=index, sticky="nsew",
                      padx=(0 if index == 0 else 10, 0))
            row.columnconfigure(index, weight=1)
            var = tk.StringVar(value="0")
            self.card_vars[key] = var
            label = ttk.Label(card, textvariable=var, style=num_style)
            if key == "checked":
                label.configure(font=("Segoe UI", 15, "bold"))
            label.pack(anchor="w")
            ttk.Label(card, text=caption, style="Card.TLabel").pack(anchor="w")

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        self._build_devices_tab()
        self._build_scanner_tab()
        self._build_speed_tab()
        self._build_log_tab()
        self._build_settings_tab()

    def _make_tree(self, parent, columns, widths) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                            show="headings", selectmode="browse")
        for (key, heading), width in zip(columns, widths):
            tree.heading(key, text=heading)
            tree.column(key, width=width, anchor="w")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        return tree

    def _build_devices_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.tabs.add(tab, text="  Devices  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        self.toggle_btn = ttk.Button(bar, text="Start Monitoring",
                                     style="Accent.TButton",
                                     command=self._toggle_monitoring)
        self.toggle_btn.pack(side="left")
        self.check_btn = ttk.Button(bar, text="Check Now", command=self._check_now)
        self.check_btn.pack(side="left", padx=8)
        ttk.Button(bar, text="Add Device", command=self._open_add_dialog).pack(
            side="left")
        ttk.Button(bar, text="Remove Selected", command=self._remove_selected).pack(
            side="left", padx=8)

        self.dev_tree = self._make_tree(
            tab,
            [("name", "Device"), ("ip", "IP Address"), ("status", "Status"),
             ("changed", "Last Change")],
            [300, 160, 140, 200])
        self.dev_tree.tag_configure("ONLINE", foreground=GREEN)
        self.dev_tree.tag_configure("OFFLINE", foreground=RED)
        self.dev_tree.tag_configure("UNKNOWN", foreground=MUTED)

    def _build_scanner_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.tabs.add(tab, text="  IP Scanner  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        self.scan_btn = ttk.Button(bar, text="Start Scan", style="Accent.TButton",
                                   command=self._start_scan)
        self.scan_btn.pack(side="left")
        ttk.Button(bar, text="Add Selected to Monitoring",
                   command=self._add_scan_selection).pack(side="left", padx=8)
        self.scan_status = tk.StringVar(value="Scans your local subnet for IP/MAC addresses.")
        ttk.Label(bar, textvariable=self.scan_status, style="Muted.TLabel").pack(
            side="left", padx=8)

        self.scan_bar = ttk.Progressbar(tab, mode="indeterminate")
        self.scan_bar.pack(fill="x", pady=(0, 8))

        self.scan_tree = self._make_tree(
            tab,
            [("ip", "IP Address"), ("mac", "MAC Address"), ("monitored", "Monitored")],
            [200, 260, 140])
        self.scan_tree.tag_configure("monitored", foreground=GREEN)
        self.scan_tree.bind("<Double-1>", lambda _e: self._add_scan_selection())

    def _build_speed_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.tabs.add(tab, text="  Speed Test  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Target").pack(side="left")
        self.speed_target = tk.StringVar(value=THIS_PC)
        self.speed_combo = ttk.Combobox(bar, textvariable=self.speed_target,
                                        state="readonly", width=28, values=[THIS_PC])
        self.speed_combo.pack(side="left", padx=8)
        self.speed_mode = tk.StringVar(value="internet")
        ttk.Radiobutton(bar, text="Its internet", value="internet",
                        variable=self.speed_mode).pack(side="left")
        ttk.Radiobutton(bar, text="Link to this PC", value="link",
                        variable=self.speed_mode).pack(side="left", padx=(8, 14))
        self.speed_btn = ttk.Button(bar, text="Run Test", style="Accent.TButton",
                                    command=self._run_selected_speed)
        self.speed_btn.pack(side="left")
        self.speed_all_btn = ttk.Button(bar, text="Test All Devices",
                                        command=self._run_all_speed)
        self.speed_all_btn.pack(side="left", padx=8)

        self.speed_status = tk.StringVar(
            value="This PC tests its own internet. Other devices need the Speed Agent running.")
        ttk.Label(tab, textvariable=self.speed_status, style="Muted.TLabel").pack(
            fill="x", pady=(0, 6))
        self.speed_bar = ttk.Progressbar(tab, mode="indeterminate")
        self.speed_bar.pack(fill="x", pady=(0, 8))

        self.speed_tree = self._make_tree(
            tab,
            [("time", "Time"), ("target", "Target"), ("test", "Test"),
             ("down", "Download (Mbps)"), ("up", "Upload (Mbps)"),
             ("lat", "Latency (ms)")],
            [150, 180, 150, 130, 120, 110])

    def _build_log_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.tabs.add(tab, text="  Activity Log  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="Clear View", command=self._clear_log).pack(side="left")
        ttk.Button(bar, text="Open Log File", command=self._open_log_file).pack(
            side="left", padx=8)

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(frame, bg=CARD, fg=FG, bd=0, wrap="word",
                                font=("Consolas", 10), state="disabled",
                                padx=10, pady=8, highlightthickness=0)
        bar_y = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=bar_y.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        bar_y.pack(side="right", fill="y")
        self.log_text.tag_configure("good", foreground=GREEN)
        self.log_text.tag_configure("bad", foreground=RED)
        self.log_text.tag_configure("info", foreground=MUTED)

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=(4, 16, 4, 0))
        self.tabs.add(tab, text="  Settings  ")
        settings = load_settings()

        def row(r: int, text: str) -> None:
            ttk.Label(tab, text=text).grid(row=r, column=0, sticky="w",
                                           pady=7, padx=(0, 20))

        row(0, "Check interval (seconds)")
        self.interval_var = tk.StringVar(value=str(settings["check_interval_seconds"]))
        ttk.Spinbox(tab, from_=1, to=3600, width=8,
                    textvariable=self.interval_var).grid(row=0, column=1, sticky="w")

        row(1, "Scanner duration (seconds)")
        self.scan_dur_var = tk.StringVar(value=str(settings["scanner_duration_seconds"]))
        ttk.Spinbox(tab, from_=5, to=600, width=8,
                    textvariable=self.scan_dur_var).grid(row=1, column=1, sticky="w")

        row(2, "Mark OFFLINE after N failed pings")
        self.failures_var = tk.StringVar(value=str(settings["offline_after_failures"]))
        ttk.Spinbox(tab, from_=1, to=10, width=8,
                    textvariable=self.failures_var).grid(row=2, column=1, sticky="w")

        row(3, "Discord webhook URL (alerts)")
        self.webhook_var = tk.StringVar(value=settings["discord_webhook_url"])
        self.webhook_entry = ttk.Entry(tab, textvariable=self.webhook_var,
                                       width=58, show="\u2022")
        self.webhook_entry.grid(row=3, column=1, sticky="w")
        self.show_hook = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tab, text="Show", variable=self.show_hook,
            command=lambda: self.webhook_entry.configure(
                show="" if self.show_hook.get() else "\u2022"),
        ).grid(row=3, column=2, sticky="w", padx=8)

        row(4, "Discord bot token (/commands)")
        self.bot_token_var = tk.StringVar(value=settings["discord_bot_token"])
        self.bot_token_entry = ttk.Entry(tab, textvariable=self.bot_token_var,
                                         width=58, show="\u2022")
        self.bot_token_entry.grid(row=4, column=1, sticky="w")
        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tab, text="Show", variable=self.show_token,
            command=lambda: self.bot_token_entry.configure(
                show="" if self.show_token.get() else "\u2022"),
        ).grid(row=4, column=2, sticky="w", padx=8)

        row(5, "Allowed user IDs (comma separated)")
        self.bot_users_var = tk.StringVar(
            value=", ".join(str(i) for i in settings["discord_allowed_user_ids"]))
        ttk.Entry(tab, textvariable=self.bot_users_var, width=58).grid(
            row=5, column=1, sticky="w")

        row(6, "Server ID (optional)")
        guild = settings["discord_guild_id"]
        self.bot_guild_var = tk.StringVar(value=str(guild) if guild else "")
        ttk.Entry(tab, textvariable=self.bot_guild_var, width=30).grid(
            row=6, column=1, sticky="w")

        self.bot_status_var = tk.StringVar(value="Bot: not running")
        ttk.Label(tab, textvariable=self.bot_status_var,
                  style="Muted.TLabel").grid(row=7, column=1, sticky="w")

        row(8, "Speed agent token")
        self.agent_token_var = tk.StringVar(value=settings["speed_agent_token"])
        self.agent_token_entry = ttk.Entry(tab, textvariable=self.agent_token_var,
                                           width=40, show="\u2022")
        self.agent_token_entry.grid(row=8, column=1, sticky="w")
        self.show_agent = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tab, text="Show", variable=self.show_agent,
            command=lambda: self.agent_token_entry.configure(
                show="" if self.show_agent.get() else "\u2022"),
        ).grid(row=8, column=2, sticky="w", padx=8)

        row(9, "Speed agent port")
        self.agent_port_var = tk.StringVar(value=str(settings["speed_agent_port"]))
        ttk.Spinbox(tab, from_=1, to=65535, width=8,
                    textvariable=self.agent_port_var).grid(row=9, column=1, sticky="w")

        self.autostart_var = tk.BooleanVar(value=settings["start_monitoring_on_launch"])
        ttk.Checkbutton(tab, text="Start monitoring when the app opens",
                        variable=self.autostart_var).grid(
            row=10, column=1, sticky="w", pady=(10, 4))

        self.winstart_var = tk.BooleanVar(value=is_windows_startup_enabled())
        winstart = ttk.Checkbutton(tab, text="Run when Windows starts (in the tray)",
                                   variable=self.winstart_var,
                                   command=self._toggle_windows_startup)
        winstart.grid(row=11, column=1, sticky="w", pady=4)
        if sys.platform != "win32":
            winstart.state(["disabled"])

        self.settings_msg = tk.StringVar()
        ttk.Button(tab, text="Save Settings", style="Accent.TButton",
                   command=self._save_settings).grid(row=12, column=1, sticky="w",
                                                     pady=(14, 4))
        ttk.Label(tab, textvariable=self.settings_msg, style="Muted.TLabel").grid(
            row=13, column=1, sticky="w")
        ttk.Label(tab, text=f"Config & logs folder: {PROJECT_ROOT}",
                  style="Muted.TLabel").grid(row=14, column=0, columnspan=3,
                                             sticky="w", pady=(18, 0))

    # --- tray -------------------------------------------------------------------
    def _setup_tray(self) -> None:
        try:
            import pystray
            image = _make_tray_icon()
        except Exception:
            self._tray = None
            return

        def post(fn):
            return lambda icon, item: self._events.put(("ui", fn))

        menu = pystray.Menu(
            pystray.MenuItem("Show Window", post(self._show_window), default=True),
            pystray.MenuItem("Start Monitoring", post(self._start_monitoring),
                             visible=lambda item: not ENGINE.is_monitoring()),
            pystray.MenuItem("Stop Monitoring", post(self._stop_monitoring),
                             visible=lambda item: ENGINE.is_monitoring()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", post(self._quit)),
        )
        try:
            self._tray = pystray.Icon("XenoTechIPMonitor", image,
                                      "XenoTech IP Monitor", menu)
            self._tray.run_detached()
        except Exception as exc:
            log_event(f"Tray unavailable: {exc}")
            self._tray = None

    def _tray_notify(self, title: str, message: str) -> None:
        if self._tray is None:
            return
        try:
            self._tray.notify(message, title)
        except Exception:
            pass

    # --- window lifecycle ---------------------------------------------------------
    def _show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        if self._tray is not None:
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray_notify("XenoTech IP Monitor",
                                  "Still monitoring in the system tray. "
                                  "Right-click the icon to exit.")
            return
        if messagebox.askokcancel("Exit", "Closing will stop monitoring. Exit now?"):
            self._quit()

    def _quit(self) -> None:
        log_event(f"GUI exit requested at {now_stamp()}")
        ENGINE.remove_listener(self._on_engine_event)
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.destroy()  # monitor/scan threads are daemons and die with the process

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: D401
        message = "".join(traceback.format_exception_only(exc, val)).strip()
        log_event(f"GUI error: {message}")
        try:
            self._log(f"Internal error: {message}", "bad")
        except Exception:
            pass

    # --- engine events -------------------------------------------------------------
    def _on_engine_event(self, event: str, payload: dict) -> None:
        # Called from the engine thread: just queue it for the UI thread.
        self._events.put((event, payload))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self._events.get_nowait()
                try:
                    self._handle_event(event, payload)
                except Exception as exc:  # never let one bad event stop the loop
                    log_event(f"GUI event error ({event}): {exc}")
        except queue.Empty:
            pass
        finally:
            self.after(200, self._drain_events)

    def _handle_event(self, event: str, payload) -> None:
        if event == "ui":
            payload()
        elif event == "check_complete":
            self._last_check = payload["time"][11:]
            self._refresh_devices()
        elif event == "status_change":
            device = payload["device"]
            status = payload["status"]
            self._last_change[device["ip"]] = payload["time"]
            self._log(f"{device['name']} ({device['ip']}): "
                      f"{payload['previous']} \u2192 {status}",
                      "good" if status == "ONLINE" else "bad")
            if status == "OFFLINE":
                self._tray_notify("Device OFFLINE", f"{device['name']} ({device['ip']})")
            elif payload["previous"] == "OFFLINE":
                self._tray_notify("Device back ONLINE", f"{device['name']} ({device['ip']})")
            self._refresh_devices()
        elif event in {"monitoring_started", "monitoring_stopped"}:
            self._log("Monitoring started" if event == "monitoring_started"
                      else "Monitoring stopped", "info")
            self._refresh_monitoring_state()
        elif event == "check_done":
            self.check_btn.state(["!disabled"])
        elif event == "speed_progress":
            self.speed_status.set(payload)
        elif event == "speed_result":
            label, test, result = payload
            self.speed_status.set(
                f"{label} ({test}): {result['download_mbps']:.1f} Mbps down / "
                f"{result['upload_mbps']:.1f} Mbps up / {result['latency_ms']:.0f} ms")
            self.speed_tree.insert("", 0, values=(
                result["time"], label, test, f"{result['download_mbps']:.1f}",
                f"{result['upload_mbps']:.1f}", f"{result['latency_ms']:.0f}"))
            self._log(f"Speed test {label} ({test}): "
                      f"{result['download_mbps']:.1f} down / "
                      f"{result['upload_mbps']:.1f} up Mbps", "good")
        elif event == "speed_error":
            self.speed_status.set(payload)
            self._log(f"Speed test failed - {payload}", "bad")
        elif event == "speed_done":
            self._speed_busy = False
            self.speed_bar.stop()
            self.speed_btn.state(["!disabled"])
            self.speed_all_btn.state(["!disabled"])
        elif event == "bot_status":
            self.bot_status_var.set(payload)
            self._log(payload, "bad" if "fail" in payload or "error" in payload
                      or "unavailable" in payload else "info")
        elif event == "scan_progress":
            self.scan_status.set(payload)
        elif event == "scan_hit":
            if not self.scan_tree.exists(payload.ip):
                self.scan_tree.insert("", "end", iid=payload.ip,
                                      values=(payload.ip, payload.mac, ""))
        elif event == "scan_done":
            self._finish_scan(payload)

    # --- devices tab ----------------------------------------------------------------
    def _refresh_devices(self) -> None:
        devices = ENGINE.get_devices()
        statuses = ENGINE.get_statuses()

        wanted = [d["ip"] for d in devices]
        if list(self.dev_tree.get_children()) != wanted:
            selected = self.dev_tree.selection()
            self.dev_tree.delete(*self.dev_tree.get_children())
            for d in devices:
                self.dev_tree.insert("", "end", iid=d["ip"], values=("", "", "", ""))
            keep = [i for i in selected if self.dev_tree.exists(i)]
            if keep:
                self.dev_tree.selection_set(keep)

        online = offline = 0
        for d in devices:
            status = statuses.get(d["ip"], "UNKNOWN")
            online += status == "ONLINE"
            offline += status == "OFFLINE"
            self.dev_tree.item(
                d["ip"],
                values=(d["name"], d["ip"], STATUS_LABELS.get(status, status),
                        self._last_change.get(d["ip"], "\u2014")),
                tags=(status,),
            )

        names = [d["name"] for d in devices]
        if names != self._speed_names:
            self._speed_names = names
            self.speed_combo.configure(values=[THIS_PC] + names)
            if self.speed_target.get() not in [THIS_PC] + names:
                self.speed_target.set(THIS_PC)

        self.card_vars["total"].set(str(len(devices)))
        self.card_vars["online"].set(str(online))
        self.card_vars["offline"].set(str(offline))
        self.card_vars["checked"].set(self._last_check)
        self._refresh_scan_monitored()
        if self._tray is not None:
            try:
                self._tray.title = f"XenoTech IP Monitor - {online}/{len(devices)} online"
            except Exception:
                pass

    def _refresh_monitoring_state(self) -> None:
        running = ENGINE.is_monitoring()
        self.state_label.configure(
            text="\u25cf Monitoring" if running else "\u25cf Stopped",
            fg=GREEN if running else RED)
        self.toggle_btn.configure(
            text="Stop Monitoring" if running else "Start Monitoring")
        self.toggle_btn.state(["!disabled"])

    def _start_monitoring(self) -> None:
        ENGINE.start_monitoring()

    def _stop_monitoring(self) -> None:
        self.toggle_btn.state(["disabled"])
        threading.Thread(target=ENGINE.stop_monitoring, daemon=True).start()

    def _toggle_monitoring(self) -> None:
        if ENGINE.is_monitoring():
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _check_now(self) -> None:
        self.check_btn.state(["disabled"])

        def worker() -> None:
            try:
                ENGINE.run_check_cycle(notify=True)
                log_event("GUI: manual check completed")
            except Exception as exc:
                log_event(f"GUI manual check failed: {exc}")
            self._events.put(("check_done", {}))

        threading.Thread(target=worker, daemon=True).start()

    def _open_add_dialog(self, ip: str = "") -> None:
        AddDeviceDialog(self, ip=ip, on_added=self._device_added)

    def _device_added(self, device) -> None:
        self._log(f"Device added: {device['name']} ({device['ip']})", "info")
        self._refresh_devices()

    def _remove_selected(self) -> None:
        selection = self.dev_tree.selection()
        if not selection:
            messagebox.showinfo("Remove device", "Select a device first.")
            return
        ip = selection[0]
        name = self.dev_tree.item(ip, "values")[0]
        if not messagebox.askyesno("Remove device", f'Stop monitoring "{name}" ({ip})?'):
            return
        try:
            remaining = [d for d in load_devices() if d["ip"] != ip]
            save_devices(remaining)
            ENGINE.reload_config()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Remove device", str(exc))
            return
        log_event(f"Device removed: {name} ({ip}) at {now_stamp()}")
        self._log(f"Device removed: {name} ({ip})", "info")
        self._refresh_devices()

    # --- scanner tab ----------------------------------------------------------------
    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.scan_btn.state(["disabled"])
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_status.set("Starting scan...")
        self.scan_bar.start(12)
        duration = load_settings()["scanner_duration_seconds"]
        put = self._events.put

        def worker() -> None:
            try:
                hits = run_lan_scan(
                    duration,
                    on_progress=lambda msg: put(("scan_progress", msg)),
                    on_discovery=lambda hit: put(("scan_hit", hit)),
                )
            except Exception as exc:
                log_event(f"GUI scan failed: {exc}")
                put(("scan_progress", f"Scan failed: {exc}"))
                hits = []
            put(("scan_done", hits))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_scan(self, hits) -> None:
        self._scanning = False
        self.scan_bar.stop()
        self.scan_btn.state(["!disabled"])
        self.scan_tree.delete(*self.scan_tree.get_children())
        for hit in hits:
            self.scan_tree.insert("", "end", iid=hit.ip, values=(hit.ip, hit.mac, ""))
        self.scan_status.set(f"Scan complete \u2014 {len(hits)} device(s) found.")
        self._refresh_scan_monitored()

    def _refresh_scan_monitored(self) -> None:
        monitored = {d["ip"] for d in ENGINE.get_devices()}
        for iid in self.scan_tree.get_children():
            ip, mac, _ = self.scan_tree.item(iid, "values")
            yes = ip in monitored
            self.scan_tree.item(iid, values=(ip, mac, "Yes" if yes else ""),
                                tags=("monitored",) if yes else ())

    def _add_scan_selection(self) -> None:
        selection = self.scan_tree.selection()
        if not selection:
            messagebox.showinfo("IP Scanner", "Select a scanned device first.")
            return
        self._open_add_dialog(ip=selection[0])

    # --- speed test tab ------------------------------------------------------------
    def _run_selected_speed(self) -> None:
        choice = self.speed_target.get()
        if choice == THIS_PC:
            self._run_speed([(THIS_PC, "internet", None)])
            return
        device = next((d for d in ENGINE.get_devices() if d["name"] == choice), None)
        if device is None:
            messagebox.showinfo("Speed Test", "Pick a target first.")
            return
        self._run_speed([(device["name"], self.speed_mode.get(), device)])

    def _run_all_speed(self) -> None:
        statuses = ENGINE.get_statuses()
        jobs = [(THIS_PC, "internet", None)]
        for device in ENGINE.get_devices():
            if statuses.get(device["ip"]) != "OFFLINE":
                jobs.append((device["name"], "internet", device))
        self._run_speed(jobs)

    def _run_speed(self, jobs: list) -> None:
        if self._speed_busy:
            return
        self._speed_busy = True
        self.speed_btn.state(["disabled"])
        self.speed_all_btn.state(["disabled"])
        self.speed_bar.start(12)
        self.speed_status.set("Starting speed test...")
        settings = load_settings()
        token, port = settings["speed_agent_token"], settings["speed_agent_port"]
        put = self._events.put

        def worker() -> None:
            for label, kind, device in jobs:
                def progress(message: str, label: str = label) -> None:
                    put(("speed_progress", f"{label}: {message}"))

                try:
                    if device is None:
                        test, result = "Internet", run_internet_speedtest(progress)
                    elif not token:
                        raise SpeedTestError(
                            "set the speed agent token in Settings first.")
                    elif kind == "link":
                        test = "Link to this PC"
                        result = link_speedtest(device["ip"], port, token,
                                                on_progress=progress)
                    else:
                        test = "Internet (device)"
                        result = agent_speedtest(device["ip"], port, token, progress)
                    save_result(label, test, result)
                    put(("speed_result", (label, test, result)))
                except SpeedTestError as exc:
                    put(("speed_error", f"{label}: {exc}"))
                except Exception as exc:
                    log_event(f"GUI speed test error: {exc}")
                    put(("speed_error", f"{label}: {type(exc).__name__}: {exc}"))
            put(("speed_done", {}))

        threading.Thread(target=worker, daemon=True).start()

    # --- log tab ------------------------------------------------------------------
    def _log(self, message: str, tag: str = "info") -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{now_stamp()}] {message}\n", tag)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 1000:
            self.log_text.delete("1.0", f"{lines - 1000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open_log_file(self) -> None:
        path = LOGS_DIR / "monitor.log"
        if sys.platform == "win32" and path.is_file():
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("Log file", f"Log file location:\n{path}")

    # --- settings tab ----------------------------------------------------------------
    def _toggle_windows_startup(self) -> None:
        want = self.winstart_var.get()
        ok = enable_windows_startup() if want else disable_windows_startup()
        if not ok:
            self.winstart_var.set(not want)
            messagebox.showerror("Windows startup",
                                 "Could not change the Windows startup entry.")

    def _save_settings(self) -> None:
        try:
            interval = int(self.interval_var.get())
            duration = int(self.scan_dur_var.get())
            failures = int(self.failures_var.get())
            agent_port = int(self.agent_port_var.get())
            if not 1 <= agent_port <= 65535:
                raise ValueError("Speed agent port must be between 1 and 65535.")
            if not 1 <= failures <= 10:
                raise ValueError("Failed pings before OFFLINE must be between 1 and 10.")
            if not 1 <= interval <= 3600:
                raise ValueError("Check interval must be between 1 and 3600 seconds.")
            if not 5 <= duration <= 600:
                raise ValueError("Scanner duration must be between 5 and 600 seconds.")
        except ValueError as exc:
            msg = str(exc) if "must be" in str(exc) else "Please enter whole numbers."
            self.settings_msg.set(msg)
            return
        raw_users = self.bot_users_var.get().replace(";", ",").replace(" ", ",")
        user_ids: list[int] = []
        for part in (p for p in raw_users.split(",") if p):
            if not part.isdigit():
                self.settings_msg.set(
                    "Allowed user IDs must be numbers (Discord > Copy User ID).")
                return
            user_ids.append(int(part))
        guild_text = self.bot_guild_var.get().strip()
        if guild_text and not guild_text.isdigit():
            self.settings_msg.set("Server ID must be a number.")
            return
        try:
            save_settings({
                "discord_webhook_url": self.webhook_var.get().strip(),
                "check_interval_seconds": interval,
                "scanner_duration_seconds": duration,
                "offline_after_failures": failures,
                "start_monitoring_on_launch": bool(self.autostart_var.get()),
                "discord_bot_token": self.bot_token_var.get().strip(),
                "discord_allowed_user_ids": user_ids,
                "discord_guild_id": int(guild_text) if guild_text else 0,
                "speed_agent_token": self.agent_token_var.get().strip(),
                "speed_agent_port": agent_port,
            })
            ENGINE.reload_config()
        except (ValueError, OSError) as exc:
            self.settings_msg.set(f"Could not save: {exc}")
            return
        log_event("Settings saved from GUI")  # never log the webhook URL
        self.settings_msg.set("Saved.")
        self._refresh_devices()
        self._restart_bot()

    def _restart_bot(self) -> None:
        """(Re)start the Discord bot from saved settings, off the UI thread."""
        settings = load_settings()
        if not settings["discord_bot_token"]:
            self.bot_status_var.set("Bot: off (no token set)")

        def worker() -> None:
            self.bot.stop()
            if settings["discord_bot_token"]:
                self._events.put(("bot_status", "Discord bot starting..."))
                self.bot.start(settings["discord_bot_token"],
                               settings["discord_allowed_user_ids"],
                               settings["discord_guild_id"])

        threading.Thread(target=worker, daemon=True).start()


def run_gui(start_minimized: bool = False) -> int:
    """Launch the desktop window. Returns a process exit code."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on HiDPI
        except Exception:
            pass

    if not _acquire_single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "XenoTech IP Monitor",
            "XenoTech IP Monitor is already running.\n"
            "Look for its icon in the system tray (near the clock).")
        root.destroy()
        return 0

    app = App(start_minimized=start_minimized)
    try:
        app.mainloop()
    finally:
        ENGINE.stop_monitoring()
    return 0
