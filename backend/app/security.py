"""Auth for agent-facing endpoints.

A single shared secret for now (the agent sends `Authorization: Bearer <token>`,
matching its LISA_AGENT_TOKEN). Per-agent tokens issued at install time are a
later step; this closes the "no auth at all" gap without over-building.
"""

from fastapi import Header, HTTPException

from app.config import get_settings


def require_agent_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().agent_token
    if expected is None:
        return  # dev mode: open
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")
