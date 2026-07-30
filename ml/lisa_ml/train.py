from __future__ import annotations

import argparse
import json
from pathlib import Path

from lisa_ml.features import build_transitions, state_app, state_app_hour
from lisa_ml.model import MarkovModel
from lisa_ml.schema import Event

_STATE_KEYS = {"app": state_app, "app_hour": state_app_hour}


def load_events(path: str | Path) -> list[Event]:
    raw = json.loads(Path(path).read_text())
    rows = raw["events"] if isinstance(raw, dict) else raw
    return [Event.from_dict(r) for r in rows]


def train(events: list[Event], state: str = "app") -> MarkovModel:
    transitions = build_transitions(events, _STATE_KEYS[state])
    return MarkovModel().fit(transitions)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the LISA behavior model")
    parser.add_argument("--events", required=True, help="events JSON (backend /events/export)")
    parser.add_argument("--out", default="model.json", help="output model path")
    parser.add_argument("--state", choices=list(_STATE_KEYS), default="app")
    args = parser.parse_args()

    events = load_events(args.events)
    model = train(events, args.state)
    model.save(args.out)
    print(f"trained on {len(events)} events, {len(model.counts)} states -> {args.out}")


if __name__ == "__main__":
    main()
