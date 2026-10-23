"""Ask the backend which app to switch to next (issue #57).

The orchestrator used to pick the next app purely locally — a transition model
baked into the package, falling back to a uniform choice. This client lets the
agent instead consult the live model via GET /api/agents/{id}/next-activity,
which is retrained on real activity as it accumulates (#50).

It is deliberately best-effort: any failure (backend down, timeout, unknown
app, or the backend itself falling back to a static guess) returns None so the
orchestrator keeps its own local fallback. The agent must never stall or crash
because the backend is unreachable.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("lisa-agent.nextapp")


class NextAppClient:
    """Fetches the next app name from the backend. Returns None on any problem."""

    def __init__(
        self,
        backend_url: str,
        agent_id: str,
        token: str | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def fetch(self, current: str | None) -> str | None:
        """Return the suggested next app name, or None to fall back locally.

        We only trust a model-backed prediction: when the backend reports
        ``source`` other than ``"model"`` (its own static fallback), we return
        None so the agent's richer local fallback provides the variety a
        constant guess would not.
        """
        if not self.backend_url:
            return None
        url = f"{self.backend_url}/api/agents/{self.agent_id}/next-activity"
        params = {"sample": "true"}
        if current:
            params["current"] = current
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            log.debug("next-activity request failed, falling back locally: %s", exc)
            return None
        if resp.status_code != 200:
            log.debug("next-activity returned status %s, falling back", resp.status_code)
            return None
        try:
            data = resp.json()
        except ValueError:
            log.debug("next-activity returned non-JSON, falling back")
            return None
        if data.get("source") != "model":
            return None
        nxt = data.get("next_activity")
        return nxt if isinstance(nxt, str) and nxt else None
