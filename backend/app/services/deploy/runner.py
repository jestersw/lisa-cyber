"""Execute a Deployment row: run the orchestration backend and record outcome.

Called from a FastAPI background task after the endpoint has created the row in
`pending`. It owns the status transitions and is the only place that writes the
result of a run, so the HTTP layer stays thin and the logic is unit-testable
without a web request.

Never raises to its caller: every path ends with a terminal status
(`succeeded`, `failed`, or `unavailable`) so the operator always sees a
definitive outcome in the panel.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime

from app.database import get_sessionmaker
from app.models.models import Deployment
from app.services.deploy import ansible

log = logging.getLogger("lisa.deploy.runner")


def _finish(session, deployment: Deployment, status: str, **fields) -> None:
    deployment.status = status
    for key, value in fields.items():
        setattr(deployment, key, value)
    deployment.finished_at = datetime.now(UTC)
    session.commit()


def run_deployment(
    deployment_id: int,
    inventory_text: str,
    *,
    backend_url: str,
    force: bool = False,
    download_token: str | None = None,
    session_factory=None,
) -> None:
    """Run the deployment identified by `deployment_id` to completion."""
    session_factory = session_factory or get_sessionmaker()
    with session_factory() as session:
        deployment = session.get(Deployment, deployment_id)
        if deployment is None:
            log.error("run_deployment for unknown deployment %s", deployment_id)
            return

        if not ansible.ansible_available():
            log.warning("ansible not available; deployment %s marked unavailable", deployment_id)
            _finish(
                session,
                deployment,
                "unavailable",
                error=(
                    "ansible-playbook is not available on the backend host, so "
                    "panel deployment can't run here. Use the committed playbook "
                    "in deploy/ansible/ directly, or run the backend on a host "
                    "with ansible installed (see docs/deployment.md)."
                ),
            )
            return

        deployment.status = "running"
        session.commit()

        try:
            returncode, output = ansible.run_playbook(
                inventory_text,
                backend_url=backend_url,
                force=force,
                download_token=download_token,
            )
        except subprocess.TimeoutExpired:
            log.warning("deployment %s timed out", deployment_id)
            _finish(session, deployment, "failed", error="deployment timed out")
            return
        except Exception as exc:  # noqa: BLE001 - any failure is a failed deploy
            log.exception("deployment %s crashed", deployment_id)
            _finish(session, deployment, "failed", error=str(exc))
            return

        status = "succeeded" if returncode == 0 else "failed"
        _finish(session, deployment, status, returncode=returncode, output=output)
        log.info("deployment %s finished: %s (rc=%s)", deployment_id, status, returncode)
