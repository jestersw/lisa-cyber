# Ansible deployment orchestration

Push and update LISA agents onto a fleet of target hosts without hand-running
the installer on each one. This is the Ansible backend for the deployment
orchestration described in the spec (*"Управление развертыванием … Ansible …"*,
issue #212).

The role fetches an agent's self-extracting installer from the backend's build
endpoint and runs it on the target:

```
GET {{ lisa_agent_backend_url }}/api/builds/{{ lisa_agent_id }}/installer_{{ lisa_agent_id }}.sh
```

That endpoint is authenticated (#202). Unless the backend runs in dev mode (no
operator password), set `lisa_agent_api_token` to an operator token (from
`POST /api/auth/login`) and the role sends it as a `Bearer` header on the
download. `lisa_agent_backend_url` should be `https` (the agent requires it,
#55).

Each host runs exactly one agent, identified by its `lisa_agent_id`. Linux and
macOS are supported (Windows is tracked in #200).

## Prerequisites

- Ansible 2.14+ on the operator's workstation (`pip install ansible`).
- SSH access from the workstation to each target host.
- The target hosts can reach `lisa_agent_backend_url` to pull their installer.
- The agent for each host has already been **built** (its installer exists at
  the build endpoint — `status: completed` in the panel). The builder only
  produces an installer once `BUILDABLE_OS` includes the host's OS.

## Quick start

1. Copy the example inventory and edit it for your range:

   ```sh
   cp inventory.example.ini inventory.ini
   # set one host line per target, each with its own lisa_agent_id
   ```

2. Deploy:

   ```sh
   ansible-playbook deploy-agents.yml \
     -e lisa_agent_backend_url=https://backend:8000 \
     -e lisa_agent_api_token="$LISA_API_TOKEN"
   ```

   (`ansible.cfg` points `inventory` at `inventory.ini`, so `-i` is optional.)

## Updating a deployed fleet

Re-run with `lisa_agent_force_reinstall=true`. On Linux the role stops the running
agent before re-installing (the Linux installer has no stop step, so this
avoids leaving two agent processes); on macOS the installer reloads its own
LaunchAgent, so the update is handled for you:

```sh
ansible-playbook deploy-agents.yml \
    -e lisa_agent_backend_url=https://backend:8000 \
    -e lisa_agent_api_token="$LISA_API_TOKEN" \
    -e lisa_agent_force_reinstall=true
```

Without the flag, hosts that already have the agent are skipped (reported via a
`debug` task), so a plain re-run is a safe no-op that only fills in missing
hosts.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `lisa_agent_backend_url` | `https://backend:8000` | Backend serving the installers (agent requires https, #55). |
| `lisa_agent_api_token` | `""` | Operator token for the authenticated installer download (#202). Empty = dev-mode backend (open). |
| `lisa_agent_id` | `""` (**required per host**) | Agent identity for the host. Set as a host var. |
| `lisa_agent_force_reinstall` | `false` | Re-deploy even if already installed (and stop the old Linux process first). |
| `lisa_agent_linux_install_dir` | `/opt/lisa` | Where the Linux installer places the binary; used to detect an existing install. |
| `lisa_agent_download_token` | `""` | Token for fetching the installer when build downloads are guarded (#202). The panel-triggered deploy sets it automatically; for a manual run against a locked backend pass an operator token (`-e lisa_agent_download_token=...`). Leave empty for an open/dev backend. |

## What the role does

- **Linux** (`roles/lisa_agent/tasks/linux.yml`): stops any running agent on an
  update, fetches the installer, runs it (drops `/opt/lisa/agent_<id>`, launches
  it with `nohup`), then removes the staged installer.
- **macOS** (`roles/lisa_agent/tasks/darwin.yml`): fetches and runs the
  installer, which registers a per-user LaunchAgent (`RunAtLoad` + `KeepAlive`)
  and reloads a previous copy on update.

Both OS installers self-check after launch and exit non-zero if the agent
didn't actually start, so a failed install fails the play instead of reporting
a false success.

## Syntax check

```sh
ansible-playbook deploy-agents.yml --syntax-check -i inventory.example.ini
```

CI runs this plus `ansible-lint` on every change under `deploy/ansible/` (see
`.github/workflows/deploy.yml`).
