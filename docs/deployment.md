# Deploying LISA agents

The builder produces two artefacts per agent:

- **the installer** — self-extracting, ~30 MB, one-shot (extracts, launches,
  exits, leaves only the agent process behind). On Linux/macOS it is a
  `/bin/sh` script, **`installer_<id>.sh`**; on Windows it is a PowerShell
  script, **`installer_<id>.ps1`**, that carries the agent as base64 inside it.
- **the raw binary** — ~28 MB, same agent, no wrapper: a Nuitka ELF on Linux
  (**`agent_<id>`**), a Mach-O on macOS, a PE on Windows (**`agent_<id>.exe`**).

Both are served by `GET /api/builds/{agent_id}/{filename}`. This endpoint is
authenticated (#202): the artefact embeds the agent's token, so it is not
world-readable. The operator panel's download buttons work out of the box — it
mints a short-lived, single-file download token and appends it to the link. For
scripted downloads (curl, Ansible) pass an operator token obtained from
`POST /api/auth/login`, either as `Authorization: Bearer <token>` or as a
`?token=<token>` query parameter. When the backend runs in dev mode (no
`OPERATOR_PASSWORD` set) the endpoint is open and no token is needed.

Which artefact you use depends on how you get files onto the target VM. Below
are the three patterns we support out of the box. They're not exclusive — the
same installer works in all three. The Linux examples below use the `.sh`
installer; for a Windows target substitute the `.ps1` (see the Windows section).

---

## Pattern 1: cloud-init (VMs created via hypervisor API)

Use this when target VMs are provisioned through Proxmox / VMware / KVM /
libvirt / OpenStack — anything that accepts a cloud-init `user-data`
block at first boot.

Put the following in `user-data` when creating the VM:

```yaml
#cloud-config
runcmd:
  - curl -sSfL -H "Authorization: Bearer $LISA_API_TOKEN" https://backend:8000/api/builds/USR001/installer_USR001.sh -o /tmp/lisa-installer.sh
  - chmod +x /tmp/lisa-installer.sh
  - /tmp/lisa-installer.sh
```

Replace `USR001` with the actual agent ID and `backend:8000` with the
reachable address of the LISA backend from inside the polygon network.

The installer will unpack the agent into `/opt/lisa/agent_USR001` and
launch it in the background. On the second boot the file at `/tmp/` is
gone but the agent has already been placed and is running from `/opt/lisa`.

**Note on outbound network:** cloud-init needs network access to fetch
the installer, but that's on the delivery layer — not the installer
itself. The installer contains everything it needs; once it's on disk,
it does not touch the network at all.

---

## Pattern 2: golden template (installer baked into the VM image)

Use this when you keep a canonical VM image (a "golden template") that's
cloned per exercise. The installer is placed into the image once at build
time; every clone runs it at first boot.

Prepare the golden image:

1. Boot a fresh VM from a stock base image.
2. Download the installer from the backend (or copy via SCP).
3. Place it at a first-boot hook — e.g. as `/etc/rc.local` or a
   systemd oneshot unit:

```ini
   # /etc/systemd/system/lisa-firstboot.service
   [Unit]
   Description=LISA agent installer (first boot only)
   ConditionFirstBoot=yes

   [Service]
   Type=oneshot
   ExecStart=/opt/lisa-installer.sh
   RemainAfterExit=no

   [Install]
   WantedBy=multi-user.target
```

```sh
   sudo systemctl enable lisa-firstboot.service
```

4. Shut down and snapshot the image.

Every VM cloned from this template will run the installer exactly once
at first boot. Subsequent boots skip it (`ConditionFirstBoot=yes`).

**Trade-off:** the golden template pattern gives you the strictest
"zero outbound network" story on the VM — the installer is inside the
image, the agent inside the installer, nothing is fetched at run time.
The trade-off is that one image = one agent identity; if you want each
clone to run a different agent config, you need one image per agent,
which doesn't scale. Use this for stable long-lived infrastructure, not
for per-exercise agents.

---

## Pattern 3: manual / SSH (operator drops the file)

Use this when the operator has shell access to the target VM and just
wants to place the agent by hand. No hypervisor API, no golden template
work — the installer is a plain executable, run it however you like.

From the operator's workstation:

```sh
# 1. Fetch the installer from the backend (token from POST /api/auth/login)
curl -sSfL -H "Authorization: Bearer $LISA_API_TOKEN" https://backend:8000/api/builds/USR001/installer_USR001.sh -o installer.sh

# 2. Copy to the target VM
scp installer.sh operator@target-vm:/tmp/

# 3. Run it there
ssh operator@target-vm 'chmod +x /tmp/installer.sh && /tmp/installer.sh'
```

The installer exits with code 0 on success, non-zero (with a message on
stderr) if the agent process died within a second of launch.

**Note:** this pattern requires SSH access from the operator to the VM,
which the earlier patterns avoid. Use it for one-off testing or when
provisioning at scale isn't feasible.

---

## Pattern 4: Ansible orchestration (fleet install/update)

Use this when you have many target hosts reachable over SSH and want to
install or update agents across all of them in one command, instead of
hand-running the installer per host (Pattern 3) or baking one agent per
image (Pattern 2).

A committed Ansible role + playbook lives in `deploy/ansible/`. Each host in
the inventory carries its own `lisa_agent_id`; the role fetches that agent's
installer from `GET /api/builds/{id}/installer_{id}.sh` and runs it, for both
Linux and macOS targets.

```sh
cd deploy/ansible
cp inventory.example.ini inventory.ini    # one host line per target, each with its lisa_agent_id
ansible-playbook deploy-agents.yml -e lisa_agent_backend_url=https://backend:8000
```

The agent requires an `https` backend URL so its token and heartbeats are
encrypted on the wire (#55). Plaintext `http` is accepted only for a loopback
host (local dev / the build smoke test) or when `LISA_ALLOW_INSECURE_HTTP=1` is
set in the agent's environment for a trusted, isolated network.

Update a deployed fleet (on Linux this stops the running agent first, since the
Linux installer has no stop step; macOS reloads its LaunchAgent itself):

```sh
ansible-playbook deploy-agents.yml \
    -e lisa_agent_backend_url=https://backend:8000 -e lisa_agent_force_reinstall=true
```

A plain re-run without the flag skips hosts that already have the agent, so it's
a safe no-op that only fills in missing hosts. See `deploy/ansible/README.md`
for the full variable reference. The playbook is syntax-checked and
`ansible-lint`ed in CI (`.github/workflows/deploy.yml`).

**Note:** like Pattern 3 this needs SSH from the control node to each target,
but it scales — one inventory, one command for the whole range.

### From the panel

The same orchestration can be triggered from the operator panel for a built
agent, so you don't have to drop to a shell. On an agent's detail page (once it
has a build) a **Deploy to hosts** panel takes a list of target hosts (and an
optional SSH user); the backend renders an inventory, runs the committed
playbook, and reflects each deployment's status (`pending` → `running` →
`succeeded` / `failed`) back in a table below the form. "Force reinstall"
maps to `lisa_agent_force_reinstall`.

Under the hood:

- `POST /api/agents/{id}/deploy` with `{ "targets": [{ "host": "...", "ssh_user": "..." }], "force": false }`
  creates a deployment and kicks off the run in the background.
- `GET /api/agents/{id}/deployments` lists recent deployments; `GET /api/deployments/{id}`
  is one deployment with its return code and output tail.

All target hosts receive the agent named in the path (one agent → many hosts).
Both routes require an operator token.

**Backend requirements.** Panel deployment runs `ansible-playbook` on the
backend host, so that host needs `ansible-playbook` on `PATH`, the committed
`deploy/ansible/` tree (set `LISA_ANSIBLE_DIR` if it isn't at the repo's default
location), and SSH reachability to the targets. The stock backend image stays
lean and ships **without** ansible; where it isn't installed, a deployment is
recorded as `unavailable` with a message pointing back to the committed
playbook, rather than failing silently. Run the backend on a host (or sidecar)
with ansible installed to enable panel deployment, or keep using the committed
playbook directly (above).

---

## What lands on the VM

After the installer runs, the VM has exactly one LISA artefact:

- `/opt/lisa/agent_<id>` — the agent binary, running in the background.

The installer itself is not left behind by design (it's dropped by
whatever delivery pattern you used and does not persist itself). No
polling process, no cron job, no scheduled task, no service outside of
the agent itself. The only LISA activity on the VM is heartbeats and
whatever the agent config tells it to simulate.

If the installer exits non-zero, no agent is running and nothing has
been placed. Rerun the installer once the underlying issue is fixed
(usually a broken binary or missing shared library on the VM).

### macOS

A macOS installer (built for `os_type=macos`) installs the agent **per-user**
and registers it with `launchd` so it starts at login and is restarted on
crash. After it runs, the user has:

- `~/Library/Application Support/lisa/agent_<id>` — the agent binary.
- `~/Library/LaunchAgents/com.lisa.agent.<id>.plist` — the LaunchAgent
  (`RunAtLoad` + `KeepAlive`), loaded via `launchctl`.
- `~/Library/Application Support/lisa/uninstall_<id>.sh` — the uninstaller.

macOS surfaces this in **System Settings → General → Login Items & Extensions**
as a background item ("… can run in the background").

**Removing a macOS agent.** `KeepAlive` means `launchd` relaunches the agent if
you just `kill` the process — you must unload the LaunchAgent. Use the
uninstaller the installer dropped:

```sh
"$HOME/Library/Application Support/lisa/uninstall_<id>.sh"
```

or do it by hand:

```sh
launchctl unload "$HOME/Library/LaunchAgents/com.lisa.agent.<id>.plist"
rm -f "$HOME/Library/LaunchAgents/com.lisa.agent.<id>.plist" \
      "$HOME/Library/Application Support/lisa/agent_<id>"
```

Verify it's gone with `launchctl list | grep lisa` (should print nothing).

**Testing a macOS agent in a throwaway VM.** Because the macOS installer
registers a `KeepAlive` LaunchAgent, test it inside a disposable VM, not on your
own Mac. On Apple Silicon, `scripts/tart-agent-test.sh <agent-id>` spins up a
fresh [tart](https://tart.run) macOS VM, runs the installer there, and verifies
the agent registered with launchd; `scripts/tart-agent-test.sh --cleanup` tears
the VM down again. See the script header for options.

### Windows

A Windows installer (built for `os_type=windows`) is a PowerShell script,
`installer_<id>.ps1`. It installs the agent **per-user** and registers a
scheduled task so it starts at logon — the Windows analogue of the macOS
LaunchAgent. Run it from a PowerShell prompt:

```powershell
# Fetch and run (per-user, no admin needed)
Invoke-WebRequest http://backend:8000/api/builds/USR001/installer_USR001.ps1 -OutFile installer.ps1
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

`-ExecutionPolicy Bypass` is needed because the script is unsigned; it applies
only to that one invocation. After it runs, the user has:

- `%LOCALAPPDATA%\lisa\agent_<id>.exe` — the agent binary.
- a scheduled task **`LISA Agent <id>`** (`schtasks /Query /TN "LISA Agent <id>"`),
  trigger `ONLOGON`, which launches the agent and survives reboots.
- `%LOCALAPPDATA%\lisa\uninstall_<id>.ps1` — the uninstaller.

The installer launches the agent immediately and exits non-zero if it didn't
stay alive, so a broken build is reported rather than silently missing.

**Removing a Windows agent.** Run the uninstaller the installer dropped:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\lisa\uninstall_<id>.ps1"
```

or do it by hand:

```powershell
schtasks /Delete /TN "LISA Agent <id>" /F
Stop-Process -Name "agent_<id>" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\lisa\agent_<id>.exe"
```

Verify it's gone with `schtasks /Query /TN "LISA Agent <id>"` (should report no
such task).

Note: the scheduled task starts the agent at logon but, unlike macOS
`KeepAlive`, does not auto-restart it if it crashes mid-session; the agent's
own single-instance mutex still ensures a rebuild/redeploy replaces a running
copy.

---

## Build workers (per OS)

Nuitka compiles for the host it runs on and cannot cross-compile, so there is
one build worker per target OS, each draining its own Redis queue
(`lisa:builder:jobs:<os>`). A worker only pops jobs for the OS it can build, so
a Linux worker never picks up a macOS job and vice versa.

**Shared artefact storage.** Built artefacts are written to (and served from)
`LISA_BUILDS_DIR` (default `/var/lisa/builds`). The compose stack bind-mounts a
host directory there — `${LISA_BUILDS_DIR:-./.builds}` — for the backend and the
Linux builder. A worker running *outside* the container (macOS/Windows) can't
use that bind, so point it at the **same host directory** via `LISA_BUILDS_DIR`;
otherwise the worker builds fine but the backend can't serve the installer (the
panel's download and Ansible fetch would 404).

- **Linux** is built by the `builder` service in `docker-compose.yml` (runs on
  `linux/amd64`). This is the default; `BUILDABLE_OS=["linux"]`.
- **macOS** needs a worker running on a Mac. Nuitka can't produce a Mach-O
  binary from Linux.
- **Windows** needs a worker running on Windows. Nuitka can't produce a PE
  (`.exe`) from Linux or macOS.

### Running a macOS build worker

On a macOS host that can reach the same Postgres and Redis as the backend:

```sh
pip install -r backend/requirements.txt nuitka
export LISA_AGENT_SOURCE_ROOT="$PWD/agent/lisa_agent"
export LISA_BACKEND_URL="https://<backend-host>"   # what the agent phones home to
export DATABASE_URL=...        # same DB as the backend
export REDIS_URL=...           # same Redis as the backend
export LISA_BUILDS_DIR="$PWD/.builds"   # SAME host dir the backend bind-mounts
python -m app.services.agent_builder   # from backend/, drains the macos queue
```

`LISA_BUILDS_DIR` must resolve to the same host directory the backend serves
from (the compose bind, `./.builds` by default) so the worker's installer is
downloadable from the panel. Without it the worker falls back to
`/var/lisa/builds`, which the containerised backend never sees.

The worker logs `os=macos queue=lisa:builder:jobs:macos` on startup. Then tell
the backend a macOS worker exists so it enqueues macOS builds instead of
refusing them:

```sh
# backend environment
BUILDABLE_OS=["linux", "macos"]
```

Without this, a macOS agent is created but its build status is `unsupported_os`
and nothing is queued (so it never hangs waiting for a worker that isn't there).

### Running a Windows build worker

On a Windows host that can reach the same Postgres and Redis as the backend,
with Python 3.12 and a C toolchain Nuitka can use (MSVC Build Tools, or let
Nuitka download MinGW on first run):

```powershell
pip install -r backend/requirements.txt nuitka
$env:LISA_AGENT_SOURCE_ROOT = "$PWD\agent\lisa_agent"
$env:LISA_BACKEND_URL = "https://<backend-host>"   # what the agent phones home to
$env:DATABASE_URL = "..."       # same DB as the backend
$env:REDIS_URL = "..."          # same Redis as the backend
python -m app.services.agent_builder   # from backend\, drains the windows queue
```

The worker logs `os=windows queue=lisa:builder:jobs:windows` on startup. Then
add Windows to the backend's buildable set so it enqueues Windows builds:

```sh
# backend environment
BUILDABLE_OS=["linux", "windows"]
```

As with macOS, without this a Windows agent is created but its build status is
`unsupported_os` and nothing is queued.

---

## Troubleshooting

**Installer says "agent process died within a second of launch":**
the binary itself is crashing on startup. Common causes:

- Missing shared library on the VM. Nuitka bakes CPython in but not
  system libs. Check with `ldd /opt/lisa/agent_<id>` on the VM.
- Wrong architecture. Building on x86_64 doesn't produce ARM binaries.
- Bad `.env` — the agent needs `LISA_BACKEND_URL` reachable from the VM.

The installer places the binary before running it, so the file will be
sitting at `/opt/lisa/agent_<id>` even after a failed launch. Run it
directly to see the actual error:

```sh
/opt/lisa/agent_<id>
```

**Installer says "extract failed":** the payload marker inside the
installer was corrupted in transit. Re-download from the backend and
verify the file size matches the `Content-Length` from the response.
