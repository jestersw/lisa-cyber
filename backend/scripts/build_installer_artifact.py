"""Build one agent installer and drop it in ./dist for CI to upload.

Runs the real build pipeline (`build_agent`) on the runner's own OS — Nuitka
cannot cross-compile, so the caller must pick a runner that matches OS_TYPE
(windows-latest for windows, macos-latest for macos, ubuntu-latest for linux).
This is what lets an operator produce a downloadable installer for an OS the
always-on backend can't build itself (macOS/Windows), on demand, from CI.

Inputs come from the environment so the workflow can pass its dispatch inputs:
  AGENT_ID     - agent identity baked into filenames/logs (required)
  OS_TYPE      - linux | macos | windows (required; must match the runner)
  BACKEND_URL  - what the installed agent phones home to (required)
  AGENT_TOKEN  - enrollment token to bake (optional; a placeholder otherwise)
  ROLE         - role name for the generated config (default: developer)
  APPS         - comma-separated application names (optional)

Writes dist/installer_<AGENT_ID>.(sh|ps1) and the raw binary beside it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.defaults import build_agent_config
from app.services.agent_builder.builder import build_agent


def main() -> int:
    agent_id = os.environ["AGENT_ID"]
    os_type = os.environ["OS_TYPE"]
    backend_url = os.environ["BACKEND_URL"]
    token = os.environ.get("AGENT_TOKEN") or "placeholder-enrollment-token"  # noqa: S105
    role = os.environ.get("ROLE", "developer")
    apps = [a.strip() for a in os.environ.get("APPS", "").split(",") if a.strip()]

    repo_root = Path(__file__).resolve().parents[2]
    out = repo_root / "dist"
    (out / "ws").mkdir(parents=True, exist_ok=True)
    (out / "stg").mkdir(parents=True, exist_ok=True)

    config = build_agent_config(agent_id, agent_id, role, os_type, apps, {})
    package = {"agent_config": config, "application_plugins": {}}

    print(f"building {agent_id} installer for {os_type} via build_agent() ...")
    result = build_agent(
        agent_id=agent_id,
        deployment_package=package,
        agent_token=token,
        backend_url=backend_url,
        agent_source_root=repo_root / "agent" / "lisa_agent",
        target_os=os_type,
        workspace_root=out / "ws",
        storage_root=out / "stg",
    )
    if not result.success:
        print("FAIL: build did not succeed")
        print((result.stderr or "")[-4000:])
        return 1

    staged = out / "stg" / agent_id
    produced = list(staged.glob("installer_*")) + list(staged.glob(f"agent_{agent_id}*"))
    for f in produced:
        shutil.copy2(f, out / f.name)
        print("artefact:", (out / f.name), f"({f.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
