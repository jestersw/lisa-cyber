import os
from unittest import mock

import pytest

from lisa_agent.config import Config, WorkSchedule, validate_backend_url


def test_defaults():
    cfg = Config()
    assert cfg.backend_url == "http://localhost:8000"
    assert cfg.auth_token is None
    assert cfg.heartbeat_interval_minutes == 30
    assert isinstance(cfg.schedule, WorkSchedule)


def test_from_env_reads_all_values():
    env = {
        "LISA_BACKEND_URL": "https://lisa.example:8000",
        "LISA_AGENT_TOKEN": "secret-token",
        "LISA_HEARTBEAT_INTERVAL_MINUTES": "15",
        "LISA_WORK_START": "08:30",
        "LISA_WORK_END": "17:30",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        cfg = Config.from_env()
    assert cfg.backend_url == "https://lisa.example:8000"
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


# ---------- TLS enforcement for backend URL (#55) ----------


def test_validate_backend_url_accepts_https():
    validate_backend_url("https://lisa.example:8000")  # no raise


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:9000", "http://[::1]/"])
def test_validate_backend_url_allows_loopback_http(url):
    validate_backend_url(url)  # loopback: nothing crosses a network


def test_validate_backend_url_rejects_remote_http():
    with pytest.raises(ValueError, match="must use https"):
        validate_backend_url("http://lisa.example:8000")


def test_validate_backend_url_insecure_override_allows_remote_http():
    validate_backend_url("http://lisa.example:8000", allow_insecure=True)  # no raise


def test_validate_backend_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="must be http or https"):
        validate_backend_url("ftp://lisa.example/agent")


def test_from_env_rejects_plaintext_http_to_remote():
    with mock.patch.dict(os.environ, {"LISA_BACKEND_URL": "http://lisa.example:8000"}, clear=False):
        os.environ.pop("LISA_ALLOW_INSECURE_HTTP", None)
        with pytest.raises(ValueError, match="must use https"):
            Config.from_env()


def test_from_env_insecure_override_env_allows_remote_http():
    env = {"LISA_BACKEND_URL": "http://lisa.example:8000", "LISA_ALLOW_INSECURE_HTTP": "1"}
    with mock.patch.dict(os.environ, env, clear=False):
        cfg = Config.from_env()
    assert cfg.backend_url == "http://lisa.example:8000"
