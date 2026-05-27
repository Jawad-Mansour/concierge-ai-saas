# Owner: Mohammad

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL is set by the backend at startup after fetching from Vault.
# For local CLI use: export DATABASE_URL=postgresql+psycopg2://...
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL not set. Fetch the value from Vault and export it before "
        "running alembic commands."
    )
config.set_main_option("sqlalchemy.url", database_url)

# Import all models so autogenerate can detect schema changes.
# Teammates: add your model imports here when you create your models.
from app.models.tenant import Tenant  # noqa: F401, E402
from app.models.user import User      # noqa: F401, E402
from app.db import Base               # noqa: F401, E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
