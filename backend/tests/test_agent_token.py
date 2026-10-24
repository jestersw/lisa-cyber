"""Per-agent token authentication (#201).

Each agent is validated against its own token (stored hashed), not a shared
secret. An agent with no token yet (created but never built) stays open, so
dev/test flows need no setup; once an agent has a token, its agent-facing
endpoints require a matching Bearer token.
"""

import app.database as database
from app.models.models import Agent
from app.security import hash_agent_token


def _create_agent(client, name="A1"):
    return client.post(
        "/api/agents/generate",
        json={"name": name, "role": "developer", "os_type": "linux", "applications": ["code"]},
    ).json()["agent_id"]


def _set_token(agent_id: str, plaintext: str) -> None:
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    agent.agent_token = hash_agent_token(plaintext)
    session.commit()
    session.close()


def _bearer(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _heartbeat(client, agent_id, token=None):
    return client.post(
        "/api/agents/heartbeat",
        json={"agent_id": agent_id, "status": "active"},
        headers=_bearer(token),
    )


# ---------- dev mode: an agent without a token is open ----------


def test_heartbeat_open_when_agent_has_no_token(client):
    agent_id = _create_agent(client)
    assert _heartbeat(client, agent_id).status_code == 200


def test_config_open_when_agent_has_no_token(client):
    agent_id = _create_agent(client)
    assert client.get(f"/api/agents/{agent_id}/config").status_code == 200


# ---------- heartbeat (agent id in body, validated in-handler) ----------


def test_heartbeat_requires_matching_token(client):
    agent_id = _create_agent(client)
    _set_token(agent_id, "s3cret-token")
    assert _heartbeat(client, agent_id).status_code == 401  # none
    assert _heartbeat(client, agent_id, "wrong").status_code == 401  # mismatch
    assert _heartbeat(client, agent_id, "s3cret-token").status_code == 200  # match


# ---------- path-based endpoints (validated by require_agent) ----------


def test_next_activity_enforces_agent_token(client):
    agent_id = _create_agent(client)
    _set_token(agent_id, "tok-next")
    assert client.get(f"/api/agents/{agent_id}/next-activity").status_code == 401
    ok = client.get(f"/api/agents/{agent_id}/next-activity", headers=_bearer("tok-next"))
    assert ok.status_code == 200


def test_events_enforce_agent_token(client):
    agent_id = _create_agent(client)
    _set_token(agent_id, "tok-evt")
    body = {"events": []}
    assert client.post(f"/api/agents/{agent_id}/events", json=body).status_code == 401
    ok = client.post(f"/api/agents/{agent_id}/events", json=body, headers=_bearer("tok-evt"))
    assert ok.status_code == 200


def test_config_enforces_agent_token(client):
    agent_id = _create_agent(client)
    _set_token(agent_id, "tok-cfg")
    # No token -> rejected before the handler runs.
    assert client.get(f"/api/agents/{agent_id}/config").status_code == 401


# ---------- tokens are per-agent ----------


def test_token_is_scoped_to_one_agent(client):
    a1 = _create_agent(client, "A1")
    a2 = _create_agent(client, "A2")
    _set_token(a1, "token-a1")
    _set_token(a2, "token-a2")
    # a1's token must not authenticate a2.
    assert _heartbeat(client, a2, "token-a1").status_code == 401
    assert _heartbeat(client, a2, "token-a2").status_code == 200


def test_unknown_agent_is_404(client):
    assert _heartbeat(client, "NOSUCH").status_code == 404
