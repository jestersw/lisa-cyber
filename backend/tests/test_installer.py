import base64
import stat
import subprocess
import time

import pytest

from app.services.agent_builder.installer import (
    InstallerArtefact,
    InstallerError,
    _bash_header,
    _macos_header,
    _windows_header,
    wrap_as_installer,
)

# A realistic deployment package (indented JSON with the braces that would break
# a naive f-string / here-string) used to exercise config delivery.
_SAMPLE_PKG = (
    '{\n  "agent_config": {\n    "agent_id": "USR001",\n    "role": "dev"\n  },\n'
    '  "application_plugins": [\n    {"name": "Chrome"}\n  ]\n}'
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
        f"#!/bin/sh\necho ran > '{marker_file}'\nsleep 30\n",
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
    fake_agent.write_text("#!/bin/sh\nsleep 30\n")
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


def test_installer_fails_when_agent_dies_immediately(tmp_path):
    """The whole point of the kill -0 check: if the binary is broken (exits
    on startup), the installer must NOT report success."""
    import subprocess

    # A fake "agent" that just exits — simulates a broken Nuitka build,
    # missing shared library, etc.
    fake_agent = tmp_path / "fake_agent"
    fake_agent.write_text("#!/bin/sh\nexit 1\n")
    fake_agent.chmod(0o755)

    installer = tmp_path / "installer.sh"
    install_dir = tmp_path / "install_root"
    wrap_as_installer(fake_agent, installer, agent_id="USR001", install_dir=str(install_dir))

    # Should exit non-zero because the "agent" died within 1s.
    result = subprocess.run([str(installer)], capture_output=True, timeout=10, check=False)
    assert result.returncode != 0
    assert b"agent process died" in result.stderr


# ---------- macOS LaunchAgent installer (#198) ----------


def _macos_installer(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    wrap_as_installer(binary, out, agent_id="USR001", target_os="macos")
    return out


def test_macos_installer_is_self_extracting_sh(tmp_path):
    out = _macos_installer(tmp_path)
    contents = out.read_bytes()
    assert contents.startswith(b"#!/bin/sh")
    assert b"\x7fELF fake agent binary" in contents  # payload preserved


def test_macos_installer_registers_launchagent(tmp_path):
    out = _macos_installer(tmp_path)
    text = out.read_text(errors="ignore")
    assert "com.lisa.agent.USR001" in text
    assert "Library/LaunchAgents" in text
    assert '"$agents_dir/$label.plist"' in text
    assert "<key>RunAtLoad</key><true/>" in text
    assert "<key>KeepAlive</key><true/>" in text
    assert "launchctl load" in text
    assert "Library/Application Support/lisa" in text


def test_macos_installer_includes_uninstaller(tmp_path):
    out = _macos_installer(tmp_path)
    text = out.read_text(errors="ignore")
    assert "uninstall_USR001.sh" in text
    assert "launchctl unload" in text


def test_macos_header_is_valid_sh_syntax():
    # Syntax-check the header alone (the full installer has a binary payload
    # appended, which is not script). No execution — launchctl must not run.
    header = _macos_header(agent_id="USR001")
    result = subprocess.run(["sh", "-n"], input=header, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_unknown_target_os_raises(tmp_path):
    binary = _fake_binary(tmp_path)
    out = tmp_path / "installer.sh"
    with pytest.raises(InstallerError, match="no installer template"):
        wrap_as_installer(binary, out, agent_id="USR001", target_os="plan9")


# ---------- Windows scheduled-task installer (#221) ----------


def _windows_installer(tmp_path, content=b"MZ\x90\x00 fake PE agent\xff\x00"):
    binary = tmp_path / "agent_USR001.exe"
    binary.write_bytes(content)
    out = tmp_path / "installer.ps1"
    wrap_as_installer(binary, out, agent_id="USR001", target_os="windows")
    return out, content


def test_windows_installer_is_powershell_text(tmp_path):
    out, _ = _windows_installer(tmp_path)
    text = out.read_text(encoding="utf-8")
    # A .ps1, not a binary polyglot: it must be valid UTF-8 text and start with
    # the PowerShell version guard.
    assert text.startswith("#Requires -Version 5")


def test_windows_installer_embeds_payload_as_base64(tmp_path):
    out, content = _windows_installer(tmp_path)
    text = out.read_text(encoding="utf-8")
    # The agent is carried as base64 inside the script (no trailing raw bytes,
    # which would break PowerShell's parse), and must decode back exactly.
    b64 = text.split("@'\n", 1)[1].split("\n'@", 1)[0]
    assert base64.b64decode(b64) == content
    assert "FromBase64String" in text


def test_windows_installer_registers_logon_scheduled_task(tmp_path):
    out, _ = _windows_installer(tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "schtasks.exe /Create" in text
    assert "/SC ONLOGON" in text
    assert "LISA Agent USR001" in text
    assert "$env:LOCALAPPDATA" in text


def test_windows_installer_includes_uninstaller(tmp_path):
    out, _ = _windows_installer(tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "uninstall_" in text
    assert "schtasks.exe /Delete" in text


def test_windows_header_mentions_agent_id(tmp_path):
    header = _windows_header(agent_id="USR001", payload_b64="QUJD")
    assert "USR001" in header
    assert header.startswith("#Requires -Version 5")


# ---------- config delivery (#212 follow-up) ----------
#
# The installer must drop the deployment package on the target and point the
# agent at it (+ backend URL / token), or the launchd/nohup/task-started agent
# looks for ./package.json in its launcher's cwd and exits.


def _sh_syntax_ok(script: str, tmp_path) -> bool:
    p = tmp_path / "h.sh"
    p.write_text(script, encoding="utf-8")
    return subprocess.run(["sh", "-n", str(p)]).returncode == 0


def test_macos_header_delivers_config(tmp_path):
    header = _macos_header(
        agent_id="USR001",
        backend_url="http://backend:8000",
        agent_token="enroll-tok",
        package_json=_SAMPLE_PKG,
    )
    # LaunchAgent env wires the agent to its package + backend (launchd does not
    # inherit the installer's environment, so these must be in the plist).
    assert "<key>EnvironmentVariables</key>" in header
    assert "<key>LISA_PACKAGE_PATH</key><string>$pkg_path</string>" in header
    assert "http://backend:8000" in header
    assert "enroll-tok" in header
    # The package itself is written next to the binary via a quoted here-doc.
    assert "package_USR001.json" in header
    assert _SAMPLE_PKG in header
    assert _sh_syntax_ok(header, tmp_path)


def test_macos_header_xml_escapes_env_values(tmp_path):
    header = _macos_header(
        agent_id="USR001",
        backend_url="http://h/?a=1&b=2",
        agent_token="t<ok>",
        package_json=_SAMPLE_PKG,
    )
    assert "http://h/?a=1&amp;b=2" in header
    assert "t&lt;ok&gt;" in header
    assert _sh_syntax_ok(header, tmp_path)


def test_bash_header_delivers_config(tmp_path):
    header = _bash_header(
        agent_id="USR001",
        install_dir="/opt/lisa",
        backend_url="http://backend:8000",
        agent_token="enroll-tok",
        package_json=_SAMPLE_PKG,
    )
    assert 'export LISA_PACKAGE_PATH="/opt/lisa/package_USR001.json"' in header
    assert "export LISA_BACKEND_URL='http://backend:8000'" in header
    assert "export LISA_AGENT_TOKEN='enroll-tok'" in header
    assert _SAMPLE_PKG in header
    assert _sh_syntax_ok(header, tmp_path)


def test_headers_without_package_carry_no_config(tmp_path):
    # Back-compat: a bare wrap (no package) stays exactly a binary dropper.
    mac = _macos_header(agent_id="USR001")
    bash = _bash_header(agent_id="USR001", install_dir="/opt/lisa")
    for header in (mac, bash):
        assert "EnvironmentVariables" not in header
        assert "LISA_PACKAGE_PATH" not in header
        assert "package_USR001.json" not in header


def test_windows_header_delivers_config(tmp_path):
    header = _windows_header(
        agent_id="USR001",
        payload_b64="QUJD",
        backend_url="http://backend:8000",
        agent_token="enroll-tok",
        package_json=_SAMPLE_PKG,
    )
    assert "SetEnvironmentVariable('LISA_PACKAGE_PATH'" in header
    assert "SetEnvironmentVariable('LISA_BACKEND_URL', 'http://backend:8000', 'User')" in header
    assert "SetEnvironmentVariable('LISA_AGENT_TOKEN', 'enroll-tok', 'User')" in header
    assert "package_" in header
    assert _SAMPLE_PKG in header
    # The uninstaller clears the vars; $null must survive as a literal (backtick).
    assert "`$null" in header


def test_running_installer_drops_package_beside_binary(tmp_path):
    # End-to-end on the Linux path: the dropped package.json lands next to the
    # agent so a cwd-less launcher still finds it via LISA_PACKAGE_PATH.
    install_dir = tmp_path / "opt"
    fake_agent = tmp_path / "agent_USR001"
    fake_agent.write_text("#!/bin/sh\nsleep 5\n")
    fake_agent.chmod(0o755)
    installer = tmp_path / "installer.sh"
    wrap_as_installer(
        fake_agent,
        installer,
        agent_id="USR001",
        install_dir=str(install_dir),
        backend_url="http://backend:8000",
        agent_token="enroll-tok",
        package_json=_SAMPLE_PKG,
    )
    subprocess.run(["sh", str(installer)], check=True)
    dropped = install_dir / "package_USR001.json"
    assert dropped.is_file()
    assert dropped.read_text(encoding="utf-8").strip() == _SAMPLE_PKG.strip()
    # Clean up the backgrounded fake agent.
    subprocess.run(["pkill", "-f", str(install_dir / "agent_USR001")])
