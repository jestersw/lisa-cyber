import json

import pytest

from app.models_store import ModelStore, configure_store, reset_store, restrict_model

SHARED = {
    "version": 1,
    "trained_on": "shared",
    "counts": {"vscode": {"terminal": 10, "monitoring": 5}, "monitoring": {"vscode": 3}},
}
DEV = {
    "version": 1,
    "trained_on": "role:developer",
    "counts": {"vscode": {"terminal": 40, "firefox": 10}, "terminal": {"vscode": 20}},
}


@pytest.fixture(autouse=True)
def _clean_store():
    reset_store()
    yield
    reset_store()


def _write_models(tmp_path):
    (tmp_path / "_shared.json").write_text(json.dumps(SHARED))
    (tmp_path / "developer.json").write_text(json.dumps(DEV))
    return tmp_path


def test_restrict_model_drops_unknown_apps():
    trimmed = restrict_model(SHARED, ["vscode", "terminal"])
    assert trimmed["counts"] == {"vscode": {"terminal": 10}}
    assert trimmed["trained_on"] == "shared"


def test_restrict_model_returns_none_without_overlap():
    assert restrict_model(SHARED, ["gimp"]) is None


def test_store_prefers_role_then_shared(tmp_path):
    store = ModelStore(_write_models(tmp_path))
    assert store.for_role("developer")["trained_on"] == "role:developer"
    assert store.for_role("admin")["trained_on"] == "shared"
    assert store.for_role(None)["trained_on"] == "shared"


def test_store_returns_none_when_empty(tmp_path):
    assert ModelStore(tmp_path).for_role("developer") is None


def test_store_ignores_malformed_file(tmp_path):
    (tmp_path / "_shared.json").write_text("not json")
    assert ModelStore(tmp_path).for_role(None) is None


def _make_agent(client, apps, role="developer"):
    return client.post(
        "/api/agents/generate",
        json={"name": "A1", "role": role, "os_type": "linux", "applications": apps},
    ).json()["agent_id"]


def test_package_includes_role_model(client, tmp_path):
    configure_store(_write_models(tmp_path))
    agent_id = _make_agent(client, ["vscode", "terminal"])
    ac = client.get(f"/api/agents/{agent_id}/config").json()["agent_config"]
    assert ac["transition_model"]["trained_on"] == "role:developer"
    assert ac["transition_model"]["counts"] == {
        "vscode": {"terminal": 40},
        "terminal": {"vscode": 20},
    }


def test_package_falls_back_to_shared(client, tmp_path):
    configure_store(_write_models(tmp_path))
    agent_id = _make_agent(client, ["vscode", "terminal"], role="admin")
    ac = client.get(f"/api/agents/{agent_id}/config").json()["agent_config"]
    assert ac["transition_model"]["trained_on"] == "shared"


def test_package_omits_model_when_untrained(client, tmp_path):
    configure_store(tmp_path)
    agent_id = _make_agent(client, ["vscode"])
    ac = client.get(f"/api/agents/{agent_id}/config").json()["agent_config"]
    assert ac["transition_model"] is None


def test_package_omits_model_when_no_app_overlap(client, tmp_path):
    configure_store(_write_models(tmp_path))
    agent_id = _make_agent(client, ["gimp"])
    ac = client.get(f"/api/agents/{agent_id}/config").json()["agent_config"]
    assert ac["transition_model"] is None


def test_store_picks_up_rewritten_model(tmp_path):
    import os
    import time

    path = tmp_path / "_shared.json"
    path.write_text(json.dumps(SHARED))
    store = ModelStore(tmp_path)
    assert store.for_role(None)["trained_on"] == "shared"

    updated = {"version": 1, "trained_on": "shared", "counts": {"gimp": {"vscode": 1}}}
    path.write_text(json.dumps(updated))
    os.utime(path, (time.time() + 10, time.time() + 10))

    assert store.for_role(None)["counts"] == {"gimp": {"vscode": 1}}


def test_store_forgets_deleted_model(tmp_path):
    path = tmp_path / "_shared.json"
    path.write_text(json.dumps(SHARED))
    store = ModelStore(tmp_path)
    assert store.for_role(None) is not None
    path.unlink()
    assert store.for_role(None) is None
