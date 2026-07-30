from datetime import datetime

import lisa_agent.heartbeat as hb
from lisa_agent.heartbeat import HeartbeatLoop, HeartbeatSender, build_payload


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_build_payload_shape():
    p = build_payload("agent-1", "working", current_app="firefox", statistics={"x": 1})
    assert p["agent_id"] == "agent-1"
    assert p["status"] == "working"
    assert p["current_activity"]["application"] == "firefox"
    assert p["statistics"] == {"x": 1}
    assert "hostname" in p["system_info"]
    # timestamp must be ISO-parseable
    datetime.fromisoformat(p["timestamp"])


def test_send_success(monkeypatch):
    calls = {}

    def fake_post(url, json, headers, timeout):
        calls["url"] = url
        calls["headers"] = headers
        return FakeResponse(200)

    monkeypatch.setattr(hb.requests, "post", fake_post)
    sender = HeartbeatSender("http://backend/hb", token="secret")
    assert sender.send({"a": 1}) is True
    assert calls["url"] == "http://backend/hb"
    assert calls["headers"]["Authorization"] == "Bearer secret"


def test_no_auth_header_without_token(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen["headers"] = headers
        return FakeResponse(200)

    monkeypatch.setattr(hb.requests, "post", fake_post)
    sender = HeartbeatSender("http://backend/hb")  # no token
    sender.send({"a": 1})
    assert "Authorization" not in seen["headers"]


def test_send_retries_then_fails(monkeypatch):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        return FakeResponse(500)

    monkeypatch.setattr(hb.requests, "post", fake_post)
    sender = HeartbeatSender("http://backend/hb", retry_count=3, retry_delay=0)
    # inject a no-op sleep so the test doesn't wait
    assert sender.send({"a": 1}, sleep=lambda _s: None) is False
    assert attempts["n"] == 3


def test_send_stops_after_first_success(monkeypatch):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        return FakeResponse(200)

    monkeypatch.setattr(hb.requests, "post", fake_post)
    sender = HeartbeatSender("http://backend/hb", retry_count=3)
    assert sender.send({"a": 1}, sleep=lambda _s: None) is True
    assert attempts["n"] == 1


def test_send_on_network_error(monkeypatch):
    def fake_post(url, json, headers, timeout):
        raise hb.requests.ConnectionError("boom")

    monkeypatch.setattr(hb.requests, "post", fake_post)
    sender = HeartbeatSender("http://backend/hb", retry_count=2, retry_delay=0)
    assert sender.send({"a": 1}, sleep=lambda _s: None) is False


def test_empty_url_skips():
    sender = HeartbeatSender("")
    assert sender.send({"a": 1}) is False


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, payload, sleep=None):
        self.sent.append(payload)
        return True


def test_loop_force_calls_provider_and_sender():
    fake = FakeSender()
    loop = HeartbeatLoop(fake, lambda: {"tick": 1}, interval_seconds=100)
    assert loop.force() is True
    assert fake.sent == [{"tick": 1}]
    assert loop.last_heartbeat is not None


def test_loop_start_stop_sends_at_least_once():
    fake = FakeSender()
    # tiny interval; start, let it fire, stop
    loop = HeartbeatLoop(fake, lambda: {"tick": 1}, interval_seconds=0.05)
    loop.start()
    import time

    time.sleep(0.15)
    loop.stop()
    assert len(fake.sent) >= 1
