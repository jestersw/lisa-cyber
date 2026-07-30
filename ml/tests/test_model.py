from lisa_ml.model import MarkovModel


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
