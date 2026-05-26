#!/bin/sh
# Owner: Mohammad
set -e

VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
export VAULT_ADDR
export VAULT_TOKEN="${VAULT_TOKEN:-dev-token}"

echo "vault-init: waiting for Vault at $VAULT_ADDR..."
until vault status >/dev/null 2>&1; do
  sleep 1
done
echo "vault-init: Vault is ready."

# Enable KV v2 — dev mode pre-mounts secret/, error is safe to ignore
vault secrets enable -path=secret kv-v2 2>/dev/null || true

PREFIX="${VAULT_KV_PATH_PREFIX:-concierge}"

# ── get-or-generate ───────────────────────────────────────────────────────
# For secrets that must stay stable across vault-init restarts (JWT signing
# keys, service auth token): reuse existing value if present; generate fresh
# randomness only when the path is empty. This prevents mid-session token
# invalidation on `docker compose restart vault-init`.
get_or_generate() {
  local path="$1" field="$2" existing
  existing=$(vault kv get -field="$field" "secret/${PREFIX}/${path}" 2>/dev/null || true)
  if [ -n "$existing" ]; then
    printf '%s' "$existing"
  else
    head -c 32 /dev/urandom | base64
  fi
}

AUTH_JWT_KEY=$(get_or_generate auth_jwt signing_key)
WIDGET_JWT_KEY=$(get_or_generate widget_jwt signing_key)
SERVICE_AUTH_TOKEN=$(get_or_generate service_auth token)

echo "vault-init: writing secrets to secret/${PREFIX}/*"

# ── Infrastructure credentials (always upsert from env) ──────────────────
vault kv put "secret/${PREFIX}/db" \
  url="${DATABASE_URL:-postgresql://postgres:postgres@postgres:5432/concierge}"

vault kv put "secret/${PREFIX}/redis" \
  url="${REDIS_URL:-redis://redis:6379/0}"

vault kv put "secret/${PREFIX}/minio" \
  endpoint="${MINIO_ENDPOINT:-http://minio:9000}" \
  access_key="${MINIO_ROOT_USER:-minioadmin}" \
  secret_key="${MINIO_ROOT_PASSWORD:-minioadmin}"

# ── JWT signing keys (stable — get-or-create) ────────────────────────────
vault kv put "secret/${PREFIX}/auth_jwt" \
  signing_key="${AUTH_JWT_KEY}" \
  algorithm="HS256" \
  lifetime_seconds="3600"

vault kv put "secret/${PREFIX}/widget_jwt" \
  signing_key="${WIDGET_JWT_KEY}" \
  algorithm="HS256" \
  lifetime_seconds="900"

# ── Service-to-service auth token (stable — get-or-create) ───────────────
vault kv put "secret/${PREFIX}/service_auth" \
  token="${SERVICE_AUTH_TOKEN}"

# ── External API keys (always upsert from env) ────────────────────────────
vault kv put "secret/${PREFIX}/anthropic" \
  api_key="${ANTHROPIC_API_KEY:-replace-me}"

vault kv put "secret/${PREFIX}/embeddings" \
  api_key="${EMBEDDINGS_API_KEY:-replace-me}" \
  model="${EMBEDDINGS_MODEL:-text-embedding-3-small}"

vault kv put "secret/${PREFIX}/langfuse" \
  public_key="${LANGFUSE_PUBLIC_KEY:-replace-me}" \
  secret_key="${LANGFUSE_SECRET_KEY:-replace-me}" \
  host="${LANGFUSE_HOST:-http://langfuse:3001}"

echo "vault-init: seeding complete."
