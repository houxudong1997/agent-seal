"""Alembic environment configuration for agent-seal.

Reads DATABASE_URL from the environment (or alembic.ini fallback),
loads all ORM models via ``agent_seal.models.Base.metadata``.
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# ── Load our models so Base.metadata is populated ─────────────
# This line MUST appear before any alembic API calls that reference
# ``target_metadata`` — otherwise autogenerate produces empty migrations.
from agent_seal.models import Base
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name) if config.config_file_name else None

# Override sqlalchemy.url from env var if present (12-factor style)
# Checks same variables as agent_seal.config.Config.db_url
_db_url = os.getenv("AGENT_SEAL_DB_URL") or os.getenv("DB_URL") or os.getenv("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
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
