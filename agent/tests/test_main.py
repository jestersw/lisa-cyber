import json
from unittest.mock import patch

from lisa_agent.config import Config
from lisa_agent.main import _work_schedule_from_package, build_agent, main
from lisa_agent.package import DeploymentPackage


def _plugin(name):
    return {
        "app_info": {"name": name, "display_name": name},
        "installation": {},  # no check_command -> assumed installed
        "execution": {"open_command": name, "close_command": f"pkill -f {name}"},
        "activities": [{"id": "use", "name": "Use", "commands": []}],
    }


def _package_dict():
    return {
        "agent_config": {
            "agent_info": {
                "agent_id": "USR001",
                "name": "Jane",
                "role": "developer",
                "os_type": "linux",
            },
            "schedule": {
                "workdays": [1, 2, 3, 4, 5],  # ISO: Mon..Fri
                "work_start": "09:30",
                "work_end": "18:15",
            },
            "behavior": {
                "session_duration": {"min": 100, "max": 200},
                "app_switch_pause": {"min": 5, "max": 15},
                "inactive_period": {"min": 3, "max": 8},
            },
            "heartbeat": {"interval_minutes": 30},
            "applications": ["editor", "browser"],
        },
        "application_plugins": {
            "editor": _plugin("editor"),
            "browser": _plugin("browser"),
        },
    }


# ---------- weekday bridge ----------


def test_work_schedule_converts_iso_to_0_indexed():
    pkg = DeploymentPackage.from_dict(_package_dict())
    ws = _work_schedule_from_package(pkg)
    # ISO 1..5 (Mon..Fri) -> 0..4
    assert ws.workdays == (0, 1, 2, 3, 4)
    assert ws.start == "09:30"
    assert ws.end == "18:15"


def test_work_schedule_carries_lunch_window():
    pkg = DeploymentPackage.from_dict(_package_dict())
    ws = _work_schedule_from_package(pkg)
    assert ws.lunch_min_minutes == 45
    assert ws.lunch_max_minutes == 75


# ---------- build_agent ----------


def test_build_agent_assembles_from_config_and_package():
    env = Config(backend_url="http://backend:8000", auth_token="tok")
    pkg = DeploymentPackage.from_dict(_package_dict())
    agent = build_agent(env, pkg)
    # apps propagated through install check
    assert [a.name for a in agent.apps] == ["editor", "browser"]
    # behaviour ranges came from the package, not defaults
    assert agent.session_min == 100
    assert agent.session_max == 200
    assert agent.switch_pause_range == (5, 15)
    assert agent.inactive_period_range == (3, 8)


def test_build_agent_drops_apps_that_fail_install(monkeypatch):
    """If installer says an app isn't usable, it should not reach the orchestrator."""
    # Force the app whose check_command is "browser --version" to appear broken.
    pkg_dict = _package_dict()
    pkg_dict["application_plugins"]["browser"]["installation"] = {
        "check_command": "browser --version",
        # no install_commands -> ensure_installed will return False
    }
    pkg = DeploymentPackage.from_dict(pkg_dict)

    # Fake runner: "editor" (no check_command) is fine; "browser --version" fails.
    from lisa_agent.activity import CommandResult

    def fake_run(cmd, timeout=60.0):
        return CommandResult(cmd, cmd != "browser --version", 0.0)

    monkeypatch.setattr("lisa_agent.installer.run_command", fake_run)

    env = Config()
    agent = build_agent(env, pkg)
    assert [a.name for a in agent.apps] == ["editor"]


# ---------- main() ----------


def test_main_returns_2_when_package_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LISA_PACKAGE_PATH", str(tmp_path / "nope.json"))
    assert main() == 2


def test_main_returns_2_when_package_is_invalid_json(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("LISA_PACKAGE_PATH", str(bad))
    assert main() == 2


def test_main_returns_0_and_starts_agent(tmp_path, monkeypatch):
    """Happy path: package loads, agent starts and stops cleanly."""
    file = tmp_path / "package.json"
    file.write_text(json.dumps(_package_dict()))
    monkeypatch.setenv("LISA_PACKAGE_PATH", str(file))

    # Patch build_agent to return a fake agent that records start()/handlers.
    calls = {}

    class FakeAgent:
        def install_signal_handlers(self):
            calls["signal_handlers"] = True

        def start(self):
            calls["started"] = True

    with patch("lisa_agent.main.build_agent", return_value=FakeAgent()):
        assert main() == 0
    assert calls == {"signal_handlers": True, "started": True}
