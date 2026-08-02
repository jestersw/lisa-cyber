import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.agent_builder.compiler import (
    CompilerError,
    CompileResult,
    compile_agent,
)


def _make_source_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')")
    return src


# ---------- happy path ----------


def test_success_when_nuitka_exits_0_and_binary_appears(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    def fake_run(cmd, **kwargs):
        # Simulate Nuitka producing the binary.
        (out / "agent_USR001").write_bytes(b"\x7fELF...")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        result = compile_agent(src, out, "agent_USR001")

    assert isinstance(result, CompileResult)
    assert result.success is True
    assert result.binary_path == out / "agent_USR001"
    assert result.binary_path.is_file()
    assert result.returncode == 0


def test_nuitka_command_is_correct(tmp_path):
    """The command line we hand to subprocess must be what Nuitka expects."""
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        (out / "agent_x").write_bytes(b"\x7fELF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        compile_agent(src, out, "agent_x")

    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/nuitka3"
    assert "--standalone" in cmd
    assert "--onefile" in cmd
    assert f"--output-dir={out}" in cmd
    assert "--output-filename=agent_x" in cmd
    assert "--assume-yes-for-downloads" in cmd
    assert any(c.startswith("--main=") and c.endswith("main.py") for c in cmd)


# ---------- failure to compile (not an environment problem) ----------


def test_returns_failure_when_nuitka_exits_nonzero(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="SyntaxError in main.py")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        result = compile_agent(src, out, "agent_x")

    assert result.success is False
    assert result.binary_path is None
    assert result.returncode == 1
    assert "SyntaxError" in result.stderr


def test_returns_failure_when_binary_missing_despite_zero_exit(tmp_path):
    """Nuitka rarely but really can exit 0 without producing a binary
    (e.g. disk full at the final link step). Treat as failure."""
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    def fake_run(cmd, **kwargs):
        # exit 0 but do NOT create the binary
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        result = compile_agent(src, out, "missing")

    assert result.success is False
    assert result.binary_path is None


# ---------- environment errors (CompilerError) ----------


def test_raises_when_entry_file_missing(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(CompilerError, match="entry file not found"):
        compile_agent(src, out, "agent_x")


def test_raises_when_nuitka_not_installed(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    with (
        patch("app.services.agent_builder.compiler.shutil.which", return_value=None),
        pytest.raises(CompilerError, match="not installed"),
    ):
        compile_agent(src, out, "agent_x")


def test_raises_when_subprocess_cant_launch(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    def raise_notfound(*a, **kw):
        raise FileNotFoundError("nuitka gone")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=raise_notfound,
        ),
        pytest.raises(CompilerError, match="not runnable"),
    ):
        compile_agent(src, out, "agent_x")


def test_raises_on_timeout(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="nuitka", timeout=1)

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            return_value="/usr/bin/nuitka3",
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=raise_timeout,
        ),
        pytest.raises(CompilerError, match="timed out"),
    ):
        compile_agent(src, out, "agent_x", timeout_seconds=1)


# ---------- nuitka lookup ----------


def test_explicit_nuitka_path_overrides_lookup(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        (out / "agent_x").write_bytes(b"\x7fELF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    # which() should not be called at all when explicit path is given
    with (
        patch("app.services.agent_builder.compiler.shutil.which") as mock_which,
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        compile_agent(src, out, "agent_x", nuitka_path="/opt/nuitka")

    assert captured["cmd"][0] == "/opt/nuitka"
    mock_which.assert_not_called()


def test_prefers_nuitka3_over_nuitka(tmp_path):
    src = _make_source_tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    captured = {}

    def which_side(name):
        # Both installed; nuitka3 must win.
        return f"/usr/bin/{name}"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        (out / "agent_x").write_bytes(b"\x7fELF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch(
            "app.services.agent_builder.compiler.shutil.which",
            side_effect=which_side,
        ),
        patch(
            "app.services.agent_builder.compiler.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        compile_agent(src, out, "agent_x")

    assert captured["cmd"][0] == "/usr/bin/nuitka3"
