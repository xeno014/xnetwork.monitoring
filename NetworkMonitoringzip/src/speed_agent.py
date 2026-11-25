"""XenoTech Speed Agent - run this on a REMOTE device you want to speed-test.

It answers three things for the XenoTech IP Monitor (all need the shared token):
  POST /speedtest  run an internet speed test on THIS device and return the result
  GET  /down       stream bytes (lets the monitor measure the link to this device)
  POST /up         swallow uploaded bytes (same purpose)

Usage:   XenoTechSpeedAgent.exe --token YOUR_SECRET [--port 8765] [--bind 0.0.0.0]
Tip: with Tailscale, use  --bind <this device's 100.x.x.x address>  so the agent
is reachable only through your private Tailscale network.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from netspeed import SpeedTestError, run_internet_speedtest

MAX_STREAM_BYTES = 2_000_000_000
BLOCK = os.urandom(65536)


def make_handler(token: str):
    test_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True  # avoid ~40 ms delays on small replies

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-Token", "")
            if hmac.compare_digest(supplied.encode(), token.encode()):
                return True
            self._json(401, {"error": "unauthorized"})
            return False

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._authorized():
                return
            url = urlparse(self.path)
            if url.path == "/ping":
                self._json(200, {"ok": True})
            elif url.path == "/down":
                try:
                    total = int(parse_qs(url.query).get("bytes", ["1000000"])[0])
                except ValueError:
                    total = 1_000_000
                total = max(0, min(total, MAX_STREAM_BYTES))
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(total))
                self.end_headers()
                sent = 0
                try:
                    while sent < total:
                        chunk = BLOCK[: min(len(BLOCK), total - sent)]
                        self.wfile.write(chunk)
                        sent += len(chunk)
                except (BrokenPipeError, ConnectionError, OSError):
                    pass  # client stopped reading: normal at end of a test
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path).path
            if path == "/up":
                remaining = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    while remaining > 0:
                        data = self.rfile.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                except (ConnectionError, OSError):
                    pass
                self.close_connection = True
            elif path == "/speedtest":
                if not test_lock.acquire(blocking=False):
                    self._json(429, {"error": "busy"})
                    return
                try:
                    result = run_internet_speedtest()
                    self._json(200, result)
                except SpeedTestError as exc:
                    self._json(200, {"error": str(exc)})
                finally:
                    test_lock.release()
            else:
                self._json(404, {"error": "not found"})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XenoTech Speed Agent")
    parser.add_argument("--token", default=os.environ.get("XENO_AGENT_TOKEN", ""),
                        help="shared secret (also read from XENO_AGENT_TOKEN)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="0.0.0.0",
                        help="address to listen on (use the Tailscale 100.x address for private-only)")
    args = parser.parse_args(argv)

    if len(args.token) < 8:
        print("Refusing to start: --token must be at least 8 characters.")
        return 2

    server = ThreadingHTTPServer((args.bind, args.port), make_handler(args.token))
    print(f"XenoTech Speed Agent listening on {args.bind}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
