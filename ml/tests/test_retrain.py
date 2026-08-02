import json
from datetime import datetime, timedelta

import pytest

import lisa_ml.retrain as retrain
from lisa_ml.model import MarkovModel
from lisa_ml.retrain import FetchError, fetch_events, retrain_once


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _events_payload(count=60):
    base = datetime(2026, 7, 6, 9, 0)
    apps = ["vscode", "terminal", "firefox"]
    return {
        "events": [
            {
                "agent_id": 1 + (i % 2),
                "app": apps[i % len(apps)],
                "activity_type": "use",
                "timestamp": (base + timedelta(minutes=5 * i)).isoformat(),
                "role": "developer" if i % 2 == 0 else "admin",
            }
            for i in range(count)
        ]
    }


def test_fetch_events_parses(monkeypatch):
    monkeypatch.setattr(
        retrain.urllib.request, "urlopen", lambda *a, **k: FakeResponse(_events_payload(4))
    )
    events = fetch_events("http://backend:8000")
    assert len(events) == 4
    assert events[0].app == "vscode"


def test_fetch_events_raises_on_network(monkeypatch):
    def boom(*args, **kwargs):
        raise retrain.urllib.error.URLError("down")

    monkeypatch.setattr(retrain.urllib.request, "urlopen", boom)
    with pytest.raises(FetchError):
        fetch_events("http://backend:8000")


def test_retrain_once_writes_models(monkeypatch, tmp_path):
    monkeypatch.setattr(
        retrain.urllib.request, "urlopen", lambda *a, **k: FakeResponse(_events_payload(60))
    )
    summary = retrain_once("http://backend:8000", tmp_path, min_events=10)
    assert "_shared" in summary
    shared = MarkovModel.load(tmp_path / "_shared.json")
    assert shared.trained_on == "shared"
    assert shared.counts


def test_retrain_once_tags_roles(monkeypatch, tmp_path):
    monkeypatch.setattr(
        retrain.urllib.request, "urlopen", lambda *a, **k: FakeResponse(_events_payload(60))
    )
    retrain_once("http://backend:8000", tmp_path, min_events=10)
    assert MarkovModel.load(tmp_path / "developer.json").trained_on == "role:developer"


def test_retrain_once_no_events(monkeypatch, tmp_path):
    monkeypatch.setattr(
        retrain.urllib.request, "urlopen", lambda *a, **k: FakeResponse({"events": []})
    )
    assert retrain_once("http://backend:8000", tmp_path) == {}
    assert list(tmp_path.iterdir()) == []
