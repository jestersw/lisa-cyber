def test_meta_lists_os_types_and_buildable(client):
    body = client.get("/api/meta").json()
    assert set(body["os_types"]) == {"linux", "macos", "windows"}
    # Default config builds linux only until other OS workers are configured.
    assert body["buildable_os"] == ["linux"]
    assert isinstance(body["buildable_os"], list)
