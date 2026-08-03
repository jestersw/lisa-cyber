import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.agent_builder import compiler
from app.services.agent_builder.builder import (
    BuildError,
    BuildResult,
    build_agent,
)


def _make_agent_source(tmp_path: Path) -> Path:
    """Fake agent/lisa_agent/ with a bare main.py."""
    root = tmp_path / "lisa_agent"
    root.mkdir()
    (root / "main.py").write_text("print('agent')")
    (root / "config.py").write_text("pass")
    return root


def _sample_package() -> dict:
    return {
        "agent_config": {
            "agent_info": {
                "agent_id": "USR001",
                "name": "Jane",
                "role": "developer",
                "os_type": "linux",
            },
            "applications": [],
        },
        "application_plugins": {},
    }


def _fake_compile_success(*args, **kwargs):
    """Pretend Nuitka ran and produced the expected binary."""
    output_dir = kwargs.get("output_dir") or args[1]
    binary_name = kwargs.get("binary_name") or args[2]
    binary_path = output_dir / binary_name
    binary_path.write_bytes(b"\x7fELF fake")
    return compiler.CompileResult(
        success=True,
        binary_path=binary_path,
        stdout="ok",
        stderr="",
        returncode=0,
    )


def _fake_compile_failure(*args, **kwargs):
    return compiler.CompileResult(
        success=False,
        binary_path=None,
        stdout="",
        stderr="SyntaxError: bad code",
        returncode=1,
    )


# ---------- happy path ----------


def test_build_success_end_to_end(tmp_path):
    src = _make_agent_source(tmp_path)
    ws_root = tmp_path / "ws"
    stg_root = tmp_path / "stg"

    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_success,
    ):
        result = build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok-abc",
            backend_url="http://backend:8000",
            agent_source_root=src,
            workspace_root=ws_root,
            storage_root=stg_root,
        )

    assert isinstance(result, BuildResult)
    assert result.success is True
    assert result.agent_id == "USR001"
    assert result.download_url == "/api/builds/USR001/agent_USR001"
    assert result.artefacts is not None
    assert result.artefacts.binary_path.is_file()
    assert result.artefacts.package_path.is_file()


def test_success_persists_correct_package_content(tmp_path):
    src = _make_agent_source(tmp_path)
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_success,
    ):
        result = build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b:8000",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )
    stored = json.loads(result.artefacts.package_path.read_text())
    assert stored["agent_config"]["agent_info"]["agent_id"] == "USR001"


def test_workspace_is_cleaned_up_after_success(tmp_path):
    src = _make_agent_source(tmp_path)
    ws_root = tmp_path / "ws"

    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_success,
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=ws_root,
            storage_root=tmp_path / "stg",
        )

    subdirs = list(ws_root.iterdir()) if ws_root.exists() else []
    assert subdirs == []


# ---------- compile failure ----------


def test_returns_failure_when_nuitka_rejects_code(tmp_path):
    src = _make_agent_source(tmp_path)
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_failure,
    ):
        result = build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    assert result.success is False
    assert result.artefacts is None
    assert result.download_url is None
    assert "SyntaxError" in result.stderr


def test_workspace_is_cleaned_up_after_failure(tmp_path):
    src = _make_agent_source(tmp_path)
    ws_root = tmp_path / "ws"
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_failure,
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=ws_root,
            storage_root=tmp_path / "stg",
        )
    subdirs = list(ws_root.iterdir()) if ws_root.exists() else []
    assert subdirs == []


def test_failure_does_not_persist_artefacts(tmp_path):
    src = _make_agent_source(tmp_path)
    stg_root = tmp_path / "stg"
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_failure,
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=stg_root,
        )
    assert not (stg_root / "USR001").exists()


# ---------- .env content ----------


def test_env_file_gets_written_before_compile(tmp_path):
    """We can't inspect the workspace after cleanup, so peek during compile."""
    src = _make_agent_source(tmp_path)
    captured = {}

    def peek_and_succeed(*args, **kwargs):
        source_dir = kwargs.get("source_dir") or args[0]
        env = source_dir.parent / ".env"
        captured["env_content"] = env.read_text() if env.is_file() else None
        return _fake_compile_success(*args, **kwargs)

    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=peek_and_succeed,
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok-abc",
            backend_url="http://backend:8000",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    assert captured["env_content"] is not None
    assert "LISA_BACKEND_URL=http://backend:8000" in captured["env_content"]
    assert "LISA_AGENT_TOKEN=tok-abc" in captured["env_content"]


# ---------- environment errors (BuildError, workspace never runs) ----------


def test_blank_agent_id_raises(tmp_path):
    src = _make_agent_source(tmp_path)
    with pytest.raises(BuildError, match="agent_id"):
        build_agent(
            agent_id="",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
        )


def test_blank_token_raises(tmp_path):
    src = _make_agent_source(tmp_path)
    with pytest.raises(BuildError, match="agent_token"):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="",
            backend_url="http://b",
            agent_source_root=src,
        )


def test_blank_backend_url_raises(tmp_path):
    src = _make_agent_source(tmp_path)
    with pytest.raises(BuildError, match="backend_url"):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="",
            agent_source_root=src,
        )


def test_missing_sources_wrapped_in_build_error(tmp_path):
    """A SourcesError becomes a BuildError so callers have one type to catch."""
    missing_src = tmp_path / "nope"
    with pytest.raises(BuildError, match="copy agent sources"):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=missing_src,
            workspace_root=tmp_path / "ws",
        )


def test_workspace_cleaned_up_even_when_sources_step_fails(tmp_path):
    missing_src = tmp_path / "nope"
    ws_root = tmp_path / "ws"
    try:
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=missing_src,
            workspace_root=ws_root,
        )
    except BuildError:
        pass
    subdirs = list(ws_root.iterdir()) if ws_root.exists() else []
    assert subdirs == []


# ---------- installer produced alongside binary ----------


def test_success_persists_installer_alongside_binary(tmp_path):
    src = _make_agent_source(tmp_path)
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_success,
    ):
        result = build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b:8000",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    # Installer URL is populated on success and lives under the same agent dir
    # as the binary (single /api/builds/{agent_id}/ endpoint serves both).
    assert result.installer_url is not None
    assert result.installer_url.startswith(f"/api/builds/{result.agent_id}/")
    # File actually landed in storage.
    installer_file = tmp_path / "stg" / "USR001" / f"installer_{result.agent_id}.sh"
    assert installer_file.is_file()


def test_installer_is_executable_after_build(tmp_path):
    """Installer must be chmod +x — otherwise the delivery layer would have
    to do it, defeating the point of self-contained delivery."""
    import stat

    src = _make_agent_source(tmp_path)
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_success,
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    installer_file = tmp_path / "stg" / "USR001" / "installer_USR001.sh"
    assert installer_file.stat().st_mode & stat.S_IXUSR


def test_failure_produces_no_installer(tmp_path):
    """Compile failure short-circuits: no installer, no installer_url."""
    src = _make_agent_source(tmp_path)
    with patch(
        "app.services.agent_builder.builder.compiler.compile_agent",
        side_effect=_fake_compile_failure,
    ):
        result = build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    assert result.success is False
    assert result.installer_url is None
    assert not (tmp_path / "stg" / "USR001").exists()


def test_installer_can_be_run_end_to_end(tmp_path):
    """The installer that the orchestrator produces should actually work when
    executed. The compile-agent mock puts arbitrary bytes in the binary, so
    we swap it for one that puts a runnable script — that way the installer
    genuinely extracts+launches something we can observe."""
    import subprocess
    import time

    from app.services.agent_builder.installer import wrap_as_installer as _orig_wrap

    src = _make_agent_source(tmp_path)
    marker = tmp_path / "agent_ran.marker"

    def compile_produces_runnable_agent(*args, **kwargs):
        output_dir = kwargs.get("output_dir") or args[1]
        binary_name = kwargs.get("binary_name") or args[2]
        binary_path = output_dir / binary_name
        binary_path.write_text(f"#!/bin/sh\necho ran > '{marker}'\n")
        binary_path.chmod(0o755)
        return compiler.CompileResult(
            success=True,
            binary_path=binary_path,
            stdout="",
            stderr="",
            returncode=0,
        )

    install_dir = tmp_path / "install_root"

    with (
        patch(
            "app.services.agent_builder.builder.compiler.compile_agent",
            side_effect=compile_produces_runnable_agent,
        ),
        # patch the default install dir so we don't try to write to /opt/lisa
        patch(
            "app.services.agent_builder.builder.installer_mod.wrap_as_installer",
            side_effect=lambda binary, out, *, agent_id, install_dir=str(install_dir): (
                _orig_wrap(binary, out, agent_id=agent_id, install_dir=install_dir)
            ),
        ),
    ):
        build_agent(
            agent_id="USR001",
            deployment_package=_sample_package(),
            agent_token="tok",
            backend_url="http://b",
            agent_source_root=src,
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )

    installer = tmp_path / "stg" / "USR001" / "installer_USR001.sh"
    subprocess.run([str(installer)], check=True, timeout=10)
    for _ in range(20):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
