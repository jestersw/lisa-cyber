"""Per-agent rate limiting backed by Redis, with fail-open behaviour.

Applied to the public agent-facing endpoints (heartbeat, event ingestion) so a
broken or hostile client can't flood them. The limit is counted per agent (keyed
by the bearer token the agent presents), so one noisy agent can't rate-limit the
others.

Fail-open: if Redis is unavailable, requests are allowed through rather than
rejected. Rate limiting protects against abuse; it must not become a single
point of failure that takes down heartbeats for every agent when Redis is down.
"""

from __future__ import annotations

import logging

import redis
from fastapi import Header, HTTPException, Request

from app.config import get_settings

log = logging.getLogger("lisa.ratelimit")

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    """Lazily create a Redis client. Returns None if it can't be reached."""
    global _redis
    if _redis is None:
        try:
            _redis = redis.Redis.from_url(
                get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
            )
        except (redis.RedisError, OSError) as exc:
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
        return True  # fail-open: no Redis, don't block
    try:
        redis_key = f"ratelimit:{key}"
        count = int(r.incr(redis_key))
        if count == 1:
            r.expire(redis_key, window_seconds)
        return count <= limit
    except (redis.RedisError, OSError) as exc:
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
