import app.database as database
from app.models.models import Agent


def _create_agent(client):
    return client.post(
        "/api/agents/generate",
        json={"name": "S1", "role": "developer", "os_type": "linux", "applications": ["code"]},
    ).json()["agent_id"]


def test_status_exposes_binary_and_installer_url(client):
    agent_id = _create_agent(client)

    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    agent.binary_url = f"/api/builds/{agent_id}/agent"
    agent.installer_url = f"/api/builds/{agent_id}/installer"
    session.commit()
    session.close()

    body = client.get(f"/api/agents/{agent_id}/status").json()["agent"]
    assert body["binary_url"] == f"/api/builds/{agent_id}/agent"
    assert body["installer_url"] == f"/api/builds/{agent_id}/installer"


def test_status_urls_null_before_build(client):
    agent_id = _create_agent(client)
    body = client.get(f"/api/agents/{agent_id}/status").json()["agent"]
    assert body["binary_url"] is None
    assert body["installer_url"] is None
