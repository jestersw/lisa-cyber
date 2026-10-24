import pytest

from app.services.deploy.inventory import InventoryError, render_inventory


def test_linux_inventory_groups_and_defaults():
    ini = render_inventory(
        "USR001", "linux", [{"host": "web01.corp.local"}, {"host": "db01.corp.local"}]
    )
    assert "[lisa_linux]" in ini
    assert "web01.corp.local ansible_become=true" in ini
    assert "db01.corp.local ansible_become=true" in ini
    assert "[lisa_linux:vars]" in ini
    assert "lisa_agent_id=USR001" in ini


def test_macos_defaults_to_no_become():
    ini = render_inventory("USR002", "macos", [{"host": "mac01.corp.local"}])
    assert "[lisa_macos]" in ini
    assert "mac01.corp.local ansible_become=false" in ini


def test_ssh_user_and_become_override():
    ini = render_inventory(
        "USR003", "linux", [{"host": "h1", "ssh_user": "operator", "become": False}]
    )
    assert "h1 ansible_user=operator ansible_become=false" in ini


def test_unsupported_os_rejected():
    with pytest.raises(InventoryError):
        render_inventory("USR004", "windows", [{"host": "h1"}])


def test_unsafe_host_rejected():
    with pytest.raises(InventoryError):
        render_inventory("USR005", "linux", [{"host": "h1 && rm -rf /"}])


def test_unsafe_agent_id_rejected():
    with pytest.raises(InventoryError):
        render_inventory("bad id", "linux", [{"host": "h1"}])


def test_empty_targets_rejected():
    with pytest.raises(InventoryError):
        render_inventory("USR006", "linux", [])
