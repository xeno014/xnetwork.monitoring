# XenoTech Network Monitor

Monitor specific IP addresses on a local network and detect whether devices are **ONLINE** or **OFFLINE**.

## Current Phase

**Phase 1 — Project Foundation**

This phase sets up the project structure, configuration, and a runnable entry point. Monitoring, notifications, and other features are intentionally deferred.

## Project Structure

```
XenoTech-Network-Monitor/
├── src/
│   ├── __init__.py
│   └── main.py          # Application entry point
├── config/
│   └── devices.json     # Device list (name, IP, enabled)
├── logs/
│   └── .gitkeep         # Reserved for future log files
├── tests/
│   └── __init__.py
├── .gitignore
├── README.md
└── requirements.txt
```

## How to Run

Requires **Python 3**. No third-party packages are needed for Phase 1.

From the project root:

```bash
python src/main.py
```

On Windows, if `python` is not on your PATH, use the launcher instead:

```bash
py -3 src/main.py
```

Expected output (device count matches `config/devices.json`):

```
XenoTech Network Monitor
========================
Phase: 1 - Project Foundation
Status: System initialized successfully.
Loaded 3 device(s) from configuration.
```

## Configuring Devices

Edit `config/devices.json` to define which devices will be monitored in later phases.

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
| `enabled` | boolean | Whether this device should be monitored (later)  |

Devices are **not** hardcoded in the application. The config file is loaded and validated at startup.

## Intentionally Not Implemented Yet

The following belong to future phases and are **not** part of Phase 1:

- IP pinging / online–offline detection
- Discord notifications
- Logging to files
- Uptime tracking
- Database storage
- FastAPI or any web API
- Web dashboard

## License

Proprietary — XenoTech.
