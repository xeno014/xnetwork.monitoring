# XenoTech Network Monitor

Monitor specific IP addresses on a local network and detect whether devices are **ONLINE** or **OFFLINE**.

## Current Phase

**Phase 2 — Basic IP Monitoring Engine**

The application loads devices from configuration and supports two monitoring modes:

- **static** — one check immediately, then wait for **Ctrl+T** to test again
- **continue** — automatic checks every `CHECK_INTERVAL` seconds (default **5**)

## Project Structure

```
XenoTech-Network-Monitor/
├── src/
│   ├── __init__.py
│   ├── main.py            # Application entry point / mode selection
│   ├── config_loader.py   # Load and validate devices.json
│   ├── monitor.py         # Ping checks, STATIC_MODE, CONTINUE_MODE
│   └── keyboard_input.py  # Windows Ctrl+T / Ctrl+C for STATIC_MODE
├── config/
│   └── devices.json       # Device list (name, IP, enabled)
├── logs/
│   └── .gitkeep           # Reserved for future log files
├── tests/
│   └── __init__.py
├── .gitignore
├── README.md
└── requirements.txt
```

## How to Run

Requires **Python 3**. Phase 2 uses only the Python standard library and the system `ping` command — no third-party packages.

From the project root:

```bash
python src/main.py
```

On Windows, if `python` is not on your PATH, use the launcher instead:

```bash
py -3 src/main.py
```

You will be prompted to choose a mode. Accepted values (case-insensitive):

| Mode | Aliases |
|------|---------|
| CONTINUE | `continue`, `1` |
| STATIC | `static`, `2` |

Invalid interactive input shows a clear message and asks again.

You can also pass the mode directly:

```bash
py -3 src/main.py continue
py -3 src/main.py 1
py -3 src/main.py static
py -3 src/main.py 2
```

**STATIC_MODE does not automatically repeat** — after each check it waits for **Ctrl+T** (test again) or **Ctrl+C** (exit).

### STATIC_MODE example

```
XenoTech Network Monitor
========================
Mode: STATIC

[18:55:01] Router                 192.168.1.1    ONLINE
[18:55:01] Main Server            192.168.1.254  ONLINE
[18:55:01] Piso Wifi Bluestucks   192.168.1.245  OFFLINE

Static check complete.

Press:
[Ctrl+T] Test again
[Ctrl+C] Exit
```

- **Ctrl+T** — run exactly one new check, then wait again
- **Ctrl+C** — exit cleanly

### CONTINUE_MODE example

```
XenoTech Network Monitor
========================
Mode: CONTINUE

Monitoring 3 device(s)...

[18:30:01] Router                 192.168.1.1    ONLINE
[18:30:01] Main Server            192.168.1.254  ONLINE
[18:30:01] Piso Wifi Bluestucks   192.168.1.245  OFFLINE

[18:30:06] Router                 192.168.1.1    ONLINE
...
```

Press **Ctrl+C** to stop. Ctrl+T is not used in CONTINUE_MODE.

```
Stopping XenoTech Network Monitor...
Monitor stopped.
```

## How IP Monitoring Works

1. `config_loader.py` reads and validates `config/devices.json`.
2. Only devices with `"enabled": true` are monitored.
3. `monitor.py` runs a system ping (Windows: `ping -n 1 -w 2000`) for each IP.
4. Reachable hosts print as **ONLINE**; unreachable (or timed-out) hosts print as **OFFLINE**.
5. Mode controls *when* checks run:
   - **static** (`2`) — one check, then wait; each **Ctrl+T** triggers exactly one new cycle (no 5-second auto loop)
   - **continue** (`1`) — automatic every `CHECK_INTERVAL` seconds (default **5**)

### Current Phase 2 limitations

- ICMP ping only (hosts that block ping may look OFFLINE)
- No retries / failure thresholds before marking OFFLINE
- No status-change detection or notifications
- STATIC_MODE Ctrl+T input is implemented for **Windows** (`keyboard_input.py`)

Future phases may add Discord alerts, persistence, APIs, and dashboards.

## Configuring Devices

Edit `config/devices.json`. **Replace the example IP addresses with devices that exist on your own network.** Addresses such as `192.168.1.1` are common router defaults, but they are not guaranteed to exist on every LAN.

```json
{
    "devices": [
        {
            "name": "Router",
            "ip": "192.168.1.1",
            "enabled": true
        },
        {
            "name": "Main Server",
            "ip": "192.168.1.254",
            "enabled": true
        },
        {
            "name": "Piso Wifi Bluestucks",
            "ip": "192.168.1.245",
            "enabled": true
        }
    ]
}
```

| Field     | Type    | Description                                      |
|-----------|---------|--------------------------------------------------|
| `name`    | string  | Friendly label for the device                    |
| `ip`      | string  | IPv4 address on the local network                |
| `enabled` | boolean | If `true`, the device is included in monitoring  |

Set `"enabled": false` to keep a device in the file without monitoring it.

Devices are **not** hardcoded in the application.

## Changing the Monitoring Interval (CONTINUE_MODE)

Open `src/main.py` and change:

```python
CHECK_INTERVAL = 5
```

The value is in **seconds**. For example, `CHECK_INTERVAL = 10` checks every 10 seconds. This setting does not affect STATIC_MODE.

## Stopping the Application

Press **Ctrl+C** in either mode. The monitor prints a short shutdown message and exits cleanly.

## Testing Tips

Use IPs from **your** network:

1. **Reachable** — your router or another online host on the LAN.
2. **Unreachable** — an unused address on your subnet (for example `192.168.1.250` if nothing uses it).
3. **Multiple devices** — enable two or more entries in `devices.json`.
4. **Disabled device** — set `"enabled": false` and confirm it does not appear in output.
5. **STATIC_MODE** — confirm one check on start, wait, Ctrl+T for one more check, Ctrl+C to exit.
6. **CONTINUE_MODE** — confirm automatic checks every 5 seconds and Ctrl+C stop.
7. **Invalid config** — break JSON temporarily and confirm the app exits with an error instead of crashing mid-loop.

## Intentionally Not Implemented Yet

The following belong to future phases and are **not** part of Phase 2:

- Discord / webhook notifications
- Status-change detection (ONLINE → OFFLINE alerts)
- Failure thresholds / retries before marking OFFLINE
- Logging to files
- Uptime statistics or historical reporting
- Database / SQLite storage
- FastAPI or any web API
- Web dashboard
- Authentication
- Windows service installation

## License

Proprietary — XenoTech.
