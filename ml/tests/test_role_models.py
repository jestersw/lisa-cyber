from datetime import datetime

from lisa_ml.model import MarkovModel
from lisa_ml.schema import Event
from lisa_ml.synthetic import generate_events
from lisa_ml.train import roles_in, save_models, train, train_by_role


def _events(role, apps, agent_id=1):
    return [
        Event(
            agent_id=agent_id,
            app=app,
            activity_type="use",
            timestamp=datetime(2026, 7, 6, 10, index),
            role=role,
        )
        for index, app in enumerate(apps)
    ]


def test_trained_on_in_dict():
    model = train(_events("dev", ["a", "b"]), trained_on="role:dev")
    assert model.to_dict()["trained_on"] == "role:dev"


def test_trained_on_absent_when_unset():
    assert "trained_on" not in MarkovModel().to_dict()


def test_trained_on_round_trip(tmp_path):
    model = train(_events("dev", ["a", "b"]), trained_on="role:dev")
    path = tmp_path / "m.json"
    model.save(path)
    assert MarkovModel.load(path).trained_on == "role:dev"


def test_restrict_to_drops_foreign_apps():
    model = MarkovModel(trained_on="shared").fit(
        [("vscode", "terminal"), ("vscode", "monitoring"), ("monitoring", "vscode")]
    )
    trimmed = model.restrict_to(["vscode", "terminal"])
    assert set(trimmed.counts) == {"vscode"}
    assert trimmed.counts["vscode"] == {"terminal": 1}
    assert trimmed.trained_on == "shared"


def test_restrict_to_empty_when_no_overlap():
    assert MarkovModel().fit([("a", "b")]).restrict_to(["x"]).counts == {}


def test_roles_in():
    events = _events("dev", ["a", "b"]) + _events("admin", ["c", "d"], agent_id=2)
    assert roles_in(events) == ["admin", "dev"]


def test_train_by_role_splits_and_tags():
    models = train_by_role(generate_events(agents=3, days=5, per_day=30, seed=1), min_events=20)
    assert models["_shared"].trained_on == "shared"
    for role in ["dev", "admin", "user"]:
        if role in models:
            assert models[role].trained_on == f"role:{role}"
            assert models[role].counts


def test_train_by_role_skips_thin_roles():
    models = train_by_role(_events("dev", ["a", "b", "c"]), min_events=20)
    assert "dev" not in models
    assert "_shared" in models


def test_save_models_writes_files(tmp_path):
    models = train_by_role(generate_events(agents=3, days=3, per_day=20, seed=2), min_events=10)
    written = save_models(models, tmp_path)
    assert len(written) == len(models)
