def test_root(client):
    assert client.get("/").json()["status"] == "running"


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] in {"healthy", "degraded"}
