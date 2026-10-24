"""Drive the committed Ansible playbook as a subprocess.

This is the thin boundary between the backend and the `deploy/ansible/`
role/playbook (#212). It writes the rendered inventory to a temp file and runs
`ansible-playbook` against it, returning the return code and a tail of the
output. It never raises for a failed play — a non-zero return code is a normal,
reported outcome; it only raises if ansible can't be invoked at all.

Graceful degradation: deployment orchestration needs `ansible-playbook` on PATH
and the committed playbook on disk, plus SSH reachability to the targets. Where
that isn't set up (e.g. the stock backend image, which stays lean), the runner
records the deployment as `unavailable` rather than failing — mirroring how the
builder reports `unsupported_os` / `queue_unavailable`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("lisa.deploy.ansible")

# How long a single deployment may run before we give up on it.
DEPLOY_TIMEOUT_SECONDS = 1800

# Keep at most this much of the playbook output in the DB (tail). Ansible can be
# verbose; the operator wants the end (recap + any failure), not megabytes.
_OUTPUT_TAIL_CHARS = 20000

_PLAYBOOK = "deploy-agents.yml"


def playbook_dir() -> Path:
    """Directory holding the committed playbook. Overridable via
    LISA_ANSIBLE_DIR for deployments run from a different checkout/mount."""
    override = os.environ.get("LISA_ANSIBLE_DIR")
    if override:
        return Path(override)
    # backend/app/services/deploy/ansible.py -> repo root is 4 parents up from
    # the package dir, then deploy/ansible.
    return Path(__file__).resolve().parents[4] / "deploy" / "ansible"


def ansible_available() -> bool:
    """True when we can actually run a deployment here: ansible-playbook on
    PATH and the committed playbook present."""
    if shutil.which("ansible-playbook") is None:
        return False
    return (playbook_dir() / _PLAYBOOK).is_file()


def run_playbook(
    inventory_text: str,
    *,
    backend_url: str,
    force: bool = False,
    timeout: int = DEPLOY_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """Run the deployment playbook against `inventory_text`.

    Returns (returncode, output_tail). The inventory is passed as a file and all
    operator input reaches ansible as argv (never a shell string), so there is
    no shell to inject into. Raises FileNotFoundError if ansible-playbook isn't
    installed and subprocess.TimeoutExpired if the run overruns `timeout`.
    """
    directory = playbook_dir()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ini", prefix="lisa-inventory-", delete=False
    ) as handle:
        handle.write(inventory_text)
        inventory_path = handle.name

    cmd = [
        "ansible-playbook",
        _PLAYBOOK,
        "-i",
        inventory_path,
        "-e",
        f"lisa_agent_backend_url={backend_url}",
    ]
    if force:
        cmd += ["-e", "lisa_agent_force_reinstall=true"]

    log.info("running deployment playbook: %s (cwd=%s)", " ".join(cmd), directory)
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell, validated input
            cmd,
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    finally:
        try:
            os.unlink(inventory_path)
        except OSError:
            pass

    output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    if len(output) > _OUTPUT_TAIL_CHARS:
        output = "...(truncated)...\n" + output[-_OUTPUT_TAIL_CHARS:]
    return proc.returncode, output
