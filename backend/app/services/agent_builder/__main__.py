from __future__ import annotations

import logging
import sys

from app.ratelimit import get_redis
from app.services.agent_builder.worker import WorkerConfigError, run

log = logging.getLogger("lisa.agent_builder")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    redis_client = get_redis()
    if redis_client is None:
        log.error("redis is unavailable, the build worker cannot start")
        return 1
    try:
        run(redis_client)
    except WorkerConfigError as exc:
        log.error("worker misconfigured: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
