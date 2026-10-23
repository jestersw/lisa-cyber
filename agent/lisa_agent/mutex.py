"""Single-instance mutex for a LISA agent.

One agent per identity, replacing any previous copy when a new one starts -
this is how an update replaces the running agent. There are two implementations,
chosen at runtime by the host OS (see `make_mutex` / the `AgentMutex` alias):

  - PosixAgentMutex (Linux, macOS): an flock-based lock file recording the
    owning PID, stale-lock cleanup, and graceful termination (SIGTERM, then
    SIGKILL) of a previous holder. Ported from the original Linux agent
    (AgentMutexManager by the agent's original author); behaviour unchanged.
  - WindowsAgentMutex (Windows, #221): a named Win32 mutex (CreateMutexW via
    ctypes) for the actual single-instance guarantee, plus the same lock
    file + PID approach to find and terminate a previous holder (OpenProcess
    to probe liveness, taskkill to stop it). No pywin32 dependency - ctypes
    only.

Both expose the same surface - acquire() / release(), plus mutex_dir /
mutex_path - so the orchestrator and main.py are OS-agnostic. The mutex
directory and identity are constructor arguments, so the logic is unit-testable
without root, /var/run, or a particular OS.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from lisa_agent.platform_ops import current_os

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
    except (OSError, AttributeError):
        # os.kill(pid, 0) is unreliable on Windows; the Windows mutex uses its
        # own _win_pid_alive instead and never calls this.
        return False
    return True


class PosixAgentMutex:
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
        import fcntl  # POSIX-only; imported here so the module loads on Windows

        try:
            if self._is_locked():
                log.info("Existing agent for %s found, terminating it", self.identity)
                self._terminate_existing()

            self._file = self.mutex_path.open("w")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            info = {
                "pid": os.getpid(),
                "identity": self.identity,
                "started_at": datetime.now(UTC).isoformat(),
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
        import fcntl  # POSIX-only; see acquire()

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
        import signal  # POSIX signals; imported here so the module loads on Windows

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


# Windows default lock location: per-user, always writable, no admin needed.
# %LOCALAPPDATA% on a normal account, falling back to the temp dir.
def _win_default_mutex_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    return Path(base) / "lisa_agents"


def _win_pid_alive(pid: int) -> bool:
    """True if a process with this PID exists on Windows.

    Uses OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION): a handle means the
    process exists; ERROR_INVALID_PARAMETER (87) means it does not;
    ERROR_ACCESS_DENIED (5) means it exists but we can't open it (still alive).
    """
    if pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    err = ctypes.get_last_error()
    ERROR_ACCESS_DENIED = 5
    return err == ERROR_ACCESS_DENIED


class WindowsAgentMutex:
    """Single-instance guarantee on Windows via a named Win32 mutex, plus a
    lock file + PID so a new copy can find and stop a previous one.

    The named mutex (one kernel object per identity, machine-wide) is what
    actually prevents two agents with the same identity running at once. The
    lock file mirrors the POSIX implementation's on-disk record so the
    replace-the-previous-copy flow (an update) works the same way: read the
    old PID, terminate it with taskkill, then take the mutex.
    """

    _MUTEX_PREFIX = "Global\\lisa_agent_"

    def __init__(
        self,
        identity: str,
        mutex_dir: Path | None = None,
        fallback_dir: Path | None = None,
    ) -> None:
        self.identity = identity
        self._handle = None  # Win32 mutex handle, set in acquire()
        self.mutex_dir = self._resolve_dir(
            mutex_dir or _win_default_mutex_dir(),
            fallback_dir or (Path(os.environ.get("TEMP", ".")) / "lisa_agents"),
        )
        self.mutex_path = self.mutex_dir / f"{identity}.lock"
        # The kernel mutex name can't contain a backslash other than the
        # namespace prefix, so sanitise the identity.
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in identity)
        self._mutex_name = f"{self._MUTEX_PREFIX}{safe}"

    @staticmethod
    def _resolve_dir(primary: Path, fallback: Path) -> Path:
        """Use primary if writable, else fall back."""
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
        import ctypes
        from ctypes import wintypes

        try:
            if self._is_locked():
                log.info("Existing agent for %s found, terminating it", self.identity)
                self._terminate_existing()

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            ERROR_ALREADY_EXISTS = 183

            handle = kernel32.CreateMutexW(None, True, self._mutex_name)
            last_error = ctypes.get_last_error()
            if not handle:
                log.error("CreateMutexW failed for %s (error %d)", self.identity, last_error)
                return False
            if last_error == ERROR_ALREADY_EXISTS:
                # Another live holder still owns the kernel mutex even though we
                # thought we cleared it (race, or a holder with no lock file).
                kernel32.CloseHandle(handle)
                log.error("Another agent already holds the mutex for %s", self.identity)
                return False

            self._handle = handle
            self.mutex_dir.mkdir(parents=True, exist_ok=True)
            info = {
                "pid": os.getpid(),
                "identity": self.identity,
                "started_at": datetime.now(UTC).isoformat(),
            }
            self.mutex_path.write_text(json.dumps(info, indent=2))
            log.info("Mutex acquired for %s (pid %d)", self.identity, os.getpid())
            return True
        except OSError as exc:
            log.error("Failed to acquire mutex for %s: %s", self.identity, exc)
            return False

    def release(self) -> None:
        """Release the mutex and remove the lock file."""
        import ctypes

        try:
            if self._handle is not None:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.ReleaseMutex(self._handle)
                kernel32.CloseHandle(self._handle)
                self._handle = None
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
        if pid is not None and _win_pid_alive(pid):
            return True
        self.mutex_path.unlink(missing_ok=True)
        return False

    def _terminate_existing(self, grace_seconds: float = 10.0) -> None:
        """Stop the previous holder with taskkill (/T kills its tree, /F forces).

        taskkill is the Windows analogue of SIGTERM->SIGKILL: we try a normal
        kill first, then force if it is still alive after the grace period.
        """
        import subprocess

        pid = self._read_pid()
        if pid is None or not _win_pid_alive(pid):
            return
        try:
            log.info("Terminating pid %d", pid)
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                check=False,
            )
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline:
                if not _win_pid_alive(pid):
                    log.info("pid %d terminated gracefully", pid)
                    return
                time.sleep(0.2)
            log.warning("pid %d did not exit, forcing", pid)
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            log.error("Error terminating pid %d: %s", pid, exc)


def make_mutex(
    identity: str,
    mutex_dir: Path | None = None,
    fallback_dir: Path | None = None,
):
    """Return the single-instance mutex implementation for the current OS."""
    cls = WindowsAgentMutex if current_os() == "windows" else PosixAgentMutex
    return cls(identity, mutex_dir=mutex_dir, fallback_dir=fallback_dir)


# Backwards-compatible name: existing callers and tests do `AgentMutex(...)`.
# On Linux/macOS this is the POSIX implementation (unchanged); the agent itself
# goes through make_mutex() so a Windows host gets the Windows one.
AgentMutex = PosixAgentMutex
