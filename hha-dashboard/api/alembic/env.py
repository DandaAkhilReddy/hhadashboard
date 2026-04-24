from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import Base + all model modules so Alembic sees every table
from app.models.base import Base
from app.models import masters  # noqa: F401  (registers models on Base.metadata)
from app.settings import settings

config = context.config

# Override sqlalchemy.url from our Settings (sync driver for Alembic)
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

OWNED_SCHEMAS = {"masters", "entries", "facts", "audit", "alerts", "dims"}


def include_name(name, type_, parent_names):
    """Limit Alembic autogenerate to our schemas."""
    if type_ == "schema":
        return name in OWNED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        compare_server_default=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
