import random

from app.defaults import build_agent_config, default_schedule


def test_default_schedule_ranges():
    sched = default_schedule(random.Random(0))
    assert sched["workdays"] == [1, 2, 3, 4, 5]
    assert "08:00" <= sched["work_start"] <= "10:00"
    assert "17:00" <= sched["work_end"] <= "19:00"
    assert sched["lunch"]["min_minutes"] == 45


def test_build_agent_config_shape():
    cfg = build_agent_config("USR1", "John", "developer", "linux", ["code"], rng=random.Random(1))
    assert cfg["agent_info"] == {
        "agent_id": "USR1",
        "name": "John",
        "role": "developer",
        "os_type": "linux",
    }
    assert cfg["heartbeat"]["interval_minutes"] == 30
    assert cfg["applications"] == ["code"]
    assert "session_duration" in cfg["behavior"]


def test_build_agent_config_overrides():
    cfg = build_agent_config(
        "USR1", "J", "admin", "windows", ["x"],
        overrides={"heartbeat_interval_minutes": 5, "schedule": {"custom": True}},
    )
    assert cfg["heartbeat"]["interval_minutes"] == 5
    assert cfg["schedule"] == {"custom": True}


def _setup(client, apps):
    r = client.post(
        "/api/roles", json={"name": "developer", "description": "d", "category": "Development"}
    ).json()
    t = client.post(
        "/api/behavior-templates",
        json={
            "name": "b",
            "role_id": r["id"],
            "template_data": {"applications_used": apps},
            "os_type": "linux",
        },
    ).json()
    return r["id"], t["id"]


def test_generate_stores_and_config_returns_package(client):
    rid, tid = _setup(client, ["code", "firefox"])
    client.post(
        "/api/application-templates",
        json={
            "name": "code",
            "template_config": {
                "app_info": {"name": "code"},
                "execution": {"open_command": "code"},
            },
            "os_type": "linux",
        },
    )
    agent_id = client.post(
        "/api/agents/generate",
        json={"name": "A1", "role_id": rid, "template_id": tid, "os_type": "linux"},
    ).json()["agent_id"]

    pkg = client.get(f"/api/agents/{agent_id}/config")
    assert pkg.status_code == 200
    body = pkg.json()

    ac = body["agent_config"]
    assert ac["agent_info"]["agent_id"] == agent_id
    assert ac["agent_info"]["role"] == "developer"
    assert ac["applications"] == ["code", "firefox"]
    assert set(ac.keys()) == {"agent_info", "schedule", "behavior", "heartbeat", "applications"}

    assert "code" in body["application_plugins"]
    assert "firefox" not in body["application_plugins"]


def test_generate_accepts_windows(client):
    r = client.post(
        "/api/roles", json={"name": "admin", "description": "d", "category": "Ops"}
    ).json()
    t = client.post(
        "/api/behavior-templates",
        json={"name": "w", "role_id": r["id"], "template_data": {}, "os_type": "windows"},
    ).json()
    resp = client.post(
        "/api/agents/generate",
        json={"name": "W1", "role_id": r["id"], "template_id": t["id"], "os_type": "windows"},
    )
    assert resp.status_code == 200
