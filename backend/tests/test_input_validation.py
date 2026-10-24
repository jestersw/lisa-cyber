"""Input validation on backend endpoints (#53).

Bodies are already Pydantic-validated and queries go through the ORM; these tests
cover the gaps closed here — bounded pagination/filter query params and a length
cap on request-body strings — so out-of-range or oversized input is rejected with
422 rather than reaching the handler.
"""

from app.schemas import MAX_STR_LEN

# ---------- query parameter bounds ----------


def test_list_roles_rejects_out_of_range_limit(client):
    assert client.get("/api/roles?limit=0").status_code == 422
    assert client.get("/api/roles?limit=100000").status_code == 422
    assert client.get("/api/roles?skip=-1").status_code == 422
    # A normal request still works.
    assert client.get("/api/roles?limit=50&skip=0").status_code == 200


def test_list_templates_rejects_bad_limit(client):
    assert client.get("/api/behavior-templates?limit=0").status_code == 422
    assert client.get("/api/behavior-templates?limit=5001").status_code == 422
    assert client.get("/api/behavior-templates").status_code == 200


def test_list_applications_rejects_bad_limit(client):
    assert client.get("/api/application-templates?limit=-1").status_code == 422
    assert client.get("/api/application-templates").status_code == 200


def test_active_agents_threshold_is_bounded(client):
    assert client.get("/api/agents-active?threshold_minutes=0").status_code == 422
    assert client.get("/api/agents-active?threshold_minutes=999999").status_code == 422
    assert client.get("/api/agents-active?threshold_minutes=30").status_code == 200


def test_heartbeats_limit_is_bounded(client):
    # The bad query is rejected before the handler, so no agent need exist.
    assert client.get("/api/agents/ANY/heartbeats?limit=0").status_code == 422
    assert client.get("/api/agents/ANY/heartbeats?limit=100000").status_code == 422


# ---------- request-body string length cap ----------


def test_role_create_rejects_oversized_string(client):
    huge = "x" * (MAX_STR_LEN + 1)
    resp = client.post(
        "/api/roles",
        json={"name": huge, "description": "d", "category": "c"},
    )
    assert resp.status_code == 422


def test_role_create_accepts_normal_string(client):
    resp = client.post(
        "/api/roles",
        json={"name": "developer-x", "description": "d", "category": "eng"},
    )
    assert resp.status_code == 200


def test_heartbeat_rejects_oversized_status(client):
    huge = "x" * (MAX_STR_LEN + 1)
    resp = client.post("/api/agents/heartbeat", json={"agent_id": "A", "status": huge})
    assert resp.status_code == 422
