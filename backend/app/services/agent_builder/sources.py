"""Copy the agent source tree into a build workspace.

The builder runs inside the backend, but the agent code lives in a sibling
directory (agent/lisa_agent/). For a build we need a clean copy of those
Python sources inside the workspace so the compiler (nuitka) can see them
without touching the repository copy.

We copy only source files (*.py). Tests, __pycache__, .mypy_cache and other
build artefacts are excluded - they'd bloat the compiled binary and add
nothing to the running agent.

Nothing here modifies the sources. main.py already knows how to read
./package.json from the working directory; the builder just needs to lay
the files out and drop the package next to them (later step).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger("lisa.builder.sources")

# Files/directories the agent tree is not supposed to carry into a build.
EXCLUDED_NAMES = {"__pycache__", ".mypy_cache", ".pytest_cache", "tests"}

# main.py is the entry point the compiler will target. If it's missing the
# whole build is pointless, so we fail fast with a clear message.
ENTRY_FILE = "main.py"


class SourcesError(RuntimeError):
    """Something went wrong locating or copying the agent sources."""


def copy_agent_sources(source_root: Path, target_dir: Path) -> list[Path]:
    """Copy every *.py file from source_root into target_dir.

    - source_root should point at the `lisa_agent` package (the directory
      containing main.py, activity.py, etc.).
    - target_dir must already exist (workspace.create() makes it).
    - Returns the list of paths copied, for logging and asserts.

    Raises SourcesError if source_root doesn't exist, isn't a directory,
    or doesn't contain main.py.
    """
    if not source_root.exists():
        raise SourcesError(f"agent source root does not exist: {source_root}")
    if not source_root.is_dir():
        raise SourcesError(f"agent source root is not a directory: {source_root}")
    if not (source_root / ENTRY_FILE).is_file():
        raise SourcesError(f"agent source root does not contain {ENTRY_FILE}: {source_root}")
    if not target_dir.exists():
        raise SourcesError(f"target directory does not exist: {target_dir}")

    copied: list[Path] = []
    for src in _iter_python_sources(source_root):
        rel = src.relative_to(source_root)
        dst = target_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)

    log.info("copied %d source files from %s to %s", len(copied), source_root, target_dir)
    return copied


def _iter_python_sources(root: Path):
    """Yield every .py file under root, skipping excluded directories.

    Uses os.walk-style pruning: we don't just filter matched paths, we prune
    the traversal itself so we never descend into __pycache__ at all.
    """
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if entry.name in EXCLUDED_NAMES:
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and entry.suffix == ".py":
                yield entry
