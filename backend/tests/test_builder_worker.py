import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services.agent_builder.builder import BuildError
from app.services.agent_builder.worker import (
    QUEUE_KEY,
    WorkerConfig,
    WorkerConfigError,
    enqueue_build,
    process_one_job,
    run,
)

# ============= WorkerConfig.from_env =============


def test_from_env_reads_both_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_AGENT_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("LISA_BACKEND_URL", "http://backend:8000")
    cfg = WorkerConfig.from_env()
    assert cfg.agent_source_root == tmp_path
    assert cfg.backend_url == "http://backend:8000"


def test_from_env_raises_without_source_root(monkeypatch):
    monkeypatch.delenv("LISA_AGENT_SOURCE_ROOT", raising=False)
    monkeypatch.setenv("LISA_BACKEND_URL", "http://b")
    with pytest.raises(WorkerConfigError, match="LISA_AGENT_SOURCE_ROOT"):
        WorkerConfig.from_env()


def test_from_env_raises_without_backend_url(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_AGENT_SOURCE_ROOT", str(tmp_path))
    monkeypatch.delenv("LISA_BACKEND_URL", raising=False)
    with pytest.raises(WorkerConfigError, match="LISA_BACKEND_URL"):
        WorkerConfig.from_env()


# ============= enqueue_build =============


def test_enqueue_pushes_json_job_to_queue():
    redis_client = MagicMock()
    enqueue_build(redis_client, "USR001")

    redis_client.lpush.assert_called_once()
    args = redis_client.lpush.call_args.args
    assert args[0] == QUEUE_KEY
    job = json.loads(args[1])
    assert job == {"agent_id": "USR001"}


def test_enqueue_rejects_blank_agent_id():
    with pytest.raises(ValueError, match="agent_id"):
        enqueue_build(MagicMock(), "")


# ============= process_one_job =============
#
# The worker calls `_load_agent(session, id)` which runs a SQL query. In tests
# we replace `_load_agent` directly so we don't need a real DB — the worker's
# job is orchestration + status bookkeeping, and that's what these tests
# check. Actual DB interaction is covered by an integration test later.


class FakeAgent:
    def __init__(self, agent_id: str, config: dict | None = None):
        self.agent_id = agent_id
        self.name = "Test Agent"
        self.status = "configured"
        self.config = config
        self.agent_token = None
        self.binary_url = None
        self.installer_url = None


class FakeSession:
    def __init__(self):
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        self.commits += 1


@contextmanager
def _patched(agent):
    """Patch out DB access so tests don't need a real SQLAlchemy session."""
    session = FakeSession()

    def fake_session_factory():
        return session

    with (
        patch("app.services.agent_builder.worker._load_agent", return_value=agent),
    ):
        yield fake_session_factory, session


def test_process_success_sets_status_ready_and_binary_url(tmp_path):
    agent = FakeAgent("USR001", config={"agent_info": {"role": "dev"}})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b:8000")

    fake_result = MagicMock()
    fake_result.success = True
    fake_result.download_url = "/api/builds/USR001/agent_USR001"

    with _patched(agent) as (session_factory, _):
        with patch(
            "app.services.agent_builder.worker.build_agent",
            return_value=fake_result,
        ) as mock_build:
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )

    assert agent.status == "ready"
    assert agent.binary_url == "/api/builds/USR001/agent_USR001"
    assert agent.agent_token is not None
    assert len(agent.agent_token) > 20  # secrets.token_urlsafe(32) ~ 43 chars

    call_kwargs = mock_build.call_args.kwargs
    assert call_kwargs["agent_id"] == "USR001"
    assert call_kwargs["agent_token"] == agent.agent_token
    assert call_kwargs["backend_url"] == "http://b:8000"


def test_process_marks_agent_building_before_calling_builder(tmp_path):
    agent = FakeAgent("USR001", config={})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    seen_status = {}

    def peek(**kwargs):
        seen_status["value"] = agent.status
        result = MagicMock()
        result.success = True
        result.download_url = "/x"
        return result

    with _patched(agent) as (session_factory, _):
        with patch("app.services.agent_builder.worker.build_agent", side_effect=peek):
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )
    assert seen_status["value"] == "building"


def test_process_marks_failed_when_compile_rejects_code(tmp_path):
    agent = FakeAgent("USR001", config={})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")

    fake_result = MagicMock()
    fake_result.success = False
    fake_result.download_url = None

    with _patched(agent) as (session_factory, _):
        with patch(
            "app.services.agent_builder.worker.build_agent",
            return_value=fake_result,
        ):
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )
    assert agent.status == "failed"
    assert agent.binary_url is None


def test_process_marks_failed_on_build_error(tmp_path):
    agent = FakeAgent("USR001", config={})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")

    with _patched(agent) as (session_factory, _):
        with patch(
            "app.services.agent_builder.worker.build_agent",
            side_effect=BuildError("no sources"),
        ):
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )
    assert agent.status == "failed"


def test_process_marks_failed_on_unexpected_exception(tmp_path):
    agent = FakeAgent("USR001", config={})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")

    with _patched(agent) as (session_factory, _):
        with patch(
            "app.services.agent_builder.worker.build_agent",
            side_effect=RuntimeError("boom"),
        ):
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )
    assert agent.status == "failed"


def test_process_drops_malformed_job(tmp_path, caplog):
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    with caplog.at_level("ERROR"):
        process_one_job(
            "not-json{{",
            config,
            session_factory=lambda: FakeSession(),
        )
    assert any("malformed" in rec.message for rec in caplog.records)


def test_process_drops_unknown_agent(tmp_path, caplog):
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    with _patched(None) as (session_factory, _):
        with caplog.at_level("ERROR"):
            process_one_job(
                json.dumps({"agent_id": "USR-does-not-exist"}),
                config,
                session_factory=session_factory,
            )
    assert any("unknown agent" in rec.message for rec in caplog.records)


def test_process_recognises_full_deployment_package(tmp_path):
    already_full = {
        "agent_config": {"agent_info": {"role": "dev"}},
        "application_plugins": {"vscode": {}},
    }
    agent = FakeAgent("USR001", config=already_full)
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    captured = {}

    def capture(**kwargs):
        captured["package"] = kwargs["deployment_package"]
        result = MagicMock()
        result.success = True
        result.download_url = "/x"
        return result

    with _patched(agent) as (session_factory, _):
        with patch("app.services.agent_builder.worker.build_agent", side_effect=capture):
            process_one_job(
                json.dumps({"agent_id": "USR001"}),
                config,
                session_factory=session_factory,
            )
    assert captured["package"] == already_full


# ============= run loop =============


class OneShotFlag:
    """Stop flag that returns False once, then True — lets the loop process
    exactly one iteration."""

    def __init__(self):
        self._calls = 0

    def is_set(self):
        self._calls += 1
        return self._calls > 1


def test_run_processes_a_job_then_stops(tmp_path):
    redis = MagicMock()
    redis.brpop.return_value = (b"queue", json.dumps({"agent_id": "USR001"}).encode())

    agent = FakeAgent("USR001", config={})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    fake_result = MagicMock()
    fake_result.success = True
    fake_result.download_url = "/x"

    with (
        _patched(agent) as (session_factory, _),
        patch(
            "app.services.agent_builder.worker.build_agent",
            return_value=fake_result,
        ),
    ):
        run(
            redis_client=redis,
            config=config,
            stop_flag=OneShotFlag(),
            session_factory=session_factory,
        )

    assert agent.status == "ready"


def test_run_skips_when_queue_is_empty(tmp_path):
    redis = MagicMock()
    redis.brpop.return_value = None
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")
    run(redis_client=redis, config=config, stop_flag=OneShotFlag())


def test_run_survives_redis_errors(tmp_path):
    redis = MagicMock()
    redis.brpop.side_effect = ConnectionError("redis down")
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")

    with patch("app.services.agent_builder.worker.time.sleep"):
        run(redis_client=redis, config=config, stop_flag=OneShotFlag())


def test_process_writes_installer_url_on_success(tmp_path):
    """Worker must record BOTH binary_url and installer_url after a
    successful build — the migration exists for this."""
    agent = FakeAgent("USR001", config={"agent_info": {"role": "dev"}})
    config = WorkerConfig(agent_source_root=tmp_path, backend_url="http://b")

    fake_result = MagicMock()
    fake_result.success = True
    fake_result.download_url = "/api/builds/USR001/agent_USR001"
    fake_result.installer_url = "/api/builds/USR001/installer_USR001.sh"

    with (
        _patched(agent) as (session_factory, _),
        patch(
            "app.services.agent_builder.worker.build_agent",
            return_value=fake_result,
        ),
    ):
        process_one_job(
            json.dumps({"agent_id": "USR001"}),
            config,
            session_factory=session_factory,
        )

    assert agent.status == "ready"
    assert agent.binary_url == "/api/builds/USR001/agent_USR001"
    assert agent.installer_url == "/api/builds/USR001/installer_USR001.sh"
