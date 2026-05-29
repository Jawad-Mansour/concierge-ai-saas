<!-- Owner: Charbel -->
# Widget Auth — Specification

**Status:** Ready for implementation
**Owner:** Charbel
**Implements:** Design F (embeddable widget) + Design E (widget authentication)

## Problem

A visitor on Tenant A's website must be able to chat with that tenant's
agent. The API must be sure the request comes from an allowed origin and
is scoped to the correct tenant — without a logged-in user session.

CORS and CSP frame-ancestors control where the widget *embeds* in a
browser. They do nothing to stop a server-side caller with curl. The
signed token is what authenticates the request.

## Token exchange flow

Host page loads widget.js
→ loader reads data-widget-id from script tag
→ loader POSTs to /widget/token {widget_id, origin}
→ server validates: widget_id exists, origin in allowed_origins
→ server returns signed JWT (15-min TTL, widget_jwt signing key)
→ loader stores token in memory, attaches to every chat request
→ server validates token on every /chat request (tenant_id from token)

## Endpoints

### POST /widget/token

**Auth:** None (public endpoint — this is how anonymous visitors authenticate)

**Request:**
```json
{
  "widget_id": "uuid",
  "origin": "https://tenant-site.com"
}
```

**Response 200:**
```json
{
  "token": "eyJ...",
  "expires_in": 900
}
```

**Response 403:** Origin not in tenant's allowed_origins
**Response 404:** widget_id not found

**Server-side origin check:** Validate `origin` matches an entry in
`widget_configs.allowed_origins` for this widget_id. This happens in
the request handler, not just in CORS headers.

### JWT payload

```json
{
  "sub": "widget:{widget_id}",
  "tenant_id": "uuid",
  "origin": "https://tenant-site.com",
  "exp": 1234567890
}
```

`tenant_id` comes from the verified token only — never from a
client-supplied field. This is the only safe way to scope
anonymous widget requests to a tenant.

## Security rules

1. Origin validation happens server-side in the handler, not just via CORS.
2. `tenant_id` is never trusted from the request body — only from the verified JWT.
3. Token TTL is 900 seconds (15 min). Short because it's public/anonymous.
4. Signing key is `secret/concierge/widget_jwt.signing_key` from Vault — separate from admin JWT key.
5. A stale token (expired or wrong signing key) returns 401.
6. A token from Tenant A cannot be used on Tenant B's widget endpoint.

## Files to implement

| File | What |
|------|------|
| `backend/app/api/widget.py` | POST /widget/token endpoint |
| `backend/app/services/widget_auth_service.py` | Token generation, origin validation |
| `backend/app/repositories/` | Read widget_configs by widget_id |
| `backend/tests/test_widget_auth.py` | Remove skip markers, implement tests |
| `widget/src/auth.ts` | Token exchange on widget load |
| `widget/src/api.ts` | Attach token to every request |
| `admin/pages/widget_config.py` | Allowed origins editor, embed snippet |

## widget_configs table (after migration 002)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| tenant_id | UUID | FK → tenants, RLS scoped |
| widget_id | UUID | UNIQUE — public identifier |
| allowed_origins | TEXT[] | Origins allowed to embed |
| theme | JSONB | Colors, font |
| greeting | TEXT | Opening message |
| enabled_tools | TEXT[] | rag_search, capture_lead, escalate |

## Friday demo requirements

1. Widget loads and shows on `localhost:8080` (allowed origin) ✓
2. Widget is blocked on `localhost:8090` (not in allowed_origins) ✓
3. `curl -X POST /widget/token -d '{"widget_id":"...","origin":"https://evil.com"}'` → 403 ✓
4. Expired token → 401 ✓
