"""Agent skeleton.

Real behaviour (scheduler, activity execution, heartbeat with version reporting)
is ported on top of this. For now it just proves the entrypoint and OS detection.
"""

import logging

from lisa_agent.platform_ops import current_os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lisa-agent")


def main() -> None:
    log.info("LISA agent starting on os=%s", current_os())
    log.info("scaffold: heartbeat loop and activity scheduler go here")


if __name__ == "__main__":
    main()
