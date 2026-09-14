# XenoTech IP Monitor

Windows-only local network monitor for configured IP addresses (**ONLINE** / **OFFLINE**), with LAN IP/MAC discovery, Discord status-change alerts, and a system tray presence.

## Current Phase

**Phase 3 — System Tray + Multi-Device Monitoring + LAN IP/MAC Scanner**

Phase 1 (foundation) and Phase 2 (Continue / Static monitoring) behavior is preserved and extended.

## Requirements

- Windows 10 / 11
- Python 3.10+ recommended (project developed on Python 3.14)
- System `ping` and `arp` commands

### Install dependencies

```bash
pip install -r requirements.txt
```

Exact packages:

```bash
pip install "pystray>=0.19.5" "Pillow>=10.0.0"
```

`pystray` + `Pillow` are used only for the Windows system tray icon/menu. Monitoring, scanning, Discord, and config I/O use the standard library.

## How to Run

### Normal operation (system tray, no lingering CMD)

```bash
pythonw src/main.py
```

or:

```bash
python src/main.py --tray
```

- Tray icon appears
- Background monitoring can start automatically (`start_monitoring_on_launch` in settings)
- Double-click the tray icon (or **Open Console**) to view the console
- Closing the console does **not** stop monitoring
- Choose **Exit** in the tray menu to stop everything

### Development / console menu

```bash
python src/main.py --console
```

### Direct modes (Phase 2 compatible)

```bash
python src/main.py continue
python src/main.py static
python src/main.py scanner
python src/main.py add
```

Numeric shortcuts: `1` Continue, `2` Static, `3` IP Scanner, `4` Add Device.

## Console Menu

```
================================================
XenoTech IP Monitor
===================

1. Continue
2. Static
3. IP Scanner
4. Add Device

Ctrl + N = Add Device
Ctrl + T = Test Again
Ctrl + C = Exit Console
=======================
```

| Shortcut | Action |
|----------|--------|
| **Ctrl+T** | One additional static/manual check |
| **Ctrl+N** | Add Device flow |
| **Ctrl+C** | Leave console view (tray app keeps running) |

## Continue Mode

- Immediate first check
- Repeats every **5 seconds** (configurable)
- Each device keeps an independent status (`UNKNOWN` / `ONLINE` / `OFFLINE`)
- Discord alerts only on **status changes**, not every poll

## Static Mode

- One check of all configured devices
- Does **not** auto-repeat
- **Ctrl+T** runs exactly one more check
- **Ctrl+C** returns to the menu / closes console cleanly

## IP Scanner

- Detects the Windows host’s local subnet automatically when possible
- Scans for up to **60 seconds**
- Displays **IP Address** and **MAC Address** only (no hostnames)
- Does **not** auto-add devices to monitoring
- Use **Add Device** / **Ctrl+N** to monitor a discovered IP

## Add Device (Ctrl+N)

1. Enter name + IPv4
2. Validate (empty / invalid / duplicates / config integrity)
3. Confirmation screen `[Y/N]`
4. Final validation
5. Atomic JSON write (temp file + replace)
6. Reload runtime device list (no restart)

## Configuration

### Devices — `config/devices.json`

```json
{
    "devices": [
        {"name": "My Device (XenoTech)", "ip": "192.168.1.192"},
        {"name": "Main Server", "ip": "192.168.1.254"},
        {"name": "PisoWifi Bluestuck", "ip": "192.168.1.245"},
        {"name": "XenoRoom Wifi", "ip": "192.168.1.191"}
    ]
}
```

### Settings — `config/settings.local.json` (gitignored)

Copy the example and edit locally:

```bash
copy config\settings.example.json config\settings.local.json
```

```json
{
    "discord_webhook_url": "https://discord.com/api/webhooks/...",
    "check_interval_seconds": 5,
    "scanner_duration_seconds": 60,
    "start_monitoring_on_launch": true
}
```

**Never commit** `settings.local.json`. The webhook URL is never printed or logged.

## Windows Startup

From the tray menu:

- **Enable Windows Startup** — per-user `HKCU\...\Run` entry (no admin)
- **Disable Windows Startup** — removes the entry

Normal startup: Windows login → app launches with `pythonw` → tray icon → background monitoring → no visible CMD.

## Project Structure

```
src/
  main.py              Entry point
  engine.py            Single shared monitoring engine
  monitor.py           Ping / reachability
  config_loader.py     Load/validate/save devices + settings
  device_manager.py    Add Device validation + atomic save
  scanner.py           LAN IP/MAC scanner
  discord_notify.py    Discord webhook (status changes)
  console_ui.py        Console menu / modes
  tray_app.py          System tray
  keyboard_input.py    Ctrl+T / Ctrl+N / Ctrl+C
  startup.py           Per-user Windows startup
  app_logger.py        Local file logging
  paths.py             Shared paths / timestamps
config/
  devices.json
  settings.example.json
  settings.local.json   (local secrets, gitignored)
logs/
  monitor.log           (runtime)
```

## Intentionally Out of Scope (Phase 3+)

- AdoPisoFi-side / remote agents / SSH / tunneling
- Web dashboard / database / cloud / mobile
- Authentication / advanced analytics

All monitoring and scanning runs **only on the Windows PC**. Monitored devices are never modified or installed upon.

## License

Proprietary — XenoTech.
