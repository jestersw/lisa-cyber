"""Single-instance mutex for a LISA agent.

Ported from the original Linux agent (AgentMutexManager by the agent's original
author). Behaviour is unchanged: one agent per identity, an flock-based lock
file recording the owning PID, automatic cleanup of stale locks, and graceful
termination (SIGTERM, then SIGKILL) of a previous copy when a new one starts -
this is how an update replaces the running agent.

Changes from the original, to fit the new package:
- uses stdlib os.kill instead of psutil (no extra dependency; POSIX-only, which
  is fine since LISA targets Linux and macOS);
- mutex directory and identity are constructor arguments, so the logic is
  unit-testable without root or writing to /var/run.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("lisa-agent.mutex")

DEFAULT_MUTEX_DIR = Path("/var/run/lisa_agents")
FALLBACK_MUTEX_DIR = Path("/tmp/lisa_agents")


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID exists (POSIX: signal 0 probes it)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user - still counts as alive.
        return True
    return True


class AgentMutex:
    """Ensures only one agent runs per identity, replacing any previous copy."""

    def __init__(
        self,
        identity: str,
        mutex_dir: Path | None = None,
        fallback_dir: Path | None = None,
    ) -> None:
        self.identity = identity
        self._file = None
        self.mutex_dir = self._resolve_dir(
            mutex_dir or DEFAULT_MUTEX_DIR,
            fallback_dir or FALLBACK_MUTEX_DIR,
        )
        self.mutex_path = self.mutex_dir / f"{identity}.lock"

    @staticmethod
    def _resolve_dir(primary: Path, fallback: Path) -> Path:
        """Use primary if writable, else fall back (e.g. no root for /var/run)."""
        try:
            primary.mkdir(parents=True, exist_ok=True)
            probe = primary / ".write_test"
            probe.touch()
            probe.unlink()
            return primary
        except OSError as exc:
            log.warning("Cannot use %s: %s; falling back to %s", primary, exc, fallback)
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def acquire(self) -> bool:
        """Acquire the mutex, terminating any previous holder first."""
        try:
            if self._is_locked():
                log.info("Existing agent for %s found, terminating it", self.identity)
                self._terminate_existing()

            self._file = self.mutex_path.open("w")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            info = {
                "pid": os.getpid(),
                "identity": self.identity,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._file.write(json.dumps(info, indent=2))
            self._file.flush()
            log.info("Mutex acquired for %s (pid %d)", self.identity, os.getpid())
            return True
        except OSError as exc:
            log.error("Failed to acquire mutex for %s: %s", self.identity, exc)
            return False

    def release(self) -> None:
        """Release the mutex and remove the lock file."""
        try:
            if self._file is not None:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
                self._file = None
            self.mutex_path.unlink(missing_ok=True)
            log.info("Mutex released for %s", self.identity)
        except OSError as exc:
            log.error("Error releasing mutex for %s: %s", self.identity, exc)

    def _read_pid(self) -> int | None:
        try:
            info = json.loads(self.mutex_path.read_text())
            pid = info.get("pid")
            return int(pid) if pid is not None else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _is_locked(self) -> bool:
        """True if a live agent already holds this mutex; clean up stale locks."""
        if not self.mutex_path.exists():
            return False
        pid = self._read_pid()
        if pid is not None and _pid_alive(pid):
            return True
        # Stale lock (owner gone or unreadable) - remove it.
        self.mutex_path.unlink(missing_ok=True)
        return False

    def _terminate_existing(self, grace_seconds: float = 10.0) -> None:
        """Stop the previous holder: SIGTERM, wait, then SIGKILL if needed."""
        pid = self._read_pid()
        if pid is None or not _pid_alive(pid):
            return
        try:
            log.info("Sending SIGTERM to pid %d", pid)
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline:
                if not _pid_alive(pid):
                    log.info("pid %d terminated gracefully", pid)
                    return
                time.sleep(0.2)
            log.warning("pid %d did not exit, sending SIGKILL", pid)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return  # already gone
        except OSError as exc:
            log.error("Error terminating pid %d: %s", pid, exc)
