"""Application installer: checks whether an app is present and installs it if not.

Uses the installation fields already parsed onto Application by activity.py
(check_command, install_commands, dependencies, post_install_commands), so the
plugin format stays the single source of truth for what "installed" means for
a given app.

Runs once per app at agent startup (see main.py), before the activity loop
begins - the agent should never try to open an app it hasn't verified/installed.
"""

from __future__ import annotations

import logging

from lisa_agent.activity import Application, Runner, run_command

log = logging.getLogger("lisa-agent.installer")


def is_installed(app: Application, runner: Runner) -> bool:
    """True if the app's check_command succeeds. No check_command = assume present."""
    if not app.check_command:
        return True
    return runner(app.check_command).success


def install(app: Application, runner: Runner) -> bool:
    """Run install_commands then post_install_commands. Stops at the first failure.

    Dependencies are not auto-installed here (they're metadata for the operator/
    template author); if a dependency needs installing, it belongs in
    install_commands.
    """
    for cmd in app.install_commands:
        result = runner(cmd)
        if not result.success:
            log.error("install step failed for %s: %s (%s)", app.name, cmd, result.stderr)
            return False
    for cmd in app.post_install_commands:
        result = runner(cmd)
        if not result.success:
            log.warning("post-install step failed for %s: %s (%s)", app.name, cmd, result.stderr)
            # post-install failures are non-fatal: the app is installed, setup
            # is best-effort.
    return True


def ensure_installed(app: Application, runner: Runner | None = None) -> bool:
    """Check the app; install it if missing. Returns True if the app is usable.

    This is what callers (main.py) actually use - it combines check + install.
    """
    runner = runner or run_command
    if is_installed(app, runner):
        log.debug("%s already installed", app.name)
        return True

    if not app.install_commands:
        log.warning("%s is not installed and has no install_commands", app.name)
        return False

    log.info("installing %s", app.name)
    if not install(app, runner):
        return False

    # Re-check after installing, in case install_commands silently failed to
    # actually produce a working app despite exiting 0.
    if app.check_command and not is_installed(app, runner):
        log.error("%s still not detected after install", app.name)
        return False
    return True


def ensure_all_installed(apps: list[Application], runner: Runner | None = None) -> dict[str, bool]:
    """Ensure every app in the list is installed. Never raises; one app's
    failure doesn't block the others. Returns {app_name: usable}."""
    runner = runner or run_command
    return {app.name: ensure_installed(app, runner) for app in apps}
