import lisa_agent.enroll as enroll_mod
from lisa_agent.enroll import default_token_path, resolve_token


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakePost:
    """Records calls and returns queued responses (or raises)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _patch_post(monkeypatch, fake):
    monkeypatch.setattr(enroll_mod.requests, "post", fake)


# ---------- stored token wins ----------


def test_stored_token_is_reused_without_enrolling(tmp_path, monkeypatch):
    token_file = tmp_path / "agent_token"
    token_file.write_text("already-real-token")
    fake = _FakePost([])  # must not be called
    _patch_post(monkeypatch, fake)

    token = resolve_token("https://b", "USR001", "enroll-tok", token_path=token_file)
    assert token == "already-real-token"
    assert fake.calls == []


# ---------- enrollment ----------


def test_enrolls_and_persists_token(tmp_path, monkeypatch):
    token_file = tmp_path / "agent_token"
    fake = _FakePost([_Resp(200, {"agent_id": "USR001", "token": "real-token"})])
    _patch_post(monkeypatch, fake)

    token = resolve_token("https://b", "USR001", "enroll-tok", token_path=token_file)
    assert token == "real-token"
    # Persisted for next time, and the bootstrap token was sent as a Bearer header.
    assert token_file.read_text() == "real-token"
    assert fake.calls[0]["url"] == "https://b/api/agents/USR001/enroll"
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer enroll-tok"


def test_persisted_token_used_on_second_call(tmp_path, monkeypatch):
    token_file = tmp_path / "agent_token"
    fake = _FakePost([_Resp(200, {"token": "real-token"})])
    _patch_post(monkeypatch, fake)
    resolve_token("https://b", "USR001", "enroll-tok", token_path=token_file)

    # Second resolve must not enroll again (no queued responses left to consume).
    fake2 = _FakePost([])
    _patch_post(monkeypatch, fake2)
    token = resolve_token("https://b", "USR001", "enroll-tok", token_path=token_file)
    assert token == "real-token"
    assert fake2.calls == []


def test_no_bootstrap_token_returns_none(tmp_path, monkeypatch):
    fake = _FakePost([])
    _patch_post(monkeypatch, fake)
    token = resolve_token("https://b", "USR001", None, token_path=tmp_path / "agent_token")
    assert token is None
    assert fake.calls == []


# ---------- failure / retry ----------


def test_retries_then_gives_up(tmp_path, monkeypatch):
    token_file = tmp_path / "agent_token"
    fake = _FakePost([_Resp(503), _Resp(503)])
    _patch_post(monkeypatch, fake)

    token = resolve_token(
        "https://b",
        "USR001",
        "enroll-tok",
        token_path=token_file,
        retries=2,
        retry_delay=0,
        sleep=lambda _s: None,
    )
    assert token is None
    assert len(fake.calls) == 2
    assert not token_file.exists()


def test_retries_then_succeeds(tmp_path, monkeypatch):
    token_file = tmp_path / "agent_token"
    fake = _FakePost([_Resp(503), _Resp(200, {"token": "real-token"})])
    _patch_post(monkeypatch, fake)

    token = resolve_token(
        "https://b",
        "USR001",
        "enroll-tok",
        token_path=token_file,
        retries=3,
        retry_delay=0,
        sleep=lambda _s: None,
    )
    assert token == "real-token"
    assert len(fake.calls) == 2


# ---------- token path ----------


def test_default_token_path_is_per_user():
    p = str(default_token_path())
    assert p.endswith("agent_token")
    assert "lisa" in p.lower()
