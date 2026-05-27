# Owner: Shared

# ── Rate limiting (Mohammad) ──────────────────────────────────────────────────
MAX_MESSAGES_PER_MINUTE: int = 60

# ── JWT lifetimes (Mohammad) ──────────────────────────────────────────────────
JWT_LIFETIME_SECONDS: int = 3600         # admin access token (60 min)
INVITE_TOKEN_LIFETIME_SECONDS: int = 900  # first-admin invite token (15 min)
WIDGET_JWT_LIFETIME_SECONDS: int = 900    # widget visitor token (15 min)

# ── Agent bounded loop (Ali) ──────────────────────────────────────────────────
MAX_TOOL_CALLS_PER_TURN: int = 5
MAX_TOKENS_PER_TURN: int = 2000

# ── Session TTL (Ali) ─────────────────────────────────────────────────────────
# Redis conversation session TTL. Set to 30 minutes of inactivity.
# Justification: balances UX continuity against privacy (visitor data not retained
# after session ends) and Redis memory cost.
SESSION_TTL_SECONDS: int = 1800

# ── Rate limit Redis window (Mohammad) ───────────────────────────────────────
RATE_LIMIT_WINDOW_SECONDS: int = 120  # 2-minute key TTL for safety margin
