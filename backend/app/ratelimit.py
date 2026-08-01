"""Per-agent rate limiting backed by Redis, with fail-open behaviour.

Applied to the public agent-facing endpoints (heartbeat, event ingestion) so a
broken or hostile client can't flood them. The limit is counted per agent (keyed
by the bearer token the agent presents), so one noisy agent can't rate-limit the
others.

Fail-open: if Redis is unavailable, requests are allowed through rather than
rejected. Rate limiting protects against abuse; it must not become a single
point of failure that takes down heartbeats for every agent when Redis is down.

The `redis` package itself is treated as optional: if it isn't installed, this
module still imports and every request is allowed through. That way a missing
optional dependency doesn't take down the whole FastAPI app.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import Header, HTTPException, Request

from app.config import get_settings

log = logging.getLogger("lisa.ratelimit")

# Optional dependency: if `redis` isn't installed, fall back to fail-open for
# every request instead of crashing the whole app at import time.
try:
    import redis as _redis_module

    _REDIS_ERRORS: tuple[type[BaseException], ...] = (_redis_module.RedisError, OSError)
except ImportError:
    _redis_module = None  # type: ignore[assignment]
    _REDIS_ERRORS = (OSError,)
    log.warning("redis package not installed; rate limiting will fail open")

_redis: Any = None


def get_redis() -> Any:
    """Lazily create a Redis client. Returns None if it can't be reached or if
    the `redis` package isn't installed."""
    global _redis
    if _redis_module is None:
        return None
    if _redis is None:
        try:
            _redis = _redis_module.Redis.from_url(
                get_settings().redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except _REDIS_ERRORS as exc:
            log.warning("Redis unavailable for rate limiting: %s", exc)
            return None
    return _redis


def _client_key(authorization: str | None, request: Request) -> str:
    """Identify the caller: prefer the agent's bearer token, else its IP."""
    if authorization and authorization.startswith("Bearer "):
        return f"token:{authorization.removeprefix('Bearer ')}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def _allow(key: str, limit: int, window_seconds: int) -> bool:
    """Increment the per-key counter in Redis; return False if over the limit.

    Fail-open: any Redis error returns True (request allowed).
    """
    r = get_redis()
    if r is None:
        return True  # fail-open: no Redis (or no redis package), don't block
    try:
        redis_key = f"ratelimit:{key}"
        count = cast(int, r.incr(redis_key))
        if count == 1:
            r.expire(redis_key, window_seconds)
        return count <= limit
    except _REDIS_ERRORS as exc:
        log.warning("Rate limit check failed, allowing request: %s", exc)
        return True  # fail-open on any Redis error


def rate_limit(limit: int = 30, window_seconds: int = 60):
    """Build a FastAPI dependency enforcing `limit` requests per `window`."""

    def dependency(request: Request, authorization: str | None = Header(default=None)) -> None:
        key = _client_key(authorization, request)
        if not _allow(key, limit, window_seconds):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded, slow down",
            )

    return dependency
