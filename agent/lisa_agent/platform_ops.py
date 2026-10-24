"""The only place the agent's supported OSes differ. Everything else is shared.

Linux and macOS were the original targets; Windows was added (#221) so a range
can run the same simulated-user agent on Windows VMs. Each OS-specific concern
is funnelled through current_os(): command translation (activity.py), the
single-instance mutex (mutex.py), and signal handling (orchestrator.py) all
branch on it, so adding an OS means touching those spots and nothing else.
"""

import platform


def current_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    if system == "Windows":
        return "windows"
    raise RuntimeError(f"Unsupported platform: {system} (LISA targets Linux, macOS and Windows)")


def open_command(target: str) -> list[str]:
    """Return the argv to open a file/URL/app on the current OS."""
    os_name = current_os()
    if os_name == "macos":
        return ["open", target]
    if os_name == "windows":
        # `start` is a cmd builtin, so it must run through cmd. The empty
        # string is start's title argument: without it start treats a quoted
        # target as the window title and opens nothing.
        return ["cmd", "/c", "start", "", target]
    return ["xdg-open", target]
