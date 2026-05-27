#!/bin/sh
# Owner: Mohammad
# Create or delete a per-tenant MinIO bucket.
# Used by tenant_service.py at provision time and erasure time.
#
# Usage:
#   buckets.sh create <tenant_id>   — idempotent: skip if bucket exists
#   buckets.sh delete <tenant_id>   — remove bucket + all objects

set -e

MC="${MC_ALIAS:-concierge}"
ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
ACCESS_KEY="${MINIO_ROOT_USER:-minioadmin}"
SECRET_KEY="${MINIO_ROOT_PASSWORD:-minioadmin}"

ACTION="$1"
TENANT_ID="$2"

if [ -z "$ACTION" ] || [ -z "$TENANT_ID" ]; then
  echo "Usage: $0 <create|delete> <tenant_id>" >&2
  exit 1
fi

BUCKET="tenant-${TENANT_ID}"

# Configure mc alias (idempotent)
mc alias set "${MC}" "${ENDPOINT}" "${ACCESS_KEY}" "${SECRET_KEY}" >/dev/null 2>&1

case "$ACTION" in
  create)
    if mc ls "${MC}/${BUCKET}" >/dev/null 2>&1; then
      echo "buckets.sh: ${BUCKET} already exists, skipping"
    else
      mc mb "${MC}/${BUCKET}"
      echo "buckets.sh: created ${BUCKET}"
    fi
    ;;

  delete)
    if mc ls "${MC}/${BUCKET}" >/dev/null 2>&1; then
      mc rb --force "${MC}/${BUCKET}"
      echo "buckets.sh: deleted ${BUCKET}"
    else
      echo "buckets.sh: ${BUCKET} does not exist, skipping"
    fi
    ;;

  *)
    echo "Unknown action: $ACTION. Use 'create' or 'delete'." >&2
    exit 1
    ;;
esac
