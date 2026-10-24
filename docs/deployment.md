# Deploying LISA agents

The builder produces two artefacts per agent:

- **`installer_<id>.sh`** — self-extracting installer, ~30 MB. Bash script
  wrapping the agent binary. One-shot: extracts, launches, exits. Leaves
  only the agent process behind.
- **`agent_<id>`** — raw Nuitka ELF, ~28 MB. Same agent, no wrapper.

Both are served by `GET /api/builds/{agent_id}/{filename}`. Which one you
use depends on how you get files onto the target VM. Below are the three
patterns we support out of the box. They're not exclusive — the same
installer works in all three.

---

## Pattern 1: cloud-init (VMs created via hypervisor API)

Use this when target VMs are provisioned through Proxmox / VMware / KVM /
libvirt / OpenStack — anything that accepts a cloud-init `user-data`
block at first boot.

Put the following in `user-data` when creating the VM:

```yaml
#cloud-config
runcmd:
  - curl -sSfL http://backend:8000/api/builds/USR001/installer_USR001.sh -o /tmp/lisa-installer.sh
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
# 1. Fetch the installer from the backend
curl -sSfL http://backend:8000/api/builds/USR001/installer_USR001.sh -o installer.sh

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
ansible-playbook deploy-agents.yml -e lisa_agent_backend_url=http://backend:8000
```

Update a deployed fleet (on Linux this stops the running agent first, since the
Linux installer has no stop step; macOS reloads its LaunchAgent itself):

```sh
ansible-playbook deploy-agents.yml \
    -e lisa_agent_backend_url=http://backend:8000 -e lisa_agent_force_reinstall=true
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

---

## Build workers (per OS)

Nuitka compiles for the host it runs on and cannot cross-compile, so there is
one build worker per target OS, each draining its own Redis queue
(`lisa:builder:jobs:<os>`). A worker only pops jobs for the OS it can build, so
a Linux worker never picks up a macOS job and vice versa.

- **Linux** is built by the `builder` service in `docker-compose.yml` (runs on
  `linux/amd64`). This is the default; `BUILDABLE_OS=["linux"]`.
- **macOS** needs a worker running on a Mac. Nuitka can't produce a Mach-O
  binary from Linux.

### Running a macOS build worker

On a macOS host that can reach the same Postgres and Redis as the backend:

```sh
pip install -r backend/requirements.txt nuitka
export LISA_AGENT_SOURCE_ROOT="$PWD/agent/lisa_agent"
export LISA_BACKEND_URL="https://<backend-host>"   # what the agent phones home to
export DATABASE_URL=...        # same DB as the backend
export REDIS_URL=...           # same Redis as the backend
python -m app.services.agent_builder   # from backend/, drains the macos queue
```

The worker logs `os=macos queue=lisa:builder:jobs:macos` on startup. Then tell
the backend a macOS worker exists so it enqueues macOS builds instead of
refusing them:

```sh
# backend environment
BUILDABLE_OS=["linux", "macos"]
```

Without this, a macOS agent is created but its build status is `unsupported_os`
and nothing is queued (so it never hangs waiting for a worker that isn't there).

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
