import json
from datetime import UTC, datetime, timedelta

import app.database as database
from app.llm import configure_provider
from app.models.models import Agent


def _agent(client, apps=None):
    return client.post(
        "/api/agents/generate",
        json={
            "name": "Dx",
            "role": "developer",
            "os_type": "linux",
            "applications": apps if apps is not None else ["code"],
        },
    ).json()["agent_id"]


def _patch_agent(agent_id, **fields):
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    for key, value in fields.items():
        setattr(agent, key, value)
    session.commit()
    session.close()


class _FakeProvider:
    def __init__(self, payload: str):
        self.payload = payload

    def generate(self, prompt):
        return self.payload


# ---------- guards ----------


def test_diagnose_unknown_agent_404(client):
    assert client.post("/api/agents/USR999/diagnose").status_code == 404


# ---------- fallback path (LLM offline via autouse fixture) ----------


def test_diagnose_fallback_includes_signals(client):
    agent_id = _agent(client)
    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["source"] == "unavailable"
    assert body["signals"]["agent_id"] == agent_id
    assert "heartbeat_interval_seconds" in body["signals"]


def test_diagnose_flags_missing_plugin(client):
    agent_id = _agent(client, apps=["obscure-app"])
    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["signals"]["applications_without_plugin"] == ["obscure-app"]
    assert any("no plugin" in f["issue"] for f in body["findings"])


def test_diagnose_flags_build_failure(client):
    agent_id = _agent(client)
    _patch_agent(
        agent_id,
        status="failed",
        version_info={"last_build_error": "xcrun: error: unable to find utility"},
    )
    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["signals"]["build_error"].startswith("xcrun")
    assert any("build failed" in f["issue"].lower() for f in body["findings"])


def test_diagnose_flags_stale_agent(client):
    agent_id = _agent(client)
    _patch_agent(agent_id, status="active", last_seen=datetime.now(UTC) - timedelta(hours=6))
    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["signals"]["seconds_since_last_seen"] is not None
    assert any("stale" in f["issue"].lower() for f in body["findings"])


# ---------- model path ----------


def test_diagnose_uses_model_when_available(client):
    agent_id = _agent(client)
    payload = json.dumps(
        {
            "summary": "The slack plugin won't launch.",
            "findings": [
                {"issue": "open_command points at a missing binary", "severity": "critical"}
            ],
            "suggested_changes": [
                {"target": "slack plugin open_command", "change": "set it to /usr/bin/slack"}
            ],
        }
    )
    configure_provider(_FakeProvider(payload))

    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["source"] == "model"
    assert body["summary"] == "The slack plugin won't launch."
    assert body["findings"][0]["severity"] == "critical"
    assert body["suggested_changes"][0]["target"] == "slack plugin open_command"
    # Signals are still attached for grounding in the panel.
    assert body["signals"]["agent_id"] == agent_id


def test_diagnose_invalid_model_json_falls_back(client):
    agent_id = _agent(client)
    configure_provider(_FakeProvider("not json at all"))
    body = client.post(f"/api/agents/{agent_id}/diagnose").json()
    assert body["source"] == "unavailable"
