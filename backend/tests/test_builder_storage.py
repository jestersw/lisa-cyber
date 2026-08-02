import pytest

from app.services.agent_builder.storage import (
    StorageError,
    StoredArtefacts,
    store,
)


def _prepare_workspace_output(tmp_path):
    """Create a fake compiled binary + package.json (as if a build just ran)."""
    binary = tmp_path / "workspace" / "out" / "agent_USR001"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x7fELF fake binary")
    package = tmp_path / "workspace" / "package.json"
    package.write_text('{"agent_config": {}, "application_plugins": {}}')
    return binary, package


# ---------- happy path ----------


def test_stores_both_files_in_agent_directory(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    storage_root = tmp_path / "storage"

    result = store("USR001", binary, package, root=storage_root)

    assert isinstance(result, StoredArtefacts)
    assert result.binary_path == storage_root / "USR001" / "agent_USR001"
    assert result.package_path == storage_root / "USR001" / "package.json"
    assert result.binary_path.is_file()
    assert result.package_path.is_file()


def test_preserves_binary_content(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    result = store("USR001", binary, package, root=tmp_path / "storage")
    assert result.binary_path.read_bytes() == b"\x7fELF fake binary"


def test_preserves_package_content(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    result = store("USR001", binary, package, root=tmp_path / "storage")
    assert result.package_path.read_text() == '{"agent_config": {}, "application_plugins": {}}'


def test_download_url_includes_agent_id_and_binary_name(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    result = store("USR001", binary, package, root=tmp_path / "storage")
    assert result.download_url == "/api/builds/USR001/agent_USR001"


def test_preserves_binary_filename(tmp_path):
    """Binary keeps the name the compiler chose, not a generic one."""
    binary = tmp_path / "workspace" / "out" / "my_custom_name"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x7fELF")
    package = tmp_path / "workspace" / "package.json"
    package.write_text("{}")

    result = store("USR001", binary, package, root=tmp_path / "storage")
    assert result.binary_path.name == "my_custom_name"


# ---------- overwrites and re-runs ----------


def test_second_store_overwrites_the_first(tmp_path):
    """Rebuilding an agent replaces its stored artefacts, no versioning."""
    storage_root = tmp_path / "storage"

    binary1, package1 = _prepare_workspace_output(tmp_path / "build1")
    binary1.write_bytes(b"OLD")
    package1.write_text('{"v": 1}')
    store("USR001", binary1, package1, root=storage_root)

    binary2, package2 = _prepare_workspace_output(tmp_path / "build2")
    binary2.write_bytes(b"NEW")
    package2.write_text('{"v": 2}')
    result = store("USR001", binary2, package2, root=storage_root)

    assert result.binary_path.read_bytes() == b"NEW"
    assert result.package_path.read_text() == '{"v": 2}'


def test_different_agents_get_different_directories(tmp_path):
    """One agent's build must not touch another's."""
    storage_root = tmp_path / "storage"
    binary, package = _prepare_workspace_output(tmp_path)

    a = store("USR001", binary, package, root=storage_root)
    b = store("USR002", binary, package, root=storage_root)

    assert a.binary_path.parent != b.binary_path.parent
    assert a.binary_path.parent.name == "USR001"
    assert b.binary_path.parent.name == "USR002"


# ---------- error cases ----------


def test_blank_agent_id_raises(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    with pytest.raises(StorageError, match="agent_id"):
        store("", binary, package, root=tmp_path / "storage")


def test_missing_binary_raises(tmp_path):
    _, package = _prepare_workspace_output(tmp_path)
    fake_binary = tmp_path / "does_not_exist"
    with pytest.raises(StorageError, match="binary not found"):
        store("USR001", fake_binary, package, root=tmp_path / "storage")


def test_missing_package_raises(tmp_path):
    binary, _ = _prepare_workspace_output(tmp_path)
    fake_package = tmp_path / "no_package.json"
    with pytest.raises(StorageError, match="package.json not found"):
        store("USR001", binary, fake_package, root=tmp_path / "storage")


def test_storage_root_created_if_missing(tmp_path):
    binary, package = _prepare_workspace_output(tmp_path)
    missing_root = tmp_path / "not_yet" / "deeper"
    result = store("USR001", binary, package, root=missing_root)
    assert result.binary_path.is_file()
    assert missing_root.is_dir()


def test_copy_failure_raises_storage_error(tmp_path, monkeypatch):
    """If the filesystem hiccups mid-copy, wrap the OSError in our own type."""
    binary, package = _prepare_workspace_output(tmp_path)

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr("app.services.agent_builder.storage.shutil.copy2", boom)
    with pytest.raises(StorageError, match="could not copy"):
        store("USR001", binary, package, root=tmp_path / "storage")
