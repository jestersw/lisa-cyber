# LISA

**Living Infrastructure Simulator Agent** — a system that generates realistic,
benign ("peaceful") user activity inside an isolated cyber-range so that defensive
teams can train detection and incident analysis against a lifelike background.

Blue teams learn to spot real malicious behavior, not the training harness itself.
The activity LISA produces — opening documents, browsing, working in a terminal,
touching files, initiating routine network traffic — is exactly the everyday noise
that monitoring tools (SIEM, NTA, EDR) record in a live environment.

## Design principle

The agent is an immutable, invisible artifact. Its configuration is baked into the
binary at build time; it carries no runtime control channel beyond a heartbeat.
Changing an agent's behavior means rebuilding and redeploying it, the way container
images are replaced rather than patched in place. This keeps LISA from becoming a
detectable tell: a defender monitoring a range VM should see simulated user activity,
not a piece of range infrastructure calling home.

Delivery follows the same rule. The builder emits a self-contained installer with the
agent baked inside — it installs, launches, and exits, leaving only the agent on the
VM, with no standing process polling the backend.

## How it works

1. An analyst defines a pseudo-user in the control panel: a role (developer, admin,
   user), an activity pool (applications, logins), and a schedule (workdays, hours).
2. The API enqueues a build. A worker compiles the agent with nuitka, bakes in the
   configuration, wraps the binary into a self-extracting installer, and stores both.
3. The agent's status moves `configured -> building -> ready`, and its binary and
   installer URLs are published.
4. The analyst downloads the installer and places it on a range VM — via cloud-init,
   a golden template, or by hand.
5. The installer extracts and launches the agent, which runs role-based activity on a
   pseudo-random schedule and sends heartbeats.
6. The panel shows the agent live: status, last seen, recent heartbeats, and the
   next-activity prediction produced from a per-role transition model.

## Architecture

- **Control panel** — a React web interface to create roles and agents, manage
  behavior templates, monitor agent status and logs, and download installers.
- **Management API** — a FastAPI service backed by PostgreSQL that owns agents,
  templates, deployment packages, and heartbeats, and enqueues builds through Redis.
- **Build pipeline** — a worker that turns a configuration into an immutable ELF via
  nuitka and packages it as a self-contained installer.
- **Agent** — a cross-platform activity simulator (Linux, macOS, Windows) that
  emulates a role on a schedule, runs as an unprivileged local user, and reports
  back by heartbeat.
- **Trainer** — an ML service that learns a per-role transition model the agent uses
  to choose realistic next actions; behavior templates can also be generated from a
  natural-language description via an LLM.

## Repository layout
backend/ FastAPI management API, build worker, ML trainer entrypoints
frontend/ React + Vite control panel
agent/ cross-platform activity agent and self-contained installer builder
ml/ transition-model training
docs/ onboarding, deployment, agent config schema, design notes
scripts/ operational scripts (backend build-to-installer smoke)
infra/ deployment assets

## Tech stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, nuitka
- Frontend: React, React Router, Vite, TypeScript
- Agent: Python packaged to a Linux ELF, delivered as a self-extracting installer
- Infrastructure: Docker Compose; CI on GitHub Actions, path-filtered per component

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

- Management API and interactive docs: http://localhost:8000/docs
- Control panel (development server): http://localhost:5173

Once the stack is up, create an agent in the panel, wait for its status to reach
`ready`, and download the installer. To verify the build-to-installer path end to end
against a running stack:

```bash
./scripts/smoke_backend.sh
```

## Deployment

The builder produces the installer as a plain file; how it reaches a range VM is a
deployment choice — cloud-init user-data, a golden VM template, or manual copy. See
`docs/deployment.md` for the options and examples.

## Scope

The agent runs on Linux, macOS and Windows range VMs from one codebase. Because Nuitka
compiles for the host it runs on and cannot cross-compile, each OS is built by a build
worker running on that OS, draining its own queue; the backend only enqueues builds for
OSes a worker exists for (`BUILDABLE_OS`). Linux is the default worker shipped in
`docker-compose.yml`; see `docs/deployment.md` for standing up macOS and Windows
workers. Builds are x86_64.

## Intended use

LISA is built for isolated training and evaluation environments — cyber ranges and lab
infrastructure you own or are authorized to operate. See `SECURITY.md`.
