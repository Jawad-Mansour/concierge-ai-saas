# Owner: Mohammad

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories import audit_repo, tenant_repo
from app.models.user import Role
from app.services import auth_service


def _minio():
    import minio  # noqa: F401 — requires minio package (add to pyproject.toml)
    return minio.Minio(
        endpoint=os.environ.get("MINIO_ENDPOINT", "minio:9000").replace("http://", ""),
        access_key=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"),
        secure=False,
    )


def _redis():
    import redis as redis_lib  # noqa: F401 — requires redis package in pyproject.toml
    return redis_lib.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))


# ── Provisioning ─────────────────────────────────────────────────────────────

def provision_tenant(
    db: Session,
    *,
    name: str,
    slug: str,
    allowed_origins: list[str],
    actor_id: str,
) -> dict[str, Any]:
    """Create a tenant and return its id + a first-admin invite token."""
    tenant = tenant_repo.create(
        db, name=name, slug=slug, allowed_origins=allowed_origins
    )
    invite_token = auth_service.issue_invite_token(tenant.id)
    audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="create_tenant",
        target_tenant_id=tenant.id,
    )
    db.commit()
    return {
        "tenant_id": tenant.id,
        "slug": tenant.slug,
        "invite_token": invite_token,
    }


def invite_first_admin(
    db: Session, *, tenant_id: str, actor_id: str
) -> dict[str, Any]:
    tenant = tenant_repo.get_by_id(db, tenant_id)
    if tenant is None:
        return {"error": "not_found"}
    invite_token = auth_service.issue_invite_token(tenant_id)
    audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="invite_first_admin",
        target_tenant_id=tenant_id,
    )
    db.commit()
    return {"tenant_id": tenant_id, "invite_token": invite_token}


def suspend_tenant(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    tenant = tenant_repo.set_active(db, tenant_id, is_active=False)
    if tenant is None:
        return {"error": "not_found"}
    # Deactivate all users of this tenant
    db.execute(
        text("UPDATE users SET is_active = false WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="suspend_tenant",
        target_tenant_id=tenant_id,
        metadata={"reason": reason} if reason else None,
    )
    db.commit()
    return {"tenant_id": tenant_id, "status": "suspended"}


def get_cost_this_week(db: Session, *, tenant_id: str) -> dict[str, Any]:
    # Placeholder until the cost attribution log table is defined by Ali/Jana.
    # Returns zeros so the endpoint is callable without breaking.
    return {
        "tenant_id": tenant_id,
        "period": "week",
        "llm_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost_usd": "0.00",
        "embedding_calls": 0,
    }


# ── Erasure ───────────────────────────────────────────────────────────────────

def erase_tenant(
    db: Session, *, tenant_id: str, actor_id: str
) -> dict[str, Any]:
    """Full erasure across all stores. Idempotent — safe to re-run after failure.

    The caller (Tenant Manager) MUST NOT have app.tenant_id set — RLS returns
    empty on any accidental SELECT, enforcing the read-prohibition structurally.
    """
    # Steps 1–5: Postgres deletions (no SELECT — DELETE only, never reads content).
    # app.erase_target activates the erase_isolation RLS policy (FOR DELETE) so the
    # Tenant Manager's session can delete target rows without setting app.tenant_id
    # (which would also allow SELECTs, violating the read prohibition).
    tables = ["leads", "cms_content", "conversations", "embeddings", "widget_configs", "users"]
    db.execute(text("SELECT set_config('app.erase_target', :tid, true)"), {"tid": tenant_id})
    try:
        for table in tables:
            db.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            audit_repo.log_action(
                db,
                actor_id=actor_id,
                action="erase_store_complete",
                target_tenant_id=None,
                metadata={"store": table, "tenant_id": tenant_id},
            )
    finally:
        db.execute(text("SELECT set_config('app.erase_target', '', true)"))

    # Step 6: MinIO bucket deletion
    bucket = f"tenant-{tenant_id}"
    mc = _minio()
    try:
        objects = mc.list_objects(bucket, recursive=True)
        for obj in objects:
            mc.remove_object(bucket, obj.object_name)
        mc.remove_bucket(bucket)
    except Exception:
        pass  # bucket may not exist (already erased or never created)
    audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="erase_store_complete",
        target_tenant_id=None,
        metadata={"store": "minio", "bucket": bucket},
    )

    # Step 7: Redis session flush
    r = _redis()
    pattern = f"session:tenant:{tenant_id}:*"
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=pattern, count=100)
        if keys:
            r.delete(*keys)
        if cursor == 0:
            break
    audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="erase_store_complete",
        target_tenant_id=None,
        metadata={"store": "redis", "pattern": pattern},
    )

    # Step 8: Delete tenant row
    db.execute(
        text("DELETE FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )

    # Step 9: Final audit entry
    entry = audit_repo.log_action(
        db,
        actor_id=actor_id,
        action="erase_tenant",
        target_tenant_id=None,
        metadata={"erased_tenant_id": tenant_id},
    )
    db.commit()
    return {
        "tenant_id": tenant_id,
        "status": "erased",
        "audit_log_entry_id": entry.id,
    }
