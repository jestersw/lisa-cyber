def _make_role(client, name="Junior Dev"):
    return client.post(
        "/api/roles", json={"name": name, "description": "d", "category": "Development"}
    )


def test_role_crud(client):
    r = _make_role(client)
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get(f"/api/roles/{rid}").json()["name"] == "Junior Dev"
    # duplicate name rejected
    assert _make_role(client).status_code == 400
    assert client.get("/api/roles").json()[0]["id"] == rid


def test_template_requires_role(client):
    bad = client.post(
        "/api/behavior-templates",
        json={"name": "t", "role_id": 999, "template_data": {}, "os_type": "linux"},
    )
    assert bad.status_code == 404


def test_full_agent_flow(client):
    rid = _make_role(client).json()["id"]
    t = client.post(
        "/api/behavior-templates",
        json={
            "name": "Dev behavior",
            "role_id": rid,
            "template_data": {"applications_used": ["code", "firefox"]},
            "os_type": "linux",
        },
    )
    assert t.status_code == 200
    tid = t.json()["id"]

    gen = client.post(
        "/api/agents/generate",
        json={"name": "A1", "role_id": rid, "template_id": tid, "os_type": "linux"},
    )
    assert gen.status_code == 200
    agent_id = gen.json()["agent_id"]

    # agent fetches its config over HTTP (no DB access on the agent side)
    cfg = client.get(f"/api/agents/{agent_id}/config")
    assert cfg.status_code == 200
    assert cfg.json()["agent_config"]["applications"] == ["code", "firefox"]

    # os mismatch is rejected
    bad = client.post(
        "/api/agents/generate",
        json={"name": "A2", "role_id": rid, "template_id": tid, "os_type": "macos"},
    )
    assert bad.status_code == 400


def test_heartbeat_updates_known_agent(client):
    rid = _make_role(client).json()["id"]
    tid = client.post(
        "/api/behavior-templates",
        json={
            "name": "Dev behavior",
            "role_id": rid,
            "template_data": {"applications_used": ["code"]},
            "os_type": "linux",
        },
    ).json()["id"]
    agent_id = client.post(
        "/api/agents/generate",
        json={"name": "A1", "role_id": rid, "template_id": tid, "os_type": "linux"},
    ).json()["agent_id"]

    payload = {
        "agent_id": agent_id,
        "status": "active",
        "system_info": {"hostname": "vm1", "platform": "Linux-6"},
        "current_activity": {"application": "firefox"},
        "version": "1.0.0",
    }
    hb = client.post("/api/agents/heartbeat", json=payload)
    assert hb.status_code == 200
    assert hb.json()["status"] == "received"

    listed = client.get("/api/agents").json()
    match = [a for a in listed if a["agent_id"] == agent_id]
    assert match and match[0]["status"] == "active"


def test_heartbeat_unknown_agent_is_rejected(client):
    payload = {
        "agent_id": "USR0000404",
        "status": "active",
        "system_info": {"hostname": "ghost", "platform": "Linux-6"},
    }
    resp = client.post("/api/agents/heartbeat", json=payload)
    assert resp.status_code == 404
    assert client.get("/api/agents").json() == []
