def _agent(client):
    r = client.post(
        "/api/roles", json={"name": "Dev", "description": "d", "category": "Development"}
    ).json()
    t = client.post(
        "/api/behavior-templates",
        json={"name": "b", "role_id": r["id"], "template_data": {}, "os_type": "linux"},
    ).json()
    return client.post(
        "/api/agents/generate",
        json={"name": "A1", "role_id": r["id"], "template_id": t["id"], "os_type": "linux"},
    ).json()["agent_id"]


def test_ingest_and_export_events(client):
    agent_id = _agent(client)
    batch = {
        "events": [
            {
                "app": "firefox",
                "activity_type": "browse",
                "timestamp": "2026-07-27T10:00:00",
                "duration_seconds": 120.0,
            },
            {
                "app": "code",
                "activity_type": "edit",
                "timestamp": "2026-07-27T10:05:00",
                "duration_seconds": 300.0,
            },
        ]
    }
    ing = client.post(f"/api/agents/{agent_id}/events", json=batch)
    assert ing.status_code == 200
    assert ing.json()["ingested"] == 2

    export = client.get("/api/events/export").json()
    assert export["count"] == 2
    apps = [e["app"] for e in export["events"]]
    assert apps == ["firefox", "code"]
    assert export["events"][0]["role"] == "Dev"


def test_ingest_unknown_agent_404(client):
    r = client.post(
        "/api/agents/NOPE/events",
        json={"events": [{"app": "x", "activity_type": "y", "timestamp": "2026-07-27T10:00:00"}]},
    )
    assert r.status_code == 404
