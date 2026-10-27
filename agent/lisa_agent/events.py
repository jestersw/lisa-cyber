"""Activity-event reporting: the agent tells the backend what it's doing.

The ActivityEngine and orchestrator call ``EventReporter.record(...)`` whenever
something observable happens — an app opens or closes, an activity runs, the
user "steps away". Events are buffered and flushed in batches to
``POST /api/agents/{id}/events`` on a background thread, so recording an event
is cheap: it never blocks the activity loop and never depends on the backend
being reachable at that moment.

This is the data source behind the operator panel's live range view, and the
raw material for retraining the next-activity model (#51) and for checking
detection realism against a SIEM (#232). It deliberately mirrors
``heartbeat.py``: one small sender object, injectable sleep, a loop that must
never die.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

import requests

log = logging.getLogger("lisa-agent.events")


class EventReporter:
    """Buffers activity events and flushes them to the backend in batches.

    ``record`` is safe to call from the activity loop at any time; it only
    appends to an in-memory buffer. A background thread flushes that buffer
    every ``flush_interval`` seconds, and ``stop`` flushes once more on the way
    out. If a flush fails (backend down), the events are put back at the front
    of the buffer and retried on the next tick, up to ``max_buffer`` — beyond
    that the oldest events are dropped so a long outage can't grow memory
    without bound.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        flush_interval: float = 15.0,
        max_buffer: int = 500,
        timeout: float = 30.0,
    ) -> None:
        self.url = url
        self.token = token
        self.flush_interval = flush_interval
        self.max_buffer = max_buffer
        self.timeout = timeout
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_buffer)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- recording -------------------------------------------------------

    def record(
        self,
        app: str,
        activity_type: str,
        *,
        duration_seconds: float | None = None,
        context: dict[str, Any] | None = None,
        role: str | None = None,
    ) -> None:
        """Queue one event. Timestamped now (UTC); never raises."""
        event = {
            "app": app,
            "activity_type": activity_type,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if duration_seconds is not None:
            event["duration_seconds"] = duration_seconds
        if context:
            event["context"] = context
        if role:
            event["role"] = role
        with self._lock:
            self._buffer.append(event)

    # -- flushing --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def flush(self) -> int:
        """Send everything buffered. Returns the number of events sent.

        On failure the drained events are re-queued at the front so the next
        flush retries them; the caller never sees the exception.
        """
        with self._lock:
            if not self._buffer:
                return 0
            batch = list(self._buffer)
            self._buffer.clear()

        if not self.url:
            log.warning("No backend URL configured; dropping %d events", len(batch))
            return 0

        try:
            resp = requests.post(
                self.url,
                json={"events": batch},
                headers=self._headers(),
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return len(batch)
            log.error("Event flush failed with status %s", resp.status_code)
        except requests.RequestException as exc:
            log.error("Event flush error: %s", exc)

        # Re-queue at the front, keeping newest if we overflow max_buffer.
        with self._lock:
            self._buffer.extendleft(reversed(batch))
        return 0

    # -- background loop -------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.flush_interval)
            try:
                self.flush()
            except Exception as exc:  # noqa: BLE001 - loop must never die
                log.error("Error in event loop: %s", exc)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Event reporter started (flush every %.0fs)", self.flush_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.flush()  # last-chance drain
        log.info("Event reporter stopped")
