"""Build workspace management.

Each agent build gets its own scratch directory under a common root
(e.g. /tmp/lisa_builds/USR001_1729873245/). The workspace holds:
  - agent/            <- copy of the agent source tree
  - package.json      <- the deployment package for this agent
  - .env              <- LISA_BACKEND_URL, LISA_AGENT_TOKEN
  - build output      <- the compiled ELF binary lands here

Directories are always disposable: nothing durable lives in a workspace, and
finalize_build() must copy anything worth keeping to permanent storage before
the workspace is cleaned up.

Uses a timestamp suffix so a retried build for the same agent_id doesn't
collide with an earlier attempt whose cleanup hasn't finished yet.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("lisa.builder.workspace")

DEFAULT_ROOT = Path("/tmp/lisa_builds")


class WorkspaceError(RuntimeError):
    """Something went wrong preparing or cleaning up a build workspace."""


@dataclass(frozen=True)
class Workspace:
    """A prepared, isolated directory for one build.

    Fields are the well-known paths inside it. Callers get the paths and write
    into them directly; this class only owns lifecycle (create / cleanup).
    """

    root: Path
    agent_dir: Path  # where the agent source tree is copied
    package_json: Path  # where the deployment package is written
    env_file: Path  # where .env is written
    output_dir: Path  # where the compiled binary lands


def create(agent_id: str, root: Path = DEFAULT_ROOT) -> Workspace:
    """Prepare a fresh workspace for `agent_id` and return its paths.

    Never reuses an existing directory: a leftover from a failed build could
    confuse the compiler. If the timestamped dir somehow already exists we
    treat it as an error rather than silently continuing.
    """
    if not agent_id:
        raise WorkspaceError("agent_id must be provided")

    root.mkdir(parents=True, exist_ok=True)

    # Timestamped suffix keeps retries isolated from each other. Nanosecond
    # resolution - even back-to-back retries won't collide.
    suffix = str(time.time_ns())
    ws_path = root / f"{agent_id}_{suffix}"
    try:
        ws_path.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise WorkspaceError(f"workspace already exists: {ws_path}") from exc

    agent_dir = ws_path / "agent"
    output_dir = ws_path / "out"
    agent_dir.mkdir()
    output_dir.mkdir()

    ws = Workspace(
        root=ws_path,
        agent_dir=agent_dir,
        package_json=ws_path / "package.json",
        env_file=ws_path / ".env",
        output_dir=output_dir,
    )
    log.info("created workspace %s", ws.root)
    return ws


def cleanup(workspace: Workspace) -> None:
    """Remove the workspace and everything under it.

    Idempotent: cleaning an already-deleted workspace is not an error, since
    we call this from finally-blocks that may run twice on odd failure paths.
    """
    if not workspace.root.exists():
        return
    try:
        shutil.rmtree(workspace.root)
        log.info("cleaned up workspace %s", workspace.root)
    except OSError as exc:
        # Don't raise - the build is done; a stale scratch dir is a small
        # cleanup issue, not something that should mask the real result.
        log.warning("could not clean up %s: %s", workspace.root, exc)
