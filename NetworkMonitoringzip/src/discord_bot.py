"""Discord slash-command bot (remote control for the monitor).

Runs in a background thread with its own asyncio loop and talks to the shared
``ENGINE``. The bot connects OUT to Discord, so no router ports are opened.

Commands: /status /check /ping /scan /start /stop
Only Discord user IDs listed in settings may use them. The bot token is never
logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
import threading
from collections.abc import Callable

from app_logger import log_event
from config_loader import load_settings
from engine import ENGINE
from monitor import is_reachable
from scanner import run_lan_scan

StatusCallback = Callable[[str], None]

_UNKNOWN_DOT = "\u26aa"
_DOT = {"ONLINE": "\U0001f7e2", "OFFLINE": "\U0001f534", "UNKNOWN": _UNKNOWN_DOT}
_MAX_LEN = 1900  # Discord limit is 2000 characters per message


def _clip(text: str) -> str:
    if len(text) <= _MAX_LEN:
        return text
    return text[: _MAX_LEN - 20].rstrip() + "\n... (truncated)"


def format_status() -> str:
    devices = ENGINE.get_devices()
    if not devices:
        return "No devices are configured."
    statuses = ENGINE.get_statuses()
    online = sum(1 for d in devices if statuses.get(d["ip"]) == "ONLINE")
    state = "RUNNING" if ENGINE.is_monitoring() else "STOPPED"
    lines = [f"**Monitoring {state}** \u2014 {online}/{len(devices)} online", ""]
    for d in devices:
        status = statuses.get(d["ip"], "UNKNOWN")
        lines.append(f"{_DOT.get(status, _UNKNOWN_DOT)} **{d['name']}** \u2014 `{d['ip']}` \u2014 {status}")
    return _clip("\n".join(lines))


class DiscordBot:
    def __init__(self, on_status: StatusCallback | None = None) -> None:
        self._on_status = on_status
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._scan_busy = False

    # --- public API ---------------------------------------------------------
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, token: str, allowed_ids: list[int], guild_id: int = 0) -> bool:
        token = (token or "").strip()
        if not token:
            return False
        if self.is_running():
            return False
        try:
            import discord  # noqa: F401
        except ImportError:
            self._status("Discord bot unavailable: discord.py is not installed.")
            return False
        thread = threading.Thread(
            target=self._run,
            args=(token, list(allowed_ids), int(guild_id or 0)),
            name="XenoTechDiscordBot",
            daemon=True,
        )
        with self._lock:
            self._thread = thread
        thread.start()
        return True

    def stop(self) -> None:
        with self._lock:
            loop, client, thread = self._loop, self._client, self._thread
        if loop is not None and client is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(client.close(), loop).result(timeout=5)
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    # --- internals ----------------------------------------------------------
    def _status(self, message: str) -> None:
        log_event(message)
        if self._on_status:
            try:
                self._on_status(message)
            except Exception:
                pass

    def _run(self, token: str, allowed: list[int], guild_id: int) -> None:
        import discord

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            loop.run_until_complete(self._main(token, allowed, guild_id))
        except discord.LoginFailure:
            self._status("Discord bot login failed - check the bot token.")
        except Exception as exc:
            text = str(exc).replace(token, "***")
            self._status(f"Discord bot error: {type(exc).__name__}: {text}")
        finally:
            try:
                loop.close()
            finally:
                with self._lock:
                    self._loop = None
                    self._client = None
                self._status("Discord bot stopped.")

    async def _main(self, token: str, allowed: list[int], guild_id: int) -> None:
        import discord
        from discord import app_commands

        bot = self
        guild = discord.Object(id=guild_id) if guild_id else None

        class XenoClient(discord.Client):
            async def setup_hook(self) -> None:
                if guild is not None:
                    tree.copy_global_to(guild=guild)
                    await tree.sync(guild=guild)
                else:
                    await tree.sync()

            async def on_ready(self) -> None:
                bot._status(f"Discord bot online as {self.user}.")

        client = XenoClient(intents=discord.Intents.default())
        tree = app_commands.CommandTree(client)
        with self._lock:
            self._client = client

        async def guard(interaction: discord.Interaction) -> bool:
            if not allowed:
                await interaction.response.send_message(
                    "This bot is locked. Add your Discord user ID under "
                    "Settings > Allowed user IDs in the app.", ephemeral=True)
                return False
            if interaction.user.id not in allowed:
                log_event(f"Discord command denied for user id {interaction.user.id}")
                await interaction.response.send_message(
                    "You are not allowed to use this bot.", ephemeral=True)
                return False
            return True

        @tree.command(name="status", description="Show every monitored device and whether it is online")
        async def status_cmd(interaction: discord.Interaction) -> None:
            if not await guard(interaction):
                return
            await interaction.response.send_message(format_status(), ephemeral=True)

        @tree.command(name="check", description="Ping all devices right now and show the results")
        async def check_cmd(interaction: discord.Interaction) -> None:
            if not await guard(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await asyncio.to_thread(ENGINE.run_check_cycle, notify=True)
            await interaction.followup.send(format_status(), ephemeral=True)

        @tree.command(name="ping", description="Ping a single IPv4 address")
        @app_commands.describe(ip="IPv4 address, e.g. 192.168.1.33")
        async def ping_cmd(interaction: discord.Interaction, ip: str) -> None:
            if not await guard(interaction):
                return
            try:
                clean = str(ipaddress.IPv4Address(ip.strip()))
            except ValueError:
                await interaction.response.send_message(
                    "That is not a valid IPv4 address.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            reachable = await asyncio.to_thread(is_reachable, clean)
            status = "ONLINE" if reachable else "OFFLINE"
            await interaction.followup.send(
                f"{_DOT[status]} `{clean}` is **{status}**", ephemeral=True)

        @tree.command(name="scan", description="Scan the local network for IP and MAC addresses")
        async def scan_cmd(interaction: discord.Interaction) -> None:
            if not await guard(interaction):
                return
            if bot._scan_busy:
                await interaction.response.send_message(
                    "A scan is already running.", ephemeral=True)
                return
            bot._scan_busy = True
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                duration = load_settings()["scanner_duration_seconds"]
                hits = await asyncio.to_thread(run_lan_scan, duration)
                monitored = {d["ip"] for d in ENGINE.get_devices()}
                lines = [f"**Scan complete** \u2014 {len(hits)} device(s) found", ""]
                for hit in hits:
                    mark = " (monitored)" if hit.ip in monitored else ""
                    lines.append(f"`{hit.ip}`  {hit.mac}{mark}")
                await interaction.followup.send(_clip("\n".join(lines)), ephemeral=True)
            finally:
                bot._scan_busy = False

        @tree.command(name="start", description="Start continuous monitoring")
        async def start_cmd(interaction: discord.Interaction) -> None:
            if not await guard(interaction):
                return
            started = ENGINE.start_monitoring()
            await interaction.response.send_message(
                "Monitoring started." if started else "Monitoring is already running.",
                ephemeral=True)

        @tree.command(name="stop", description="Stop continuous monitoring")
        async def stop_cmd(interaction: discord.Interaction) -> None:
            if not await guard(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            stopped = await asyncio.to_thread(ENGINE.stop_monitoring)
            await interaction.followup.send(
                "Monitoring stopped." if stopped else "Monitoring was not running.",
                ephemeral=True)

        @tree.error
        async def on_error(interaction: discord.Interaction, error: Exception) -> None:
            log_event(f"Discord command error: {type(error).__name__}")
            message = "Something went wrong running that command."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except Exception:
                pass

        try:
            await client.start(token)
        finally:
            await client.close()
