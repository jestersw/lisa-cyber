"""Serve compiled agent binaries and their deployment packages.

The builder worker (see app.services.agent_builder.worker) puts finished
artefacts under DEFAULT_STORAGE_ROOT/<agent_id>/. This module exposes them
over HTTP so the operator can download the binary from the panel.

The URL shape (/api/builds/{agent_id}/{filename}) matches the download_url
that storage.store() writes into the DB, so the frontend can hand out the
URL as-is without any rewriting.

Security note: the path parameters are validated so nobody can climb out of
the storage directory. If the storage root is ever moved to S3, this
endpoint becomes a redirect — the rest of the system doesn't change.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.agent_builder.storage import DEFAULT_STORAGE_ROOT

log = logging.getLogger("lisa.api.builds")

router = APIRouter()

# What we consider a legal segment in a path parameter. Anything else (slashes,
# dots, spaces, control chars) is rejected outright — no need to worry about
# path traversal because we never construct paths from unsafe input.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_segment(segment: str, kind: str) -> None:
    """Reject anything that could escape the storage root."""
    if not segment or not _SAFE_SEGMENT.match(segment):
        raise HTTPException(status_code=400, detail=f"invalid {kind}: {segment!r}")
    if segment.startswith(".") or ".." in segment:
        raise HTTPException(status_code=400, detail=f"invalid {kind}: {segment!r}")


@router.get("/builds/{agent_id}/{filename}")
def download_build_artefact(agent_id: str, filename: str) -> FileResponse:
    """Serve a single artefact (binary or package.json) for one agent.

    404 when the agent has no build on disk or the file doesn't exist.
    Otherwise streams the file with the right media type.
    """
    _validate_segment(agent_id, "agent_id")
    _validate_segment(filename, "filename")

    file_path = DEFAULT_STORAGE_ROOT / agent_id / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="artefact not found")

    # A last sanity check: after resolving the path (following any symlinks
    # that could have snuck in), it must still live under the storage root.
    # This catches the exotic case where an operator has placed a symlink in
    # the storage directory pointing outside it.
    try:
        file_path.resolve().relative_to(DEFAULT_STORAGE_ROOT.resolve())
    except ValueError:
        log.warning("path traversal attempt via symlink: %s", file_path)
        raise HTTPException(status_code=404, detail="artefact not found") from None

    media_type = "application/json" if filename.endswith(".json") else "application/octet-stream"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )
