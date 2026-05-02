# AI BOT V2 — Alembic Migrations

Harness only. Zero migration version scripts are checked in at this
milestone (C — database skeleton). Authoring of schema-defining version
files belongs to milestone C proper and requires explicit human
approval.

## Layout
- `env.py` — Alembic environment. Binds `target_metadata` to
  `app.adapters.db.base.Base.metadata`. Reads `DATABASE_URL` from the
  process environment when present, otherwise falls back to
  `sqlalchemy.url` from `alembic.ini`.
- `script.py.mako` — Mako template used by `alembic revision`.
- `versions/` — empty (`.gitkeep` only) until milestone C proper.

## Round-trip contract
With zero version scripts the harness must satisfy:
- `alembic -c v2/alembic.ini upgrade head` → exit 0 (no-op).
- `alembic -c v2/alembic.ini downgrade base` → exit 0 (no-op).

This contract is asserted by
`backend/tests/integration/test_alembic_round_trip.py` against an
ephemeral PostgreSQL container booted by `testcontainers`.

## Required runtime environment
- `DATABASE_URL` — full SQLAlchemy URL, e.g.
  `postgresql+psycopg://user:pass@host:5432/db`.
- A psycopg driver must be installed; the project pins
  `psycopg[binary]==3.2.1` in dev dependencies for this purpose.
- Docker is required only to run the integration round-trip test;
  the harness itself does not depend on Docker.

## Boundary policy
- This harness must NEVER be run against any legacy or production
  database. Only ephemeral, throwaway test databases are permitted.
- Migration version scripts must be authored only in milestone C
  proper, with explicit human approval and Codex review.
- The harness obeys the V2 default-deny posture: live trading remains
  BLOCKED regardless of database state.
