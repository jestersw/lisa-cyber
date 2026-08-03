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
