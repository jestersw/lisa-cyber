from __future__ import annotations

import json
import threading
from pathlib import Path


class MarkovInference:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._counts: dict[str, dict[str, int]] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def load(self) -> bool:
        with self._lock:
            if not self.path.exists():
                self._counts = {}
                self._loaded = False
                return False
            data = json.loads(self.path.read_text())
            self._counts = {s: dict(n) for s, n in data.get("counts", {}).items()}
            self._loaded = True
            return True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def state_count(self) -> int:
        return len(self._counts)

    def predict(self, state: str) -> str | None:
        self.ensure_loaded()
        bucket = self._counts.get(state)
        if not bucket:
            return None
        return max(bucket.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def proba(self, state: str) -> dict[str, float]:
        self.ensure_loaded()
        bucket = self._counts.get(state)
        if not bucket:
            return {}
        total = sum(bucket.values())
        return {app: n / total for app, n in bucket.items()}


_inference: MarkovInference | None = None
_lock = threading.Lock()


def get_inference() -> MarkovInference:
    global _inference
    if _inference is None:
        with _lock:
            if _inference is None:
                from app.config import get_settings

                _inference = MarkovInference(get_settings().ml_model_path)
    return _inference


def configure_inference(path: str | Path) -> MarkovInference:
    global _inference
    _inference = MarkovInference(path)
    return _inference


def reset_inference() -> None:
    global _inference
    _inference = None
