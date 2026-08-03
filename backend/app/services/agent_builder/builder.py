"""Orchestrate one agent build end to end.

Ties together the individual builder steps:

  workspace.create()          scratch dir per build
  sources.copy_agent_sources() copy agent/*.py in
  write_package()             drop package.json next to the sources
  write_env()                 drop .env with backend URL + token
  compiler.compile_agent()    nuitka --onefile
  storage.store()             persist binary + package to durable storage
  workspace.cleanup()         always, even on failure

Returns a BuildResult so the caller (Redis worker, API, tests) can act on
the outcome without having to know which step failed.

The builder is a pure function of its inputs - no DB, no HTTP calls. The
worker that dispatches builds is responsible for:
  * reading the deployment package from the DB / backend endpoint
  * generating and remembering the agent token
  * updating agent status (building -> ready / failed) after we return

That separation keeps this module cheap to test and easy to reason about.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.agent_builder import (
    compiler,
    sources,
    storage,
    workspace,
)
from app.services.agent_builder import (
    installer as installer_mod,
)

log = logging.getLogger("lisa.builder")


class BuildError(RuntimeError):
    """The builder environment is broken (bad host, missing sources, etc.).

    Distinct from a BuildResult with success=False: BuildError means the
    caller can't do anything about it at runtime and the build never really
    started; a failed BuildResult means Nuitka ran but rejected the code.
    """


@dataclass(frozen=True)
class BuildResult:
    """Outcome of one end-to-end build.

    On success, `download_url` points at the raw agent binary and
    `installer_url` at the self-extracting installer that wraps it. Callers
    that only care about one artefact can pick whichever they need; both
    live in the same per-agent storage directory.

    On compile failure, `stdout`/`stderr` carry the Nuitka output so the
    operator can see why.
    """

    success: bool
    agent_id: str
    download_url: str | None
    stdout: str
    stderr: str
    artefacts: storage.StoredArtefacts | None = None
    installer_url: str | None = None


def build_agent(
    agent_id: str,
    deployment_package: dict[str, Any],
    agent_token: str,
    backend_url: str,
    *,
    agent_source_root: Path,
    workspace_root: Path = workspace.DEFAULT_ROOT,
    storage_root: Path = storage.DEFAULT_STORAGE_ROOT,
) -> BuildResult:
    """Run one build end to end.

    - agent_id: identifier from the backend (also becomes the workspace /
      storage key and part of the binary filename)
    - deployment_package: the {agent_config, application_plugins} dict per
      docs/agent-config-schema.md; written verbatim to package.json
    - agent_token: unique bearer token this agent will present on heartbeat
    - backend_url: what LISA_BACKEND_URL points at inside the agent
    - agent_source_root: path to agent/lisa_agent/ in the repo

    Raises BuildError if the environment is broken before Nuitka can run
    (missing sources, blank ids, misconfigured host). Returns a BuildResult
    with success=False if Nuitka ran but rejected the code.

    The workspace is always cleaned up, even on failure.
    """
    if not agent_id:
        raise BuildError("agent_id must be provided")
    if not agent_token:
        raise BuildError("agent_token must be provided")
    if not backend_url:
        raise BuildError("backend_url must be provided")

    ws = workspace.create(agent_id, root=workspace_root)
    log.info("build %s: workspace=%s", agent_id, ws.root)

    try:
        # 1. Copy the agent sources into the workspace.
        try:
            sources.copy_agent_sources(agent_source_root, ws.agent_dir)
        except sources.SourcesError as exc:
            raise BuildError(f"could not copy agent sources: {exc}") from exc

        # 2. Write the deployment package. The agent's main.py reads it from
        #    the current working directory as package.json.
        ws.package_json.write_text(json.dumps(deployment_package, indent=2))

        # 3. Write the .env the agent will read at runtime.
        _write_env(ws.env_file, agent_token=agent_token, backend_url=backend_url)

        # 4. Compile. This is where most real failures land.
        binary_name = f"agent_{agent_id}"
        result = compiler.compile_agent(
            source_dir=ws.agent_dir,
            output_dir=ws.output_dir,
            binary_name=binary_name,
        )

        if not result.success:
            log.warning("build %s: nuitka rejected the code", agent_id)
            return BuildResult(
                success=False,
                agent_id=agent_id,
                download_url=None,
                stdout=result.stdout,
                stderr=result.stderr,
                artefacts=None,
            )

        # 5. Persist the binary + package next to it.
        assert result.binary_path is not None  # success=True guarantees this
        artefacts = storage.store(
            agent_id=agent_id,
            binary=result.binary_path,
            package_json=ws.package_json,
            root=storage_root,
        )

        # 6. Wrap the binary into a self-extracting installer and persist
        #    that too. Installer lives beside the binary; delivery layer
        #    (cloud-init, golden template, hand-run) picks whichever it
        #    needs by URL.
        installer_path = ws.output_dir / f"installer_{agent_id}.sh"
        installer_mod.wrap_as_installer(result.binary_path, installer_path, agent_id=agent_id)
        installer_url = storage.store_installer(
            agent_id=agent_id, installer=installer_path, root=storage_root
        )

        log.info(
            "build %s: success, binary=%s installer=%s",
            agent_id,
            artefacts.download_url,
            installer_url,
        )
        return BuildResult(
            success=True,
            agent_id=agent_id,
            download_url=artefacts.download_url,
            stdout=result.stdout,
            stderr=result.stderr,
            artefacts=artefacts,
            installer_url=installer_url,
        )
    finally:
        workspace.cleanup(ws)


def _write_env(path: Path, *, agent_token: str, backend_url: str) -> None:
    """Write the .env the agent needs to reach the backend."""
    path.write_text(
        f"LISA_BACKEND_URL={backend_url}\nLISA_AGENT_TOKEN={agent_token}\n",
        encoding="utf-8",
    )
