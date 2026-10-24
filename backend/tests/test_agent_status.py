from urllib.parse import parse_qs, urlparse

import app.database as database
from app.config import get_settings
from app.models.models import Agent
from app.security import create_operator_token, verify_download_token


def _create_agent(client, headers=None):
    return client.post(
        "/api/agents/generate",
        json={"name": "S1", "role": "developer", "os_type": "linux", "applications": ["code"]},
        headers=headers or {},
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


def test_status_urls_are_tokenized_when_secured(client, monkeypatch):
    # With operator auth on, the panel's download URLs carry a short-lived,
    # single-file download token (#202) so the browser link can authenticate.
    monkeypatch.setenv("OPERATOR_PASSWORD", "s3cret")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    get_settings.cache_clear()
    try:
        headers = {"Authorization": f"Bearer {create_operator_token()}"}
        agent_id = _create_agent(client, headers=headers)
        installer_name = f"installer_{agent_id}.sh"

        session = database._SessionLocal()
        agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
        agent.installer_url = f"/api/builds/{agent_id}/{installer_name}"
        session.commit()
        session.close()

        url = client.get(f"/api/agents/{agent_id}/status", headers=headers).json()["agent"][
            "installer_url"
        ]
        assert url.startswith(f"/api/builds/{agent_id}/{installer_name}?token=")
        token = parse_qs(urlparse(url).query)["token"][0]
        assert verify_download_token(token, agent_id, installer_name)
    finally:
        get_settings.cache_clear()
