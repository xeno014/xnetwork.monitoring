"""Discord webhook notifications (status changes only).

The webhook URL is loaded from external settings and must never be printed,
logged, or embedded in source code.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app_logger import log_event
from paths import now_stamp


def send_status_change_notification(
    webhook_url: str,
    *,
    device_name: str,
    ip: str,
    new_status: str,
    previous_status: str,
) -> bool:
    """Send a Discord webhook for a device status change.

    Returns True on HTTP success, False on any failure.
    Failures are logged without exposing the webhook URL.
    """
    url = (webhook_url or "").strip()
    if not url:
        return False

    stamp = now_stamp()
    content = (
        "## XenoTech IP Monitor\n\n"
        f"**Device:**\n{device_name}\n\n"
        f"**IP:**\n{ip}\n\n"
        f"**Status:**\n{new_status}\n\n"
        f"**Previous:**\n{previous_status}\n\n"
        f"**Time:**\n{stamp}"
    )
    payload = json.dumps({"content": content}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "XenoTech-IP-Monitor"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            ok = 200 <= getattr(response, "status", 200) < 300
        if ok:
            log_event(
                f"Discord notification sent: {device_name} "
                f"{previous_status} -> {new_status}"
            )
        else:
            log_event("Discord notification failed: unexpected HTTP status")
        return ok
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        log_event("Discord notification failed: network or HTTP error")
        return False
    except Exception:
        log_event("Discord notification failed: unexpected error")
        return False
