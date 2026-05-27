# Owner: Mohammad
# Vault policy for the backend service.
# Backend needs read access to all concierge secrets (DB, Redis, JWT keys, external APIs).

path "secret/data/concierge/*" {
  capabilities = ["read"]
}

path "secret/metadata/concierge/*" {
  capabilities = ["list"]
}
