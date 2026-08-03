from __future__ import annotations

import logging
import sys

from app.config import get_settings
from app.services.agent_builder.worker import POLL_TIMEOUT_SECONDS, WorkerConfigError, run

log = logging.getLogger("lisa.agent_builder")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        import redis
    except ImportError:
        log.error("the redis package is not installed, the build worker cannot start")
        return 1

    redis_client = redis.Redis.from_url(
        get_settings().redis_url,
        socket_timeout=POLL_TIMEOUT_SECONDS + 10,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    try:
        run(redis_client)
    except WorkerConfigError as exc:
        log.error("worker misconfigured: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
