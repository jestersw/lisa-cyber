def test_create_list_delete_host(client):
    created = client.post(
        "/api/hosts",
        json={"label": "Web 01", "address": "web01.corp.local", "ssh_user": "operator"},
    )
    assert created.status_code == 201
    host = created.json()
    assert host["address"] == "web01.corp.local"
    assert host["ssh_user"] == "operator"

    listed = client.get("/api/hosts").json()
    assert any(h["id"] == host["id"] for h in listed)

    assert client.delete(f"/api/hosts/{host['id']}").status_code == 204
    assert all(h["id"] != host["id"] for h in client.get("/api/hosts").json())


def test_duplicate_address_conflicts(client):
    client.post("/api/hosts", json={"label": "A", "address": "dup.local"})
    again = client.post("/api/hosts", json={"label": "B", "address": "dup.local"})
    assert again.status_code == 409


def test_delete_unknown_host_404(client):
    assert client.delete("/api/hosts/999").status_code == 404


def test_rejects_unsafe_address(client):
    bad = client.post("/api/hosts", json={"label": "X", "address": "h; rm -rf /"})
    assert bad.status_code == 422


def test_os_type_persists(client):
    created = client.post(
        "/api/hosts", json={"label": "Mac", "address": "mac01.local", "os_type": "macos"}
    )
    assert created.status_code == 201
    assert created.json()["os_type"] == "macos"
