"""Heartbeat: periodically report the agent's status to the backend.

Ported from the original Linux agent (HeartbeatManager by the agent's original
author). The retry logic, background loop with a stop event, interval handling,
and force-send are all kept. Two changes to fit the new package:

- uses `requests` instead of `urllib`;
- the auth token and backend URL come from configuration (environment), never
  hardcoded - the original embedded an API key in the source;
- decoupled from the agent: the sender is given a ready-made payload (or a
  provider callable) instead of reaching into agent internals, so it is
  unit-testable on its own.
"""

from __future__ import annotations

import logging
import platform
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger("lisa-agent.heartbeat")


def system_info() -> dict[str, Any]:
    """Static-ish facts about the host, included in every heartbeat."""
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }


def build_payload(
    agent_id: str,
    status: str,
    *,
    current_app: str | None = None,
    statistics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a heartbeat body. Mirrors the original payload shape."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "status": status,
        "system_info": system_info(),
        "current_activity": {"application": current_app},
        "statistics": statistics or {},
    }


class HeartbeatSender:
    """Sends a single heartbeat over HTTP, with retries and auth."""

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        retry_count: int = 3,
        retry_delay: float = 60.0,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.retry_count = max(1, retry_count)
        self.retry_delay = retry_delay

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def send(self, payload: dict[str, Any], sleep: Callable[[float], None] | None = None) -> bool:
        """POST the payload, retrying on failure. Returns True on success.

        `sleep` is injectable so tests don't actually wait between retries.
        """
        import time

        sleep = sleep or time.sleep
        if not self.url:
            log.warning("No backend URL configured; skipping heartbeat")
            return False

        for attempt in range(1, self.retry_count + 1):
            try:
                resp = requests.post(
                    self.url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return True
                log.error(
                    "Heartbeat failed with status %s (attempt %d)",
                    resp.status_code,
                    attempt,
                )
            except requests.RequestException as exc:
                log.error("Heartbeat attempt %d error: %s", attempt, exc)

            if attempt < self.retry_count:
                sleep(self.retry_delay)
        return False


class HeartbeatLoop:
    """Runs a HeartbeatSender on a background thread at a fixed interval."""

    def __init__(
        self,
        sender: HeartbeatSender,
        payload_provider: Callable[[], dict[str, Any]],
        interval_seconds: float,
    ) -> None:
        self.sender = sender
        self.payload_provider = payload_provider
        self.interval_seconds = interval_seconds
        self.last_heartbeat: datetime | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def force(self) -> bool:
        """Send one heartbeat right now (e.g. at startup or shutdown)."""
        ok = self.sender.send(self.payload_provider())
        if ok:
            self.last_heartbeat = datetime.now(timezone.utc)
        return ok

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.force():
                    log.debug("Heartbeat sent at %s", self.last_heartbeat)
            except Exception as exc:  # noqa: BLE001 - loop must never die
                log.error("Error in heartbeat loop: %s", exc)
                self._stop.wait(60)
                continue
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Heartbeat loop started (interval %.0fs)", self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Heartbeat loop stopped")
