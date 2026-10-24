"""Install-time enrollment endpoint (#201 part B).

A built agent carries a one-time enrollment token; it exchanges it for its real
token via POST /api/agents/{id}/enroll, once.
"""

import app.database as database
from app.models.models import Agent
from app.security import agent_token_matches, hash_agent_token


def _create_agent(client, name="E1"):
    return client.post(
        "/api/agents/generate",
        json={"name": name, "role": "developer", "os_type": "linux", "applications": ["code"]},
    ).json()["agent_id"]


def _arm_enrollment(agent_id: str, enrollment_plain: str) -> None:
    """Put an agent in the built-but-not-enrolled state the worker leaves."""
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    agent.enrollment_token_hash = hash_agent_token(enrollment_plain)
    agent.enrolled = False
    agent.agent_token = None
    session.commit()
    session.close()


def _agent_state(agent_id: str) -> dict:
    session = database._SessionLocal()
    agent = session.query(Agent).filter(Agent.agent_id == agent_id).first()
    state = {
        "enrolled": agent.enrolled,
        "agent_token": agent.agent_token,
        "enrollment_token_hash": agent.enrollment_token_hash,
    }
    session.close()
    return state


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _enroll(client, agent_id, token):
    return client.post(f"/api/agents/{agent_id}/enroll", headers=_bearer(token))


def _heartbeat(client, agent_id, token):
    return client.post(
        "/api/agents/heartbeat",
        json={"agent_id": agent_id, "status": "active"},
        headers=_bearer(token),
    )


def test_enroll_exchanges_enrollment_token_for_real_token(client):
    agent_id = _create_agent(client)
    _arm_enrollment(agent_id, "enroll-tok")

    resp = _enroll(client, agent_id, "enroll-tok")
    assert resp.status_code == 200
    real = resp.json()["token"]
    assert real

    state = _agent_state(agent_id)
    assert state["enrolled"] is True
    assert state["enrollment_token_hash"] is None  # consumed
    # The stored real-token hash matches the token handed back.
    assert agent_token_matches(f"Bearer {real}", state["agent_token"])


def test_enroll_is_single_use(client):
    agent_id = _create_agent(client)
    _arm_enrollment(agent_id, "enroll-tok")
    assert _enroll(client, agent_id, "enroll-tok").status_code == 200
    # Second attempt (even with the same token) is rejected — rebuild to re-enroll.
    assert _enroll(client, agent_id, "enroll-tok").status_code == 409


def test_enroll_rejects_wrong_token(client):
    agent_id = _create_agent(client)
    _arm_enrollment(agent_id, "enroll-tok")
    assert _enroll(client, agent_id, "wrong").status_code == 401
    assert client.post(f"/api/agents/{agent_id}/enroll").status_code == 401  # no token


def test_enroll_unknown_agent_404(client):
    assert _enroll(client, "NOSUCH", "x").status_code == 404


def test_enroll_rejects_agent_without_pending_enrollment(client):
    # A dev agent that was never built has no enrollment token to exchange.
    agent_id = _create_agent(client)
    assert _enroll(client, agent_id, "x").status_code == 409


def test_unenrolled_agent_cannot_heartbeat_until_enrolled(client):
    agent_id = _create_agent(client)
    _arm_enrollment(agent_id, "enroll-tok")

    # Built but not enrolled: the enrollment token is not a valid agent token.
    assert _heartbeat(client, agent_id, "enroll-tok").status_code == 401

    real = _enroll(client, agent_id, "enroll-tok").json()["token"]

    # Now the real token works, and the (consumed) enrollment token does not.
    assert _heartbeat(client, agent_id, real).status_code == 200
    assert _heartbeat(client, agent_id, "enroll-tok").status_code == 401
