"""Redis-backed worker that dispatches agent build jobs.

The API endpoint that creates an agent pushes a job onto a Redis list; a
long-running worker process pops from it and calls build_agent(). This
module is the worker: it owns the job format, the polling loop, and the
side-effects that follow a build (DB status, download URL).

Design notes:

- No queue library. Just LPUSH/BRPOP on Redis. Fewer moving parts, no new
  dependency, and rate_limit.py already talks to Redis so the connection
  code is well understood.

- Jobs are simple JSON dicts. Enqueueing is a one-liner from the API side;
  we don't need typed job objects on the wire.

- The worker's job is orchestration and DB updates, not the build itself.
  The build is build_agent() from ../builder.py - a pure function of its
  inputs. That separation keeps this module focused on failure recovery
  and status bookkeeping.

- Failures never abort the worker. A single bad build sets the agent's
  status to `failed` and moves on to the next job. Only startup errors
  (Redis unreachable, no source root) are fatal.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_sessionmaker
from app.models.models import Agent
from app.services.agent_builder.builder import BuildError, build_agent

log = logging.getLogger("lisa.builder.worker")

# Redis list that jobs live on. LPUSH from the API side, BRPOP here.
QUEUE_KEY = "lisa:builder:jobs"

# BRPOP timeout (seconds) - how long the worker blocks before checking the
# stop flag. Short enough to shut down responsively, long enough not to hot-loop.
POLL_TIMEOUT_SECONDS = 5


class WorkerConfigError(RuntimeError):
    """Something the worker needs at startup is missing (agent source root,
    backend URL, Redis)."""


@dataclass(frozen=True)
class WorkerConfig:
    agent_source_root: Path
    backend_url: str

    @classmethod
    def from_env(cls) -> WorkerConfig:
        source_root = os.environ.get("LISA_AGENT_SOURCE_ROOT")
        backend_url = os.environ.get("LISA_BACKEND_URL")
        if not source_root:
            raise WorkerConfigError("LISA_AGENT_SOURCE_ROOT is not set (path to agent/lisa_agent)")
        if not backend_url:
            raise WorkerConfigError(
                "LISA_BACKEND_URL is not set (URL the agent will send heartbeats to)"
            )
        return cls(
            agent_source_root=Path(source_root),
            backend_url=backend_url,
        )


def enqueue_build(redis_client: Any, agent_id: str) -> None:
    """Push a build job onto the queue. Called from the API when a new agent
    is registered (status transitions to `building`).

    We only push the agent_id - everything else the worker needs (config, os)
    it reads from the DB, so there's a single source of truth."""
    if not agent_id:
        raise ValueError("agent_id must be provided")
    job = json.dumps({"agent_id": agent_id})
    redis_client.lpush(QUEUE_KEY, job)
    log.info("enqueued build for %s", agent_id)


def process_one_job(
    job_payload: str,
    config: WorkerConfig,
    session_factory=None,
) -> None:
    """Handle a single job from the queue.

    Never raises to the outer loop: every failure ends with the agent status
    set to 'failed' (or 'ready' on success) so the operator always sees a
    definitive outcome.
    """
    session_factory = session_factory or get_sessionmaker()
    try:
        job = json.loads(job_payload)
        agent_id = job["agent_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.error("malformed job, dropping: %s (%s)", job_payload, exc)
        return

    with session_factory() as session:
        agent = _load_agent(session, agent_id)
        if agent is None:
            log.error("job for unknown agent %s, dropping", agent_id)
            return

        # A fresh token per build. Rotating the token means rebuilding the
        # binary, which matches how the builder works anyway.
        token = secrets.token_urlsafe(32)
        agent.agent_token = token
        agent.status = "building"
        session.commit()

        try:
            result = build_agent(
                agent_id=agent_id,
                deployment_package=_package_from_config(agent),
                agent_token=token,
                backend_url=config.backend_url,
                agent_source_root=config.agent_source_root,
            )
        except BuildError as exc:
            log.error("build %s failed to start: %s", agent_id, exc)
            _mark_failed(session, agent)
            return
        except Exception:
            # Any other unexpected error: log it, mark the agent failed, keep
            # the worker alive for the next job. log.exception grabs the
            # traceback automatically.
            log.exception("build %s crashed unexpectedly", agent_id)
            _mark_failed(session, agent)
            return

        if result.success:
            agent.status = "ready"
            agent.binary_url = result.download_url
            session.commit()
            log.info("build %s ready: %s", agent_id, result.download_url)
        else:
            log.warning("build %s: nuitka rejected the code", agent_id)
            _mark_failed(session, agent)


def run(
    redis_client: Any,
    config: WorkerConfig | None = None,
    stop_flag: Any = None,
    session_factory=None,
) -> None:
    """Main loop: BRPOP from the queue, process, repeat.

    stop_flag: any object with an .is_set() method (threading.Event by
    default in production; a stub in tests). The loop checks it after each
    BRPOP wakeup.
    """
    config = config or WorkerConfig.from_env()
    stop_flag = stop_flag or _install_signal_stop()
    session_factory = session_factory or get_sessionmaker()

    log.info("worker starting: queue=%s source=%s", QUEUE_KEY, config.agent_source_root)
    while not stop_flag.is_set():
        try:
            item = redis_client.brpop(QUEUE_KEY, timeout=POLL_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            # Redis blip - back off briefly and keep going. The alternative
            # is dying, which loses the whole worker for one transient error.
            log.warning("redis error while polling, retrying: %s", exc)
            time.sleep(1)
            continue

        if item is None:
            continue  # BRPOP timed out with no work; loop back to stop check

        # brpop returns (queue_name, value); we only pushed to one queue.
        _, payload = item
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        process_one_job(payload, config, session_factory=session_factory)

    log.info("worker stopped")


# --------------- helpers ---------------


def _load_agent(session: Session, agent_id: str) -> Agent | None:
    stmt = select(Agent).where(Agent.agent_id == agent_id)
    return session.scalars(stmt).one_or_none()


def _package_from_config(agent: Agent) -> dict[str, Any]:
    """Turn the stored agent config into the deployment package the builder
    needs. Backend code that assembles the package lives elsewhere; here we
    just pass what's already in the DB."""
    config = agent.config or {}
    if "agent_config" in config and "application_plugins" in config:
        # Already the full deployment package
        return config
    return {"agent_config": config, "application_plugins": {}}


def _mark_failed(session: Session, agent: Agent) -> None:
    agent.status = "failed"
    session.commit()


def _install_signal_stop():
    """Install SIGTERM/SIGINT handlers that flip a threading Event."""
    import threading

    event = threading.Event()

    def _handler(_signum, _frame):
        log.info("worker received shutdown signal")
        event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    return event
