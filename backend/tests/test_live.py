def _agent(client, name="A1", role_name="Dev"):
    r = client.post(
        "/api/roles", json={"name": role_name, "description": "d", "category": "Development"}
    ).json()
    t = client.post(
        "/api/behavior-templates",
        json={"name": f"b-{name}", "role_id": r["id"], "template_data": {}, "os_type": "linux"},
    ).json()
    return client.post(
        "/api/agents/generate",
        json={"name": name, "role_id": r["id"], "template_id": t["id"], "os_type": "linux"},
    ).json()["agent_id"]


def _event(app, activity_type, ts, **kw):
    return {"app": app, "activity_type": activity_type, "timestamp": ts, **kw}


# ---------- fleet ----------


def test_fleet_lists_agents_with_role_and_current_app(client):
    agent_id = _agent(client, name="Fleet1", role_name="Analyst")
    # A heartbeat sets the current app + last_seen the grid shows.
    client.post(
        "/api/agents/heartbeat",
        json={
            "agent_id": agent_id,
            "status": "active",
            "current_activity": {"application": "code"},
        },
    )
    fleet = client.get("/api/live/fleet").json()["agents"]
    row = next(a for a in fleet if a["agent_id"] == agent_id)
    assert row["name"] == "Fleet1"
    assert row["role"] == "Analyst"
    assert row["os_type"] == "linux"
    assert row["current_app"] == "code"
    assert row["last_seen"] is not None


def test_fleet_empty_when_no_agents(client):
    assert client.get("/api/live/fleet").json() == {"agents": []}


# ---------- events feed ----------


def test_events_newest_first_with_ids(client):
    agent_id = _agent(client)
    client.post(
        f"/api/agents/{agent_id}/events",
        json={
            "events": [
                _event("firefox", "app_open", "2026-07-27T10:00:00"),
                _event("firefox", "network", "2026-07-27T10:01:00", context={"detail": "wiki"}),
            ]
        },
    )
    body = client.get("/api/live/events").json()
    apps = [(e["app"], e["activity_type"]) for e in body["events"]]
    # newest first
    assert apps[0] == ("firefox", "network")
    assert apps[1] == ("firefox", "app_open")
    # enriched with the public agent id + name from the join
    assert body["events"][0]["agent_id"] == agent_id
    assert body["events"][0]["name"] is not None
    assert body["latest_id"] == max(e["id"] for e in body["events"])


def test_events_after_cursor_returns_only_newer(client):
    agent_id = _agent(client)
    client.post(
        f"/api/agents/{agent_id}/events",
        json={"events": [_event("a", "app_open", "2026-07-27T10:00:00")]},
    )
    first = client.get("/api/live/events").json()
    cursor = first["latest_id"]

    # Nothing newer yet.
    assert client.get(f"/api/live/events?after={cursor}").json()["events"] == []

    client.post(
        f"/api/agents/{agent_id}/events",
        json={"events": [_event("b", "network", "2026-07-27T10:05:00")]},
    )
    newer = client.get(f"/api/live/events?after={cursor}").json()
    assert [e["app"] for e in newer["events"]] == ["b"]
    assert newer["latest_id"] > cursor


def test_events_limit_is_bounded(client):
    assert client.get("/api/live/events?limit=0").status_code == 422
    assert client.get("/api/live/events?limit=9999").status_code == 422


def test_events_empty_feed_echoes_cursor(client):
    body = client.get("/api/live/events?after=5").json()
    assert body["events"] == []
    assert body["latest_id"] == 5
