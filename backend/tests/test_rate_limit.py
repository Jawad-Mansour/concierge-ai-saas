# Owner: Mohammad

"""Unit tests for per-tenant rate limiting middleware.

No DB or Redis required — Redis is mocked. These run in standard CI.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.auth_middleware import UserClaims
from app.middleware.rate_limit import MAX_MESSAGES_PER_MINUTE, check_rate_limit


def _claims(tenant_id: str | None = "test-tenant-id", role: str = "tenant_admin") -> UserClaims:
    return UserClaims(user_id="test-user-id", tenant_id=tenant_id, role=role)


def _mock_redis(incr_return: int) -> MagicMock:
    r = MagicMock()
    r.incr.return_value = incr_return
    return r


class TestRateLimit:
    def test_under_limit_does_not_raise(self):
        """Requests under the per-minute cap must pass through."""
        with patch("app.middleware.rate_limit._get_redis", return_value=_mock_redis(1)):
            check_rate_limit(claims=_claims())  # must not raise

    def test_at_limit_does_not_raise(self):
        """The request that reaches exactly MAX_MESSAGES_PER_MINUTE must still pass."""
        with patch("app.middleware.rate_limit._get_redis", return_value=_mock_redis(MAX_MESSAGES_PER_MINUTE)):
            check_rate_limit(claims=_claims())  # must not raise

    def test_over_limit_raises_429(self):
        """The first request over the cap must raise HTTP 429 with Retry-After header."""
        with patch("app.middleware.rate_limit._get_redis", return_value=_mock_redis(MAX_MESSAGES_PER_MINUTE + 1)):
            with pytest.raises(HTTPException) as exc_info:
                check_rate_limit(claims=_claims())
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers["Retry-After"] == "60"

    def test_tenant_manager_is_not_rate_limited(self):
        """tenant_manager has no tenant_id — must bypass rate limiting entirely."""
        with patch("app.middleware.rate_limit._get_redis") as mock_get_redis:
            check_rate_limit(claims=_claims(tenant_id=None, role="tenant_manager"))
        mock_get_redis.assert_not_called()

    def test_rate_key_is_per_tenant(self):
        """Two different tenants use different Redis keys — one tenant's count must not affect the other."""
        redis_a = _mock_redis(MAX_MESSAGES_PER_MINUTE + 1)  # tenant A is over limit
        redis_b = _mock_redis(1)                             # tenant B is fine

        with patch("app.middleware.rate_limit._get_redis", side_effect=[redis_a, redis_b]):
            with pytest.raises(HTTPException) as exc_info:
                check_rate_limit(claims=_claims(tenant_id="tenant-a"))
            assert exc_info.value.status_code == 429

            check_rate_limit(claims=_claims(tenant_id="tenant-b"))  # must not raise

        key_a = redis_a.incr.call_args[0][0]
        key_b = redis_b.incr.call_args[0][0]
        assert "tenant-a" in key_a
        assert "tenant-b" in key_b
        assert key_a != key_b
