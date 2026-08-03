import stat
import subprocess
import time

import pytest

from app.services.agent_builder.installer import (
    InstallerArtefact,
    InstallerError,
    wrap_as_installer,
)


def _fake_binary(tmp_path, content=b"\x7fELF fake agent binary"):
    p = tmp_path / "agent_USR001"
    p.write_bytes(content)
    return p


# ---------- structure ----------


def test_returns_artefact_with_size(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"

    result = wrap_as_installer(binary, out, agent_id="USR001")

    assert isinstance(result, InstallerArtefact)
    assert result.path == out
    assert result.size_bytes > 0
    assert result.size_bytes == out.stat().st_size


def test_installer_starts_with_shebang(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001")

    contents = out.read_bytes()
    assert contents.startswith(b"#!/bin/sh")


def test_installer_is_executable(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001")

    mode = out.stat().st_mode
    # owner + group + other should have execute
    assert mode & stat.S_IXUSR
    assert mode & stat.S_IXGRP
    assert mode & stat.S_IXOTH


def test_installer_contains_the_payload(tmp_path):
    payload = b"\x7fELF FAKE PAYLOAD DATA"
    binary = _fake_binary(tmp_path, content=payload)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001")

    contents = out.read_bytes()
    # Payload must appear verbatim in the installer.
    assert payload in contents


def test_installer_mentions_agent_id_in_header(tmp_path):
    """Operators reading the installer with `head` should see whose it is."""
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001")

    header = out.read_bytes()[:512].decode("utf-8", errors="replace")
    assert "USR001" in header


def test_install_dir_is_configurable(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001", install_dir="/custom/path")

    header = out.read_bytes()[:1024].decode("utf-8", errors="replace")
    assert "/custom/path" in header


# ---------- end-to-end: actually run the installer ----------
#
# The most valuable test: prove that the installer bash header correctly
# extracts the payload and launches it. We stand in for the agent binary
# with a tiny shell script that writes proof-of-life to a file so we can
# verify it ran.


def test_running_installer_extracts_and_launches_agent(tmp_path):
    # A fake "agent" that just leaves a marker file when run.
    marker_file = tmp_path / "agent_ran.marker"
    fake_agent = tmp_path / "fake_agent"
    fake_agent.write_text(
        f"#!/bin/sh\necho ran > '{marker_file}'\n",
    )
    fake_agent.chmod(0o755)

    installer = tmp_path / "installer.sh"
    install_dir = tmp_path / "install_root"
    wrap_as_installer(fake_agent, installer, agent_id="USR001", install_dir=str(install_dir))

    # Run the installer. It should drop the "agent" into install_dir and
    # background-launch it. We wait briefly for the agent to write its marker.
    subprocess.run([str(installer)], check=True, timeout=10)

    # Wait a moment for the backgrounded process to actually run.
    for _ in range(20):
        if marker_file.exists():
            break
        time.sleep(0.1)

    assert marker_file.exists(), "agent was not launched by the installer"
    assert marker_file.read_text().strip() == "ran"

    # Installer should have placed the agent binary in the install dir.
    placed = install_dir / "agent_USR001"
    assert placed.is_file()
    assert placed.stat().st_mode & stat.S_IXUSR


def test_running_installer_places_agent_with_expected_name(tmp_path):
    fake_agent = tmp_path / "fake_agent"
    fake_agent.write_text("#!/bin/sh\nexit 0\n")
    fake_agent.chmod(0o755)

    installer = tmp_path / "installer.sh"
    install_dir = tmp_path / "install_root"
    wrap_as_installer(fake_agent, installer, agent_id="TEAM42", install_dir=str(install_dir))
    subprocess.run([str(installer)], check=True, timeout=10)

    # Filename uses agent_id so two installers on the same VM don't collide.
    assert (install_dir / "agent_TEAM42").is_file()


# ---------- errors ----------


def test_missing_binary_raises(tmp_path):
    with pytest.raises(InstallerError, match="not found"):
        wrap_as_installer(tmp_path / "nope", tmp_path / "out", agent_id="USR001")


def test_blank_agent_id_raises(tmp_path):
    binary = _fake_binary(tmp_path)
    with pytest.raises(InstallerError, match="agent_id"):
        wrap_as_installer(binary, tmp_path / "out", agent_id="")


def test_unwritable_output_raises(tmp_path):
    binary = _fake_binary(tmp_path)
    # Try to write into a non-existent directory (no mkdir).
    bad_out = tmp_path / "does" / "not" / "exist" / "installer.sh"
    with pytest.raises(InstallerError, match="could not write"):
        wrap_as_installer(binary, bad_out, agent_id="USR001")
