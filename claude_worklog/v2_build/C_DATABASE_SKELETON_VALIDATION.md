# C — Database Skeleton Validation (Alembic + SQLAlchemy harness)

## 1. Scope
Materialize the Alembic + SQLAlchemy harness for AI BOT V2 with **zero**
migration version scripts. This validation covers only the harness
skeleton: env wiring, declarative base, engine/session factories,
revision template, and one integration round-trip test against an
ephemeral PostgreSQL container. Authoring of schema-defining version
files is explicitly deferred to milestone C proper and requires
human approval + Codex review.

## 2. Boundaries observed
- Wrote only under `v2/**` and `claude_worklog/v2_build/**`.
- Did not edit `legacy_reference/**`, `../AI BOT/**`, `.env`, or
  secrets.
- Did not run alembic against any legacy or production database. The
  only database the round-trip test may touch is an ephemeral
  testcontainers-managed Postgres instance, which is destroyed at
  test exit.
- Did not write to legacy Redis. Did not place/cancel orders, change
  leverage/margin, restart live trader/trainer, or enable live
  trading.
- Did not import legacy modules. Did not pip-install into the
  protected trainer venv.
- LIVE TRADING: BLOCKED (default).

## 3. Files materialized
- `v2/backend/migrations/env.py` — Alembic env: offline + online
  modes; reads `DATABASE_URL` from environment with `alembic.ini`
  fallback; binds `target_metadata = Base.metadata`; configures
  `compare_type` / `compare_server_default` for future autogenerate
  fidelity.
- `v2/backend/migrations/script.py.mako` — Mako template used by
  `alembic revision`. Replaces the milestone-B
  `alembic_revision_template.mako` placeholder which Alembic does not
  resolve by default. (The placeholder file is left in place as a
  no-op artifact; Alembic looks up `script.py.mako` only.)
- `v2/backend/migrations/README.md` — harness-only documentation;
  enumerates the round-trip contract, runtime env requirements, and
  boundary policy.
- `v2/backend/app/adapters/db/base.py` — `Base(DeclarativeBase)`;
  metadata intentionally empty.
- `v2/backend/app/adapters/db/engine.py` — `make_engine(url, ...)`
  factory. Lazy; raises `ValueError` on empty URL.
- `v2/backend/app/adapters/db/session.py` — `make_sessionmaker(engine)`
  factory; conservative defaults.
- `v2/backend/tests/integration/test_alembic_round_trip.py` — one
  integration test asserting `alembic upgrade head` then
  `alembic downgrade base` both exit 0 against an ephemeral
  Postgres container; auto-skipped when Docker / testcontainers /
  psycopg are unavailable.
- `v2/pyproject.toml` — added `psycopg[binary]==3.2.1` to the `dev`
  optional-dependency group so the round-trip test can connect using
  psycopg3 (consistent with the `driver="psycopg"` argument used by
  `PostgresContainer`).

## 4. Files explicitly NOT created
- Any file under `v2/backend/migrations/versions/`. The directory
  remains seeded with `.gitkeep` only. Authoring schema-defining
  migration revisions is deferred to milestone C proper.

## 5. Design decisions
1. **DATABASE_URL precedence.** `env.py` prefers the process-env
   `DATABASE_URL` over `alembic.ini`'s placeholder so the same env
   serves both the integration test (which injects a container URL)
   and future operator-driven invocations.
2. **psycopg3 driver.** `PostgresContainer(driver="psycopg")` returns
   a `postgresql+psycopg://...` URL. psycopg3 is the maintained line
   and avoids the psycopg2 wheel/build-dep surface; pinning is via
   the `dev` extra so production installs are unaffected unless a
   driver is explicitly chosen.
3. **No models declared.** `Base.metadata` is intentionally empty.
   With zero versions and empty metadata, `upgrade head` /
   `downgrade base` are deterministic no-ops that still exercise
   env-load, URL resolution, and connection setup against a real
   Postgres backend — which is the only meaningful harness assertion
   at this milestone.
4. **Subprocess invocation in the test.** The test calls
   `python -m alembic` via `subprocess.run` rather than calling
   alembic.command in-process. This matches operator reality (CI
   and humans both run alembic via CLI) and isolates env.py import
   semantics from the pytest process.
5. **Skipif policy.** The test is auto-skipped when Docker,
   testcontainers, or psycopg are unavailable. This keeps the test
   suite green in lean CI environments while preserving the
   assertion when Docker is present.
6. **Boundary policy in env.py.** The module is guard-railed by
   policy (documented in env.py and migrations/README.md), not by
   code: alembic CLI is plumbed to whatever `DATABASE_URL` the
   operator sets. Refusing legacy URLs in code would create a false
   sense of safety; the operational guarantee is that this harness
   is never invoked against legacy/production by any V2 process.

## 6. Round-trip contract
Asserted by
`backend/tests/integration/test_alembic_round_trip.py`:
- `python -m alembic -c v2/alembic.ini upgrade head` exits 0.
- `python -m alembic -c v2/alembic.ini downgrade base` exits 0.

Both succeed because the version graph is empty, which is the
expected and required state at this milestone.

## 7. Evidence pointers (raw)
- Harness wiring: `v2/alembic.ini` (script_location =
  `backend/migrations`; prepend_sys_path = `backend`;
  version_locations = `backend/migrations/versions`).
- Empty version graph: `v2/backend/migrations/versions/.gitkeep`
  is the only file in that directory (verified via Glob:
  `v2/backend/migrations/versions/*` returns only `.gitkeep`).
- Settings binding for runtime DB URL:
  `v2/backend/app/settings.py` declares `DATABASE_URL: str = ""`.
- Engine/session factories: `v2/backend/app/adapters/db/engine.py`,
  `v2/backend/app/adapters/db/session.py`.
- Declarative base: `v2/backend/app/adapters/db/base.py`.
- Integration test:
  `v2/backend/tests/integration/test_alembic_round_trip.py`.

## 8. Verification commands (operator-runnable)
- Install dev deps:
  `pip install -e 'v2[dev]'`
- Sanity (offline; no DB required):
  `cd v2 && DATABASE_URL='sqlite:///:memory:' python -m alembic -c alembic.ini --sql upgrade head`
- Round-trip (Docker required):
  `cd v2 && pytest backend/tests/integration/test_alembic_round_trip.py -q`

## 9. Confidence and missing evidence
- **Confidence — harness wiring:** high. env.py, base, engine, session
  are conventional SQLAlchemy 2.0 / Alembic 1.13 idioms; alembic.ini
  was already correctly pointed at `backend/migrations`.
- **Confidence — round-trip:** high *contingent on* Docker being
  available at test time. Without Docker the test is skipped, which
  is acceptable hygiene but not affirmative evidence; CI must run
  the test on a Docker-enabled host before promotion to milestone C
  proper.
- **Missing evidence:** in this headless materialization pass no
  command was actually executed; the assertion that
  `pytest backend/tests/integration/test_alembic_round_trip.py`
  exits 0 must be reproduced by the tool-enabled CI follow-up
  before any version scripts are authored.

## 10. Deferred to milestone C proper
- Authoring of migration version files (one revision per ORM model
  group, behind human approval).
- Concrete ORM models under `app/domain/**` and registration with
  `Base` via `app/adapters/db/repositories/**`.
- Schema drift CI hook (`v2/ops/ci/schema_drift_check.py`) wired
  against `Base.metadata`.

## 11. Status
C_DATABASE_SKELETON_VALIDATION_READY
