"""Real download/upload speed tests (no Ookla, standard library only).

* ``run_internet_speedtest``  - this PC's internet speed, measured against
  Cloudflare's public speed endpoints (multi-connection, ramp-up excluded).
* ``agent_speedtest``         - asks a remote *speed agent* to run the same test
  on ITS internet connection and report back.
* ``link_speedtest``          - measures raw throughput between this PC and a
  remote speed agent (useful over Tailscale to test the path between sites).

All speeds are in megabits per second (Mbps).
"""

from __future__ import annotations

import csv
import http.client
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from paths import LOGS_DIR, now_stamp

Progress = Callable[[str], None]

CF_HOST = "speed.cloudflare.com"
USER_AGENT = "Mozilla/5.0 XenoTechIPMonitor/1.0"
DOWNLOAD_CHUNK = 25_000_000   # bytes per download request
UPLOAD_CHUNK = 25_000_000     # bytes declared per upload request
RAMP_SECONDS = 1.0            # warm-up excluded from the measurement
CSV_PATH = LOGS_DIR / "speedtests.csv"

# Only one speed test at a time (they saturate the link).
_TEST_LOCK = threading.Lock()


class SpeedTestError(RuntimeError):
    """A speed test could not be completed (message is user-friendly)."""


# --- measurement core --------------------------------------------------------
class _Counter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self.errors: list[str] = []

    def add(self, count: int) -> None:
        with self._lock:
            self._total += count

    def read(self) -> int:
        with self._lock:
            return self._total

    def fail(self, exc: Exception) -> None:
        with self._lock:
            self.errors.append(f"{type(exc).__name__}: {exc}")


def _measure(
    worker: Callable[[float, _Counter], None],
    *,
    connections: int,
    duration: float,
    label: str,
    on_progress: Progress | None,
) -> float:
    """Run ``worker`` on several threads and return the steady-state Mbps."""
    counter = _Counter()

    def safe(stop_at: float, ctr: _Counter) -> None:
        try:
            worker(stop_at, ctr)
        except Exception as exc:  # network errors end this connection only
            ctr.fail(exc)

    stop_at = time.monotonic() + duration
    threads = [
        threading.Thread(target=safe, args=(stop_at, counter), daemon=True)
        for _ in range(connections)
    ]
    for thread in threads:
        thread.start()

    time.sleep(min(RAMP_SECONDS, duration))
    start_bytes, start_time = counter.read(), time.monotonic()
    last_bytes, last_time = start_bytes, start_time
    end_bytes, end_time = start_bytes, start_time

    while True:
        remaining = stop_at - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
        end_bytes, end_time = counter.read(), time.monotonic()
        if on_progress and end_time > last_time:
            rate = (end_bytes - last_bytes) * 8 / (end_time - last_time) / 1e6
            on_progress(f"{label}... {rate:.1f} Mbps")
            last_bytes, last_time = end_bytes, end_time

    for thread in threads:
        thread.join(timeout=3)

    elapsed = end_time - start_time
    if end_bytes <= start_bytes or elapsed <= 0:
        reason = counter.errors[0] if counter.errors else "no data was transferred"
        raise SpeedTestError(f"{label} test failed ({reason}).")
    return (end_bytes - start_bytes) * 8 / elapsed / 1e6


def _get_worker(url: str, headers: dict[str, str]):
    def worker(stop_at: float, counter: _Counter) -> None:
        while time.monotonic() < stop_at:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                while time.monotonic() < stop_at:
                    block = response.read(65536)
                    if not block:
                        break
                    counter.add(len(block))
    return worker


def _post_worker(https: bool, host: str, port: int | None, path: str,
                 headers: dict[str, str], total: int):
    block = os.urandom(65536)

    def worker(stop_at: float, counter: _Counter) -> None:
        while time.monotonic() < stop_at:
            cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
            conn = cls(host, port, timeout=15)
            try:
                conn.putrequest("POST", path)
                conn.putheader("Content-Length", str(total))
                conn.putheader("Content-Type", "application/octet-stream")
                for key, value in headers.items():
                    conn.putheader(key, value)
                conn.endheaders()
                sent = 0
                while sent < total and time.monotonic() < stop_at:
                    conn.send(block)
                    counter.add(len(block))
                    sent += len(block)
            finally:
                conn.close()
    return worker


def _latency_ms(https: bool, host: str, port: int | None, path: str,
                headers: dict[str, str], samples: int = 6) -> float:
    """Median request round-trip on one kept-alive connection (handshake dropped)."""
    cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
    conn = cls(host, port, timeout=10)
    times: list[float] = []
    try:
        for _ in range(samples):
            start = time.perf_counter()
            conn.request("GET", path, headers=headers)
            conn.getresponse().read()
            times.append((time.perf_counter() - start) * 1000)
    finally:
        conn.close()
    return round(statistics.median(times[1:] or times), 1)


def _result(download: float, upload: float, latency: float, server: str) -> dict[str, Any]:
    return {
        "download_mbps": round(download, 2),
        "upload_mbps": round(upload, 2),
        "latency_ms": latency,
        "server": server,
        "time": now_stamp(),
    }


class _Exclusive:
    """Context manager: raise if another speed test is already running."""

    def __enter__(self) -> None:
        if not _TEST_LOCK.acquire(blocking=False):
            raise SpeedTestError("Another speed test is already running.")

    def __exit__(self, *exc) -> None:
        _TEST_LOCK.release()


# --- this PC's internet ------------------------------------------------------------
def run_internet_speedtest(on_progress: Progress | None = None,
                           duration: float = 8.0, connections: int = 4) -> dict[str, Any]:
    """Measure THIS machine's internet download/upload speed (Cloudflare)."""
    headers = {"User-Agent": USER_AGENT}
    with _Exclusive():
        try:
            if on_progress:
                on_progress("Measuring latency...")
            latency = _latency_ms(True, CF_HOST, None, "/__down?bytes=0", headers)
        except (OSError, http.client.HTTPException) as exc:
            raise SpeedTestError(
                f"Cannot reach the speed test server ({type(exc).__name__}). "
                "Check the internet connection.") from exc

        down = _measure(
            _get_worker(f"https://{CF_HOST}/__down?bytes={DOWNLOAD_CHUNK}", headers),
            connections=connections, duration=duration, label="Download",
            on_progress=on_progress)
        up = _measure(
            _post_worker(True, CF_HOST, None, "/__up", headers, UPLOAD_CHUNK),
            connections=connections, duration=duration, label="Upload",
            on_progress=on_progress)
    return _result(down, up, latency, "Cloudflare")


# --- remote speed agents --------------------------------------------------------------
def _agent_headers(token: str) -> dict[str, str]:
    return {"X-Token": token, "User-Agent": USER_AGENT}


def _agent_error(ip: str, port: int, exc: Exception) -> SpeedTestError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return SpeedTestError("The agent rejected the token (check the speed agent token).")
        if exc.code == 429:
            return SpeedTestError("The agent is already running a test.")
        return SpeedTestError(f"The agent returned an error (HTTP {exc.code}).")
    return SpeedTestError(
        f"No speed agent answering on {ip}:{port}. Is the agent running there?")


def agent_speedtest(ip: str, port: int, token: str,
                    on_progress: Progress | None = None) -> dict[str, Any]:
    """Ask the agent on ``ip`` to speed-test ITS OWN internet connection."""
    try:  # fail fast (5 s) if the device or agent is not answering
        urllib.request.urlopen(
            urllib.request.Request(f"http://{ip}:{port}/ping", headers=_agent_headers(token)),
            timeout=5).read()
    except (urllib.error.URLError, OSError) as exc:
        raise _agent_error(ip, port, exc) from exc
    if on_progress:
        on_progress(f"Asking {ip} to run its internet speed test (about 25 s)...")
    request = urllib.request.Request(
        f"http://{ip}:{port}/speedtest", data=b"", method="POST",
        headers=_agent_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _agent_error(ip, port, exc) from exc
    if "error" in data:
        raise SpeedTestError(str(data["error"]))
    return data


def link_speedtest(ip: str, port: int, token: str, duration: float = 6.0,
                   connections: int = 4,
                   on_progress: Progress | None = None) -> dict[str, Any]:
    """Measure throughput between THIS PC and the agent on ``ip``."""
    headers = _agent_headers(token)
    with _Exclusive():
        try:  # fail fast with a clear message if the agent is missing / token wrong
            urllib.request.urlopen(
                urllib.request.Request(f"http://{ip}:{port}/ping", headers=headers),
                timeout=8).read()
            latency = _latency_ms(False, ip, port, "/ping", headers)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise _agent_error(ip, port, exc) from exc
        down = _measure(
            _get_worker(f"http://{ip}:{port}/down?bytes=500000000", headers),
            connections=connections, duration=duration,
            label="Link download (device to PC)", on_progress=on_progress)
        up = _measure(
            _post_worker(False, ip, port, "/up", headers, 500_000_000),
            connections=connections, duration=duration,
            label="Link upload (PC to device)", on_progress=on_progress)
    return _result(down, up, latency, f"link to {ip}")


# --- history ------------------------------------------------------------------------
def save_result(target: str, kind: str, result: dict[str, Any]) -> None:
    """Append a result row to logs/speedtests.csv (best effort)."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        new_file = not CSV_PATH.exists()
        with CSV_PATH.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if new_file:
                writer.writerow(["time", "target", "test", "download_mbps",
                                 "upload_mbps", "latency_ms"])
            writer.writerow([result.get("time", now_stamp()), target, kind,
                             result["download_mbps"], result["upload_mbps"],
                             result["latency_ms"]])
    except OSError:
        pass


def format_result(result: dict[str, Any]) -> str:
    return (f"\u2b07\ufe0f Download: **{result['download_mbps']:.1f} Mbps**\n"
            f"\u2b06\ufe0f Upload: **{result['upload_mbps']:.1f} Mbps**\n"
            f"\u23f1\ufe0f Latency: **{result['latency_ms']:.0f} ms**")
