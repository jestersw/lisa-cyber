from lisa_ml.features import build_transitions
from lisa_ml.model import MarkovModel
from lisa_ml.predict import next_activity
from lisa_ml.synthetic import generate_events
from lisa_ml.train import train


def test_end_to_end_learns_something():
    events = generate_events(agents=3, days=5, per_day=30, seed=1)
    assert len(events) == 3 * 5 * 30
    model = train(events, state="app")
    assert model.counts
    for app in ["code", "firefox", "terminal"]:
        if app in model.counts:
            assert model.predict_next(app) is not None


def test_train_matches_manual_transitions():
    events = generate_events(agents=1, days=1, per_day=10, seed=2)
    manual = MarkovModel().fit(build_transitions(events))
    assert train(events).to_dict() == manual.to_dict()


def test_next_activity_fallback():
    model = MarkovModel()
    assert next_activity(model, "unknown", fallback="firefox") == "firefox"
