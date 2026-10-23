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
from fastapi import Header, HTTPException

from app.config import Settings, get_settings

_JWT_ALGORITHM = "HS256"
_JWT_SUBJECT = "operator"


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


def require_operator(authorization: str | None = Header(default=None)) -> None:
    """Guard operator-facing endpoints: a valid, unexpired operator JWT."""
    settings = get_settings()
    if settings.operator_password is None:
        return  # dev mode: open
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing operator token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, _signing_key(settings), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired operator token") from exc
    if payload.get("sub") != _JWT_SUBJECT:
        raise HTTPException(status_code=401, detail="Invalid operator token")
