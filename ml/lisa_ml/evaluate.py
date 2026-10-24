"""Evaluation harness for next-app prediction (issue #51).

The goal of #51 is to compare a better model (boosting / RNN) against the
Markov baseline *once enough logs exist*, and to keep whichever wins swappable
behind the same artifact contract. This module is that harness:

- `NextAppPredictor` is the contract — anything with `predict_next(state)` can
  be scored, so a future GBM/RNN drops in without touching the runtime (the
  agent and backend already consume `predict_next` / the `counts` artifact).
- a chronological train/test split (per agent, no leakage) and a top-1 accuracy
  metric give an apples-to-apples comparison.
- the Markov model plus two dependency-free baselines (most-frequent, persist)
  are wired in so the harness is runnable today on synthetic or exported logs;
  heavier candidates are added later behind the same Protocol.

Run: `python -m lisa_ml.evaluate --events events.json` (or `--synthetic`).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lisa_ml.features import (
    StateKey,
    _by_agent,
    build_bigram_transitions,
    build_transitions,
    state_app,
    state_app_hour,
)
from lisa_ml.model import BackoffMarkovModel, MarkovModel
from lisa_ml.schema import Event

TransitionBuilder = Callable[[list[Event]], list[tuple[str, str]]]


class NextAppPredictor(Protocol):
    """The contract every candidate model implements. The Markov artifact and
    any future model (boosting, RNN) are interchangeable through this."""

    def predict_next(self, state: str) -> str | None: ...


class MostFrequentApp:
    """Baseline: always predict the globally most common next app, ignoring
    state. The floor any real model must beat."""

    def __init__(self) -> None:
        self._top: str | None = None

    def fit(self, transitions: list[tuple[str, str]]) -> MostFrequentApp:
        counter = Counter(nxt for _, nxt in transitions)
        self._top = counter.most_common(1)[0][0] if counter else None
        return self

    def predict_next(self, state: str) -> str | None:
        return self._top


class PersistApp:
    """Baseline: predict that the next app equals the current one. With an
    app-based state key the state string *is* the current app."""

    def fit(self, transitions: list[tuple[str, str]]) -> PersistApp:
        return self

    def predict_next(self, state: str) -> str | None:
        return state or None


def split_events(events: list[Event], frac: float = 0.8) -> tuple[list[Event], list[Event]]:
    """Chronological per-agent split: the first `frac` of each agent's events
    train, the rest test. Keeps the time ordering so we never train on the
    future of the sequence we score."""
    train: list[Event] = []
    test: list[Event] = []
    for rows in _by_agent(events).values():
        cut = int(len(rows) * frac)
        train.extend(rows[:cut])
        test.extend(rows[cut:])
    return train, test


@dataclass(frozen=True)
class Score:
    name: str
    accuracy: float
    n: int  # test transitions scored


@dataclass(frozen=True)
class Candidate:
    name: str
    state_key: StateKey
    factory: object  # callable returning a fresh predictor with .fit
    # Optional custom transition builder (e.g. higher-order history). When set
    # it is used instead of build_transitions(events, state_key), so a candidate
    # can train/score on a different state space (the agent sees Event lists).
    transitions: TransitionBuilder | None = None

    def build(self, events: list[Event]) -> list[tuple[str, str]]:
        if self.transitions is not None:
            return self.transitions(events)
        return build_transitions(events, self.state_key)


def _top1_accuracy(
    model: NextAppPredictor, transitions: list[tuple[str, str]]
) -> tuple[float, int]:
    if not transitions:
        return 0.0, 0
    hits = sum(1 for state, nxt in transitions if model.predict_next(state) == nxt)
    return hits / len(transitions), len(transitions)


def default_candidates() -> list[Candidate]:
    """The models the harness compares out of the box. Add GBM/RNN candidates
    here (same NextAppPredictor contract) once logs justify them."""
    return [
        Candidate("markov(app)", state_app, MarkovModel),
        Candidate("markov(app_hour)", state_app_hour, MarkovModel),
        Candidate("backoff(app)", state_app, BackoffMarkovModel),
        Candidate("backoff(app_hour)", state_app_hour, BackoffMarkovModel),
        Candidate("markov(bigram)", state_app, MarkovModel, transitions=build_bigram_transitions),
        Candidate(
            "backoff(bigram)", state_app, BackoffMarkovModel, transitions=build_bigram_transitions
        ),
        Candidate("most_frequent", state_app, MostFrequentApp),
        Candidate("persist", state_app, PersistApp),
    ]


def evaluate(
    events: list[Event],
    candidates: list[Candidate] | None = None,
    frac: float = 0.8,
) -> list[Score]:
    """Train each candidate on the split's train half and score top-1 accuracy
    on the test half. Returns scores sorted best-first."""
    candidates = candidates or default_candidates()
    train_events, test_events = split_events(events, frac)
    scores: list[Score] = []
    for cand in candidates:
        model = cand.factory()  # type: ignore[operator]
        model.fit(cand.build(train_events))
        acc, n = _top1_accuracy(model, cand.build(test_events))
        scores.append(Score(cand.name, acc, n))
    return sorted(scores, key=lambda s: s.accuracy, reverse=True)


def format_table(scores: list[Score]) -> str:
    width = max((len(s.name) for s in scores), default=5)
    lines = [f"{'model'.ljust(width)}  accuracy  n", f"{'-' * width}  --------  -"]
    lines += [f"{s.name.ljust(width)}  {s.accuracy:8.3f}  {s.n}" for s in scores]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare next-app models (issue #51)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--events", help="events JSON (backend /events/export)")
    src.add_argument("--synthetic", action="store_true", help="use generated events")
    parser.add_argument("--frac", type=float, default=0.8, help="train fraction (0-1)")
    parser.add_argument("--json", action="store_true", help="emit scores as JSON")
    args = parser.parse_args()

    if args.synthetic:
        from lisa_ml.synthetic import generate_events

        events = generate_events(agents=5, days=10, per_day=40)
    else:
        raw = json.loads(Path(args.events).read_text())
        rows = raw["events"] if isinstance(raw, dict) else raw
        events = [Event.from_dict(r) for r in rows]

    scores = evaluate(events, frac=args.frac)
    if args.json:
        print(json.dumps([vars(s) for s in scores], indent=2))
    else:
        print(format_table(scores))


if __name__ == "__main__":
    main()
