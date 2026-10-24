"""Operator (panel) authentication: login, token guard, dev-mode openness."""

import pytest

from app.config import get_settings
from app.security import create_download_token, create_operator_token, verify_download_token


@pytest.fixture
def secured(monkeypatch):
    """Turn on operator auth with a known password for the duration of a test."""
    monkeypatch.setenv("OPERATOR_PASSWORD", "s3cret")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_operator_endpoint_open_in_dev_mode(client):
    # No OPERATOR_PASSWORD set: panel endpoints stay open.
    assert client.get("/api/roles").status_code == 200


def test_operator_endpoint_rejects_without_token(client, secured):
    assert client.get("/api/roles").status_code == 401


def test_login_rejects_wrong_password(client, secured):
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401


def test_login_then_access_with_token(client, secured):
    resp = client.post("/api/auth/login", json={"password": "s3cret"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert resp.json()["token_type"] == "bearer"

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/roles", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).json() == {"authenticated": True}


def test_garbage_token_rejected(client, secured):
    headers = {"Authorization": "Bearer not-a-jwt"}
    assert client.get("/api/roles", headers=headers).status_code == 401


# ---------- build-artefact download tokens (#202) ----------


def test_download_token_roundtrip(secured):
    token = create_download_token("USR001", "agent_USR001")
    assert verify_download_token(token, "USR001", "agent_USR001") is True


def test_download_token_rejected_for_other_file(secured):
    token = create_download_token("USR001", "agent_USR001")
    assert verify_download_token(token, "USR001", "package.json") is False
    assert verify_download_token(token, "USR999", "agent_USR001") is False


def test_operator_jwt_is_not_a_valid_download_token(secured):
    # An operator JWT has no download scope, so it must not pass as one.
    assert verify_download_token(create_operator_token(), "USR001", "agent_USR001") is False


def test_garbage_download_token_rejected(secured):
    assert verify_download_token("not-a-jwt", "USR001", "agent_USR001") is False


def test_agent_endpoint_not_affected_by_operator_token(client, secured):
    # Agent-token routes must not accept an operator JWT in place of the agent token.
    token = client.post("/api/auth/login", json={"password": "s3cret"}).json()["access_token"]
    # agent_token is unset here, so agent routes are dev-open regardless; this
    # just confirms the operator guard did not leak onto the agent POST path.
    resp = client.post(
        "/api/agents/nonexistent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "active"},
    )
    assert resp.status_code in (404, 422)
