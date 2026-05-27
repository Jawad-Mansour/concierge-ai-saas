# Owner: Mohammad

import bcrypt
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.user import Role, User


def get_by_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_by_email(db: Session, email: str) -> User | None:
    # Login precedes tenant context: email is platform-unique so no tenant filter needed.
    # app.login_lookup='true' activates the email_login_lookup RLS policy (FOR SELECT)
    # which allows the lookup without app.tenant_id. Reset immediately after.
    db.execute(text("SELECT set_config('app.login_lookup', 'true', true)"))
    try:
        return (
            db.query(User)
            .filter(func.lower(User.email) == email.strip().lower())
            .first()
        )
    finally:
        db.execute(text("SELECT set_config('app.login_lookup', '', true)"))


def list_by_tenant(db: Session, tenant_id: str) -> list[User]:
    # Tenant filter in addition to RLS (defence-in-depth).
    return db.query(User).filter(User.tenant_id == tenant_id).all()


def create(
    db: Session,
    *,
    email: str,
    plain_password: str,
    role: Role,
    tenant_id: str | None,
) -> User:
    hashed = bcrypt.hashpw(
        plain_password.encode(), bcrypt.gensalt()
    ).decode()
    user = User(
        email=email.strip().lower(),
        hashed_password=hashed,
        role=role,
        tenant_id=tenant_id,
    )
    user.validate_role_tenant_consistency()
    db.add(user)
    db.flush()
    return user


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
