# Owner: Charbel

"""Widget config repository — reads widget_configs table."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_by_widget_id(widget_id: str, db: Session) -> dict | None:
    """Return widget_config row as dict, or None if not found.

    Does NOT set RLS tenant context — this is a pre-auth lookup.
    widget_id is a public identifier so we read without tenant filter.
    Uses app.widget_lookup='true' to activate the widget_id_lookup RLS
    bypass policy (mirrors the app.login_lookup pattern on users).
    """
    db.execute(text("SELECT set_config('app.widget_lookup', 'true', true)"))
    try:
        row = db.execute(
            text("SELECT * FROM widget_configs WHERE widget_id = CAST(:wid AS uuid)"),
            {"wid": widget_id},
        ).fetchone()
    finally:
        db.execute(text("SELECT set_config('app.widget_lookup', '', true)"))
    if row is None:
        return None
    return dict(row._mapping)
