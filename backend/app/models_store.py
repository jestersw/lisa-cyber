from __future__ import annotations

import json
import threading
from pathlib import Path


class ModelStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _load(self, name: str) -> dict | None:
        path = self.directory / f"{name}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        if not isinstance(data, dict) or "counts" not in data:
            return None
        return data

    def get(self, name: str) -> dict | None:
        path = self.directory / f"{name}.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            with self._lock:
                self._cache.pop(name, None)
            return None

        with self._lock:
            cached = self._cache.get(name)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            data = self._load(name)
            if data is None:
                self._cache.pop(name, None)
                return None
            self._cache[name] = (mtime, data)
            return data

    def clear(self) -> None:
        with self._lock:
            self._cache = {}

    def for_role(self, role: str | None) -> dict | None:
        if role:
            model = self.get(role)
            if model is not None:
                return model
        return self.get("_shared")


def restrict_model(model: dict, applications: list[str]) -> dict | None:
    allowed = set(applications)
    trimmed: dict[str, dict[str, int]] = {}
    for state, nexts in model.get("counts", {}).items():
        if state not in allowed:
            continue
        kept = {app: n for app, n in nexts.items() if app in allowed}
        if kept:
            trimmed[state] = kept
    if not trimmed:
        return None
    payload: dict = {"version": model.get("version", 1), "counts": trimmed}
    if model.get("trained_on"):
        payload["trained_on"] = model["trained_on"]
    return payload


_store: ModelStore | None = None
_lock = threading.Lock()


def get_store() -> ModelStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                from app.config import get_settings

                _store = ModelStore(get_settings().ml_models_dir)
    return _store


def configure_store(directory: str | Path) -> ModelStore:
    global _store
    _store = ModelStore(directory)
    return _store


def reset_store() -> None:
    global _store
    _store = None
