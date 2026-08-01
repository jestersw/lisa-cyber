import json

import pytest

from app.llm import LLMError, configure_provider, parse_template, reset_provider


class FakeProvider:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error

    def generate(self, prompt):
        if self.error:
            raise LLMError(self.error)
        return self.output


@pytest.fixture(autouse=True)
def _clean_provider():
    reset_provider()
    yield
    reset_provider()


def test_parse_template_valid():
    raw = json.dumps(
        {"applications_used": ["code", "firefox"], "work_start": "09:00", "work_end": "18:00"}
    )
    data = parse_template(raw)
    assert data["applications_used"] == ["code", "firefox"]
    assert data["activities"] == []


def test_parse_template_strips_code_fence():
    raw = '```json\n{"applications_used": ["code"]}\n```'
    assert parse_template(raw)["applications_used"] == ["code"]


def test_parse_template_rejects_empty_apps():
    assert parse_template(json.dumps({"applications_used": []})) is None


def test_parse_template_rejects_garbage():
    assert parse_template("not json at all") is None


def test_generate_endpoint_success(client):
    configure_provider(FakeProvider(output=json.dumps({"applications_used": ["code", "slack"]})))
    resp = client.post(
        "/api/behavior-templates/generate",
        json={"description": "junior backend dev", "os_type": "linux"},
    )
    assert resp.status_code == 200
    assert resp.json()["template_data"]["applications_used"] == ["code", "slack"]


def test_generate_endpoint_bad_model_output(client):
    configure_provider(FakeProvider(output="sorry I cannot"))
    resp = client.post(
        "/api/behavior-templates/generate",
        json={"description": "x", "os_type": "linux"},
    )
    assert resp.status_code == 422


def test_generate_endpoint_provider_down(client):
    configure_provider(FakeProvider(error="connection refused"))
    resp = client.post(
        "/api/behavior-templates/generate",
        json={"description": "x", "os_type": "linux"},
    )
    assert resp.status_code == 503


PLUGIN_JSON = json.dumps(
    {
        "app_info": {"name": "discord", "display_name": "Discord", "category": "communication"},
        "installation": {"check_command": "discord --version", "dependencies": ["xdotool"]},
        "execution": {"open_command": "discord", "close_command": "pkill -f discord"},
        "activities": [
            {
                "id": "check_servers",
                "name": "Check servers",
                "weight": 60,
                "min_duration": 15,
                "max_duration": 45,
                "commands": [{"type": "key_combination", "keys": "ctrl+k", "delay": 1}],
            },
            {
                "id": "read",
                "name": "Read",
                "weight": 40,
                "commands": [{"type": "key", "key": "Down", "delay": 1}],
            },
        ],
        "settings": {"usage_probability": 0.8, "work_hours_only": True},
    }
)


def test_parse_plugin_valid():
    from app.llm import parse_plugin

    data = parse_plugin(PLUGIN_JSON)
    assert data["app_info"]["name"] == "discord"
    assert len(data["activities"]) == 2
    assert data["execution"]["open_command"] == "discord"


def test_parse_plugin_rejects_no_activities():
    from app.llm import parse_plugin

    bad = json.dumps(
        {"app_info": {"name": "x"}, "execution": {"open_command": "x"}, "activities": []}
    )
    assert parse_plugin(bad) is None


def test_parse_plugin_rejects_bad_command_type():
    from app.llm import parse_plugin

    bad = json.dumps(
        {
            "app_info": {"name": "x"},
            "execution": {"open_command": "x"},
            "activities": [{"id": "a", "name": "a", "commands": [{"type": "shell"}]}],
        }
    )
    assert parse_plugin(bad) is None


def test_plugin_generation_endpoint(client):
    configure_provider(FakeProvider(output=PLUGIN_JSON))
    resp = client.post(
        "/api/application-templates/generate",
        json={"name": "discord", "os_type": "linux"},
    )
    assert resp.status_code == 200
    assert resp.json()["template_config"]["app_info"]["name"] == "discord"


def test_plugin_generation_endpoint_invalid(client):
    configure_provider(FakeProvider(output="nope"))
    resp = client.post(
        "/api/application-templates/generate",
        json={"name": "discord", "os_type": "linux"},
    )
    assert resp.status_code == 422


def test_config_generates_missing_plugin_and_caches(client):
    configure_provider(FakeProvider(output=PLUGIN_JSON))
    agent_id = client.post(
        "/api/agents/generate",
        json={
            "name": "A1",
            "role": "developer",
            "os_type": "linux",
            "applications": ["discord"],
        },
    ).json()["agent_id"]

    pkg = client.get(f"/api/agents/{agent_id}/config").json()
    assert "discord" in pkg["application_plugins"]
    assert pkg["application_plugins"]["discord"]["execution"]["open_command"] == "discord"

    stored = client.get("/api/application-templates").json()
    assert any(item["name"] == "discord" for item in stored)


def test_config_skips_when_llm_unavailable(client):
    configure_provider(FakeProvider(error="down"))
    agent_id = client.post(
        "/api/agents/generate",
        json={"name": "A2", "role": "admin", "os_type": "linux", "applications": ["ghost"]},
    ).json()["agent_id"]

    pkg = client.get(f"/api/agents/{agent_id}/config").json()
    assert pkg["application_plugins"] == {}
    assert pkg["agent_config"]["applications"] == ["ghost"]
