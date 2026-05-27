# Owner: Mohammad

from sqlalchemy.orm import Session

from app.models.tenant import Tenant


def get_by_id(db: Session, tenant_id: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()


def get_by_slug(db: Session, slug: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.slug == slug).first()


def list_active(db: Session) -> list[Tenant]:
    return db.query(Tenant).filter(Tenant.is_active.is_(True)).all()


def create(
    db: Session,
    *,
    name: str,
    slug: str,
    allowed_origins: list[str],
) -> Tenant:
    tenant = Tenant(name=name, slug=slug, allowed_origins=allowed_origins)
    tenant.validate()
    db.add(tenant)
    db.flush()
    return tenant


def set_active(db: Session, tenant_id: str, *, is_active: bool) -> Tenant | None:
    tenant = get_by_id(db, tenant_id)
    if tenant is None:
        return None
    tenant.is_active = is_active
    db.flush()
    return tenant
