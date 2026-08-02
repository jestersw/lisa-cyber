import pytest

from app.services.agent_builder.sources import (
    SourcesError,
    copy_agent_sources,
)


def _make_fake_agent(tmp_path, files: dict[str, str]) -> tuple:
    """Build a mini agent source tree and empty target dir under tmp_path."""
    src = tmp_path / "lisa_agent"
    src.mkdir()
    for rel, content in files.items():
        full = src / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    dst = tmp_path / "workspace_agent"
    dst.mkdir()
    return src, dst


# ---------- happy path ----------


def test_copies_all_python_sources(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            "activity.py": "pass",
            "config.py": "pass",
            "package.py": "pass",
        },
    )
    result = copy_agent_sources(src, dst)

    assert len(result) == 4
    assert (dst / "main.py").is_file()
    assert (dst / "activity.py").is_file()
    assert (dst / "config.py").is_file()
    assert (dst / "package.py").is_file()


def test_preserves_content(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "hello world",
            "activity.py": "print('activity')",
        },
    )
    copy_agent_sources(src, dst)
    assert (dst / "main.py").read_text() == "hello world"
    assert (dst / "activity.py").read_text() == "print('activity')"


def test_copies_nested_subpackages(tmp_path):
    """Agent might grow subpackages later; must recurse."""
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            "activity.py": "pass",
            "adapters/__init__.py": "",
            "adapters/xdotool.py": "pass",
        },
    )
    copy_agent_sources(src, dst)
    assert (dst / "adapters" / "xdotool.py").is_file()
    assert (dst / "adapters" / "__init__.py").is_file()


# ---------- exclusions ----------


def test_skips_pycache(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            "__pycache__/main.cpython-312.pyc": "binary",
        },
    )
    copy_agent_sources(src, dst)
    assert (dst / "main.py").is_file()
    assert not (dst / "__pycache__").exists()


def test_skips_tests_directory(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            "tests/test_main.py": "pass",
            "tests/__init__.py": "",
        },
    )
    copy_agent_sources(src, dst)
    assert (dst / "main.py").is_file()
    assert not (dst / "tests").exists()


def test_skips_mypy_and_pytest_caches(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            ".mypy_cache/something.json": "{}",
            ".pytest_cache/CACHEDIR.TAG": "tag",
        },
    )
    copy_agent_sources(src, dst)
    assert not (dst / ".mypy_cache").exists()
    assert not (dst / ".pytest_cache").exists()


def test_skips_non_python_files(tmp_path):
    src, dst = _make_fake_agent(
        tmp_path,
        {
            "main.py": "pass",
            "README.md": "docs",
            "config.yaml": "settings: {}",
            "requirements.txt": "requests",
        },
    )
    result = copy_agent_sources(src, dst)
    assert len(result) == 1
    assert (dst / "main.py").is_file()
    assert not (dst / "README.md").exists()


# ---------- error cases ----------


def test_source_root_missing_raises(tmp_path):
    src = tmp_path / "does_not_exist"
    dst = tmp_path / "out"
    dst.mkdir()
    with pytest.raises(SourcesError, match="does not exist"):
        copy_agent_sources(src, dst)


def test_source_root_is_file_not_dir(tmp_path):
    src = tmp_path / "file.py"
    src.write_text("pass")
    dst = tmp_path / "out"
    dst.mkdir()
    with pytest.raises(SourcesError, match="not a directory"):
        copy_agent_sources(src, dst)


def test_source_root_missing_main_py(tmp_path):
    """A tree without main.py can't be built - fail fast, clear message."""
    src, dst = _make_fake_agent(
        tmp_path,
        {"activity.py": "pass", "config.py": "pass"},
    )
    with pytest.raises(SourcesError, match="main.py"):
        copy_agent_sources(src, dst)


def test_target_dir_missing_raises(tmp_path):
    src, _ = _make_fake_agent(tmp_path, {"main.py": "pass"})
    missing_dst = tmp_path / "not_yet"
    with pytest.raises(SourcesError, match="target"):
        copy_agent_sources(src, missing_dst)
