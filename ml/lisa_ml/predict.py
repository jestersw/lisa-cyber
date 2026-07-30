from __future__ import annotations

from pathlib import Path

from lisa_ml.model import MarkovModel


def load_model(path: str | Path) -> MarkovModel:
    return MarkovModel.load(path)


def next_activity(model: MarkovModel, current_app: str, fallback: str = "firefox") -> str:
    return model.predict_next(current_app) or fallback
