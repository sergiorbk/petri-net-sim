"""Tests for the rate-limit dependency and trusted-proxy client-IP resolution."""

import pytest
from starlette.requests import Request

from src.api.shared.client_ip import get_client_ip
from src.api.shared.exceptions import RateLimitException, ServiceUnavailableException
from src.api.shared.rate_limit import _identity, rate_limit
from src.core.security_config import security_settings


def make_request(path="/", headers=None, client=("203.0.113.7", 5555)) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw_headers,
        "client": client,
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


# --- client IP resolution ---


def test_client_ip_ignores_xff_when_proxy_untrusted(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_TRUST_PROXY_HEADERS", False)
    req = make_request(headers={"X-Forwarded-For": "1.2.3.4"}, client=("10.0.0.1", 1))
    assert get_client_ip(req) == "10.0.0.1"


def test_client_ip_uses_proxy_appended_entry_when_trusted(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(security_settings, "SECURITY_TRUSTED_PROXY_HOPS", 1)
    # The client spoofed "6.6.6.6"; our single trusted proxy appended the real
    # peer "9.9.9.9". With 1 trusted hop we take the rightmost (proxy-appended)
    # entry, defeating the spoof.
    req = make_request(
        headers={"X-Forwarded-For": "6.6.6.6, 9.9.9.9"}, client=("10.0.0.1", 1)
    )
    assert get_client_ip(req) == "9.9.9.9"


def test_client_ip_trusted_falls_back_to_peer_without_xff(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_TRUST_PROXY_HEADERS", True)
    req = make_request(client=("172.16.0.5", 1))
    assert get_client_ip(req) == "172.16.0.5"


# --- identity ---


def test_identity_by_token_hashes_credential():
    req = make_request(headers={"Authorization": "Bearer sk-secret-key"})
    ident = _identity(req, "token")
    assert ident.startswith("tok:")
    assert "sk-secret-key" not in ident  # raw credential never leaked


def test_identity_by_token_falls_back_to_ip_when_anonymous(monkeypatch):
    monkeypatch.setattr(security_settings, "SECURITY_TRUST_PROXY_HEADERS", False)
    req = make_request(client=("198.51.100.2", 1))
    ident = _identity(req, "token")
    assert ident == "ip:198.51.100.2"


def test_identity_by_ip():
    req = make_request(client=("198.51.100.9", 1))
    assert _identity(req, "ip") == "ip:198.51.100.9"


# --- enforcement ---


async def test_rate_limit_allows_under_limit(monkeypatch):
    async def fake_hit(key, max_requests, window):
        return True, 1, window

    monkeypatch.setattr("src.api.shared.rate_limit._hit", fake_hit)
    dep = rate_limit("test", 5, 60, by="ip")
    # Should not raise.
    await dep(make_request())


async def test_rate_limit_rejects_over_limit(monkeypatch):
    async def fake_hit(key, max_requests, window):
        return False, 6, 42

    monkeypatch.setattr("src.api.shared.rate_limit._hit", fake_hit)
    dep = rate_limit("test", 5, 60, by="ip")
    with pytest.raises(RateLimitException) as exc_info:
        await dep(make_request())
    exc = exc_info.value
    assert exc.status_code == 429
    assert exc.retry_after == 42
    assert exc.limit == 5
    headers = exc.rate_limit_headers()
    assert headers["Retry-After"] == "42"
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_rate_limit_fails_open_on_limiter_error(monkeypatch):
    async def boom(key, max_requests, window):
        raise RuntimeError("limiter error")

    monkeypatch.setattr("src.api.shared.rate_limit._hit", boom)
    monkeypatch.setattr(security_settings, "SECURITY_RATE_LIMIT_FAIL_OPEN", True)
    dep = rate_limit("test", 5, 60, by="ip")
    # Fail-open: must allow the request rather than break the API.
    await dep(make_request())


async def test_rate_limit_fails_closed_when_configured(monkeypatch):
    async def boom(key, max_requests, window):
        raise RuntimeError("limiter error")

    monkeypatch.setattr("src.api.shared.rate_limit._hit", boom)
    monkeypatch.setattr(security_settings, "SECURITY_RATE_LIMIT_FAIL_OPEN", False)
    dep = rate_limit("test", 5, 60, by="ip")
    with pytest.raises(ServiceUnavailableException):
        await dep(make_request())


class TestSingleUserModeIsNotRationed:
    """A rate limit keeps one caller from crowding out the others. In
    single-user mode there are no others: every rejection would be the
    owner of the machine being told to wait by their own machine."""

    @pytest.mark.asyncio
    async def test_no_limit_is_applied(self, monkeypatch):
        from src.core.auth_config import auth_settings

        monkeypatch.setattr(auth_settings, "AUTH_MODE", "single_user")
        dependency = rate_limit("chat", max_requests=1, window_seconds=60)

        # Far past a budget of one; none of these may be refused.
        for _ in range(5):
            await dependency(make_request())

    @pytest.mark.asyncio
    async def test_the_counter_is_not_even_touched(self, monkeypatch):
        """Returning early rather than counting-and-allowing: nothing about
        a single-user request belongs in a shared-resource ledger."""
        from src.api.shared import rate_limit as module
        from src.core.auth_config import auth_settings

        monkeypatch.setattr(auth_settings, "AUTH_MODE", "single_user")

        async def _explode(*args, **kwargs):
            raise AssertionError("the limiter was consulted")

        monkeypatch.setattr(module, "_hit", _explode)
        await rate_limit("chat", max_requests=1, window_seconds=60)(make_request())

    @pytest.mark.asyncio
    async def test_multi_user_mode_still_enforces(self, monkeypatch):
        from src.core.auth_config import auth_settings

        monkeypatch.setattr(auth_settings, "AUTH_MODE", "multi")
        dependency = rate_limit("chat-multi-test", max_requests=1, window_seconds=60)

        await dependency(make_request())
        with pytest.raises(RateLimitException):
            await dependency(make_request())
