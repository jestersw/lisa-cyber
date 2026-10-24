"""Backend-driven next-app selection (issue #57): best-effort, always falls back."""

import lisa_agent.nextapp as na
from lisa_agent.nextapp import NextAppClient


class FakeResponse:
    def __init__(self, status_code, payload=None, *, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _client():
    return NextAppClient("http://backend:8000/", "agent-1", token="secret")


def test_model_prediction_is_returned(monkeypatch):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return FakeResponse(200, {"next_activity": "firefox", "source": "model"})

    monkeypatch.setattr(na.requests, "get", fake_get)
    assert _client().fetch("terminal") == "firefox"
    assert seen["url"] == "http://backend:8000/api/agents/agent-1/next-activity"
    assert seen["params"]["current"] == "terminal"
    assert seen["headers"]["Authorization"] == "Bearer secret"


def test_backoff_source_is_trusted(monkeypatch):
    # A global-marginal back-off is still a model-backed, data-driven guess (#51).
    monkeypatch.setattr(
        na.requests,
        "get",
        lambda *a, **k: FakeResponse(200, {"next_activity": "terminal", "source": "backoff"}),
    )
    assert _client().fetch("gimp") == "terminal"


def test_backend_fallback_source_yields_none(monkeypatch):
    # The backend's own static fallback is not trusted; the agent falls back locally.
    monkeypatch.setattr(
        na.requests,
        "get",
        lambda *a, **k: FakeResponse(200, {"next_activity": "firefox", "source": "fallback"}),
    )
    assert _client().fetch("terminal") is None


def test_network_error_yields_none(monkeypatch):
    def boom(*a, **k):
        raise na.requests.RequestException("down")

    monkeypatch.setattr(na.requests, "get", boom)
    assert _client().fetch("terminal") is None


def test_non_200_yields_none(monkeypatch):
    monkeypatch.setattr(na.requests, "get", lambda *a, **k: FakeResponse(503))
    assert _client().fetch(None) is None


def test_bad_json_yields_none(monkeypatch):
    monkeypatch.setattr(na.requests, "get", lambda *a, **k: FakeResponse(200, bad_json=True))
    assert _client().fetch(None) is None


def test_no_current_omits_param(monkeypatch):
    seen = {}

    def fake_get(*a, **k):
        seen.update(k)
        return FakeResponse(200, {"next_activity": "code", "source": "model"})

    monkeypatch.setattr(na.requests, "get", fake_get)
    assert _client().fetch(None) == "code"
    assert "current" not in seen["params"]
