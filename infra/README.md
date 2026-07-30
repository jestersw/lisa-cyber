# infra

## Local (default)
```bash
cp .env.example .env
docker compose up --build
# backend  http://localhost:8000/docs
# frontend http://localhost:5173
```
Agents run in local VMs (Multipass / VirtualBox / Proxmox) on the same network
and send heartbeats to the host's LAN IP. This is the normal mode for a cyber range.

## Remote access without a server
Put the host and all agent VMs on one **Tailscale** tailnet; agents reach the
backend over the private mesh. Nothing is exposed publicly.

## A real always-on box, free
**Oracle Cloud Always Free** ARM VM: put this compose file on it. Images are already
multi-arch (amd64 + arm64) via the docker-publish workflow, so ARM just works.
