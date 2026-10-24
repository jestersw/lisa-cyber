"""Auth for agent-facing and operator-facing endpoints.

Agents authenticate with a single shared secret (`Authorization: Bearer
<token>`, matching their LISA_AGENT_TOKEN). Per-agent tokens issued at install
time are a later step; this closes the "no auth at all" gap without
over-building.

Operators log in with a shared password (`operator_password`) and receive a
signed JWT, which the panel then sends as `Authorization: Bearer <jwt>`. When
`operator_password` is unset the operator endpoints are open — dev mode,
matching the agent token above — so tests and local runs need no setup.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Header, HTTPException, Query

from app.config import Settings, get_settings

_JWT_ALGORITHM = "HS256"
_JWT_SUBJECT = "operator"
# Scope claim on a build-artefact download token, so an operator JWT and a
# narrow download token can't be used in place of one another.
_DOWNLOAD_SCOPE = "build-download"
# How long a minted download link stays valid. Short, because the operator
# downloads right after opening the agent; a leaked URL expires quickly.
_DOWNLOAD_TTL_MINUTES = 15


def require_agent_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().agent_token
    if expected is None:
        return  # dev mode: open
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")


def _signing_key(settings: Settings) -> str:
    """The JWT signing secret: jwt_secret if set, else derived from the
    operator password so a single env var locks the panel."""
    if settings.jwt_secret:
        return settings.jwt_secret
    # operator_password is guaranteed non-None by the callers below.
    return hashlib.sha256(f"lisa-operator:{settings.operator_password}".encode()).hexdigest()


def verify_operator_password(password: str) -> bool:
    """Constant-time check of a login password against the configured one."""
    expected = get_settings().operator_password
    if expected is None:
        return True  # dev mode: any password accepted (panel is open anyway)
    return secrets.compare_digest(password, expected)


def create_operator_token() -> str:
    """Mint a signed JWT for an authenticated operator."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": _JWT_SUBJECT,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, _signing_key(settings), algorithm=_JWT_ALGORITHM)


def _is_valid_operator_token(token: str, settings: Settings) -> bool:
    """True if `token` is a valid, unexpired operator JWT."""
    try:
        payload = jwt.decode(token, _signing_key(settings), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("sub") == _JWT_SUBJECT


def require_operator(authorization: str | None = Header(default=None)) -> None:
    """Guard operator-facing endpoints: a valid, unexpired operator JWT."""
    settings = get_settings()
    if settings.operator_password is None:
        return  # dev mode: open
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing operator token")
    if not _is_valid_operator_token(authorization.removeprefix("Bearer "), settings):
        raise HTTPException(status_code=401, detail="Invalid or expired operator token")


# --- build-artefact download tokens (#202) ---


def create_download_token(agent_id: str, filename: str) -> str:
    """Mint a short-lived, single-file token for downloading one build artefact.

    Scoped to exactly one agent_id + filename so it can't be replayed against a
    different artefact, and short-lived so a URL that leaks (e.g. into a server
    log) stops working quickly."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "scope": _DOWNLOAD_SCOPE,
        "agent_id": agent_id,
        "filename": filename,
        "iat": now,
        "exp": now + timedelta(minutes=_DOWNLOAD_TTL_MINUTES),
    }
    return jwt.encode(payload, _signing_key(settings), algorithm=_JWT_ALGORITHM)


def verify_download_token(token: str, agent_id: str, filename: str) -> bool:
    """True if `token` is a valid download token for this exact artefact."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, _signing_key(settings), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return False
    return (
        payload.get("scope") == _DOWNLOAD_SCOPE
        and payload.get("agent_id") == agent_id
        and payload.get("filename") == filename
    )


def require_download_access(
    agent_id: str,
    filename: str,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Guard build-artefact downloads (#202).

    The artefact (installer / binary / package.json) carries the agent's baked
    token, so it must not be world-readable. Access is granted by any of:
      - a valid operator JWT in the Authorization header (API clients);
      - a valid operator JWT passed as ?token= (header-less callers);
      - a scoped, short-lived download token for this exact artefact, which the
        operator panel embeds in the URL it hands out (so a browser <a download>
        link, which cannot send a header, still authenticates).
    Dev mode (no operator_password) stays open, matching the other guards.
    """
    settings = get_settings()
    if settings.operator_password is None:
        return  # dev mode: open
    if authorization and authorization.startswith("Bearer "):
        if _is_valid_operator_token(authorization.removeprefix("Bearer "), settings):
            return
    if token:
        if _is_valid_operator_token(token, settings):
            return
        if verify_download_token(token, agent_id, filename):
            return
    raise HTTPException(status_code=401, detail="Missing or invalid download token")
