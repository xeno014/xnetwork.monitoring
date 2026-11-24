"""LAN IP/MAC scanner (Windows-side discovery only).

Discovers devices visible on the local subnet. Does not resolve hostnames,
does not modify remote devices, and does not auto-add to monitoring.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from app_logger import log_event
from monitor import is_reachable
from paths import now_stamp

ProgressCallback = Callable[[str], None]


@dataclass
class ScanHit:
    ip: str
    mac: str


def _creationflags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def detect_local_subnet() -> ipaddress.IPv4Network:
    """Detect the active local IPv4 subnet; fall back to hostname IP /24."""
    local_ip = _guess_primary_ipv4()
    prefix = _guess_prefix_length(local_ip)
    network = ipaddress.IPv4Network(f"{local_ip}/{prefix}", strict=False)
    return network


def _guess_primary_ipv4() -> str:
    """Best-effort primary LAN IPv4 for this Windows host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass

    hostname = socket.gethostname()
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            candidate = info[4][0]
            if not candidate.startswith("127."):
                return candidate
    except OSError:
        pass

    return "192.168.1.1"


def _guess_prefix_length(local_ip: str) -> int:
    """Parse ipconfig for the subnet mask when available; else assume /24."""
    if sys.platform != "win32":
        return 24
    try:
        completed = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=_creationflags(),
            encoding="utf-8",
            errors="replace",
        )
        lines = completed.stdout.splitlines()
        for index, line in enumerate(lines):
            if local_ip in line and "IPv4" in line:
                for follow in lines[index + 1 : index + 6]:
                    match = re.search(
                        r"Subnet Mask[^:]*:\s*([\d.]+)", follow, re.IGNORECASE
                    )
                    if match:
                        mask = match.group(1)
                        return ipaddress.IPv4Network(
                            f"0.0.0.0/{mask}"
                        ).prefixlen
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return 24


def _read_arp_table() -> dict[str, str]:
    """Parse ``arp -a`` into IP → MAC mappings."""
    mapping: dict[str, str] = {}
    try:
        completed = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=_creationflags(),
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return mapping

    # Example: 192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
    pattern = re.compile(
        r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-:]{11,17})\s+",
        re.MULTILINE,
    )
    for match in pattern.finditer(completed.stdout):
        ip = match.group(1)
        mac_raw = match.group(2).replace("-", ":").upper()
        if mac_raw.lower() in {"ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"}:
            continue
        mapping[ip] = mac_raw
    return mapping


def _format_mac(mac: str | None) -> str:
    if not mac:
        return "MAC unavailable"
    return mac


def run_lan_scan(
    duration_seconds: int = 60,
    *,
    on_progress: ProgressCallback | None = None,
    on_discovery: Callable[[ScanHit], None] | None = None,
) -> list[ScanHit]:
    """Scan the local subnet for up to ``duration_seconds``.

    Returns unique hits sorted by IP. Hostnames are never resolved.
    """
    log_event(f"IP scanner started at {now_stamp()}")
    start = time.monotonic()
    deadline = start + max(1, duration_seconds)

    try:
        network = detect_local_subnet()
    except Exception as exc:
        log_event(f"IP scanner subnet detection failed: {exc}")
        if on_progress:
            on_progress(f"ERROR: Could not determine local subnet ({exc}).")
        return []

    hosts = [str(host) for host in network.hosts()]
    # Cap extremely large subnets for safety.
    if len(hosts) > 1024:
        hosts = hosts[:1024]

    if on_progress:
        on_progress(f"Local subnet: {network}")
        on_progress("Scanning local network...")

    discovered: dict[str, str] = {}
    reported: set[str] = set()

    def _probe(ip: str) -> str | None:
        if time.monotonic() >= deadline:
            return None
        if is_reachable(ip, timeout_ms=800):
            return ip
        return None

    def _remaining() -> int:
        return max(0, int(deadline - time.monotonic()))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            futures = {pool.submit(_probe, ip): ip for ip in hosts}
            for future in concurrent.futures.as_completed(futures, timeout=duration_seconds + 5):
                if time.monotonic() >= deadline:
                    break
                try:
                    ip = future.result()
                except Exception:
                    continue
                if not ip:
                    continue
                arp = _read_arp_table()
                mac = _format_mac(arp.get(ip))
                discovered[ip] = mac
                if ip not in reported:
                    reported.add(ip)
                    hit = ScanHit(ip=ip, mac=mac)
                    if on_discovery:
                        on_discovery(hit)
                if on_progress:
                    on_progress(f"Time remaining: {_remaining()} seconds")
    except Exception as exc:
        log_event(f"IP scanner error: {exc}")
        if on_progress:
            on_progress(f"Scanner error: {exc}")

    # Final ARP pass to fill MACs for hosts that responded.
    arp_final = _read_arp_table()
    for ip in list(discovered):
        if discovered[ip] == "MAC unavailable" and ip in arp_final:
            discovered[ip] = arp_final[ip]

    # Include ARP-visible hosts on our subnet even if ping was flaky.
    for ip, mac in arp_final.items():
        try:
            if ipaddress.IPv4Address(ip) in network:
                discovered.setdefault(ip, mac)
        except ValueError:
            continue

    hits = [
        ScanHit(ip=ip, mac=_format_mac(mac))
        for ip, mac in sorted(
            discovered.items(),
            key=lambda item: tuple(int(part) for part in item[0].split(".")),
        )
    ]
    log_event(
        f"IP scanner completed at {now_stamp()}: {len(hits)} device(s) discovered"
    )
    return hits
