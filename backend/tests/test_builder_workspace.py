import pytest

from app.services.agent_builder.workspace import (
    WorkspaceError,
    cleanup,
    create,
)


def test_create_makes_all_paths(tmp_path):
    ws = create("USR001", root=tmp_path)

    assert ws.root.exists() and ws.root.is_dir()
    assert ws.agent_dir.exists() and ws.agent_dir.is_dir()
    assert ws.output_dir.exists() and ws.output_dir.is_dir()
    # package.json and .env are files the builder writes later; the workspace
    # only reserves their paths, so they must not exist yet.
    assert not ws.package_json.exists()
    assert not ws.env_file.exists()
    # agent_id ends up in the path so operators can tell whose build is whose.
    assert "USR001" in ws.root.name


def test_create_isolates_retries(tmp_path):
    """Two builds for the same agent_id must not collide, even back to back."""
    a = create("USR001", root=tmp_path)
    b = create("USR001", root=tmp_path)
    assert a.root != b.root
    assert a.root.exists() and b.root.exists()


def test_create_rejects_blank_agent_id(tmp_path):
    with pytest.raises(WorkspaceError):
        create("", root=tmp_path)


def test_create_creates_root_if_missing(tmp_path):
    missing_root = tmp_path / "does" / "not" / "exist"
    ws = create("USR001", root=missing_root)
    assert ws.root.exists()
    assert missing_root.exists()


def test_cleanup_removes_workspace(tmp_path):
    ws = create("USR001", root=tmp_path)
    # simulate some build output
    (ws.agent_dir / "main.py").write_text("print('hi')")
    (ws.package_json).write_text("{}")

    cleanup(ws)
    assert not ws.root.exists()


def test_cleanup_is_idempotent(tmp_path):
    """Cleanup runs from finally-blocks that can fire twice; a second call
    must not raise even though the directory is already gone."""
    ws = create("USR001", root=tmp_path)
    cleanup(ws)
    cleanup(ws)  # must not raise
    assert not ws.root.exists()


def test_cleanup_survives_permission_errors(tmp_path, monkeypatch, caplog):
    """A cleanup problem is logged, not raised - otherwise a bad scratch dir
    would mask the real build result."""
    ws = create("USR001", root=tmp_path)

    def boom(*_a, **_kw):
        raise OSError("filesystem hiccup")

    monkeypatch.setattr("app.services.agent_builder.workspace.shutil.rmtree", boom)
    with caplog.at_level("WARNING"):
        cleanup(ws)  # must not raise
    assert any("could not clean up" in record.message for record in caplog.records)


def test_workspace_paths_are_all_inside_root(tmp_path):
    ws = create("USR001", root=tmp_path)
    for path in (ws.agent_dir, ws.output_dir, ws.package_json, ws.env_file):
        assert ws.root in path.parents or ws.root == path.parent
