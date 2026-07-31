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
    raw = "```json\n{\"applications_used\": [\"code\"]}\n```"
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
