import random

from lisa_agent.activity import (
    Activity,
    Application,
    ActivityEngine,
    Command,
    CommandResult,
    pick_next_app,
    pick_weighted_activity,
    run_command,
    should_switch,
)

# A full plugin in the app_template.json format from the spec.
PLUGIN = {
    "app_info": {"name": "editor", "display_name": "Editor", "category": "dev"},
    "installation": {
        "check_command": "editor --version",
        "install_commands": ["apt install -y editor"],
        "dependencies": ["xdotool"],
        "post_install_commands": ["editor --setup"],
    },
    "execution": {
        "open_command": "editor",
        "close_command": "pkill -f editor",
        "startup_delay": 3,
    },
    "activities": [
        {
            "id": "open_file",
            "name": "Open File",
            "weight": 30,
            "min_duration": 10,
            "max_duration": 60,
            "commands": [
                {"type": "key_combination", "keys": "ctrl+o", "delay": 1},
                {"type": "type_text", "text": "example.txt", "delay": 0.5},
                {"type": "key", "key": "Return", "delay": 2},
            ],
        },
        {
            "id": "edit",
            "name": "Edit",
            "weight": 70,
            "commands": [{"type": "type_text", "text": "hello", "delay": 0}],
        },
    ],
    "settings": {"usage_probability": 0.8},
}


# ---------- parsing ----------


def test_application_parses_full_plugin():
    app = Application.from_dict(PLUGIN)
    assert app.name == "editor"
    assert app.open_cmd == "editor"
    assert app.close_cmd == "pkill -f editor"
    assert app.startup_delay == 3
    assert app.check_command == "editor --version"
    assert app.install_commands == ["apt install -y editor"]
    assert app.dependencies == ["xdotool"]
    assert app.post_install_commands == ["editor --setup"]
    assert app.usage_probability == 0.8
    assert len(app.activities) == 2


def test_activity_parses_fields():
    app = Application.from_dict(PLUGIN)
    act = app.activities[0]
    assert act.id == "open_file"
    assert act.name == "Open File"
    assert act.weight == 30
    assert act.min_duration == 10
    assert act.max_duration == 60
    assert len(act.commands) == 3


# ---------- command -> shell translation ----------


def test_command_key():
    assert Command("key", key="Return").to_shell() == "xdotool key Return"


def test_command_key_combination():
    assert Command("key_combination", keys="ctrl+s").to_shell() == "xdotool key ctrl+s"


def test_command_type_text():
    assert Command("type_text", text="hi").to_shell() == "xdotool type --clearmodifiers 'hi'"


def test_command_type_text_escapes_quotes():
    out = Command("type_text", text="it's").to_shell()
    # single quote is escaped so the shell string stays valid
    assert out == "xdotool type --clearmodifiers 'it'\\''s'"


def test_command_unknown_type_returns_none():
    assert Command("mystery").to_shell() is None


# ---------- weighted selection ----------


def test_pick_weighted_activity_respects_weights():
    acts = Application.from_dict(PLUGIN).activities  # weights 30 / 70
    rng = random.Random(0)
    counts = {"open_file": 0, "edit": 0}
    for _ in range(2000):
        counts[pick_weighted_activity(acts, rng).id] += 1
    # "edit" (70) should be picked clearly more often than "open_file" (30)
    assert counts["edit"] > counts["open_file"]


def test_pick_weighted_activity_empty():
    assert pick_weighted_activity([], random.Random()) is None


# ---------- engine with a fake runner ----------


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


def test_open_app_runs_open_and_waits_startup():
    engine, fake = make_engine()
    app = Application.from_dict(PLUGIN)
    assert engine.open_app(app) is True
    assert fake.commands == ["editor"]


def test_open_app_without_open_cmd():
    engine, fake = make_engine()
    app = Application(name="noop")
    assert engine.open_app(app) is False
    assert fake.commands == []


def test_close_app_runs_close():
    engine, fake = make_engine()
    app = Application.from_dict(PLUGIN)
    engine.close_app(app)
    assert fake.commands == ["pkill -f editor"]


def test_perform_activity_translates_commands_to_shell():
    engine, fake = make_engine(seed=1)
    app = Application.from_dict(PLUGIN)
    assert engine.perform_activity(app) is True
    # every issued command must be a translated xdotool string
    assert fake.commands
    assert all(c.startswith("xdotool ") for c in fake.commands)


def test_perform_activity_skips_unknown_command_type():
    app = Application(
        name="x",
        activities=[
            Activity(
                id="a",
                name="a",
                commands=[Command("weird"), Command("key", key="a")],
            )
        ],
    )
    engine, fake = make_engine()
    engine.perform_activity(app)
    # only the valid key command translated; the unknown one was skipped
    assert fake.commands == ["xdotool key a"]


def test_perform_activity_no_activities():
    engine, fake = make_engine()
    app = Application(name="empty", open_cmd="editor")
    assert engine.perform_activity(app) is False
    assert fake.commands == []


# ---------- helpers ----------


def test_should_switch():
    assert should_switch(100, 60) is True
    assert should_switch(30, 60) is False


def test_pick_next_app_avoids_current():
    apps = [Application(name="a"), Application(name="b"), Application(name="c")]
    for _ in range(50):
        assert pick_next_app(apps, apps[0], random.Random()).name != "a"


def test_pick_next_app_empty():
    assert pick_next_app([]) is None


# ---------- run_command still works (real, cross-platform) ----------


def test_run_command_success():
    assert run_command("true").success is True


def test_run_command_failure():
    assert run_command("false").success is False
