from lisa_agent.platform_ops import current_os, open_command


def test_current_os_is_supported():
    assert current_os() in {"linux", "macos"}


def test_open_command_matches_os():
    cmd = open_command("https://example.com")
    assert cmd[-1] == "https://example.com"
    assert cmd[0] in {"open", "xdg-open"}
