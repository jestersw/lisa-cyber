from lisa_ml.evaluate import (
    Candidate,
    MostFrequentApp,
    PersistApp,
    Score,
    default_candidates,
    evaluate,
    format_table,
    split_events,
)
from lisa_ml.features import state_app
from lisa_ml.model import MarkovModel
from lisa_ml.synthetic import generate_events


def test_split_is_chronological_and_per_agent():
    events = generate_events(agents=2, days=2, per_day=10, seed=1)
    train, test = split_events(events, frac=0.8)
    assert train and test
    assert len(train) + len(test) == len(events)
    # Every test event comes no earlier than its agent's last train event.
    for agent in {e.agent_id for e in events}:
        tr = [e.timestamp for e in train if e.agent_id == agent]
        te = [e.timestamp for e in test if e.agent_id == agent]
        if tr and te:
            assert max(tr) <= min(te)


def test_most_frequent_predicts_global_mode():
    m = MostFrequentApp().fit([("a", "x"), ("b", "x"), ("c", "y")])
    assert m.predict_next("anything") == "x"


def test_persist_returns_current_state():
    assert PersistApp().predict_next("firefox") == "firefox"
    assert PersistApp().predict_next("") is None


def test_evaluate_scores_all_candidates_in_range():
    events = generate_events(agents=5, days=8, per_day=40, seed=2)
    scores = evaluate(events)
    names = {s.name for s in scores}
    assert names == {
        "markov(app)",
        "markov(app_hour)",
        "backoff(app)",
        "backoff(app_hour)",
        "markov(bigram)",
        "backoff(bigram)",
        "most_frequent",
        "persist",
    }
    assert all(isinstance(s, Score) and 0.0 <= s.accuracy <= 1.0 and s.n > 0 for s in scores)
    # sorted best-first
    assert scores == sorted(scores, key=lambda s: s.accuracy, reverse=True)


def test_backoff_never_worse_than_markov():
    # Back-off only changes behaviour on states unseen in training, where it
    # guesses the global mode instead of nothing — so accuracy can only hold or
    # improve. A sparse, finely-split config makes the gain show up.
    events = generate_events(agents=12, days=2, per_day=12, seed=7)
    by_name = {s.name: s.accuracy for s in evaluate(events)}
    assert by_name["backoff(app)"] >= by_name["markov(app)"]
    assert by_name["backoff(app_hour)"] >= by_name["markov(app_hour)"]


def test_bigram_candidate_runs_on_history_states():
    events = generate_events(agents=4, days=5, per_day=30, seed=8)
    scores = {s.name: s for s in evaluate(events)}
    assert scores["markov(bigram)"].n > 0
    assert 0.0 <= scores["markov(bigram)"].accuracy <= 1.0


def test_markov_beats_the_most_frequent_floor_on_structured_data():
    # Synthetic data has real transition structure, so a stateful model should
    # beat the stateless most-frequent baseline.
    events = generate_events(agents=5, days=10, per_day=40, seed=3)
    by_name = {s.name: s.accuracy for s in evaluate(events)}
    assert by_name["markov(app)"] >= by_name["most_frequent"]


def test_custom_candidate_via_protocol():
    # Anything with fit + predict_next plugs in through the same contract.
    events = generate_events(agents=2, days=3, per_day=20, seed=4)
    scores = evaluate(events, candidates=[Candidate("markov(app)", state_app, MarkovModel)])
    assert len(scores) == 1 and scores[0].name == "markov(app)"


def test_default_candidates_shape():
    cands = default_candidates()
    assert [c.name for c in cands][0] == "markov(app)"


def test_format_table_contains_models():
    table = format_table(evaluate(generate_events(agents=2, days=2, per_day=10, seed=5)))
    assert "accuracy" in table and "markov(app)" in table
