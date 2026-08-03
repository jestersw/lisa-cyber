import pytest

import app.api.endpoints.agents as agents_module


class FakeRedis:
    def __init__(self):
        self.pushed = []

    def lpush(self, key, value):
        self.pushed.append((key, value))


class BrokenRedis:
    def lpush(self, key, value):
        raise RuntimeError("redis is down")


@pytest.fixture
def _no_redis(monkeypatch):
    monkeypatch.setattr(agents_module, "get_redis", lambda: None)


def _generate(client, os_type="linux"):
    return client.post(
        "/api/agents/generate",
        json={
            "name": "A",
            "role": "developer",
            "os_type": os_type,
            "applications": ["vscode"],
        },
    )


def test_build_is_queued_and_status_becomes_building(client, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(agents_module, "get_redis", lambda: fake)

    body = _generate(client).json()
    assert body["config"]["build_status"] == "queued"
    assert len(fake.pushed) == 1
    assert body["agent_id"] in fake.pushed[0][1]

    listed = client.get("/api/agents").json()
    match = [a for a in listed if a["agent_id"] == body["agent_id"]]
    assert match and match[0]["status"] == "building"


def test_agent_is_still_created_without_redis(client, _no_redis):
    resp = _generate(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["config"]["build_status"] == "queue_unavailable"

    listed = client.get("/api/agents").json()
    match = [a for a in listed if a["agent_id"] == body["agent_id"]]
    assert match and match[0]["status"] == "configured"


def test_agent_survives_a_broken_redis(client, monkeypatch):
    monkeypatch.setattr(agents_module, "get_redis", lambda: BrokenRedis())

    resp = _generate(client)
    assert resp.status_code == 200
    assert resp.json()["config"]["build_status"] == "queue_unavailable"


def test_config_still_served_after_failed_enqueue(client, _no_redis):
    agent_id = _generate(client).json()["agent_id"]
    pkg = client.get(f"/api/agents/{agent_id}/config")
    assert pkg.status_code == 200
    assert pkg.json()["agent_config"]["agent_info"]["agent_id"] == agent_id


def test_windows_agent_is_created_but_not_queued(client, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(agents_module, "get_redis", lambda: fake)

    body = _generate(client, os_type="windows").json()
    assert body["config"]["build_status"] == "unsupported_os"
    assert fake.pushed == []

    listed = client.get("/api/agents").json()
    match = [a for a in listed if a["agent_id"] == body["agent_id"]]
    assert match and match[0]["status"] == "configured"


def test_macos_agent_is_created_but_not_queued(client, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(agents_module, "get_redis", lambda: fake)

    body = _generate(client, os_type="macos").json()
    assert body["config"]["build_status"] == "unsupported_os"
    assert fake.pushed == []


def test_windows_agent_still_gets_its_package(client, monkeypatch):
    monkeypatch.setattr(agents_module, "get_redis", lambda: FakeRedis())
    agent_id = _generate(client, os_type="windows").json()["agent_id"]
    pkg = client.get(f"/api/agents/{agent_id}/config").json()
    assert pkg["agent_config"]["agent_info"]["os_type"] == "windows"
