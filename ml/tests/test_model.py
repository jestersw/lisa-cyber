from lisa_ml.model import BackoffMarkovModel, MarkovModel


def test_fit_and_predict():
    model = MarkovModel().fit([("code", "terminal"), ("code", "terminal"), ("code", "firefox")])
    assert model.predict_next("code") == "terminal"
    proba = model.predict_proba("code")
    assert abs(proba["terminal"] - 2 / 3) < 1e-9


def test_unseen_state():
    model = MarkovModel()
    assert model.predict_next("nope") is None
    assert model.predict_proba("nope") == {}


def test_serialization_round_trip(tmp_path):
    model = MarkovModel().fit([("a", "b"), ("a", "b"), ("b", "a")])
    path = tmp_path / "m.json"
    model.save(path)
    loaded = MarkovModel.load(path)
    assert loaded.predict_next("a") == "b"
    assert loaded.to_dict() == model.to_dict()


# ---------- back-off model (#51) ----------

_TRANSITIONS = [
    ("code", "terminal"),
    ("code", "terminal"),
    ("code", "firefox"),
    ("terminal", "code"),
]


def test_backoff_matches_markov_on_seen_states():
    markov = MarkovModel().fit(_TRANSITIONS)
    backoff = BackoffMarkovModel().fit(_TRANSITIONS)
    assert backoff.predict_next("code") == markov.predict_next("code") == "terminal"


def test_backoff_uses_global_mode_on_unseen_state():
    # Plain Markov returns nothing for an unseen state; back-off returns the
    # global most-frequent next app (terminal appears most across all states).
    backoff = BackoffMarkovModel().fit(_TRANSITIONS)
    assert MarkovModel().fit(_TRANSITIONS).predict_next("gimp") is None
    assert backoff.predict_next("gimp") == "terminal"
    assert backoff.predict_proba("gimp")  # non-empty global distribution


def test_backoff_empty_model_still_returns_none():
    assert BackoffMarkovModel().predict_next("anything") is None


def test_backoff_shares_markov_artifact(tmp_path):
    # The artifacts are byte-identical: a model stored as Markov loads as
    # back-off (and vice versa) with no contract change.
    markov = MarkovModel(trained_on="role:dev").fit(_TRANSITIONS)
    assert BackoffMarkovModel(trained_on="role:dev").fit(_TRANSITIONS).to_dict() == markov.to_dict()
    path = tmp_path / "m.json"
    markov.save(path)
    loaded = BackoffMarkovModel.load(path)
    assert loaded.predict_next("code") == "terminal"
    assert loaded.predict_next("unseen") == "terminal"  # back-off kicks in


def test_backoff_restrict_to_keeps_type():
    restricted = BackoffMarkovModel().fit(_TRANSITIONS).restrict_to(["code", "terminal"])
    assert isinstance(restricted, BackoffMarkovModel)
    assert "firefox" not in restricted.predict_proba("code")
    assert restricted.predict_next("unseen") in {"code", "terminal"}
