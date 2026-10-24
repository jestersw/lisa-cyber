import random

from lisa_agent.activity import (
    Activity,
    ActivityEngine,
    Application,
    Command,
    CommandResult,
    pick_next_app,
    pick_weighted_activity,
    resolve_os_command,
    resolve_os_commands,
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
    assert Command("key", key="Return").to_shell("linux") == "xdotool key Return"


def test_command_key_combination():
    assert Command("key_combination", keys="ctrl+s").to_shell("linux") == "xdotool key ctrl+s"


def test_command_type_text():
    assert Command("type_text", text="hi").to_shell("linux") == "xdotool type --clearmodifiers 'hi'"


def test_command_type_text_escapes_quotes():
    out = Command("type_text", text="it's").to_shell("linux")
    # single quote is escaped so the shell string stays valid
    assert out == "xdotool type --clearmodifiers 'it'\\''s'"


def test_command_unknown_type_returns_none():
    assert Command("mystery").to_shell("linux") is None


# ---------- macOS keystroke injection (#205) ----------


def test_macos_type_text_uses_osascript_keystroke():
    out = Command("type_text", text="hi").to_shell("macos")
    assert out == 'osascript -e \'tell application "System Events" to keystroke "hi"\''


def test_macos_type_text_escapes_quotes_and_backslashes():
    # A single quote in the text must keep the shell arg valid.
    out = Command("type_text", text="it's").to_shell("macos")
    assert out == ("osascript -e 'tell application \"System Events\" to keystroke \"it'\\''s\"'")
    # Double quotes/backslashes are escaped for AppleScript.
    out2 = Command("type_text", text='say "hi"').to_shell("macos")
    assert 'keystroke \\"say \\\\\\"hi\\\\\\"\\"' not in out2  # sanity: not double-mangled
    assert "keystroke" in out2


def test_macos_key_combination_maps_modifiers():
    out = Command("key_combination", keys="ctrl+s").to_shell("macos")
    assert out == (
        'osascript -e \'tell application "System Events" to keystroke "s" using {control down}\''
    )


def test_macos_key_combination_multiple_modifiers():
    out = Command("key_combination", keys="cmd+shift+t").to_shell("macos")
    assert 'keystroke "t" using {command down, shift down}' in out


def test_macos_special_key_uses_key_code():
    out = Command("key", key="Return").to_shell("macos")
    assert out == "osascript -e 'tell application \"System Events\" to key code 36'"


def test_macos_special_key_with_modifier():
    out = Command("key_combination", keys="cmd+Tab").to_shell("macos")
    assert out == (
        "osascript -e 'tell application \"System Events\" to key code 48 using {command down}'"
    )


def test_macos_unknown_modifier_or_key_returns_none():
    assert Command("key_combination", keys="hyper+k").to_shell("macos") is None  # unknown modifier
    assert Command("key", key="F13").to_shell("macos") is None  # unmapped non-printable
    assert Command("mystery").to_shell("macos") is None


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


def test_perform_activity_translates_commands_to_shell(monkeypatch):
    monkeypatch.setattr("lisa_agent.activity.current_os", lambda: "linux")
    engine, fake = make_engine(seed=1)
    app = Application.from_dict(PLUGIN)
    assert engine.perform_activity(app) is True
    # every issued command must be a translated xdotool string
    assert fake.commands
    assert all(c.startswith("xdotool ") for c in fake.commands)


def test_perform_activity_skips_unknown_command_type(monkeypatch):
    monkeypatch.setattr("lisa_agent.activity.current_os", lambda: "linux")
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
# `exit N` is a builtin of both /bin/sh (Linux/macOS) and cmd.exe (Windows),
# so these exercise the real subprocess path on every supported OS.


def test_run_command_success():
    assert run_command("exit 0").success is True


def test_run_command_failure():
    assert run_command("exit 1").success is False


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


# ---------- per-OS command resolution (#197) ----------

_CROSS_OS_PLUGIN = {
    "app_info": {"name": "discord"},
    "installation": {
        "check_command": {"linux": "discord --version", "macos": "ls /Applications/Discord.app"},
        "install_commands": {
            "linux": ["apt install -y discord"],
            "macos": ["brew install --cask discord"],
        },
    },
    "execution": {
        "open_command": {"linux": "discord", "macos": "open -a Discord"},
        "close_command": {
            "linux": "pkill -f discord",
            "macos": "osascript -e 'quit app \"Discord\"'",
        },
    },
}


def test_resolve_os_command_string_is_shared():
    assert resolve_os_command("discord", "macos") == "discord"


def test_resolve_os_command_picks_os_then_default_then_none():
    val = {"linux": "a", "default": "d"}
    assert resolve_os_command(val, "linux") == "a"
    assert resolve_os_command(val, "macos") == "d"  # falls back to default
    assert resolve_os_command({"linux": "a"}, "macos") is None
    assert resolve_os_command(None, "linux") is None


def test_resolve_os_commands_list_and_mapping():
    assert resolve_os_commands(["a", "b"], "macos") == ["a", "b"]
    assert resolve_os_commands({"linux": ["x"], "macos": ["y"]}, "macos") == ["y"]
    assert resolve_os_commands({"linux": ["x"]}, "macos") == []
    assert resolve_os_commands(None, "linux") == []


def test_application_resolves_macos_commands():
    app = Application.from_dict(_CROSS_OS_PLUGIN, os_name="macos")
    assert app.open_cmd == "open -a Discord"
    assert app.close_cmd == "osascript -e 'quit app \"Discord\"'"
    assert app.check_command == "ls /Applications/Discord.app"
    assert app.install_commands == ["brew install --cask discord"]


def test_application_resolves_linux_commands():
    app = Application.from_dict(_CROSS_OS_PLUGIN, os_name="linux")
    assert app.open_cmd == "discord"
    assert app.close_cmd == "pkill -f discord"
    assert app.install_commands == ["apt install -y discord"]


# ---------- network + file activity (#213) ----------

SANDBOX = '"$HOME/.lisa/activity"'


def test_http_request_uses_curl():
    out = Command("http_request", url="https://intranet.range.local/wiki").to_shell("linux")
    assert out == "curl -s -o /dev/null --max-time 15 'https://intranet.range.local/wiki'"
    # same on macOS (POSIX, OS-neutral)
    assert Command("http_request", url="http://x.local").to_shell("macos").startswith("curl ")


def test_http_request_rejects_non_http_scheme():
    assert Command("http_request", url="file:///etc/passwd").to_shell("linux") is None
    assert Command("http_request", url=None).to_shell("linux") is None


def test_dns_lookup_uses_nslookup():
    out = Command("dns_lookup", host="mail.range.local").to_shell("linux")
    assert out == "nslookup 'mail.range.local' >/dev/null 2>&1"


def test_dns_lookup_rejects_bad_host():
    assert Command("dns_lookup", host="bad;rm -rf /").to_shell("linux") is None


def test_ldap_query_opens_tcp_to_port():
    out = Command("ldap_query", host="dc.range.local").to_shell("linux")
    assert out == "nc -z -w 3 'dc.range.local' 389 >/dev/null 2>&1"
    out2 = Command("ldap_query", host="dc.range.local", port=636).to_shell("linux")
    assert "636" in out2


def test_file_create_is_sandboxed():
    out = Command("file_create", target="report.txt").to_shell("linux")
    assert out == f"mkdir -p {SANDBOX} && touch {SANDBOX}/report.txt"


def test_file_rename_and_copy():
    r = Command("file_rename", target="a.txt", dest="b.txt").to_shell("linux")
    assert r == f"mkdir -p {SANDBOX} && mv {SANDBOX}/a.txt {SANDBOX}/b.txt"
    c = Command("file_copy", target="a.txt", dest="b.txt").to_shell("linux")
    assert c == f"mkdir -p {SANDBOX} && cp {SANDBOX}/a.txt {SANDBOX}/b.txt"


def test_file_delete():
    assert Command("file_delete", target="a.txt").to_shell("linux") == f"rm -f {SANDBOX}/a.txt"


def test_file_ops_reject_path_traversal():
    assert Command("file_create", target="../escape").to_shell("linux") is None
    assert Command("file_create", target="sub/dir").to_shell("linux") is None
    assert Command("file_rename", target="ok.txt", dest="../evil").to_shell("linux") is None
    assert Command("file_delete", target="..").to_shell("linux") is None


def test_network_file_types_are_os_neutral():
    # Network/file commands resolve the same regardless of OS.
    for cmd in (
        Command("dns_lookup", host="x.local"),
        Command("file_create", target="f.txt"),
    ):
        assert cmd.to_shell("linux") == cmd.to_shell("macos")


def test_command_from_dict_parses_new_fields():
    c = Command.from_dict({"type": "ldap_query", "host": "dc.local", "port": 636, "delay": 2})
    assert c.type == "ldap_query" and c.host == "dc.local" and c.port == 636 and c.delay == 2.0


# ---------- Windows keystroke injection via SendKeys (#221) ----------

_SENDKEYS_PREFIX = (
    "powershell -NoProfile -Command "
    "'Add-Type -AssemblyName System.Windows.Forms; "
    "[System.Windows.Forms.SendKeys]::SendWait("
)


def test_windows_type_text_uses_sendkeys():
    out = Command("type_text", text="hi").to_shell("windows")
    assert out.startswith(_SENDKEYS_PREFIX)
    assert "SendWait('\\''hi'\\''" in out  # 'hi' as a single-quoted PS literal


def test_windows_type_text_escapes_sendkeys_specials():
    # +, ^, %, (), {} are SendKeys metacharacters and must be braced.
    out = Command("type_text", text="a+b (c) 50%").to_shell("windows")
    assert "a{+}b {(}c{)} 50{%}" in out


def test_windows_type_text_escapes_single_quote_for_powershell():
    import shlex

    out = Command("type_text", text="it's").to_shell("windows")
    # After the outer shell strips its own quoting, PowerShell must receive the
    # text as a single-quoted literal with the quote doubled: SendWait('it''s').
    parts = shlex.split(out)
    ps_arg = parts[parts.index("-Command") + 1]
    assert "SendWait('it''s')" in ps_arg


def test_windows_key_maps_special_key_token():
    assert "SendWait('\\''{ENTER}'\\''" in Command("key", key="Return").to_shell("windows")
    assert "{ESC}" in Command("key", key="Escape").to_shell("windows")
    assert "{TAB}" in Command("key", key="Tab").to_shell("windows")


def test_windows_key_combination_maps_modifiers():
    # ctrl -> ^, shift -> +, alt -> %
    assert "SendWait('\\''^s'\\''" in Command("key_combination", keys="ctrl+s").to_shell("windows")
    out = Command("key_combination", keys="ctrl+shift+t").to_shell("windows")
    assert "^+t" in out
    assert "%{TAB}" in Command("key_combination", keys="alt+Tab").to_shell("windows")


def test_windows_single_printable_char():
    assert "SendWait('\\''a'\\''" in Command("key", key="a").to_shell("windows")


def test_windows_unknown_modifier_or_key_returns_none():
    assert Command("key_combination", keys="hyper+k").to_shell("windows") is None  # unknown mod
    assert Command("key", key="F13").to_shell("windows") is None  # unmapped non-printable
    assert Command("mystery").to_shell("windows") is None


# ---------- Windows network + file activity via PowerShell (#221) ----------


def test_windows_http_request_uses_invoke_webrequest():
    out = Command("http_request", url="https://intranet.range.local/wiki").to_shell("windows")
    assert "Invoke-WebRequest" in out and "-UseBasicParsing" in out
    assert "intranet.range.local/wiki" in out


def test_windows_http_request_rejects_non_http_scheme():
    assert Command("http_request", url="file:///etc/passwd").to_shell("windows") is None
    assert Command("http_request", url=None).to_shell("windows") is None


def test_windows_dns_lookup_uses_resolve_dnsname():
    out = Command("dns_lookup", host="mail.range.local").to_shell("windows")
    assert "Resolve-DnsName" in out and '"mail.range.local"' in out


def test_windows_dns_lookup_rejects_bad_host():
    assert Command("dns_lookup", host="bad;rm -rf /").to_shell("windows") is None


def test_windows_ldap_query_uses_test_netconnection():
    out = Command("ldap_query", host="dc.range.local").to_shell("windows")
    assert "Test-NetConnection" in out and "-Port 389" in out
    out2 = Command("ldap_query", host="dc.range.local", port=636).to_shell("windows")
    assert "-Port 636" in out2


def test_windows_file_create_is_sandboxed():
    out = Command("file_create", target="report.txt").to_shell("windows")
    assert "New-Item" in out and "report.txt" in out
    # Confined to the per-user sandbox under %USERPROFILE%\.lisa\activity.
    assert "$env:USERPROFILE" in out and ".lisa\\activity" in out


def test_windows_file_rename_and_copy_and_delete():
    r = Command("file_rename", target="a.txt", dest="b.txt").to_shell("windows")
    assert "Move-Item" in r and "a.txt" in r and "b.txt" in r
    c = Command("file_copy", target="a.txt", dest="b.txt").to_shell("windows")
    assert "Copy-Item" in c
    d = Command("file_delete", target="a.txt").to_shell("windows")
    assert "Remove-Item" in d and "a.txt" in d


def test_windows_file_ops_reject_path_traversal():
    assert Command("file_create", target="../escape").to_shell("windows") is None
    assert Command("file_create", target="sub/dir").to_shell("windows") is None
    assert Command("file_rename", target="ok.txt", dest="..\\evil").to_shell("windows") is None
    assert Command("file_delete", target="..").to_shell("windows") is None


def test_windows_network_file_differ_from_posix():
    # Same activity, genuinely different command on Windows vs POSIX.
    for cmd in (
        Command("dns_lookup", host="x.local"),
        Command("file_create", target="f.txt"),
        Command("http_request", url="https://x.local"),
    ):
        assert cmd.to_shell("windows") != cmd.to_shell("linux")
        assert cmd.to_shell("windows").startswith("powershell ")
