import random

from lisa_agent.activity import (
    Application,
    ActivityEngine,
    CommandResult,
    pick_next_app,
    run_command,
    should_switch,
)

APP_DATA = {
    "open": "echo open",
    "close": "echo close",
    "activities": [
        {"description": "type a file", "commands": ["echo a", "echo b"]},
        {"description": "browse", "commands": ["echo c"]},
    ],
}


def test_application_from_dict():
    app = Application.from_dict("editor", APP_DATA)
    assert app.name == "editor"
    assert app.open_cmd == "echo open"
    assert app.close_cmd == "echo close"
    assert len(app.activities) == 2
    assert app.activities[0].description == "type a file"
    assert app.activities[0].commands == ["echo a", "echo b"]


def test_run_command_success():
    res = run_command("true")
    assert isinstance(res, CommandResult)
    assert res.success is True


def test_run_command_failure():
    res = run_command("false")
    assert res.success is False


def test_run_command_timeout():
    res = run_command("sleep 5", timeout=0.2)
    assert res.success is False
    assert res.stderr == "timeout"


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        return CommandResult(command, True, 0.0)


def make_engine(seed=0):
    fake = FakeRunner()
    engine = ActivityEngine(runner=fake, rng=random.Random(seed), sleep=lambda _s: None)
    return engine, fake


def test_open_app_runs_open_command():
    engine, fake = make_engine()
    app = Application.from_dict("editor", APP_DATA)
    assert engine.open_app(app) is True
    assert fake.commands == ["echo open"]


def test_open_app_without_open_cmd_returns_false():
    engine, fake = make_engine()
    app = Application("noop")  # no open command
    assert engine.open_app(app) is False
    assert fake.commands == []


def test_close_app_runs_close_command():
    engine, fake = make_engine()
    app = Application.from_dict("editor", APP_DATA)
    engine.close_app(app)
    assert fake.commands == ["echo close"]


def test_perform_activity_runs_all_commands_of_chosen_activity():
    engine, fake = make_engine(seed=0)
    app = Application.from_dict("editor", APP_DATA)
    assert engine.perform_activity(app) is True
    chosen = [a for a in app.activities if a.commands == fake.commands]
    assert len(chosen) == 1


def test_perform_activity_no_activities():
    engine, fake = make_engine()
    app = Application("empty", open_cmd="echo x")
    assert engine.perform_activity(app) is False
    assert fake.commands == []


def test_should_switch():
    assert should_switch(elapsed=100, session_duration=60) is True
    assert should_switch(elapsed=30, session_duration=60) is False


def test_pick_next_app_avoids_current():
    apps = [Application("a"), Application("b"), Application("c")]
    current = apps[0]
    for _ in range(50):
        nxt = pick_next_app(apps, current, rng=random.Random())
        assert nxt.name != "a"


def test_pick_next_app_single_app_returns_it():
    apps = [Application("only")]
    assert pick_next_app(apps, apps[0]).name == "only"


def test_pick_next_app_empty():
    assert pick_next_app([]) is None
