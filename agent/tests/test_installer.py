from lisa_agent.activity import Application, CommandResult
from lisa_agent.installer import (
    ensure_all_installed,
    ensure_installed,
    install,
    is_installed,
)


class FakeRunner:
    """A runner whose outcomes per command are pre-scripted."""

    def __init__(self, outcomes: dict[str, bool] | None = None, default: bool = True):
        self.outcomes = outcomes or {}
        self.default = default
        self.calls: list[str] = []

    def __call__(self, command: str) -> CommandResult:
        self.calls.append(command)
        ok = self.outcomes.get(command, self.default)
        return CommandResult(command, ok, 0.0, stderr="" if ok else "boom")


def app(**overrides):
    base = {
        "name": "editor",
        "check_command": "editor --version",
        "install_commands": ["apt install -y editor"],
        "post_install_commands": ["editor --setup"],
    }
    base.update(overrides)
    return Application(**base)


# ---------- is_installed ----------


def test_is_installed_true_when_check_succeeds():
    runner = FakeRunner({"editor --version": True})
    assert is_installed(app(), runner) is True


def test_is_installed_false_when_check_fails():
    runner = FakeRunner({"editor --version": False})
    assert is_installed(app(), runner) is False


def test_is_installed_true_when_no_check_command():
    runner = FakeRunner()
    assert is_installed(app(check_command=None), runner) is True
    assert runner.calls == []  # nothing was even run


# ---------- install ----------


def test_install_runs_install_then_post_install_in_order():
    runner = FakeRunner()
    assert install(app(), runner) is True
    assert runner.calls == ["apt install -y editor", "editor --setup"]


def test_install_stops_at_first_failed_install_command():
    runner = FakeRunner({"apt install -y editor": False})
    a = app(install_commands=["apt install -y editor", "echo never runs"])
    assert install(a, runner) is False
    assert runner.calls == ["apt install -y editor"]  # second command never ran


def test_install_post_install_failure_is_non_fatal():
    runner = FakeRunner({"editor --setup": False})
    # install_commands succeed, post_install fails -> still True overall
    assert install(app(), runner) is True


# ---------- ensure_installed (the main entry point) ----------


def test_ensure_installed_skips_install_if_already_present():
    runner = FakeRunner({"editor --version": True})
    assert ensure_installed(app(), runner) is True
    # only the check ran, nothing was installed
    assert runner.calls == ["editor --version"]


def test_ensure_installed_installs_when_missing():
    # first check fails (missing), then install, then re-check succeeds
    calls_seen = []

    def scripted(cmd):
        calls_seen.append(cmd)
        if cmd == "editor --version" and calls_seen.count(cmd) == 1:
            return CommandResult(cmd, False, 0.0)
        return CommandResult(cmd, True, 0.0)

    assert ensure_installed(app(), scripted) is True
    assert calls_seen == [
        "editor --version",  # initial check: missing
        "apt install -y editor",  # install
        "editor --setup",  # post-install
        "editor --version",  # re-check: now present
    ]


def test_ensure_installed_fails_when_install_commands_fail():
    runner = FakeRunner({"editor --version": False, "apt install -y editor": False})
    assert ensure_installed(app(), runner) is False


def test_ensure_installed_fails_gracefully_with_no_install_commands():
    runner = FakeRunner({"editor --version": False})
    a = app(install_commands=[])
    assert ensure_installed(a, runner) is False


def test_ensure_installed_fails_if_still_missing_after_install():
    # install "succeeds" but the app still isn't detected afterwards
    def scripted(cmd):
        if cmd == "editor --version":
            return CommandResult(cmd, False, 0.0)  # always missing
        return CommandResult(cmd, True, 0.0)

    assert ensure_installed(app(), scripted) is False


# ---------- ensure_all_installed (batch) ----------


def test_ensure_all_installed_one_failure_does_not_block_others():
    def scripted(cmd):
        if cmd == "good --version":
            return CommandResult(cmd, True, 0.0)
        if cmd == "bad --version":
            return CommandResult(cmd, False, 0.0)
        if cmd.startswith("install bad"):
            return CommandResult(cmd, False, 0.0)  # bad's install fails
        return CommandResult(cmd, True, 0.0)

    apps = [
        Application(name="good", check_command="good --version"),
        Application(name="bad", check_command="bad --version", install_commands=["install bad"]),
    ]
    result = ensure_all_installed(apps, scripted)
    assert result == {"good": True, "bad": False}
