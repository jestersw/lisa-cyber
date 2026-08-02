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


def train(events: list[Event], state: str = "app", trained_on: str | None = None) -> MarkovModel:
    transitions = build_transitions(events, _STATE_KEYS[state])
    return MarkovModel(trained_on=trained_on).fit(transitions)


def roles_in(events: list[Event]) -> list[str]:
    return sorted({e.role for e in events if e.role})


def train_by_role(
    events: list[Event], state: str = "app", min_events: int = 20
) -> dict[str, MarkovModel]:
    models: dict[str, MarkovModel] = {}
    for role in roles_in(events):
        subset = [e for e in events if e.role == role]
        if len(subset) < min_events:
            continue
        models[role] = train(subset, state, trained_on=f"role:{role}")
    models["_shared"] = train(events, state, trained_on="shared")
    return models


def save_models(models: dict[str, MarkovModel], out_dir: str | Path) -> list[Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for role, model in models.items():
        path = directory / f"{role}.json"
        model.save(path)
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the LISA behavior model")
    parser.add_argument("--events", required=True, help="events JSON (backend /events/export)")
    parser.add_argument("--out", default="model.json", help="output model path or directory")
    parser.add_argument("--state", choices=list(_STATE_KEYS), default="app")
    parser.add_argument("--by-role", action="store_true", help="train one model per role")
    parser.add_argument("--min-events", type=int, default=20)
    args = parser.parse_args()

    events = load_events(args.events)
    if args.by_role:
        models = train_by_role(events, args.state, args.min_events)
        for path in save_models(models, args.out):
            print(f"{path.stem}: {len(MarkovModel.load(path).counts)} states -> {path}")
        return

    model = train(events, args.state, trained_on="shared")
    model.save(args.out)
    print(f"trained on {len(events)} events, {len(model.counts)} states -> {args.out}")


if __name__ == "__main__":
    main()
