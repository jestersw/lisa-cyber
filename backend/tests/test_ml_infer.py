import json

import pytest

from app.ml_infer import MarkovInference, configure_inference, reset_inference


@pytest.fixture(autouse=True)
def _clean_inference():
    reset_inference()
    yield
    reset_inference()


def _write_model(path, counts):
    path.write_text(json.dumps({"version": 1, "counts": counts}))


def test_predict_argmax(tmp_path):
    p = tmp_path / "model.json"
    _write_model(p, {"code": {"terminal": 3, "firefox": 1}})
    inf = MarkovInference(p)
    assert inf.predict("code") == "terminal"
    assert inf.loaded is True
    assert inf.state_count == 1


def test_predict_unseen_state(tmp_path):
    p = tmp_path / "model.json"
    _write_model(p, {"code": {"terminal": 1}})
    inf = MarkovInference(p)
    assert inf.predict("nope") is None


def test_missing_file_is_not_loaded(tmp_path):
    inf = MarkovInference(tmp_path / "absent.json")
    assert inf.load() is False
    assert inf.predict("code") is None


def test_proba_normalizes(tmp_path):
    p = tmp_path / "model.json"
    _write_model(p, {"code": {"terminal": 3, "firefox": 1}})
    inf = MarkovInference(p)
    proba = inf.proba("code")
    assert abs(proba["terminal"] - 0.75) < 1e-9


def _make_agent(client):
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


def test_next_activity_from_model(client, tmp_path):
    p = tmp_path / "model.json"
    _write_model(p, {"code": {"terminal": 5, "firefox": 1}})
    configure_inference(p)
    agent_id = _make_agent(client)
    resp = client.get(f"/api/agents/{agent_id}/next-activity?current=code")
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_activity"] == "terminal"
    assert body["source"] == "model"


def test_next_activity_fallback_when_no_model(client, tmp_path):
    configure_inference(tmp_path / "absent.json")
    agent_id = _make_agent(client)
    resp = client.get(f"/api/agents/{agent_id}/next-activity?current=code")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fallback"
    assert body["next_activity"] == "firefox"


def test_next_activity_unknown_agent(client):
    resp = client.get("/api/agents/NOPE/next-activity?current=code")
    assert resp.status_code == 404


def test_ml_status_and_reload(client, tmp_path):
    p = tmp_path / "model.json"
    _write_model(p, {"code": {"terminal": 2}})
    configure_inference(p)
    status = client.get("/api/ml/status").json()
    assert status["model_loaded"] in {True, False}
    reload_resp = client.post("/api/ml/reload").json()
    assert reload_resp["reloaded"] is True
    assert reload_resp["states"] == 1
