# Agent behaviour diagnosis (AI assistant)

An operator can ask the panel *why* an agent is misbehaving and get an
LLM-backed analysis grounded in that agent's real signals, with concrete config
fixes (issue #211, from the spec's "ИИ / MCP-модуль" — *автоматическая отладка
поведения агента*).

## What it does

`POST /api/agents/{id}/diagnose` (operator-only) collects the signals LISA
already stores for the agent and runs them through the configured LLM provider:

- agent `status`, `os_type`, `last_seen`, `last_activity`;
- staleness (time since last heartbeat vs the agent's heartbeat interval);
- recent heartbeats and activity events, plus the total event count;
- configured applications and which of them have **no plugin** (so can't launch);
- the last **build error** (Nuitka stderr tail), persisted on build failure.

From those it derives deterministic *observations* (e.g. "the agent is stale",
"these apps have no plugin", "the last build failed"), then asks the LLM for a
`summary`, `findings` (issue / evidence / severity) and `suggested_changes`
(target / change). The response also returns the raw `signals` so the panel can
show the grounding.

On the agent detail page, a **Behaviour diagnosis** panel runs this on demand
and renders the summary, findings (colour-coded by severity) and suggested
changes.

## LLM provider — free by default

This reuses the existing `LLMProvider` abstraction in `app/llm.py`, same as the
template/plugin generation. The default provider is **Ollama** (`LLM_PROVIDER=ollama`),
a self-hosted, free, local model — nothing is sent to a paid third-party API and
the agent's logs never leave the range. Point `LLM_BASE_URL` / `LLM_MODEL` at
your Ollama instance.

## Best-effort / graceful degradation

The assistant never hard-fails: if the LLM is unavailable or returns invalid
JSON, the endpoint still returns `200` with `source: "unavailable"` and the
deterministic observations as findings, so the operator always gets something
actionable. When the LLM answers, `source` is `"model"`.
