"""Wrap a compiled agent binary into a self-extracting installer.

The installer is a hybrid file: bash header at the top, raw agent bytes
below a marker. When executed on the target VM:

  1. bash reads its own script until the marker
  2. copies everything after the marker to /opt/lisa/agent_<id>
  3. chmod +x, execs it in the background
  4. exits - leaves nothing running of the installer itself

This gives us "pull-model" delivery without a long-lived poller on the VM:
the installer runs once, unpacks the agent, and disappears. The agent that
stays behind is the only LISA artefact on the machine.

The installer has zero outbound network of its own. All bytes it needs are
inside it. Delivery (cloud-init / golden template / hand-run) is a
separate concern; from the installer's point of view it just gets executed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("lisa.builder.installer")

# Sentinel line that marks the boundary between bash header and binary payload.
# Chosen to be very unlikely to appear in a real bash script or ELF file.
_PAYLOAD_MARKER = b"__LISA_AGENT_PAYLOAD_BELOW__"


class InstallerError(RuntimeError):
    """Something went wrong producing the installer artefact."""


@dataclass(frozen=True)
class InstallerArtefact:
    """Result of wrapping a binary. The path is the executable installer."""

    path: Path
    size_bytes: int


def wrap_as_installer(
    agent_binary: Path,
    output_path: Path,
    *,
    agent_id: str,
    install_dir: str = "/opt/lisa",
    target_os: str = "linux",
) -> InstallerArtefact:
    """Produce a self-extracting installer at `output_path`.

    - agent_binary: the binary the compiler just produced.
    - output_path: where to write the installer file.
    - agent_id: used in filenames and log lines on the target VM. Also
      protects concurrent installers from clobbering each other.
    - install_dir: where the Linux installer places the agent on the VM.
      Overridable so tests can use tmp. (macOS ignores this and installs
      per-user under ~/Library — see below.)
    - target_os: shapes how the agent is installed and kept alive. "linux"
      drops the binary and launches it with nohup; "macos" installs a
      per-user LaunchAgent so it starts at login and restarts on crash (#198).

    The output file is chmod +x so it can be executed directly. Fails with
    InstallerError if the input binary is missing or the output path can't
    be written.
    """
    if not agent_binary.is_file():
        raise InstallerError(f"agent binary not found: {agent_binary}")
    if not agent_id:
        raise InstallerError("agent_id must be provided")

    try:
        payload = agent_binary.read_bytes()
    except OSError as exc:
        raise InstallerError(f"could not read agent binary: {exc}") from exc

    if target_os == "macos":
        header_text = _macos_header(agent_id=agent_id)
    elif target_os == "linux":
        header_text = _bash_header(agent_id=agent_id, install_dir=install_dir)
    else:
        raise InstallerError(f"no installer template for target OS {target_os!r}")
    header = header_text.encode("utf-8")

    # Structure: bash header, marker on its own line, then the raw bytes.
    # The header uses `sed` + `tail` to locate the marker and stream the
    # payload out - no need to know the exact byte offset ahead of time.
    contents = header + b"\n" + _PAYLOAD_MARKER + b"\n" + payload

    try:
        output_path.write_bytes(contents)
        output_path.chmod(0o755)
    except OSError as exc:
        raise InstallerError(f"could not write installer to {output_path}: {exc}") from exc

    log.info(
        "wrote installer for %s to %s (%d bytes)",
        agent_id,
        output_path,
        len(contents),
    )
    return InstallerArtefact(path=output_path, size_bytes=len(contents))


def _bash_header(*, agent_id: str, install_dir: str) -> str:
    """The bash script that extracts and launches the agent.

    Kept small and readable - an operator can `head` the installer file and
    understand what it will do. Uses only /bin/sh-compatible builtins so it
    works on minimal VMs that lack bash proper.

    After launching, waits a moment and checks the agent is still alive.
    A broken binary (missing lib, crash on startup) would nohup+background
    cleanly, and the installer would report success even though nothing is
    running. The kill -0 check catches this so callers see a nonzero exit
    when the agent didn't actually stay up.
    """
    marker = _PAYLOAD_MARKER.decode("ascii")
    # Path where the agent will end up on the VM. agent_id in the name so
    # two installers for two different agents don't fight over the same file.
    agent_path = f"{install_dir}/agent_{agent_id}"
    return f"""#!/bin/sh
# LISA agent installer for {agent_id}. Self-extracting: script + binary.
# Runs once, drops the agent, launches it in the background, exits.
set -e

install_dir='{install_dir}'
agent_path='{agent_path}'

mkdir -p "$install_dir"

# Copy everything after the marker line into the agent binary. `sed` prints
# lines strictly after the match, so the marker itself is not included.
sed -e '1,/^{marker}$/d' "$0" > "$agent_path"
chmod +x "$agent_path"

# Launch detached from this shell so the installer can exit cleanly.
# nohup + & keeps the agent alive after the installer process ends.
nohup "$agent_path" >/dev/null 2>&1 &
agent_pid=$!

# Give the agent a moment to fail fast (missing lib, crash on startup),
# then check it's actually still alive. Without this, a broken binary would
# nohup+background cleanly and we'd exit 0 while nothing is really running.
sleep 1
if ! kill -0 "$agent_pid" 2>/dev/null; then
    echo "installer: agent process died within a second of launch" >&2
    exit 1
fi

# Successful exit. Anything after this line is the binary payload and must
# never be interpreted as script - `exit 0` above ends execution first.
exit 0
"""


def _macos_header(*, agent_id: str) -> str:
    """Self-extracting installer that registers the agent as a per-user
    LaunchAgent (issue #198).

    LaunchAgents run as the logged-in user, so everything lives under
    ~/Library (no root, no /opt). `RunAtLoad` starts the agent at login and
    `KeepAlive` restarts it if it crashes — the persistence Linux gets from
    being relaunched is provided here by launchd. An `uninstall.sh` is dropped
    beside the binary so the agent can be removed cleanly.

    Like the Linux header this is /bin/sh + `sed` self-extraction; only the
    install/launch tail differs.
    """
    marker = _PAYLOAD_MARKER.decode("ascii")
    label = f"com.lisa.agent.{agent_id}"
    return f"""#!/bin/sh
# LISA agent installer for {agent_id} (macOS). Self-extracting: script + binary.
# Installs a per-user LaunchAgent so the agent starts at login and is kept
# alive by launchd, then exits.
set -e

label='{label}'
app_support="$HOME/Library/Application Support/lisa"
agents_dir="$HOME/Library/LaunchAgents"
agent_path="$app_support/agent_{agent_id}"
plist="$agents_dir/$label.plist"
uninstall="$app_support/uninstall_{agent_id}.sh"

mkdir -p "$app_support" "$agents_dir"

# Copy everything after the marker line into the agent binary. `sed` prints
# lines strictly after the match, so the marker itself is not included.
sed -e '1,/^{marker}$/d' "$0" > "$agent_path"
chmod +x "$agent_path"

# LaunchAgent definition: start at login, restart on crash, logs discarded.
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key><array><string>$agent_path</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/dev/null</string>
    <key>StandardErrorPath</key><string>/dev/null</string>
</dict>
</plist>
PLIST

# Drop a matching uninstaller so the agent can be removed cleanly.
cat > "$uninstall" <<UNINSTALL
#!/bin/sh
launchctl unload "$plist" 2>/dev/null || true
rm -f "$plist" "$agent_path" "$uninstall"
UNINSTALL
chmod +x "$uninstall"

# (Re)load the LaunchAgent. Unload first so re-running the installer updates
# a previous copy instead of failing on an already-loaded label.
launchctl unload "$plist" 2>/dev/null || true
launchctl load "$plist"

# Confirm launchd actually registered it; otherwise report failure so the
# operator doesn't think a dead install succeeded.
sleep 1
if ! launchctl list | grep -q "$label"; then
    echo "installer: launchd did not register $label" >&2
    exit 1
fi

# Successful exit. Anything after this line is the binary payload and must
# never be interpreted as script - `exit 0` above ends execution first.
exit 0
"""
