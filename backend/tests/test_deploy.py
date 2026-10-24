import pytest

import app.database as database
from app.models.models import Agent
from app.services.deploy import ansible
from app.services.deploy.ansible import extra_vars


def test_extra_vars_includes_download_token_when_set():
    args = extra_vars("http://b:8000", force=False, download_token="tok123")
    assert "lisa_agent_download_token=tok123" in args
    assert "lisa_agent_backend_url=http://b:8000" in args


def test_extra_vars_omits_token_when_none_and_handles_force():
    args = extra_vars("http://b:8000", force=True, download_token=None)
    assert "lisa_agent_force_reinstall=true" in args
    assert not any("download_token" in a for a in args)


def _built_agent(client, os_type: str = "linux") -> str:
    """Create an agent and mark it as built (installer present)."""
    agent_id = client.post(
        "/api/agents/generate",
        json={"name": "D1", "role": "developer", "os_type": os_type, "applications": ["code"]},
    ).json()["agent_id"]
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    agent.installer_url = f"/api/builds/{agent_id}/installer_{agent_id}.sh"
    agent.os_type = os_type
    session.commit()
    session.close()
    return agent_id


@pytest.fixture
def ansible_ok(monkeypatch):
    """Pretend ansible is installed and the playbook succeeds."""
    calls = {}

    def fake_run(inventory_text, *, backend_url, force=False, download_token=None, **_):
        calls["inventory"] = inventory_text
        calls["backend_url"] = backend_url
        calls["force"] = force
        calls["download_token"] = download_token
        return 0, "PLAY RECAP\nweb01 : ok=3 changed=1 failed=0"

    monkeypatch.setattr(ansible, "ansible_available", lambda: True)
    monkeypatch.setattr(ansible, "run_playbook", fake_run)
    return calls


# ---------- happy path ----------


def test_deploy_runs_and_succeeds(client, ansible_ok):
    agent_id = _built_agent(client)
    resp = client.post(
        f"/api/agents/{agent_id}/deploy",
        json={"targets": [{"host": "web01.corp.local"}], "force": True},
    )
    assert resp.status_code == 200
    dep_id = resp.json()["id"]

    # Background task has run by the time TestClient returns; it is now terminal.
    detail = client.get(f"/api/deployments/{dep_id}").json()
    assert detail["status"] == "succeeded"
    assert detail["returncode"] == 0
    assert "PLAY RECAP" in detail["output"]
    # The agent id reached the rendered inventory, and force was passed through.
    assert f"lisa_agent_id={agent_id}" in ansible_ok["inventory"]
    assert ansible_ok["force"] is True


def test_deploy_no_token_in_dev_mode(client, ansible_ok):
    # Operator password is unset in tests (dev); downloads are open, so no
    # token is minted or passed to the playbook.
    agent_id = _built_agent(client)
    client.post(f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]})
    assert ansible_ok["download_token"] is None


def test_deploy_uses_public_base_url_by_default(client, ansible_ok):
    agent_id = _built_agent(client)
    client.post(
        f"/api/agents/{agent_id}/deploy",
        json={"targets": [{"host": "web01"}]},
    )
    assert ansible_ok["backend_url"].startswith("http")


def test_deploy_backend_url_override(client, ansible_ok):
    agent_id = _built_agent(client)
    client.post(
        f"/api/agents/{agent_id}/deploy",
        json={"targets": [{"host": "web01"}], "backend_url": "https://range.corp.local"},
    )
    assert ansible_ok["backend_url"] == "https://range.corp.local"


def test_list_deployments(client, ansible_ok):
    agent_id = _built_agent(client)
    client.post(f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]})
    client.post(f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h2"}]})
    items = client.get(f"/api/agents/{agent_id}/deployments").json()
    assert len(items) == 2
    assert all(d["agent_id"] == agent_id for d in items)


# ---------- failure / degradation ----------


def test_deploy_failed_returncode(client, monkeypatch):
    monkeypatch.setattr(ansible, "ansible_available", lambda: True)
    monkeypatch.setattr(ansible, "run_playbook", lambda *a, **k: (2, "fatal: unreachable"))
    agent_id = _built_agent(client)
    dep_id = client.post(
        f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]}
    ).json()["id"]
    detail = client.get(f"/api/deployments/{dep_id}").json()
    assert detail["status"] == "failed"
    assert detail["returncode"] == 2


def test_deploy_unavailable_when_no_ansible(client, monkeypatch):
    monkeypatch.setattr(ansible, "ansible_available", lambda: False)
    agent_id = _built_agent(client)
    dep_id = client.post(
        f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]}
    ).json()["id"]
    detail = client.get(f"/api/deployments/{dep_id}").json()
    assert detail["status"] == "unavailable"
    assert "ansible-playbook" in detail["error"]


# ---------- guards ----------


def test_deploy_unknown_agent_404(client):
    resp = client.post("/api/agents/USR999/deploy", json={"targets": [{"host": "h1"}]})
    assert resp.status_code == 404


def test_deploy_unbuilt_agent_409(client):
    agent_id = client.post(
        "/api/agents/generate",
        json={"name": "NB", "role": "developer", "os_type": "linux", "applications": ["code"]},
    ).json()["agent_id"]
    resp = client.post(f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]})
    assert resp.status_code == 409


def test_deploy_unsupported_os_400(client, ansible_ok):
    agent_id = _built_agent(client, os_type="windows")
    resp = client.post(f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1"}]})
    assert resp.status_code == 400


def test_deploy_rejects_bad_host(client, ansible_ok):
    agent_id = _built_agent(client)
    resp = client.post(
        f"/api/agents/{agent_id}/deploy", json={"targets": [{"host": "h1; rm -rf /"}]}
    )
    assert resp.status_code == 422  # schema rejects it before the endpoint


def test_deploy_requires_at_least_one_target(client, ansible_ok):
    agent_id = _built_agent(client)
    resp = client.post(f"/api/agents/{agent_id}/deploy", json={"targets": []})
    assert resp.status_code == 422
