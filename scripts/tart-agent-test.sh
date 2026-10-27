#!/usr/bin/env bash
#
# End-to-end test of a LISA macOS agent installer inside a throwaway tart VM.
#
# DEVELOPER TOOL, not a deployment path. This exists so we can smoke-test the
# macOS installer on a clean VM while working on LISA. Operators deploying to a
# range never use this or install tart — they deploy to their own range hosts
# (see docs/deployment.md).
#
# Builds nothing — it takes an already-built agent (its installer), spins up a
# fresh macOS VM with tart, runs the installer there, and checks the agent
# registered with launchd. The installer only ever runs INSIDE the VM, never on
# the host (the agent is a KeepAlive LaunchAgent; keeping it off the host is the
# whole point of testing in a VM).
#
# Requirements: Apple Silicon host, `tart` (brew install cirruslabs/cli/tart),
# and a reachable LISA backend serving the installer.
#
# Usage:
#   scripts/tart-agent-test.sh <AGENT_ID> [installer.sh]
#       Create/boot the VM, install the agent, verify it. If no installer file
#       is given it is downloaded from $DOWNLOAD_URL.
#   scripts/tart-agent-test.sh --cleanup
#       Uninstall the agent in the VM (best effort), stop and delete the VM.
#
# Env overrides:
#   VM_NAME       VM name (default: lisa-test)
#   BASE_IMAGE    tart base image (default: ghcr.io/cirruslabs/macos-sequoia-base:latest)
#   VM_USER       SSH user in the image (default: admin; password: admin)
#   DOWNLOAD_URL  where to fetch the installer from (default: http://localhost:8000)
set -euo pipefail

VM_NAME="${VM_NAME:-lisa-test}"
BASE_IMAGE="${BASE_IMAGE:-ghcr.io/cirruslabs/macos-sequoia-base:latest}"
VM_USER="${VM_USER:-admin}"
DOWNLOAD_URL="${DOWNLOAD_URL:-http://localhost:8000}"

# One SSH control connection reused by every ssh/scp call below, so the VM
# password (admin) is typed once, not on every step.
SSH_CTL="/tmp/lisa-tart-${VM_NAME}.ctl"
SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -o ControlMaster=auto
  -o "ControlPath=${SSH_CTL}"
  -o ControlPersist=120
)

die() { echo "error: $*" >&2; exit 1; }
info() { echo ">> $*"; }

vm_ssh() { ssh "${SSH_OPTS[@]}" "${VM_USER}@${VM_IP}" "$@"; }

require_tart() {
  command -v tart >/dev/null 2>&1 || die "tart not found (brew install cirruslabs/cli/tart)"
  [ "$(uname -m)" = "arm64" ] || die "tart needs Apple Silicon (host is $(uname -m))"
}

cleanup() {
  require_tart
  if tart list 2>/dev/null | grep -qw "${VM_NAME}"; then
    VM_IP="$(tart ip "${VM_NAME}" 2>/dev/null || true)"
    if [ -n "${VM_IP:-}" ] && [ -n "${AGENT_ID:-}" ]; then
      info "uninstalling agent in VM (best effort)"
      vm_ssh "\"\$HOME/Library/Application Support/lisa/uninstall_${AGENT_ID}.sh\"" || true
    fi
    info "stopping and deleting VM ${VM_NAME}"
    tart stop "${VM_NAME}" 2>/dev/null || true
    tart delete "${VM_NAME}"
  else
    info "no VM named ${VM_NAME}"
  fi
  rm -f "${SSH_CTL}"
  info "done"
}

main() {
  AGENT_ID="$1"
  local installer="${2:-}"

  require_tart

  if ! tart list 2>/dev/null | grep -qw "${VM_NAME}"; then
    info "cloning ${BASE_IMAGE} -> ${VM_NAME} (first pull is large)"
    tart clone "${BASE_IMAGE}" "${VM_NAME}"
  fi

  info "booting ${VM_NAME} (headless)"
  tart run --no-graphics "${VM_NAME}" >/dev/null 2>&1 &

  info "waiting for VM IP"
  VM_IP=""
  for _ in $(seq 1 60); do
    VM_IP="$(tart ip "${VM_NAME}" 2>/dev/null || true)"
    [ -n "${VM_IP}" ] && break
    sleep 2
  done
  [ -n "${VM_IP}" ] || die "VM did not get an IP in time"
  info "VM IP: ${VM_IP}"

  info "waiting for SSH (password is '${VM_USER}')"
  for _ in $(seq 1 60); do
    vm_ssh true 2>/dev/null && break
    sleep 2
  done
  vm_ssh true 2>/dev/null || die "SSH to VM failed"

  if [ -z "${installer}" ]; then
    installer="$(mktemp -t lisa-installer).sh"
    info "downloading installer for ${AGENT_ID} from ${DOWNLOAD_URL}"
    curl -fsSL "${DOWNLOAD_URL}/api/builds/${AGENT_ID}/installer_${AGENT_ID}.sh" -o "${installer}" \
      || die "could not download installer (is ${AGENT_ID} built?)"
  fi
  [ -f "${installer}" ] || die "installer not found: ${installer}"
  info "installer: ${installer} ($(du -h "${installer}" | cut -f1))"

  info "copying + running installer inside VM"
  scp "${SSH_OPTS[@]}" "${installer}" "${VM_USER}@${VM_IP}:/tmp/installer.sh"
  vm_ssh "chmod +x /tmp/installer.sh && /tmp/installer.sh"

  info "verifying the agent registered with launchd"
  if vm_ssh "launchctl list | grep -q com.lisa.agent.${AGENT_ID}"; then
    info "OK: com.lisa.agent.${AGENT_ID} is loaded in the VM"
  else
    die "agent did not register (check the installer output above)"
  fi

  cat <<EOF

Done. The agent is running inside VM '${VM_NAME}' (${VM_IP}).
- Watch the panel for heartbeats from ${AGENT_ID} (needs the binary's
  LISA_BACKEND_URL to be reachable from the VM).
- Tear everything down with:
      AGENT_ID=${AGENT_ID} VM_NAME=${VM_NAME} scripts/tart-agent-test.sh --cleanup
EOF
}

if [ "${1:-}" = "--cleanup" ]; then
  AGENT_ID="${AGENT_ID:-}"
  cleanup
elif [ -n "${1:-}" ]; then
  main "$@"
else
  grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed -n '2,40p'
  exit 1
fi
