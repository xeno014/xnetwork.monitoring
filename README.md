# XenoTech IP Monitor

A Windows desktop app that watches the devices on your local network, shows whether each one is **ONLINE** or **OFFLINE**, scans your LAN for IP/MAC addresses, sends Discord alerts when a device changes state, and can be controlled remotely from Discord with slash commands.

Everything runs on your own PC. Monitored devices are never modified and nothing is installed on them.

## Features

- **Desktop GUI** with live device status, summary cards, and color-coded rows
- **Continuous monitoring** (configurable interval) or a one-off **Check Now**
- **IP Scanner**: discovers IP and MAC addresses on your subnet and lets you add a result to monitoring with a double-click
- **Add / remove devices** from the window (validated, atomic saves)
- **Discord webhook alerts** on real status changes only (no spam on every poll)
- **Discord slash commands** to check your network without touching the PC
- **System tray**: closing the window hides it to the tray; tray notifications when a device goes offline or comes back
- **Run at Windows startup** (per user, no admin rights needed)
- **Single `.exe` build** with one script
- Single-instance protection so you never get duplicate alerts

## Requirements

- Windows 10 / 11
- Python 3.10+ (developed on 3.14) to run from source or build the exe
- Uses the built-in `ping` and `arp` commands, so **no admin rights and no Npcap** are needed

## Quick start

### Option A: build the exe

1. Install Python from python.org and tick **Add python.exe to PATH**.
2. Double-click `build_exe.bat`.
3. Your app is at `dist\XenoTechIPMonitor.exe`.

Put the exe in a normal user folder (Desktop, Documents), not Program Files. On first run it creates `config\` and `logs\` next to itself.

If Windows Defender flags the exe, that is a common false positive with PyInstaller builds; add an exclusion for it.

### Option B: run from source

```bash
pip install -r requirements.txt
python src/main.py
```

## Using the app

| Tab | What it does |
|-----|--------------|
| **Devices** | Live status of every monitored device. Start/Stop monitoring, Check Now, Add Device, Remove Selected |
| **IP Scanner** | Scans your subnet for IP and MAC addresses. Select a result and add it to monitoring |
| **Activity Log** | Live status changes and events. Button to open the log file |
| **Settings** | Check interval, scan duration, Discord webhook, Discord bot, auto-start options, Windows startup |

Closing the window hides the app to the system tray and monitoring keeps running. Right-click the tray icon and choose **Exit** to quit completely.

### Command-line modes

```bash
python src/main.py               # GUI (default on Windows)
python src/main.py --gui         # force the GUI
python src/main.py --minimized   # GUI, hidden in the tray
python src/main.py --console     # legacy console menu
python src/main.py --tray        # legacy tray-only mode
python src/main.py continue      # continuous monitoring in the terminal
python src/main.py static        # one check
python src/main.py scanner       # LAN scan
python src/main.py add           # add a device
```

## Configuration

### Devices: `config/devices.json`

```json
{
    "devices": [
        {"name": "Main Server", "ip": "192.168.1.254"},
        {"name": "PLDT Router", "ip": "192.168.1.1"}
    ]
}
```

You can edit this by hand or use the **Add Device** / **Remove Selected** buttons. Names and IPs must be unique, and IPs must be valid IPv4.

### Settings: `config/settings.local.json` (gitignored)

Normally you edit these in the **Settings** tab. To set them by hand, copy `config/settings.example.json` to `config/settings.local.json`:

```json
{
    "discord_webhook_url": "https://discord.com/api/webhooks/...",
    "check_interval_seconds": 5,
    "scanner_duration_seconds": 60,
    "start_monitoring_on_launch": true,
    "discord_bot_token": "",
    "discord_allowed_user_ids": [],
    "discord_guild_id": 0
}
```

**Never commit `settings.local.json`.** It holds your webhook URL and bot token. The app never prints or logs either one.

## Discord alerts (webhook)

Paste a webhook URL in **Settings > Discord webhook URL** (Discord: Channel settings > Integrations > Webhooks). The app posts a message only when a device's status actually changes.

## Discord slash commands (remote control)

The bot connects **out** to Discord, so you do not need to open any ports on your router.

| Command | Action |
|---------|--------|
| `/status` | Show every device and whether it is online |
| `/check` | Ping all devices right now and show the results |
| `/ping <ip>` | Ping a single IPv4 address |
| `/scan` | Scan the LAN and list IP and MAC addresses |
| `/start` | Start continuous monitoring |
| `/stop` | Stop continuous monitoring |

Replies are private to you. Only Discord user IDs listed in settings can use the commands; with no IDs set, the bot refuses everything.

### Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**.
2. Open **Bot**, click **Reset Token**, then **Copy**. The token is shown only once.
3. Open **OAuth2 > URL Generator**, tick the scopes `bot` and `applications.commands`, and open the generated URL to invite the bot to your server.
4. In Discord, enable Developer Mode (Settings > Advanced), then right-click your name and choose **Copy User ID**.
5. In the app, open **Settings**, paste the token and your user ID (comma-separate extra users), and click **Save Settings**.
6. Optional: add your **Server ID** so the commands appear instantly instead of after a delay.

The PC and the app must be running for the bot to answer. If the token ever leaks, click **Reset Token** again and the old one stops working.

## Project structure

```
src/
  main.py            Entry point and mode selection
  gui_app.py         Desktop window (Tkinter) and tray integration
  engine.py          Shared monitoring engine (one loop for everything)
  monitor.py         Ping / reachability checks
  scanner.py         LAN IP/MAC scanner
  discord_notify.py  Discord webhook alerts (status changes)
  discord_bot.py     Discord slash-command bot
  device_manager.py  Add-device validation and atomic save
  config_loader.py   Load/validate/save devices and settings
  startup.py         Per-user Windows startup entry
  tray_app.py        Legacy tray-only mode
  console_ui.py      Legacy console menu
  keyboard_input.py  Console shortcuts
  app_logger.py      Local file logging
  paths.py           Shared paths (exe-aware)
assets/
  xenotech.ico       App icon
config/
  devices.json
  settings.example.json
  settings.local.json   (your secrets, gitignored)
logs/
  monitor.log           (created at runtime)
build_exe.bat        One-click exe build (PyInstaller)
requirements.txt
```

## Notes and limits

- Windows only; monitoring and scanning run only on the PC where the app runs.
- Checks use ICMP ping, so a device that blocks ping will show as OFFLINE.
- The scanner covers the PC's local subnet (up to 1024 hosts) and does not resolve hostnames.
- Out of scope: remote agents, web dashboard, database, cloud, authentication.

## License

Proprietary, XenoTech.
