"""Read-only metadata for the operator panel.

Exposes which OSes the deployment can actually build right now (`buildable_os`)
so the New-agent UI can reflect it — e.g. flag an OS that has no build worker
running instead of silently producing an agent whose build never queues (#200).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import OSType

router = APIRouter()


@router.get("/meta")
def meta() -> dict:
    return {
        "os_types": [o.value for o in OSType],
        "buildable_os": get_settings().buildable_os,
    }
