from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from lisa_ml.schema import Event
from lisa_ml.train import save_models, train_by_role

log = logging.getLogger("lisa-ml.retrain")


class FetchError(RuntimeError):
    pass


def fetch_events(backend_url: str, token: str | None = None, timeout: float = 30.0) -> list[Event]:
    url = f"{backend_url.rstrip('/')}/api/events/export"
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise FetchError(str(exc)) from exc
    rows = payload.get("events", []) if isinstance(payload, dict) else payload
    return [Event.from_dict(row) for row in rows]


def retrain_once(
    backend_url: str,
    out_dir: str | Path,
    token: str | None = None,
    min_events: int = 20,
) -> dict[str, int]:
    events = fetch_events(backend_url, token)
    if not events:
        log.info("no events yet, nothing to train")
        return {}
    models = train_by_role(events, min_events=min_events)
    save_models(models, out_dir)
    summary = {name: len(model.counts) for name, model in models.items()}
    log.info("trained %d models from %d events: %s", len(models), len(events), summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain LISA behavior models")
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--out", default="models")
    parser.add_argument("--token", default=None)
    parser.add_argument("--min-events", type=int, default=20)
    parser.add_argument("--interval", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    while True:
        try:
            retrain_once(args.backend, args.out, args.token, args.min_events)
        except FetchError as exc:
            log.warning("cannot reach backend: %s", exc)
        if args.interval <= 0:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
