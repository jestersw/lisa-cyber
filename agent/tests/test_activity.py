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


# ---------- transition_model integration ----------


def _model(counts):
    """Wrap raw counts in the model envelope agents receive."""
    return {"version": 1, "counts": counts}


def test_pick_next_app_uses_transition_model_when_available():
    """With a decisive model (all weight on one target), picks that target."""
    apps = [Application(name=n) for n in ("vscode", "terminal", "firefox")]
    current = apps[0]  # vscode
    model = _model({"vscode": {"terminal": 100}})
    for _ in range(20):
        chosen = pick_next_app(apps, current, random.Random(), transition_model=model)
        assert chosen.name == "terminal"


def test_pick_next_app_weights_from_model_are_respected():
    """A skewed model produces a matching skew in choices over many samples."""
    apps = [Application(name=n) for n in ("vscode", "terminal", "firefox")]
    current = apps[0]
    model = _model({"vscode": {"terminal": 90, "firefox": 10}})
    counts = {"terminal": 0, "firefox": 0}
    rng = random.Random(0)
    for _ in range(500):
        chosen = pick_next_app(apps, current, rng, transition_model=model)
        counts[chosen.name] += 1
    # Terminal should heavily dominate. A loose bound catches accidental
    # inversion (weights swapped) without being flaky.
    assert counts["terminal"] > counts["firefox"] * 3


def test_pick_next_app_falls_back_when_model_absent():
    """No model given -> old uniform behaviour that avoids current."""
    apps = [Application(name=n) for n in ("a", "b")]
    for _ in range(20):
        chosen = pick_next_app(apps, apps[0], random.Random())
        assert chosen.name == "b"


def test_pick_next_app_falls_back_when_current_unknown_to_model():
    """Model doesn't have a row for `current` -> fall back, don't crash."""
    apps = [Application(name=n) for n in ("a", "b")]
    model = _model({"c": {"a": 10, "b": 10}})  # no row for 'a' or 'b'
    for _ in range(20):
        chosen = pick_next_app(apps, apps[0], random.Random(), transition_model=model)
        # Fallback avoids current, so should always be 'b'.
        assert chosen.name == "b"


def test_pick_next_app_falls_back_when_model_next_apps_not_in_apps():
    """Model knows the current app but its `next` names don't overlap with
    the agent's app list -> fall back rather than returning None."""
    apps = [Application(name=n) for n in ("a", "b")]
    model = _model({"a": {"unknown_x": 50, "unknown_y": 50}})
    for _ in range(20):
        chosen = pick_next_app(apps, apps[0], random.Random(), transition_model=model)
        assert chosen.name == "b"


def test_pick_next_app_falls_back_on_garbled_model():
    """Model shape is wrong -> ignore silently, keep serving the agent."""
    apps = [Application(name=n) for n in ("a", "b")]
    for garbled in (
        {"version": 1},  # no counts key
        {"counts": "not a dict"},
        {"counts": {"a": "not a dict"}},
        {"counts": {"a": {}}},  # row exists but is empty
    ):
        for _ in range(5):
            chosen = pick_next_app(apps, apps[0], random.Random(), transition_model=garbled)
            assert chosen.name == "b"  # uniform fallback avoiding current


def test_pick_next_app_ignores_non_numeric_weights():
    """Model row has garbage numeric values -> skip them, use what's valid."""
    apps = [Application(name=n) for n in ("a", "b", "c")]
    model = _model({"a": {"b": "not_a_number", "c": 100}})
    for _ in range(20):
        chosen = pick_next_app(apps, apps[0], random.Random(), transition_model=model)
        assert chosen.name == "c"


def test_pick_next_app_no_current_falls_back_to_uniform():
    """No current app to look up in the model -> uniform choice."""
    apps = [Application(name=n) for n in ("a", "b")]
    model = _model({"a": {"b": 100}})
    # With current=None, the model can't help. Both apps should appear.
    seen = set()
    rng = random.Random(0)
    for _ in range(50):
        seen.add(pick_next_app(apps, None, rng, transition_model=model).name)
    assert seen == {"a", "b"}
