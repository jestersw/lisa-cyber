"""Agent entry point: wires everything into a running agent.

Reads two inputs at startup and never talks to the backend for anything else
except heartbeats (see docs/agent-config-schema.md):

  - env vars (backend URL, auth token, interval) via Config.from_env()
  - the deployment package (agent config + application plugins) via
    DeploymentPackage.load() from a local JSON file

Then it stands up mutex + installer + activity engine + heartbeat + orchestrator
and runs until stopped (SIGTERM / SIGINT).

Package path is LISA_PACKAGE_PATH (env) or ./package.json by default. The path
matches what the builder drops next to the compiled binary on the target VM.
"""

from __future__ import annotations

import logging
import os
import sys

from lisa_agent.activity import ActivityEngine
from lisa_agent.config import Config, WorkSchedule
from lisa_agent.heartbeat import HeartbeatLoop, HeartbeatSender, build_payload
from lisa_agent.installer import ensure_all_installed
from lisa_agent.mutex import AgentMutex
from lisa_agent.orchestrator import Agent
from lisa_agent.package import DeploymentPackage, PackageError
from lisa_agent.platform_ops import current_os

log = logging.getLogger("lisa-agent")


def _work_schedule_from_package(pkg: DeploymentPackage) -> WorkSchedule:
    """Bridge the package's AgentSchedule (ISO weekdays 1-7) to the orchestrator's
    WorkSchedule (0-indexed weekdays 0-6, Mon=0)."""
    return WorkSchedule(
        start=pkg.schedule.work_start,
        end=pkg.schedule.work_end,
        workdays=tuple(d - 1 for d in pkg.schedule.workdays),
        lunch_earliest=pkg.schedule.lunch.earliest,
        lunch_latest=pkg.schedule.lunch.latest,
        lunch_min_minutes=pkg.schedule.lunch.min_minutes,
        lunch_max_minutes=pkg.schedule.lunch.max_minutes,
    )


def _package_path() -> str:
    return os.environ.get("LISA_PACKAGE_PATH", "./package.json")


def build_agent(env_config: Config, pkg: DeploymentPackage) -> Agent:
    """Assemble every runtime object from the loaded config + package.

    Separated from main() so it can be tested without actually running the loop.
    """
    identity = pkg.identity

    # One-per-machine lock, keyed to this agent's identity.
    mutex = AgentMutex(identity.agent_id)

    # Check every configured app; install if missing. One app's failure doesn't
    # block the others.
    install_report = ensure_all_installed(pkg.applications)
    usable_apps = [a for a in pkg.applications if install_report.get(a.name)]
    if not usable_apps:
        log.warning("no usable applications after install checks")

    engine = ActivityEngine()

    # Heartbeat: one sender, wrapped in a loop that runs on a background thread.
    sender = HeartbeatSender(
        url=f"{env_config.backend_url}/api/agents/heartbeat",
        token=env_config.auth_token,
    )

    def payload_provider() -> dict:
        current = agent.current_app.name if agent.current_app else None
        return build_payload(identity.agent_id, "active", current_app=current)

    heartbeat = HeartbeatLoop(
        sender=sender,
        payload_provider=payload_provider,
        interval_seconds=pkg.heartbeat.interval_minutes * 60,
    )

    # The orchestrator ties schedule + apps + engine + heartbeat + mutex together.
    behavior = pkg.behavior
    agent = Agent(
        schedule=_work_schedule_from_package(pkg),
        apps=usable_apps,
        engine=engine,
        heartbeat=heartbeat,
        mutex=mutex,
        session_min=int(behavior.session_duration.min),
        session_max=int(behavior.session_duration.max),
        switch_pause_range=(
            int(behavior.app_switch_pause.min),
            int(behavior.app_switch_pause.max),
        ),
        inactive_period_range=(
            int(behavior.inactive_period.min),
            int(behavior.inactive_period.max),
        ),
    )
    return agent


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("LISA agent starting on os=%s", current_os())

    env_config = Config.from_env()

    package_path = _package_path()
    try:
        pkg = DeploymentPackage.load(package_path)
    except PackageError as exc:
        log.error("Failed to load deployment package from %s: %s", package_path, exc)
        return 2
    except OSError as exc:
        log.error("Cannot read deployment package at %s: %s", package_path, exc)
        return 2

    log.info(
        "loaded package: agent_id=%s role=%s os=%s apps=%d",
        pkg.identity.agent_id,
        pkg.identity.role,
        pkg.identity.os_type,
        len(pkg.applications),
    )

    agent = build_agent(env_config, pkg)
    agent.install_signal_handlers()
    agent.start()  # blocks; returns when the loop is stopped
    return 0


if __name__ == "__main__":
    sys.exit(main())
