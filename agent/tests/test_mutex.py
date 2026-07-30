import json
import os
import subprocess
import sys

from lisa_agent.mutex import AgentMutex, _pid_alive


def make(tmp_path, identity="agent_u1"):
    # Inject tmp dirs so the test needs no root and touches no /var/run or /tmp.
    return AgentMutex(identity, mutex_dir=tmp_path / "run", fallback_dir=tmp_path / "fallback")


def test_acquire_creates_lock_with_our_pid(tmp_path):
    m = make(tmp_path)
    assert m.acquire() is True
    assert m.mutex_path.exists()
    info = json.loads(m.mutex_path.read_text())
    assert info["pid"] == os.getpid()
    assert info["identity"] == "agent_u1"
    m.release()


def test_release_removes_lock(tmp_path):
    m = make(tmp_path)
    m.acquire()
    m.release()
    assert not m.mutex_path.exists()


def test_release_is_safe_without_acquire(tmp_path):
    # Should not raise even if never acquired.
    make(tmp_path).release()


def test_falls_back_when_primary_unwritable(tmp_path):
    # Primary points at a file (not a dir) so mkdir/probe fails -> fallback used.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a dir")
    fallback = tmp_path / "fb"
    m = AgentMutex("agent_u2", mutex_dir=blocker, fallback_dir=fallback)
    assert m.mutex_dir == fallback
    assert m.acquire() is True
    m.release()


def test_stale_lock_is_reclaimed(tmp_path):
    # Write a lock file owning a PID that is definitely dead, then acquire.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()  # now dead.pid refers to an exited process
    m = make(tmp_path, "agent_stale")
    m.mutex_dir.mkdir(parents=True, exist_ok=True)
    m.mutex_path.write_text(json.dumps({"pid": dead.pid, "identity": "agent_stale"}))
    # A stale lock must not block us.
    assert m.acquire() is True
    info = json.loads(m.mutex_path.read_text())
    assert info["pid"] == os.getpid()
    m.release()


def test_terminates_previous_live_holder(tmp_path):
    # Spawn a real long-lived process, register it as the holder, then acquire.
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        m = make(tmp_path, "agent_live")
        m.mutex_dir.mkdir(parents=True, exist_ok=True)
        m.mutex_path.write_text(json.dumps({"pid": victim.pid, "identity": "agent_live"}))
        assert m.acquire() is True
        # The previous holder must have been signalled and must exit. We reap it
        # here (in production the killed agent is not our child, so it just
        # disappears; as our child it would linger as a zombie until waited on).
        returncode = victim.wait(timeout=5)
        # Negative return code means the process was terminated by a signal.
        assert returncode is not None
        assert returncode < 0
        m.release()
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait()


def test_pid_alive_basic():
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(-1) is False
