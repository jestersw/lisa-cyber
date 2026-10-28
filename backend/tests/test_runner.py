import time

import app.database as database
import app.services.sim_runner as sim
from app.api.endpoints.runner import _build_apps
from app.models.models import Agent
from app.services.sim_runner import _activity_descriptor

# ---------- pure: activity classification ----------


def test_activity_descriptor_precedence():
    net = {"name": "browse", "commands": [{"type": "http_request", "url": "http://wiki"}]}
    assert _activity_descriptor(net) == {
        "category": "network",
        "detail": "http://wiki",
        "name": "browse",
    }

    host = {"name": "dns", "commands": [{"type": "dns_lookup", "host": "db", "port": 53}]}
    assert _activity_descriptor(host) == {"category": "network", "detail": "db:53", "name": "dns"}

    f = {"name": "save", "commands": [{"type": "file_rename", "target": "a", "dest": "b"}]}
    assert _activity_descriptor(f) == {"category": "file", "detail": "a -> b", "name": "save"}

    inp = {"name": "type", "commands": [{"type": "type_text", "text": "hi"}]}
    assert _activity_descriptor(inp) == {"category": "input", "detail": None, "name": "type"}

    proc = {"name": "run", "commands": [{"type": "weird"}]}
    assert _activity_descriptor(proc) == {"category": "process", "detail": None, "name": "run"}


# ---------- helpers ----------


def _agent_with_apps(client, apps=("code",)):
    return client.post(
        "/api/agents/generate",
        json={"name": "R1", "role": "developer", "os_type": "linux", "applications": list(apps)},
    ).json()["agent_id"]


# ---------- _build_apps ----------


def test_build_apps_uses_plugin_activities(client):
    # A plugin with a network activity should surface as a network descriptor.
    client.post(
        "/api/application-templates",
        json={
            "name": "browser",
            "os_type": "linux",
            "template_config": {
                "app_info": {"name": "browser"},
                "activities": [
                    {"name": "visit", "commands": [{"type": "http_request", "url": "http://x"}]}
                ],
            },
        },
    )
    agent_id = _agent_with_apps(client, apps=["browser"])
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    apps = _build_apps(session, agent)
    session.close()
    assert len(apps) == 1
    assert apps[0]["name"] == "browser"
    assert apps[0]["activities"][0]["category"] == "network"


def test_build_apps_defaults_when_no_plugin(client):
    agent_id = _agent_with_apps(client, apps=["ghost"])
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    apps = _build_apps(session, agent)
    session.close()
    assert apps == [
        {"name": "ghost", "activities": [{"category": "process", "detail": None, "name": "work"}]}
    ]


# ---------- run lifecycle (loop stubbed so it doesn't touch the DB) ----------


def _stub_loop(monkeypatch):
    # Replace the work loop with one that just idles until stopped.
    monkeypatch.setattr(sim.SimRegistry, "_loop", lambda self, *a: a[-1].wait())


def test_run_start_status_stop(client, monkeypatch):
    _stub_loop(monkeypatch)
    agent_id = _agent_with_apps(client)

    start = client.post(f"/api/agents/{agent_id}/run")
    assert start.status_code == 200
    assert start.json()["running"] is True

    assert client.get(f"/api/agents/{agent_id}/run").json()["running"] is True

    # Starting again while active is a conflict.
    assert client.post(f"/api/agents/{agent_id}/run").status_code == 409

    stop = client.post(f"/api/agents/{agent_id}/run/stop")
    assert stop.status_code == 200
    assert stop.json()["running"] is False
    assert client.get(f"/api/agents/{agent_id}/run").json()["running"] is False


def test_run_unknown_agent_404(client, monkeypatch):
    _stub_loop(monkeypatch)
    assert client.post("/api/agents/NOPE/run").status_code == 404
    assert client.get("/api/agents/NOPE/run").status_code == 404


def test_run_no_applications_409(client, monkeypatch):
    _stub_loop(monkeypatch)
    agent_id = _agent_with_apps(client, apps=[])
    assert client.post(f"/api/agents/{agent_id}/run").status_code == 409


def test_run_real_loop_emits_events(client):
    # The real loop (not stubbed) must write activity events the live view reads.
    agent_id = _agent_with_apps(client, apps=["code"])
    assert client.post(f"/api/agents/{agent_id}/run").status_code == 200
    try:
        events: list = []
        for _ in range(40):  # up to ~4s for the first events to land
            events = client.get("/api/live/events").json()["events"]
            if events:
                break
            time.sleep(0.1)
        assert events, "demo run produced no events"
        assert any(e["activity_type"] == "app_open" for e in events)
        assert all(e["agent_id"] == agent_id for e in events)
    finally:
        client.post(f"/api/agents/{agent_id}/run/stop")
