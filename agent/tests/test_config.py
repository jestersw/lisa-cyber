import os
from unittest import mock

from lisa_agent.config import Config, WorkSchedule


def test_defaults():
    cfg = Config()
    assert cfg.backend_url == "http://localhost:8000"
    assert cfg.auth_token is None
    assert cfg.heartbeat_interval_minutes == 30
    assert isinstance(cfg.schedule, WorkSchedule)


def test_from_env_reads_all_values():
    env = {
        "LISA_BACKEND_URL": "http://lisa.example:8000",
        "LISA_AGENT_TOKEN": "secret-token",
        "LISA_HEARTBEAT_INTERVAL_MINUTES": "15",
        "LISA_WORK_START": "08:30",
        "LISA_WORK_END": "17:30",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        cfg = Config.from_env()
    assert cfg.backend_url == "http://lisa.example:8000"
    assert cfg.auth_token == "secret-token"
    assert cfg.heartbeat_interval_minutes == 15
    assert cfg.schedule.start == "08:30"
    assert cfg.schedule.end == "17:30"


def test_from_env_uses_defaults_when_unset():
    # Ensure the relevant vars are absent, then check defaults apply.
    to_clear = [
        "LISA_BACKEND_URL",
        "LISA_AGENT_TOKEN",
        "LISA_HEARTBEAT_INTERVAL_MINUTES",
        "LISA_WORK_START",
        "LISA_WORK_END",
    ]
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in to_clear:
            os.environ.pop(k, None)
        cfg = Config.from_env()
    assert cfg.backend_url == "http://localhost:8000"
    assert cfg.heartbeat_interval_minutes == 30


def test_invalid_interval_raises():
    with mock.patch.dict(os.environ, {"LISA_HEARTBEAT_INTERVAL_MINUTES": "notanumber"}):
        try:
            Config.from_env()
        except ValueError as exc:
            assert "LISA_HEARTBEAT_INTERVAL_MINUTES" in str(exc)
        else:
            raise AssertionError("expected ValueError for non-integer interval")
