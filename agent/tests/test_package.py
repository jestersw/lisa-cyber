import json

import pytest

from lisa_agent.package import (
    AgentIdentity,
    DeploymentPackage,
    PackageError,
)


# ---------- fixtures ----------


def sample_plugin(name="editor"):
    return {
        "app_info": {"name": name, "display_name": name.title(), "category": "dev"},
        "installation": {
            "check_command": f"{name} --version",
            "install_commands": [f"apt install -y {name}"],
        },
        "execution": {"open_command": name, "close_command": f"pkill -f {name}"},
        "activities": [{"id": "use", "name": "Use", "commands": []}],
    }


def sample_package(applications=None, plugins=None):
    return {
        "agent_config": {
            "agent_info": {
                "agent_id": "USR001",
                "name": "John Doe",
                "role": "developer",
                "os_type": "linux",
            },
            "schedule": {
                "workdays": [1, 2, 3, 4, 5],
                "work_start": "09:12",
                "work_end": "18:03",
                "lunch": {
                    "earliest": "13:00",
                    "latest": "14:30",
                    "min_minutes": 45,
                    "max_minutes": 60,
                },
            },
            "behavior": {
                "session_duration": {"min": 300, "max": 900},
                "app_switch_pause": {"min": 30, "max": 120},
                "inactive_period": {"min": 10, "max": 20},
            },
            "heartbeat": {"interval_minutes": 15},
            "applications": applications if applications is not None else ["editor", "browser"],
        },
        "application_plugins": plugins
        if plugins is not None
        else {"editor": sample_plugin("editor"), "browser": sample_plugin("browser")},
    }


# ---------- happy path ----------


def test_load_full_package():
    pkg = DeploymentPackage.from_dict(sample_package())
    assert pkg.identity.agent_id == "USR001"
    assert pkg.identity.role == "developer"
    assert pkg.identity.os_type == "linux"
    assert pkg.schedule.work_start == "09:12"
    assert pkg.schedule.work_end == "18:03"
    assert pkg.schedule.workdays == (1, 2, 3, 4, 5)
    assert pkg.schedule.lunch.min_minutes == 45
    assert pkg.behavior.session_duration.min == 300
    assert pkg.behavior.session_duration.max == 900
    assert pkg.heartbeat.interval_minutes == 15
    assert [a.name for a in pkg.applications] == ["editor", "browser"]


def test_load_from_file(tmp_path):
    file = tmp_path / "package.json"
    file.write_text(json.dumps(sample_package()))
    pkg = DeploymentPackage.load(file)
    assert pkg.identity.agent_id == "USR001"


def test_defaults_applied_for_missing_optional_blocks():
    minimal = {
        "agent_config": {
            "agent_info": {
                "agent_id": "USR002",
                "name": "Jane",
                "role": "user",
                "os_type": "linux",
            },
            "applications": [],
        },
        "application_plugins": {},
    }
    pkg = DeploymentPackage.from_dict(minimal)
    # defaults from the spec
    assert pkg.schedule.work_start == "09:00"
    assert pkg.schedule.work_end == "18:00"
    assert pkg.schedule.workdays == (1, 2, 3, 4, 5)
    assert pkg.behavior.session_duration.min == 300
    assert pkg.heartbeat.interval_minutes == 30


# ---------- missing-plugin rule ----------


def test_missing_plugin_is_warned_and_skipped(caplog):
    """applications names an app that has no plugin -> skip, not crash."""
    pkg_data = sample_package(
        applications=["editor", "ghost"],
        plugins={"editor": sample_plugin("editor")},  # no "ghost"
    )
    with caplog.at_level("WARNING"):
        pkg = DeploymentPackage.from_dict(pkg_data)
    assert [a.name for a in pkg.applications] == ["editor"]
    assert any("ghost" in rec.message for rec in caplog.records)


def test_malformed_plugin_is_logged_and_skipped(caplog):
    pkg_data = sample_package(
        applications=["editor", "broken"],
        plugins={
            "editor": sample_plugin("editor"),
            "broken": "not a plugin object",  # totally malformed
        },
    )
    with caplog.at_level("ERROR"):
        pkg = DeploymentPackage.from_dict(pkg_data)
    assert [a.name for a in pkg.applications] == ["editor"]


# ---------- error handling ----------


def test_missing_agent_config_raises():
    with pytest.raises(PackageError, match="agent_config"):
        DeploymentPackage.from_dict({"application_plugins": {}})


def test_missing_required_identity_field_raises():
    data = sample_package()
    del data["agent_config"]["agent_info"]["role"]
    with pytest.raises(PackageError, match="role"):
        DeploymentPackage.from_dict(data)


def test_applications_must_be_list():
    data = sample_package()
    data["agent_config"]["applications"] = "not a list"
    with pytest.raises(PackageError, match="applications"):
        DeploymentPackage.from_dict(data)


def test_application_plugins_must_be_object():
    data = sample_package()
    data["application_plugins"] = ["not", "an", "object"]
    with pytest.raises(PackageError, match="application_plugins"):
        DeploymentPackage.from_dict(data)


def test_top_level_must_be_object():
    with pytest.raises(PackageError):
        DeploymentPackage.from_dict("not a dict")  # type: ignore[arg-type]


def test_invalid_json_raises_package_error(tmp_path):
    file = tmp_path / "bad.json"
    file.write_text("{not json")
    with pytest.raises(PackageError, match="valid JSON"):
        DeploymentPackage.load(file)


# ---------- identity edge cases ----------


def test_agent_identity_from_dict_ok():
    ident = AgentIdentity.from_dict(
        {"agent_id": "x", "name": "n", "role": "developer", "os_type": "linux"}
    )
    assert ident.agent_id == "x"


# ---------- transition_model ----------


def test_transition_model_parsed_verbatim():
    """A well-formed model is passed through to the DeploymentPackage as-is."""
    data = sample_package()
    data["agent_config"]["transition_model"] = {
        "version": 1,
        "trained_on": "role:developer",
        "counts": {"editor": {"browser": 42}},
    }
    pkg = DeploymentPackage.from_dict(data)
    assert pkg.transition_model == {
        "version": 1,
        "trained_on": "role:developer",
        "counts": {"editor": {"browser": 42}},
    }


def test_transition_model_absent_is_none():
    """No `transition_model` in agent_config -> None (fallback signal)."""
    pkg = DeploymentPackage.from_dict(sample_package())
    assert pkg.transition_model is None


def test_transition_model_wrong_type_becomes_none():
    """A non-dict transition_model (garbled config) is dropped, not raised."""
    for bad in ("just a string", 42, [1, 2, 3], None):
        data = sample_package()
        data["agent_config"]["transition_model"] = bad
        pkg = DeploymentPackage.from_dict(data)
        assert pkg.transition_model is None
