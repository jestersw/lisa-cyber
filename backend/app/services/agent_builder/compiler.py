"""Compile the prepared agent source tree into a standalone native binary.

Delegates the actual compilation to Nuitka in --onefile --standalone mode:
Nuitka produces a self-contained executable that includes the Python
interpreter and every module the agent imports. On the target VM there's no
need for a system Python. The output is an ELF on Linux, a Mach-O on macOS and
a PE (.exe) on Windows (#221) - Nuitka builds for whatever host it runs on.

We invoke Nuitka as a subprocess (there's no stable public API), stream its
stdout/stderr through our logger, and return a rich result object so the
orchestrator can distinguish "compilation failed" (surface stderr to the
operator) from "we couldn't even start Nuitka" (misconfiguration on the
builder host itself).

Nuitka cannot cross-compile, so each OS target is built on a runner of that OS
(the build gate in builder.py enforces this). On Windows Nuitka appends a
`.exe` extension to the output filename, which _output_filename handles so the
builder finds the artefact regardless of host.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("lisa.builder.compiler")


def builder_os() -> str:
    """The OS this builder host can produce binaries for.

    Nuitka compiles for the host it runs on and cannot cross-compile, so the
    builder can only target its own platform. Matches the agent's own
    platform_ops mapping (Darwin -> macos, Linux -> linux)."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    if system == "Windows":
        return "windows"
    return system.lower()


def _output_filename(binary_name: str, host_os: str) -> str:
    """The filename Nuitka will actually produce for `binary_name` on `host_os`.

    Nuitka appends `.exe` on Windows; on Linux/macOS the name is used verbatim.
    We pass this exact name to --output-filename and expect it on disk, so the
    builder finds the artefact no matter which OS it ran on."""
    if host_os == "windows" and not binary_name.lower().endswith(".exe"):
        return f"{binary_name}.exe"
    return binary_name


# Give the compiler a generous but finite budget. Nuitka builds a small agent
# in well under a minute; anything approaching this cap is almost certainly
# a hung process rather than legitimate work.
DEFAULT_TIMEOUT_SECONDS = 600


class CompilerError(RuntimeError):
    """Raised when the compilation environment itself is broken.

    Distinct from "the agent code failed to compile": that returns a
    CompileResult with success=False so the orchestrator can report the
    Nuitka output to the operator. CompilerError means the operator can't
    do anything about it - the builder host needs fixing.
    """


@dataclass(frozen=True)
class CompileResult:
    """Outcome of one compile attempt.

    success is True iff Nuitka exited 0 AND we found the expected binary on
    disk. stdout/stderr are captured for logging and for surfacing failures
    to the operator.
    """

    success: bool
    binary_path: Path | None
    stdout: str
    stderr: str
    returncode: int


def compile_agent(
    source_dir: Path,
    output_dir: Path,
    binary_name: str,
    *,
    entry_file: str = "main.py",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    nuitka_path: str | None = None,
) -> CompileResult:
    """Run Nuitka on the source tree; return the outcome.

    - source_dir: the directory sources.copy_agent_sources() wrote into.
    - output_dir: where the compiled binary should land.
    - binary_name: the desired filename for the output (e.g. agent_USR001).

    Raises CompilerError if the environment is broken (Nuitka not installed,
    entry file missing, timeout, subprocess failed to launch). Returns a
    CompileResult with success=False if Nuitka ran but rejected the code.
    """
    entry = source_dir / entry_file
    if not entry.is_file():
        raise CompilerError(f"entry file not found: {entry}")

    nuitka = _resolve_nuitka(nuitka_path)

    # Nuitka builds for the host it runs on; resolve the exact output filename
    # for that OS (adds .exe on Windows) so we both ask Nuitka for it and look
    # for it on disk under the same name.
    host_os = builder_os()
    output_filename = _output_filename(binary_name, host_os)

    cmd = [
        nuitka,
        "--standalone",
        "--onefile",
        f"--output-dir={output_dir}",
        f"--output-filename={output_filename}",
        # Assume yes to any Nuitka prompt (e.g. "download ccache?") - the
        # builder must be non-interactive.
        "--assume-yes-for-downloads",
        # Don't clobber files outside output_dir. Everything Nuitka needs
        # already lives inside the workspace.
        f"--main={entry}",
    ]

    # On Apple Silicon, the ccache binary Nuitka auto-downloads is x86_64 and
    # breaks the build (it drags in an x86_64 `xcrun`, which can't load the
    # arm64-only libxcrun). Use the native toolchain directly instead.
    if host_os == "macos":
        cmd.insert(-1, "--disable-ccache")

    log.info("running: %s", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CompilerError(f"nuitka executable not runnable: {nuitka}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CompilerError(f"nuitka timed out after {timeout_seconds}s") from exc

    binary_path = output_dir / output_filename
    # Nuitka may exit 0 but still fail to produce a binary in edge cases
    # (out of disk, permission denied on the last step). Treat that as a
    # failure and surface the logs.
    success = completed.returncode == 0 and binary_path.is_file()

    if not success:
        log.warning(
            "nuitka exited with %s; binary present: %s",
            completed.returncode,
            binary_path.is_file(),
        )

    return CompileResult(
        success=success,
        binary_path=binary_path if success else None,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _resolve_nuitka(explicit: str | None) -> str:
    """Pick which nuitka executable to invoke.

    Preference order: explicit argument, then PATH lookup for `nuitka3`, then
    `nuitka`. Raises CompilerError if none is available - the builder host
    is misconfigured and there's nothing the caller can do at runtime.
    """
    if explicit:
        return explicit
    for name in ("nuitka3", "nuitka"):
        found = shutil.which(name)
        if found:
            return found
    raise CompilerError("nuitka is not installed on this host (looked for nuitka3, nuitka)")
