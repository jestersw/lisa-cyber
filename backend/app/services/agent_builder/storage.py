"""Persist the built artefacts (agent binary + deployment package).

The workspace is thrown away after every build. Anything worth keeping -
the compiled binary and the package.json it needs beside it - has to be
copied to durable storage before we clean up.

For now storage is the local filesystem, under a per-agent directory
(/var/lisa/builds/<agent_id>/). The rest of the system only sees
StoredArtefacts.download_url and doesn't care where the file physically
lives, so we can swap this out for S3/MinIO later without touching the
orchestrator or the API.

The download URL is a path relative to the backend, not an absolute URL.
The FastAPI app decides the host/scheme when serving the file.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("lisa.builder.storage")

DEFAULT_STORAGE_ROOT = Path("/var/lisa/builds")


class StorageError(RuntimeError):
    """Something went wrong writing the built artefacts to durable storage."""


@dataclass(frozen=True)
class StoredArtefacts:
    """Where a completed build's files ended up, and how to fetch them.

    The paths are on the builder host's filesystem; the URL is what the
    frontend or a deploy script would ask the backend for.
    """

    binary_path: Path
    package_path: Path
    download_url: str


def store(
    agent_id: str,
    binary: Path,
    package_json: Path,
    root: Path = DEFAULT_STORAGE_ROOT,
) -> StoredArtefacts:
    """Copy the binary and package.json into the agent's storage directory.

    - agent_id: identifies the build. Also becomes part of the download URL.
    - binary: the ELF the compiler just produced.
    - package_json: the deployment package written into the workspace.

    Overwrites any previous build for the same agent_id: the newest artefact
    wins, older ones are gone. If we ever need history, that goes on top -
    the simple case doesn't pay for it.
    """
    if not agent_id:
        raise StorageError("agent_id must be provided")
    if not binary.is_file():
        raise StorageError(f"binary not found: {binary}")
    if not package_json.is_file():
        raise StorageError(f"package.json not found: {package_json}")

    dest_dir = root / agent_id
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"could not create storage dir {dest_dir}: {exc}") from exc

    # Preserve the original binary's filename in storage so the operator sees
    # the name the compiler chose (e.g. agent_USR001), not a generic one.
    dest_binary = dest_dir / binary.name
    dest_package = dest_dir / "package.json"

    try:
        shutil.copy2(binary, dest_binary)
        shutil.copy2(package_json, dest_package)
    except OSError as exc:
        raise StorageError(f"could not copy artefacts to {dest_dir}: {exc}") from exc

    download_url = f"/api/builds/{agent_id}/{binary.name}"
    log.info("stored artefacts for %s at %s (url: %s)", agent_id, dest_dir, download_url)

    return StoredArtefacts(
        binary_path=dest_binary,
        package_path=dest_package,
        download_url=download_url,
    )
