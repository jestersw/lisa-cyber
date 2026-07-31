import fakeredis
import pytest
from fastapi import HTTPException

import app.ratelimit as rl
from app.ratelimit import _allow, _client_key, rate_limit


class FakeRequest:
    def __init__(self, host="1.2.3.4"):
        self.client = type("C", (), {"host": host})()


@pytest.fixture
def fake_redis(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(rl, "_redis", fake)
    return fake


def test_key_prefers_token():
    assert _client_key("Bearer abc123", FakeRequest()) == "token:abc123"


def test_key_falls_back_to_ip():
    assert _client_key(None, FakeRequest(host="9.9.9.9")) == "ip:9.9.9.9"


def test_allows_under_limit(fake_redis):
    for _ in range(5):
        assert _allow("token:x", limit=10, window_seconds=60) is True


def test_blocks_over_limit(fake_redis):
    results = [_allow("token:y", limit=3, window_seconds=60) for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_limit_is_per_key(fake_redis):
    for _ in range(3):
        _allow("token:A", limit=3, window_seconds=60)
    assert _allow("token:A", limit=3, window_seconds=60) is False
    # A different agent is unaffected.
    assert _allow("token:B", limit=3, window_seconds=60) is True


def test_fail_open_when_no_redis(monkeypatch):
    monkeypatch.setattr(rl, "get_redis", lambda: None)
    for _ in range(100):
        assert _allow("token:z", limit=1, window_seconds=60) is True


def test_fail_open_on_redis_error(monkeypatch):
    class BrokenRedis:
        def incr(self, *a):
            raise rl.redis.RedisError("boom")

    monkeypatch.setattr(rl, "get_redis", lambda: BrokenRedis())
    assert _allow("token:err", limit=1, window_seconds=60) is True


def test_dependency_raises_429_over_limit(fake_redis):
    dep = rate_limit(limit=2, window_seconds=60)
    req = FakeRequest()
    dep(req, authorization="Bearer t")
    dep(req, authorization="Bearer t")
    with pytest.raises(HTTPException) as exc:
        dep(req, authorization="Bearer t")
    assert exc.value.status_code == 429
