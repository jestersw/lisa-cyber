from __future__ import annotations

import json
from pathlib import Path


class MarkovModel:
    def __init__(self, trained_on: str | None = None) -> None:
        self.counts: dict[str, dict[str, int]] = {}
        self.trained_on = trained_on

    def fit(self, transitions: list[tuple[str, str]]) -> MarkovModel:
        for state, nxt in transitions:
            bucket = self.counts.setdefault(state, {})
            bucket[nxt] = bucket.get(nxt, 0) + 1
        return self

    def predict_proba(self, state: str) -> dict[str, float]:
        bucket = self.counts.get(state)
        if not bucket:
            return {}
        total = sum(bucket.values())
        return {app: n / total for app, n in bucket.items()}

    def predict_next(self, state: str) -> str | None:
        bucket = self.counts.get(state)
        if not bucket:
            return None
        return max(bucket.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def to_dict(self) -> dict:
        payload: dict = {"version": 1, "counts": self.counts}
        if self.trained_on is not None:
            payload["trained_on"] = self.trained_on
        return payload

    def restrict_to(self, applications: list[str]) -> MarkovModel:
        allowed = set(applications)
        trimmed: dict[str, dict[str, int]] = {}
        for state, nexts in self.counts.items():
            if state not in allowed:
                continue
            kept = {app: n for app, n in nexts.items() if app in allowed}
            if kept:
                trimmed[state] = kept
        model = MarkovModel(trained_on=self.trained_on)
        model.counts = trimmed
        return model

    @classmethod
    def from_dict(cls, data: dict) -> MarkovModel:
        model = cls(trained_on=data.get("trained_on"))
        model.counts = {s: dict(n) for s, n in data.get("counts", {}).items()}
        return model

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict()))

    @classmethod
    def load(cls, path: str | Path) -> MarkovModel:
        return cls.from_dict(json.loads(Path(path).read_text()))
