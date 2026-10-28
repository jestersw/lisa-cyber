# Demo deployment (show-to-customer)

A minimal, public, TLS-secured bring-up of the LISA panel for a live demo. It
runs the panel + API behind Caddy on one origin, with the panel **locked** and
the live Range driven by the server-side **Run simulator** — so you need no real
target hosts, no SSH, and no per-OS build workers.

This is deliberately *not* the full production spec (see issue #234): no build
workers, backups, or observability. It is the slice that lets you show the
product safely over the internet.

What runs: `caddy` (public 80/443) → `backend` (FastAPI) + `frontend` (SPA),
with `postgres` and `redis`. Only Caddy is exposed; everything else is internal.

---

## 1. A server

Anything that runs Docker with a public IP works. These notes target the
**Oracle Cloud Free Tier** (Ampere A1 / ARM — always-on, $0). Our images are
multi-arch, so arm64 builds fine on the box.

1. Create an **Ampere (ARM) VM**, Ubuntu 22.04+, e.g. 2 OCPU / 12 GB.
2. **Open 80 and 443.** Two layers on Oracle:
   - VCN → the subnet's **Security List** → add Ingress rules: source `0.0.0.0/0`, TCP ports `80` and `443`.
   - The Ubuntu image also ships iptables rules that block everything but SSH:
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
3. Install Docker + compose plugin:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER" && newgrp docker
   ```

## 2. A hostname (for a real TLS cert)

Caddy gets a free Let's Encrypt cert automatically — but only for a DNS name,
not a bare IP. If you don't own a domain, use wildcard DNS that maps to your IP:

```
DEMO_DOMAIN=<your-public-ip>.nip.io      # e.g. 203.0.113.10.nip.io
```

`nip.io` / `sslip.io` resolve `<ip>.nip.io` → `<ip>`, so the cert issues with no
DNS setup. With your own domain, point an **A record** at the IP and use that.

## 3. Configure + launch

```bash
git clone https://github.com/jestersw/lisa-cyber.git && cd lisa-cyber

cp deploy/demo/.env.demo.example deploy/demo/.env.demo
# Generate secrets:
openssl rand -base64 32   # -> OPERATOR_PASSWORD
openssl rand -base64 32   # -> JWT_SECRET
openssl rand -base64 32   # -> POSTGRES_PASSWORD
nano deploy/demo/.env.demo    # fill DEMO_DOMAIN + the three secrets

docker compose --env-file deploy/demo/.env.demo -f docker-compose.demo.yml up -d --build
```

Compose **refuses to start** if `OPERATOR_PASSWORD`, `JWT_SECRET`,
`POSTGRES_PASSWORD`, or `DEMO_DOMAIN` is missing — a blank-secret public start is
rejected by design.

First build takes a few minutes (compiling the frontend on ARM). Watch it:
```bash
docker compose -f docker-compose.demo.yml logs -f caddy backend
```

## 4. Show it

1. Open `https://<DEMO_DOMAIN>` — valid padlock, no warning.
2. Log in with `OPERATOR_PASSWORD`.
3. Create a **role** and an **agent**, then open **Range** and hit **Run** on the
   agent: the simulator emits live activity and the agent animates on the range.
   (Seed a role or two before the customer joins so the range isn't empty.)

## 5. Operate

```bash
# Logs
docker compose -f docker-compose.demo.yml logs -f backend

# Update to latest
git pull && docker compose --env-file deploy/demo/.env.demo -f docker-compose.demo.yml up -d --build

# Stop (data persists in named volumes)
docker compose -f docker-compose.demo.yml down

# Back up the database
docker compose -f docker-compose.demo.yml exec -T postgres \
  pg_dump -U lisa lisa > lisa-demo-$(date +%F).sql
```

Data lives in the `pgdata` (Postgres), `models`, and `builds` named volumes and
survives `down`/restarts. `docker compose ... down -v` deletes it.

## Notes / limits

- **Simulator only.** Real agents deployed over SSH (Ansible) are *not* part of
  this demo; that path needs the build workers and target hosts and belongs to
  the full prod spec (#234). The Range shows simulated activity, which is what a
  demo needs.
- **Single origin.** The SPA is built with an empty `VITE_API_URL` and calls
  `/api/*` on the same host; Caddy routes `/api/*` to the backend. No CORS.
- **Secrets** live only in `deploy/demo/.env.demo` (gitignored). Rotate by
  editing it and re-running the `up -d` command.
