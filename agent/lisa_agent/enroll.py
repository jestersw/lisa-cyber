"""Install-time enrollment: turn the baked one-time token into the real one (#201).

The build bakes a single-use *enrollment* token into the binary (LISA_AGENT_TOKEN),
not a long-lived credential. On first run the agent exchanges it for its real
per-agent token via POST /api/agents/{id}/enroll, stores that token locally, and
uses it for every later request. On subsequent runs the stored token is loaded
and no enrollment happens. This keeps the real token out of the downloadable
artefact (which only ever carries the short-lived enrollment token).

resolve_token() is the single entry point:
  - a stored token on disk wins (already enrolled);
  - otherwise enroll with the bootstrap token and persist the result;
  - no bootstrap token (dev build) means no auth — return None, matching the
    backend's dev-open behaviour.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("lisa-agent.enroll")


def default_token_path() -> Path:
    """Where the resolved real token is persisted, per OS.

    A per-user location that needs no privileges: %LOCALAPPDATA%\\lisa on
    Windows, ~/.lisa elsewhere — the same per-user area the mutex and activity
    sandbox already use.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "lisa" / "agent_token"
    return Path(os.path.expanduser("~")) / ".lisa" / "agent_token"


def _read_token(path: Path) -> str | None:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def _write_token(path: Path, token: str) -> None:
    """Persist the token for later runs, readable only by the owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        # chmod is best-effort (e.g. on Windows / odd filesystems); the token is
        # still written. Not fatal.
        log.debug("could not chmod token file %s", path)


def _enroll_once(
    backend_url: str, agent_id: str, bootstrap_token: str, timeout: float
) -> str | None:
    """One enrollment attempt. Returns the real token, or None on any failure."""
    url = f"{backend_url.rstrip('/')}/api/agents/{agent_id}/enroll"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {bootstrap_token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        log.warning("enrollment request failed: %s", exc)
        return None
    if resp.status_code != 200:
        log.warning("enrollment rejected with status %s", resp.status_code)
        return None
    try:
        token = resp.json().get("token")
    except ValueError:
        log.warning("enrollment returned non-JSON")
        return None
    return token if isinstance(token, str) and token else None


def resolve_token(
    backend_url: str,
    agent_id: str,
    bootstrap_token: str | None,
    *,
    token_path: Path | None = None,
    retries: int = 5,
    retry_delay: float = 30.0,
    timeout: float = 15.0,
    sleep=time.sleep,
) -> str | None:
    """Return the agent's real token, enrolling on first run if needed.

    A token already on disk is returned as-is. Otherwise, with a bootstrap
    (enrollment) token, enroll and persist the result, retrying on transient
    failures. With no bootstrap token (a dev build) there is nothing to enroll
    with, so None is returned and the agent runs unauthenticated against a
    dev-open backend.
    """
    path = token_path or default_token_path()

    existing = _read_token(path)
    if existing:
        log.info("using stored agent token")
        return existing

    if not bootstrap_token:
        log.info("no enrollment token provided; running without agent auth (dev)")
        return None

    for attempt in range(1, max(1, retries) + 1):
        token = _enroll_once(backend_url, agent_id, bootstrap_token, timeout)
        if token:
            _write_token(path, token)
            log.info("enrolled; stored agent token at %s", path)
            return token
        if attempt < retries:
            log.info("enrollment attempt %d failed; retrying in %.0fs", attempt, retry_delay)
            sleep(retry_delay)

    log.error("enrollment failed after %d attempts", retries)
    return None
