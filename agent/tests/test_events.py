import pytest
import requests

from lisa_agent.events import EventReporter


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture
def post_calls(monkeypatch):
    """Capture POSTs and let each test say what the server returns."""
    calls = []
    outcome = {"status": 200, "raise": False}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if outcome["raise"]:
            raise requests.ConnectionError("backend down")
        return FakeResponse(outcome["status"])

    monkeypatch.setattr("lisa_agent.events.requests.post", fake_post)
    return calls, outcome


def _reporter(url="http://b:8000/api/agents/USR001/events", **kw):
    return EventReporter(url, token="tok", **kw)


def test_record_only_buffers_no_network(post_calls):
    calls, _ = post_calls
    r = _reporter()
    r.record("Chrome", "app_open")
    r.record("Chrome", "network", context={"detail": "http://wiki"}, duration_seconds=3.0)
    assert calls == []  # nothing sent until a flush
    assert len(r._buffer) == 2


def test_flush_posts_batch_with_auth_and_clears(post_calls):
    calls, _ = post_calls
    r = _reporter()
    r.record("Chrome", "app_open")
    r.record("Slack", "input", context={"activity": "sent message"})
    sent = r.flush()
    assert sent == 2
    assert len(calls) == 1
    body = calls[0]["json"]
    assert [e["app"] for e in body["events"]] == ["Chrome", "Slack"]
    assert all("timestamp" in e for e in body["events"])
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert len(r._buffer) == 0  # drained on success


def test_record_includes_optional_fields(post_calls):
    r = _reporter()
    r.record("Code", "file", duration_seconds=12.5, context={"detail": "main.py"}, role="developer")
    e = r._buffer[0]
    assert e["duration_seconds"] == 12.5
    assert e["context"] == {"detail": "main.py"}
    assert e["role"] == "developer"


def test_flush_requeues_on_server_error(post_calls):
    _calls, outcome = post_calls
    outcome["status"] = 503
    r = _reporter()
    r.record("Chrome", "app_open")
    assert r.flush() == 0
    assert len(r._buffer) == 1  # kept for retry
    # Backend recovers; next flush delivers it.
    outcome["status"] = 200
    assert r.flush() == 1
    assert len(r._buffer) == 0


def test_flush_requeues_on_connection_error(post_calls):
    _calls, outcome = post_calls
    outcome["raise"] = True
    r = _reporter()
    r.record("Chrome", "app_open")
    assert r.flush() == 0
    assert len(r._buffer) == 1


def test_flush_empty_is_noop(post_calls):
    calls, _ = post_calls
    assert _reporter().flush() == 0
    assert calls == []


def test_flush_without_url_drops(post_calls):
    calls, _ = post_calls
    r = EventReporter("", token=None)
    r.record("Chrome", "app_open")
    assert r.flush() == 0
    assert calls == []
    assert len(r._buffer) == 0


def test_buffer_is_bounded(post_calls):
    r = _reporter(max_buffer=3)
    for i in range(10):
        r.record("Chrome", f"e{i}")
    assert len(r._buffer) == 3
    # deque keeps the most recent on overflow
    assert [e["activity_type"] for e in r._buffer] == ["e7", "e8", "e9"]


def test_stop_flushes_remaining(post_calls):
    calls, _ = post_calls
    r = _reporter()
    r.record("Chrome", "app_open")
    r.stop()  # not started, but stop must still drain
    assert len(calls) == 1
    assert len(r._buffer) == 0
