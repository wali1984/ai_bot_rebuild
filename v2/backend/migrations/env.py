"""Alembic env for AI BOT V2.

Harness only at this milestone. No migration version scripts exist
under ``backend/migrations/versions/``; with an empty version graph
``alembic upgrade head`` and ``alembic downgrade base`` resolve to
no-ops and exit 0. Authoring of version files is reserved for
milestone C proper, behind explicit human approval.

``target_metadata`` is bound to
:pydata:`app.adapters.db.base.Base.metadata` so future autogenerate
runs will see declared models. Today that metadata is intentionally
empty.

Database URL resolution order:
1. ``DATABASE_URL`` from the process environment (preferred; the
   integration test sets this against an ephemeral container).
2. ``sqlalchemy.url`` from ``alembic.ini`` (placeholder by default).

This env must NEVER be invoked against a legacy or production
database. The harness is paper/read-only by V2 policy.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.adapters.db.base import Base

config = context.config

_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live engine + connection)."""
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
