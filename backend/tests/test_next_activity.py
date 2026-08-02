import json

import pytest

from app.models_store import configure_store, reset_store

DEV = {
    "version": 1,
    "trained_on": "role:developer",
    "counts": {"vscode": {"terminal": 44, "vscode": 12}, "terminal": {"vscode": 23}},
}


@pytest.fixture(autouse=True)
def _clean_store():
    reset_store()
    yield
    reset_store()


def _models(tmp_path):
    (tmp_path / "developer.json").write_text(json.dumps(DEV))
    return tmp_path


def _agent(client, apps=("vscode", "terminal"), role="developer"):
    return client.post(
        "/api/agents/generate",
        json={"name": "A", "role": role, "os_type": "linux", "applications": list(apps)},
    ).json()["agent_id"]


def test_predicts_from_role_model(client, tmp_path):
    configure_store(_models(tmp_path))
    agent_id = _agent(client)
    body = client.get(f"/api/agents/{agent_id}/next-activity?current=vscode").json()
    assert body["next_activity"] == "terminal"
    assert body["source"] == "model"
    assert body["trained_on"] == "role:developer"
    assert body["distribution"]["terminal"] > body["distribution"]["vscode"]


def test_fallback_without_model(client, tmp_path):
    configure_store(tmp_path)
    agent_id = _agent(client)
    body = client.get(f"/api/agents/{agent_id}/next-activity?current=vscode").json()
    assert body["source"] == "fallback"
    assert body["next_activity"] == "vscode"


def test_fallback_for_unknown_state(client, tmp_path):
    configure_store(_models(tmp_path))
    agent_id = _agent(client)
    body = client.get(f"/api/agents/{agent_id}/next-activity?current=gimp").json()
    assert body["source"] == "fallback"


def test_model_trimmed_to_agent_apps(client, tmp_path):
    configure_store(_models(tmp_path))
    agent_id = _agent(client, apps=("vscode",))
    body = client.get(f"/api/agents/{agent_id}/next-activity?current=vscode").json()
    assert body["next_activity"] == "vscode"
    assert "terminal" not in body.get("distribution", {})


def test_sampling_stays_within_distribution(client, tmp_path):
    configure_store(_models(tmp_path))
    agent_id = _agent(client)
    picks = {
        client.get(f"/api/agents/{agent_id}/next-activity?current=vscode&sample=true").json()[
            "next_activity"
        ]
        for _ in range(25)
    }
    assert picks <= {"terminal", "vscode"}


def test_unknown_agent(client, tmp_path):
    configure_store(_models(tmp_path))
    assert client.get("/api/agents/NOPE/next-activity").status_code == 404


def test_ml_status_reports_shared(client, tmp_path):
    (tmp_path / "_shared.json").write_text(json.dumps({"version": 1, "counts": {"a": {"b": 1}}}))
    configure_store(tmp_path)
    body = client.get("/api/ml/status").json()
    assert body["shared_loaded"] is True
    assert body["shared_states"] == 1


def test_ml_reload_picks_up_new_model(client, tmp_path):
    configure_store(tmp_path)
    assert client.get("/api/ml/status").json()["shared_loaded"] is False
    (tmp_path / "_shared.json").write_text(json.dumps({"version": 1, "counts": {"a": {"b": 1}}}))
    assert client.post("/api/ml/reload").json()["reloaded"] is True
