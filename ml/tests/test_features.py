from datetime import datetime

from lisa_ml.features import build_transitions, feature_rows, hour_bucket, state_app_hour
from lisa_ml.schema import Event


def _e(agent_id, app, minute):
    return Event(
        agent_id=agent_id, app=app, activity_type="use", timestamp=datetime(2026, 7, 6, 10, minute)
    )


def test_hour_bucket():
    assert hour_bucket(datetime(2026, 1, 1, 3)) == "night"
    assert hour_bucket(datetime(2026, 1, 1, 9)) == "morning"
    assert hour_bucket(datetime(2026, 1, 1, 14)) == "afternoon"
    assert hour_bucket(datetime(2026, 1, 1, 20)) == "evening"


def test_transitions_ordered_per_agent():
    events = [_e(1, "code", 10), _e(1, "terminal", 5), _e(2, "firefox", 1)]
    pairs = build_transitions(events)
    assert pairs == [("terminal", "code")]


def test_state_app_hour_key():
    assert state_app_hour(_e(1, "code", 0)) == "code@morning"


def test_feature_rows_carry_prev_app():
    events = [_e(1, "code", 1), _e(1, "firefox", 2)]
    rows = feature_rows(events)
    assert rows[0]["prev_app"] is None
    assert rows[1]["prev_app"] == "code"
