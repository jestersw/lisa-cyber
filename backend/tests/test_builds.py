import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import builds
from app.config import get_settings
from app.security import create_download_token, create_operator_token


@pytest.fixture
def storage(monkeypatch, tmp_path):
    """Redirect the endpoint's storage root to a temp dir so tests are hermetic."""
    monkeypatch.setattr(builds, "DEFAULT_STORAGE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(builds.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def secured(monkeypatch):
    """Turn on operator auth so the download guard (#202) is active."""
    monkeypatch.setenv("OPERATOR_PASSWORD", "s3cret")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_artefact(storage, agent_id: str, filename: str, content: bytes) -> None:
    d = storage / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(content)


# ---------- happy path ----------


def test_downloads_binary(client, storage):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF fake binary")
    resp = client.get("/api/builds/USR001/agent_USR001")
    assert resp.status_code == 200
    assert resp.content == b"\x7fELF fake binary"
    assert resp.headers["content-type"] == "application/octet-stream"


def test_downloads_package_json_as_json(client, storage):
    _make_artefact(storage, "USR001", "package.json", b'{"agent_config": {}}')
    resp = client.get("/api/builds/USR001/package.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")


# ---------- 404 ----------


def test_returns_404_for_unknown_agent(client, storage):
    resp = client.get("/api/builds/USR999/agent_USR999")
    assert resp.status_code == 404


def test_returns_404_for_missing_file(client, storage):
    _make_artefact(storage, "USR001", "package.json", b"{}")
    resp = client.get("/api/builds/USR001/agent_USR001")  # binary doesn't exist
    assert resp.status_code == 404


# ---------- path safety ----------


def test_rejects_path_traversal_in_agent_id(client, storage):
    resp = client.get("/api/builds/..%2Fetc/passwd")
    # FastAPI may url-decode differently; the important part is: not 200 with
    # /etc/passwd content.
    assert resp.status_code in (400, 404)


def test_rejects_slashes_in_filename(client, storage):
    # A slash would split into a third path segment - no such route.
    resp = client.get("/api/builds/USR001/sub/file")
    assert resp.status_code == 404


def test_rejects_dotdot_segment(client, storage):
    resp = client.get("/api/builds/USR001/..")
    assert resp.status_code in (400, 404)


def test_rejects_hidden_dotfile(client, storage):
    _make_artefact(storage, "USR001", ".env", b"secret")
    resp = client.get("/api/builds/USR001/.env")
    assert resp.status_code == 400


def test_rejects_agent_id_with_special_chars(client, storage):
    resp = client.get("/api/builds/USR%20001/agent")
    assert resp.status_code in (400, 404)


# ---------- authenticated download (#202) ----------


def test_open_in_dev_mode(client, storage):
    # No OPERATOR_PASSWORD: downloads stay open (dev), matching the other guards.
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    assert client.get("/api/builds/USR001/agent_USR001").status_code == 200


def test_rejects_download_without_token_when_secured(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    assert client.get("/api/builds/USR001/agent_USR001").status_code == 401


def test_allows_download_with_scoped_token(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF payload")
    token = create_download_token("USR001", "agent_USR001")
    resp = client.get(f"/api/builds/USR001/agent_USR001?token={token}")
    assert resp.status_code == 200
    assert resp.content == b"\x7fELF payload"


def test_rejects_token_scoped_to_a_different_file(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    # Token minted for a different filename must not unlock this one.
    token = create_download_token("USR001", "package.json")
    assert client.get(f"/api/builds/USR001/agent_USR001?token={token}").status_code == 401


def test_rejects_token_scoped_to_a_different_agent(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    token = create_download_token("USR999", "agent_USR001")
    assert client.get(f"/api/builds/USR001/agent_USR001?token={token}").status_code == 401


def test_allows_download_with_operator_jwt_header(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    jwt_token = create_operator_token()
    resp = client.get(
        "/api/builds/USR001/agent_USR001",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert resp.status_code == 200


def test_allows_download_with_operator_jwt_as_query_token(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    jwt_token = create_operator_token()
    assert client.get(f"/api/builds/USR001/agent_USR001?token={jwt_token}").status_code == 200


def test_rejects_garbage_token_when_secured(client, storage, secured):
    _make_artefact(storage, "USR001", "agent_USR001", b"\x7fELF")
    assert client.get("/api/builds/USR001/agent_USR001?token=not-a-jwt").status_code == 401


def test_rejects_symlink_pointing_outside_storage(client, storage, tmp_path_factory):
    """Even if someone drops a symlink in the storage dir, we won't serve
    files outside it. `outside` lives in a completely separate temp dir so it
    can't accidentally count as 'inside storage' after path resolution."""
    outside_dir = tmp_path_factory.mktemp("outside")
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("secret")

    agent_dir = storage / "USR001"
    agent_dir.mkdir()
    (agent_dir / "trap").symlink_to(outside_file)

    resp = client.get("/api/builds/USR001/trap")
    assert resp.status_code == 404
