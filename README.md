# LISA

Living Infrastructure Simulation Agent — simulates legitimate ("peaceful") user
activity on VMs for a cyber range. Roles + behavior templates drive agents that
emulate human activity on a schedule.

## Structure

```
backend/    FastAPI + PostgreSQL management API
agent/      POSIX activity agent (Linux + macOS)
frontend/   React + Vite control panel
infra/      docker-compose + deployment
docs/       onboarding & customer docs
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

- Backend API + docs: http://localhost:8000/docs
- Frontend: http://localhost:5173

## Development

See `CONTRIBUTING.md` for the branch/PR workflow. CI runs per component
(path-filtered) on every PR; images are published multi-arch to GHCR from `main`.
