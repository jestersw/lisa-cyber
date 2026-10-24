# Security

This document describes the security model of LISA: what the system is, what we
protect, what we deliberately do **not** try to protect against, and the
practices that keep secrets and untrusted input under control.

LISA is a training tool for a cyber range. Its agents simulate ordinary user
activity (opening apps, browsing, editing files) so that SOC analysts can train
against a realistic background of "peaceful" activity. Everything below is
scoped to that purpose and to an **isolated training environment**.

Our goal is not an unbreakable system — that does not exist — but a system with
no obvious, well-known classes of vulnerability (roughly, the OWASP Top 10).

## Assets we protect

- **Backend credentials and agent tokens.** The token an agent uses to talk to
  the backend, and any backend/database credentials.
- **The integrity of the LISA control plane.** The backend API and the panel
  that operators use to create roles, templates, and agents.
- **Operator-authored templates.** Activity templates define what commands an
  agent runs; they are trusted input and must not be modifiable by untrusted
  parties.

## Trust boundaries

- **Operator → LISA.** Operators are trusted. They author roles, templates, and
  decide where agents are deployed.
- **Agent → Backend.** Each agent authenticates to the backend with its own
  bearer token (`LISA_AGENT_TOKEN`), unique per agent and issued per build. The
  backend stores only the token's hash and verifies each agent-facing request
  against that specific agent's token, so a leaked or rotated token affects only
  one agent rather than a shared secret.
- **Backend → Agent.** Configuration and activity templates flow from the
  backend to the agent. The agent treats template command strings as trusted
  (they originate from operators), and runs them via the shell.

## Threats we address

- **Secrets leaking into the repository.** Prevented at two layers: a
  `gitleaks` pre-commit hook and a `security` CI workflow scan the code and full
  history for API keys and passwords. All configuration comes from environment
  variables (`config.py`), documented in `agent/.env.example`; nothing is
  hardcoded. The original agent embedded a DB password and an API key in source
  — that is now gone.
- **Unauthenticated status/telemetry.** The agent sends its heartbeat with an
  `Authorization: Bearer` token so the backend can reject reports from unknown
  agents. (Backend-side verification is tracked in the roadmap below.)
- **A stuck or duplicated agent.** A single-instance mutex ensures only one
  agent runs per identity; a command timeout prevents a hung activity from
  wedging the agent.

## Explicitly out of scope

These are conscious decisions, consistent with the project brief (the focus is
emulating user activity, not attacking or defending the host):

- **Defending the target host against attack.** LISA generates activity; the OS
  and the range's own monitoring (SIEM/EDR/auditd) observe it. Hardening the
  host is out of scope.
- **Malicious activity automation.** Agents simulate legitimate (and, optionally,
  benign-but-suspicious-looking) activity only. Automating genuinely malicious
  actions is explicitly not a goal.

## Security roadmap

Tracks the state of each hardening item. This is a living list.

**Done**
- Secret scanning (`gitleaks`) in pre-commit and CI.
- All secrets moved to environment variables; none hardcoded.
- `.env.example` documenting required configuration.
- Input validation on backend endpoints (#53). Request bodies are Pydantic
  schemas (with a length cap on string fields), list/pagination/threshold query
  parameters are range-bounded, and all DB access goes through the ORM (no raw
  SQL), so malformed, oversized, or out-of-range input is rejected with 422.
- Per-agent backend authentication (#201). Each agent has its own token (hashed
  at rest), and every agent-facing request is verified against that agent's
  token; a missing or wrong token is rejected (dev/unbuilt agents stay open).

**In progress**
- Issuing the per-agent token at install time instead of baking it into the
  built binary (#201 follow-up), so the token never sits in the stored artefact.

**Planned**
- Operator authentication for the web panel. *Open question — not yet designed:*
  the team still needs to decide how operators log in (e.g. username/password,
  session vs. token). Until then the panel must not be exposed outside the
  isolated environment.
- Rejecting unknown fields on request bodies (Pydantic `extra="forbid"`) — a
  stricter follow-up to the input validation above, pending a frontend pass so
  it doesn't break a panel that sends extra keys.
- Rate limiting on public endpoints (e.g. heartbeat) to prevent flooding.
- TLS for agent ↔ backend traffic so tokens can't be intercepted.
- Authorization (not just authentication): decide whether operators are
  restricted to their own agents, or share all of them.

## Practices

- Secrets only via environment variables; never committed. See
  `agent/.env.example`.
- `gitleaks` runs in pre-commit and in CI on every pull request.
- Activity template command strings must come only from trusted, operator-
  authored templates — never from unvalidated external input.
- Agents run as an unprivileged local user and do not require administrator
  rights.

## Reporting

This is a student project developed in the open. If you find a security issue,
open an issue describing it (avoid including live secrets in the report).
