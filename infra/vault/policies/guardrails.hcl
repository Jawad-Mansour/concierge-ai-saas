# Owner: Mohammad
# Vault policy for the guardrails service.
# Guardrails needs only the service-to-service auth token to verify backend calls.

path "secret/data/concierge/service_auth" {
  capabilities = ["read"]
}
