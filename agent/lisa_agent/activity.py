"""Activity engine: open apps, perform their activities, switch between them.

Parses the full application-plugin format from the config spec
(docs/agent-config-schema.md): installation, execution, and activities whose
commands are structured objects (key / key_combination / type_text) rather than
raw shell strings. Structured commands are translated to shell via xdotool at
run time. Activity selection is weighted by each activity's `weight`.

Originally ported from the Linux agent's open/close/simulate_activity logic;
extended here to the plugin format.

Security note (AppSec): run_command uses shell=True because plugin commands rely
on shell features. Command strings come only from trusted operator-authored (or
generated-then-stored) plugins, never from unvalidated external input.
"""

from __future__ import annotations

import logging
import random
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lisa_agent.platform_ops import current_os

log = logging.getLogger("lisa-agent.activity")


def resolve_os_command(value: Any, os_name: str) -> str | None:
    """Resolve a plugin command that may be OS-specific (issue #197).

    A command field is either a plain string (shared across every OS) or an
    object keyed by OS name, e.g.::

        {"linux": "discord", "macos": "open -a Discord", "default": "discord"}

    For an object we return the entry for `os_name`, then `default`, else None
    (the engine treats a missing open/close command as "nothing to run").
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        picked = value.get(os_name) or value.get("default")
        return picked if isinstance(picked, str) else None
    return None


def resolve_os_commands(value: Any, os_name: str) -> list[str]:
    """Like resolve_os_command but for list-valued fields (install commands).

    Accepts a list (shared), or an object mapping OS name -> list, with an
    optional `default` list. Returns [] when nothing applies to this OS.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [c for c in value if isinstance(c, str)]
    if isinstance(value, dict):
        picked = value.get(os_name)
        if picked is None:
            picked = value.get("default")
        if isinstance(picked, list):
            return [c for c in picked if isinstance(c, str)]
    return []


@dataclass
class CommandResult:
    command: str
    success: bool
    duration: float
    stdout: str = ""
    stderr: str = ""


def run_command(command: str, timeout: float = 60.0) -> CommandResult:
    """Run a shell command, returning a structured result (never raises)."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,  # plugin commands are trusted operator input; see module docstring
            check=False,  # we inspect returncode ourselves
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        success = proc.returncode == 0
        if success:
            log.debug("ok: %s (%.2fs)", command, duration)
        else:
            log.warning("failed: %s - %s", command, proc.stderr.strip())
        return CommandResult(command, success, duration, proc.stdout[:500], proc.stderr[:500])
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        log.warning("timeout after %.0fs: %s", timeout, command)
        return CommandResult(command, False, duration, stderr="timeout")
    except OSError as exc:
        duration = time.monotonic() - start
        log.error("error: %s - %s", command, exc)
        return CommandResult(command, False, duration, stderr=str(exc))


def _sh_squote(s: str) -> str:
    """Wrap a string as a single shell argument, safe for any content."""
    return "'" + s.replace("'", "'\\''") + "'"


# --- network + file activity (#213) ---

# Per-user sandbox for file activity. Embedded as a shell literal so $HOME
# expands on the target and nothing is ever written outside this directory.
ACTIVITY_DIR = '"$HOME/.lisa/activity"'

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


def _safe_name(name: str | None) -> str | None:
    """A plain filename (no path separators, no traversal) or None."""
    if not name or name in (".", "..") or not _SAFE_NAME.match(name):
        return None
    return name


def _http_request(url: str | None) -> str | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    return f"curl -s -o /dev/null --max-time 15 {_sh_squote(url)}"


def _dns_lookup(host: str | None) -> str | None:
    if not host or not _SAFE_HOST.match(host):
        return None
    return f"nslookup {_sh_squote(host)} >/dev/null 2>&1"


def _ldap_query(host: str | None, port: int | None) -> str | None:
    # No ldapsearch is guaranteed on a target, so we open a TCP connection to
    # the LDAP port — enough to produce the network event monitoring looks for.
    if not host or not _SAFE_HOST.match(host):
        return None
    p = port or 389
    if not (0 < p < 65536):
        return None
    return f"nc -z -w 3 {_sh_squote(host)} {p} >/dev/null 2>&1"


def _file_in_sandbox(name: str) -> str:
    return f"{ACTIVITY_DIR}/{name}"


def _file_create(target: str | None) -> str | None:
    name = _safe_name(target)
    if name is None:
        return None
    return f"mkdir -p {ACTIVITY_DIR} && touch {_file_in_sandbox(name)}"


def _file_two_arg(tool: str, target: str | None, dest: str | None) -> str | None:
    src = _safe_name(target)
    dst = _safe_name(dest)
    if src is None or dst is None:
        return None
    return f"mkdir -p {ACTIVITY_DIR} && {tool} {_file_in_sandbox(src)} {_file_in_sandbox(dst)}"


def _file_delete(target: str | None) -> str | None:
    name = _safe_name(target)
    if name is None:
        return None
    return f"rm -f {_file_in_sandbox(name)}"


def _osascript(action: str) -> str:
    """A shell command that runs one System Events action via osascript."""
    return "osascript -e " + _sh_squote(f'tell application "System Events" to {action}')


# xdotool key names -> AppleScript `key code` for non-printable keys. Printable
# single characters are sent with `keystroke` instead.
_MAC_KEY_CODES = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "esc": 53,
    "delete": 51,
    "backspace": 51,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
}

# xdotool modifier names -> AppleScript `using` clause tokens.
_MAC_MODIFIERS = {
    "ctrl": "control down",
    "control": "control down",
    "cmd": "command down",
    "command": "command down",
    "super": "command down",
    "alt": "option down",
    "option": "option down",
    "shift": "shift down",
}


def _applescript_key(spec: str | None) -> str | None:
    """Convert an xdotool-style key spec (e.g. "ctrl+k", "Return") into an
    AppleScript System Events action. Returns None for anything we can't map
    cleanly, so the caller skips it rather than emit broken AppleScript."""
    if not spec:
        return None
    *mods, key = spec.split("+")
    modifiers = []
    for m in mods:
        token = _MAC_MODIFIERS.get(m.lower())
        if token is None:
            return None  # unknown modifier - skip rather than guess
        modifiers.append(token)

    low = key.lower()
    if low in _MAC_KEY_CODES:
        action = f"key code {_MAC_KEY_CODES[low]}"
    elif len(key) == 1:
        action = f'keystroke "{key}"'
    else:
        return None  # unknown non-printable key name

    if modifiers:
        action += " using {" + ", ".join(modifiers) + "}"
    return action


@dataclass
class Command:
    """A single structured command inside an activity."""

    type: str
    delay: float = 0.0
    # depending on type, one of these is set:
    key: str | None = None
    keys: str | None = None
    text: str | None = None
    # network / file activity (#213)
    url: str | None = None
    host: str | None = None
    port: int | None = None
    target: str | None = None  # filename inside the activity sandbox
    dest: str | None = None  # second filename (rename/copy)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Command:
        port = data.get("port")
        return cls(
            type=data.get("type", ""),
            delay=float(data.get("delay", 0.0)),
            key=data.get("key"),
            keys=data.get("keys"),
            text=data.get("text"),
            url=data.get("url"),
            host=data.get("host"),
            port=int(port) if port is not None else None,
            target=data.get("target"),
            dest=data.get("dest"),
        )

    def to_shell(self, os_name: str | None = None) -> str | None:
        """Translate this command to a shell string for the agent's OS.

        Network and file activity (#213) is POSIX-portable, so it resolves the
        same on Linux and macOS. Keystroke activity differs: Linux uses
        xdotool, macOS uses osascript (System Events, #205). Returns None for
        an unknown or unmappable command so the caller skips it.
        """
        shared = self._to_shared()
        if shared is not None:
            return shared
        os_name = os_name or current_os()
        if os_name == "macos":
            return self._to_macos()
        return self._to_xdotool()

    def _to_shared(self) -> str | None:
        """OS-neutral activity types (network + file), using POSIX tools that
        exist on Linux and macOS. Returns None for the keystroke types, which
        the OS-specific methods handle."""
        if self.type == "http_request":
            return _http_request(self.url)
        if self.type == "dns_lookup":
            return _dns_lookup(self.host)
        if self.type == "ldap_query":
            return _ldap_query(self.host, self.port)
        if self.type == "file_create":
            return _file_create(self.target)
        if self.type == "file_rename":
            return _file_two_arg("mv", self.target, self.dest)
        if self.type == "file_copy":
            return _file_two_arg("cp", self.target, self.dest)
        if self.type == "file_delete":
            return _file_delete(self.target)
        return None

    def _to_xdotool(self) -> str | None:
        if self.type == "key" and self.key:
            return f"xdotool key {self.key}"
        if self.type == "key_combination" and self.keys:
            return f"xdotool key {self.keys}"
        if self.type == "type_text" and self.text is not None:
            # --clearmodifiers so held keys don't corrupt the typed text
            escaped = self.text.replace("'", "'\\''")
            return f"xdotool type --clearmodifiers '{escaped}'"
        return None

    def _to_macos(self) -> str | None:
        if self.type == "type_text" and self.text is not None:
            esc = self.text.replace("\\", "\\\\").replace('"', '\\"')
            return _osascript(f'keystroke "{esc}"')
        if self.type in ("key", "key_combination"):
            spec = self.key if self.type == "key" else self.keys
            action = _applescript_key(spec)
            return _osascript(action) if action else None
        return None


@dataclass
class Activity:
    id: str
    name: str
    weight: int = 1
    min_duration: float = 0.0
    max_duration: float = 0.0
    commands: list[Command] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Activity:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "activity")),
            weight=int(data.get("weight", 1)),
            min_duration=float(data.get("min_duration", 0.0)),
            max_duration=float(data.get("max_duration", 0.0)),
            commands=[Command.from_dict(c) for c in data.get("commands", [])],
        )


@dataclass
class Application:
    """A single application plugin (app_template.json format)."""

    name: str
    open_cmd: str | None = None
    close_cmd: str | None = None
    startup_delay: float = 0.0
    check_command: str | None = None
    install_commands: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    post_install_commands: list[str] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    usage_probability: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any], os_name: str | None = None) -> Application:
        """Build an Application, resolving any OS-specific command fields for
        `os_name` (defaults to the OS the agent is running on). See
        resolve_os_command for the per-OS plugin format (#197)."""
        os_name = os_name or current_os()
        info = data.get("app_info", {})
        install = data.get("installation", {})
        execution = data.get("execution", {})
        settings = data.get("settings", {})
        return cls(
            name=info.get("name", data.get("name", "unknown")),
            open_cmd=resolve_os_command(execution.get("open_command"), os_name),
            close_cmd=resolve_os_command(execution.get("close_command"), os_name),
            startup_delay=float(execution.get("startup_delay", 0.0)),
            check_command=resolve_os_command(install.get("check_command"), os_name),
            install_commands=resolve_os_commands(install.get("install_commands"), os_name),
            dependencies=list(install.get("dependencies", [])),
            post_install_commands=resolve_os_commands(
                install.get("post_install_commands"), os_name
            ),
            activities=[Activity.from_dict(a) for a in data.get("activities", [])],
            usage_probability=float(settings.get("usage_probability", 1.0)),
        )


# A runner takes a command string and returns a CommandResult. Injectable so the
# engine can be tested without spawning real processes.
Runner = Callable[[str], CommandResult]


def pick_weighted_activity(activities: list[Activity], rng: random.Random) -> Activity | None:
    """Choose an activity, biased by weight. Falls back to uniform if no weights."""
    if not activities:
        return None
    weights = [max(0, a.weight) for a in activities]
    if sum(weights) <= 0:
        return rng.choice(activities)
    return rng.choices(activities, weights=weights, k=1)[0]


class ActivityEngine:
    """Opens applications and performs their activities."""

    def __init__(
        self,
        runner: Runner | None = None,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.run = runner or run_command
        self.rng = rng or random.Random()
        self.sleep = sleep or time.sleep

    def open_app(self, app: Application) -> bool:
        if not app.open_cmd:
            log.warning("no open command for %s", app.name)
            return False
        log.info("opening %s", app.name)
        ok = self.run(app.open_cmd).success
        if ok and app.startup_delay:
            self.sleep(app.startup_delay)
        return ok

    def close_app(self, app: Application) -> None:
        if app.close_cmd:
            log.info("closing %s", app.name)
            self.run(app.close_cmd)

    def perform_activity(self, app: Application) -> bool:
        """Pick a weighted activity and run its commands, honouring per-command delays."""
        activity = pick_weighted_activity(app.activities, self.rng)
        if activity is None:
            return False
        log.info("%s: %s", app.name, activity.name)
        for command in activity.commands:
            shell = command.to_shell()
            if shell is None:
                log.warning("unknown command type %r in %s, skipping", command.type, activity.id)
                continue
            self.run(shell)
            if command.delay:
                self.sleep(command.delay)
        return True


def should_switch(elapsed: float, session_duration: float) -> bool:
    """True once the current app has been in use long enough to switch."""
    return elapsed >= session_duration


def pick_next_app(
    apps: list[Application],
    current: Application | None = None,
    rng: random.Random | None = None,
    transition_model: dict | None = None,
) -> Application | None:
    """Choose the next app.

    If a `transition_model` is supplied and it has counts for the current
    app that overlap with `apps`, the next app is sampled weighted by those
    counts (see docs/agent-config-schema.md for the model format).

    Otherwise falls back to a uniform choice that avoids the current app
    when possible. The fallback preserves the pre-ML behaviour so agents
    without a model in their config keep working.
    """
    if not apps:
        return None
    rng = rng or random.Random()

    weighted = _weighted_next_from_model(apps, current, transition_model, rng)
    if weighted is not None:
        return weighted

    candidates = [a for a in apps if current is None or a.name != current.name]
    return rng.choice(candidates or apps)


def _weighted_next_from_model(
    apps: list[Application],
    current: Application | None,
    transition_model: dict | None,
    rng: random.Random,
) -> Application | None:
    """Try to pick the next app from the markov model. Returns None if the
    model isn't usable for this transition (missing, unknown current app,
    no overlap with available apps) so the caller can fall back."""
    if not transition_model or current is None:
        return None
    counts = transition_model.get("counts")
    if not isinstance(counts, dict):
        return None
    row = counts.get(current.name)
    if not isinstance(row, dict) or not row:
        return None

    # Only apps we actually have (and can weight positively) are candidates.
    # A model trained on a different app set is normal; we just skip the
    # names we don't recognise and use whatever overlap remains.
    apps_by_name = {a.name: a for a in apps}
    candidates: list[Application] = []
    weights: list[float] = []
    for next_name, weight in row.items():
        app = apps_by_name.get(next_name)
        if app is None:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        candidates.append(app)
        weights.append(w)

    if not candidates:
        return None
    return rng.choices(candidates, weights=weights, k=1)[0]
