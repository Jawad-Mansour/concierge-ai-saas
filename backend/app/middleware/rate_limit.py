# Owner: Mohammad

import time

import redis as redis_lib
from fastapi import Depends, HTTPException, status

from app.middleware.auth_middleware import UserClaims, get_current_user

MAX_MESSAGES_PER_MINUTE = 60
_WINDOW_SECONDS = 120  # 2-minute key TTL for safety margin


def _get_redis() -> redis_lib.Redis:
    import os
    return redis_lib.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))


def check_rate_limit(claims: UserClaims = Depends(get_current_user)) -> None:
    """FastAPI dependency: enforce per-tenant sliding-window rate limit.

    Key: ratelimit:{tenant_id}:{unix_minute}
    Limit: MAX_MESSAGES_PER_MINUTE requests per minute per tenant.
    A 429 response includes Retry-After: 60 so clients know when to retry.

    Wire as a dependency on POST /chat and POST /widget/token only.
    """
    tenant_id = claims.tenant_id
    if not tenant_id:
        return  # tenant_manager and unauthenticated calls are not rate-limited here

    window = int(time.time()) // 60
    key = f"ratelimit:{tenant_id}:{window}"

    r = _get_redis()
    count = r.incr(key)
    if count == 1:
        r.expire(key, _WINDOW_SECONDS)

    if count > MAX_MESSAGES_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )
