"""The only place Linux and macOS differ. Everything else in the agent is shared."""

import platform


def current_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    raise RuntimeError(f"Unsupported platform: {system} (LISA targets Linux and macOS)")


def open_command(target: str) -> list[str]:
    """Return the argv to open a file/URL/app on the current OS."""
    return ["open", target] if current_os() == "macos" else ["xdg-open", target]
