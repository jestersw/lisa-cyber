"""Render an Ansible inventory for a panel-triggered deployment.

The committed role/playbook (deploy/ansible/, #212) expect one inventory group
per OS (`lisa_linux` / `lisa_macos`) and a per-host (or per-group) `lisa_agent_id`.
A panel deployment pushes *one* agent onto many hosts, so every host gets the
same `lisa_agent_id` as a group var and lands in the group for the agent's OS.

The host/user values come straight from operator input, so they are quoted/validated
before they reach the file. The schema (DeployTarget) already restricts them to a
conservative charset; this module is the second line of defence and also keeps the
rendering logic in one testable place.
"""

from __future__ import annotations

import re

# OS -> inventory group name the playbook iterates over.
_GROUP_FOR_OS = {"linux": "lisa_linux", "macos": "lisa_macos"}

# Linux installs to /opt/lisa (needs root); macOS installs per-user (no root).
_DEFAULT_BECOME = {"linux": True, "macos": False}

# Belt-and-braces validation mirroring the DeployTarget schema, so a caller
# that bypasses the schema still can't inject inventory/shell syntax.
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


class InventoryError(ValueError):
    """A target or agent id can't be rendered into a safe inventory."""


def group_for_os(os_type: str) -> str:
    group = _GROUP_FOR_OS.get(os_type)
    if group is None:
        raise InventoryError(f"no deployment inventory group for OS {os_type!r}")
    return group


def render_inventory(agent_id: str, os_type: str, targets: list[dict]) -> str:
    """Build an INI inventory placing every target host under the agent's OS
    group, all sharing `agent_id`.

    targets: list of dicts with keys host (required), ssh_user (optional),
    become (optional bool; defaults per-OS).
    """
    if not _SAFE.match(agent_id or ""):
        raise InventoryError(f"unsafe agent_id: {agent_id!r}")
    if not targets:
        raise InventoryError("at least one target host is required")

    group = group_for_os(os_type)
    default_become = _DEFAULT_BECOME[os_type]

    lines = [f"[{group}]"]
    for target in targets:
        host = target.get("host", "")
        if not _SAFE.match(host or ""):
            raise InventoryError(f"unsafe host: {host!r}")
        parts = [host]
        ssh_user = target.get("ssh_user")
        if ssh_user:
            if not _SAFE.match(ssh_user):
                raise InventoryError(f"unsafe ssh_user: {ssh_user!r}")
            parts.append(f"ansible_user={ssh_user}")
        become = target.get("become")
        if become is None:
            become = default_become
        parts.append(f"ansible_become={'true' if become else 'false'}")
        lines.append(" ".join(parts))

    lines.append("")
    lines.append(f"[{group}:vars]")
    lines.append(f"lisa_agent_id={agent_id}")
    lines.append("")
    return "\n".join(lines)
