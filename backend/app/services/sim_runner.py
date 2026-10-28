"""Server-side "demo run" of an agent.

A one-click alternative to launching the agent from a terminal. The backend
starts a background thread that reproduces the agent's *observable telemetry* —
a heartbeat-style current app plus activity events (app_open, an OS-level action,
app_close, with occasional glances at another app and idle breaks) — using the
agent's own stored config and application plugins. It writes the same rows the
real agent would, so the live range view lights up identically, with no
terminal and no packaging.

This is a demo / visualisation aid. The *real* agent, which actually drives
applications on a host, is deployed via the installer or the Ansible
"Deploy to hosts" flow. Runs live in-process (one per agent) and are lost on a
backend restart.
"""

from __future__ import annotations

import logging
import random
import threading
from datetime import UTC, datetime
from typing import Any

from app.database import get_sessionmaker
from app.models.models import ActivityEvent, Agent

log = logging.getLogger("lisa.sim_runner")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _category(cmd: dict[str, Any]) -> tuple[str, str | None]:
    """Classify a plugin command into an OS-level category + a telling detail,
    mirroring the agent's own activity_category (network > file > input)."""
    if cmd.get("url"):
        return "network", str(cmd["url"])
    if cmd.get("host"):
        port = cmd.get("port")
        return "network", f"{cmd['host']}:{port}" if port else str(cmd["host"])
    if cmd.get("target"):
        dest = cmd.get("dest")
        return "file", f"{cmd['target']} -> {dest}" if dest else str(cmd["target"])
    if cmd.get("text") or cmd.get("key") or cmd.get("keys"):
        return "input", None
    return "process", None


def _activity_descriptor(activity: dict[str, Any]) -> dict[str, Any]:
    """Precompute {category, detail, name} for one plugin activity."""
    name = activity.get("name") or activity.get("id") or "activity"
    cmds = activity.get("commands") or []
    # Same precedence the agent uses: the first network/file/input command wins.
    for c in cmds:
        if c.get("url") or c.get("host"):
            cat, detail = _category(c)
            return {"category": cat, "detail": detail, "name": name}
    for c in cmds:
        if c.get("target"):
            cat, detail = _category(c)
            return {"category": cat, "detail": detail, "name": name}
    for c in cmds:
        if c.get("text") or c.get("key") or c.get("keys"):
            return {"category": "input", "detail": None, "name": name}
    return {"category": "process", "detail": None, "name": name}


class _Run:
    def __init__(self, thread: threading.Thread, stop: threading.Event, started_at: datetime):
        self.thread = thread
        self.stop = stop
        self.started_at = started_at


class SimRegistry:
    """Tracks the running demo threads, one per agent id."""

    def __init__(self) -> None:
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()

    def is_running(self, agent_id: str) -> bool:
        with self._lock:
            run = self._runs.get(agent_id)
            return bool(run and run.thread.is_alive())

    def status(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(agent_id)
            running = bool(run and run.thread.is_alive())
            return {
                "running": running,
                "started_at": run.started_at.isoformat() if running and run else None,
            }

    def start(
        self, agent_pk: int, agent_id: str, role: str | None, apps: list[dict[str, Any]]
    ) -> bool:
        """Start a demo run. Returns False if one is already running."""
        with self._lock:
            existing = self._runs.get(agent_id)
            if existing and existing.thread.is_alive():
                return False
            stop = threading.Event()
            thread = threading.Thread(
                target=self._loop,
                args=(agent_pk, agent_id, role, apps, stop),
                name=f"sim-{agent_id}",
                daemon=True,
            )
            self._runs[agent_id] = _Run(thread, stop, _utcnow())
            thread.start()
            log.info("demo run started for %s (%d apps)", agent_id, len(apps))
            return True

    def stop(self, agent_id: str) -> bool:
        """Stop a demo run. Returns False if none was running."""
        with self._lock:
            run = self._runs.get(agent_id)
            if not run or not run.thread.is_alive():
                self._runs.pop(agent_id, None)
                return False
            run.stop.set()
        run.thread.join(timeout=5)
        with self._lock:
            self._runs.pop(agent_id, None)
        log.info("demo run stopped for %s", agent_id)
        return True

    # -- the simulated work loop -----------------------------------------

    def _loop(
        self,
        agent_pk: int,
        agent_id: str,
        role: str | None,
        apps: list[dict[str, Any]],
        stop: threading.Event,
    ) -> None:
        session = get_sessionmaker()()
        rng = random.Random()
        try:
            while not stop.is_set():
                app = rng.choice(apps)
                self._open(session, agent_pk, agent_id, app["name"], role)
                for _ in range(rng.randint(1, 4)):
                    if stop.is_set():
                        break
                    self._act(session, agent_pk, app, role)
                    stop.wait(rng.uniform(2.0, 5.0))
                # A quick glance at another app and back.
                if len(apps) > 1 and rng.random() < 0.3 and not stop.is_set():
                    other = rng.choice([a for a in apps if a is not app])
                    self._open(session, agent_pk, agent_id, other["name"], role)
                    self._act(session, agent_pk, other, role)
                    self._emit(session, agent_pk, other["name"], "app_close", role)
                    stop.wait(rng.uniform(2.0, 4.0))
                # An occasional step away.
                if rng.random() < 0.2 and not stop.is_set():
                    self._emit(
                        session, agent_pk, app["name"], "idle", role, {"reason": "stepped_away"}
                    )
                    stop.wait(rng.uniform(3.0, 6.0))
                self._emit(session, agent_pk, app["name"], "app_close", role)
                stop.wait(rng.uniform(2.0, 5.0))
        except Exception as exc:  # noqa: BLE001 - a demo thread must not crash the server
            log.warning("demo run for %s ended on error: %s", agent_id, exc)
        finally:
            session.close()

    def _open(self, session, agent_pk: int, agent_id: str, app: str, role: str | None) -> None:
        self._emit(session, agent_pk, app, "app_open", role)
        # Reflect the current app on the agent row, like a heartbeat would, so
        # the range grid and "now" strip track it.
        agent = session.get(Agent, agent_pk)
        if agent is not None:
            agent.status = "active"
            agent.last_activity = app
            agent.last_seen = _utcnow()
            session.commit()

    def _act(self, session, agent_pk: int, app: dict[str, Any], role: str | None) -> None:
        descriptors = app["activities"]
        d = (
            random.choice(descriptors)
            if descriptors
            else {"category": "process", "name": "work", "detail": None}
        )
        context: dict[str, Any] = {"activity": d["name"]}
        if d.get("detail"):
            context["detail"] = d["detail"]
        self._emit(session, agent_pk, app["name"], d["category"], role, context)

    def _emit(
        self,
        session,
        agent_pk: int,
        app: str,
        activity_type: str,
        role: str | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            ActivityEvent(
                agent_id=agent_pk,
                app=app,
                activity_type=activity_type,
                role=role,
                context=context,
                timestamp=_utcnow(),
            )
        )
        session.commit()


# Process-wide registry (the backend runs a single worker).
registry = SimRegistry()
