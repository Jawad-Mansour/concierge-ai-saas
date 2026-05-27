# Owner: Mohammad
# Vault policy for the modelserver service.
# Modelserver needs only the embeddings API key and the service-to-service auth token.

path "secret/data/concierge/embeddings" {
  capabilities = ["read"]
}

path "secret/data/concierge/service_auth" {
  capabilities = ["read"]
}
