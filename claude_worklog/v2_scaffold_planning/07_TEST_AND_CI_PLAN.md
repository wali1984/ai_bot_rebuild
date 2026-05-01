# 07 — Test and CI Plan

## 1. Test pyramid
- Unit (domain): 60%+ — pure functions in `app/domain/**`. No I/O. Property tests for lineage invariants via Hypothesis.
- Integration (services + adapters): 25–30% — runs against ephemeral Postgres and a sandbox Redis namespace `v2:test:*`. Never targets the legacy DB or legacy Redis.
- Contract (API): 10% — test vectors from `05_API_CONTRACTS.md` §13 plus `12B`, `12C`, `12D` closure vectors materialized as YAML fixtures.
- E2E (frontend): small surface — Playwright against the FastAPI app in test mode with synthetic fixtures.
- Property: dedicated suite for lineage chain invariants, idempotency replay, optimistic concurrency, audit-chain monotonicity.

## 2. Required test suites by milestone
- B: lint + type-check + import-cycle + schema-drift smoke. No domain tests yet.
- C: integration tests proving every NOT NULL/FK/CHECK/index from §3 of `03_DATABASE_SCHEMA.md`. Audit-chain INSERT-only test.
- D: contract tests for every API test vector. Middleware-order startup assertion test. Idempotency replay test. ETag concurrency test.
- E: Playwright nav test. RBAC visibility test. LIVE TRADING: BLOCKED banner persistence test. Default-deny inventory test (every dangerous control disabled).
- F: monitor-rendering tests for each packet type and rejection class. Validation run age-window test.
- G: discovery determinism test (same input → same candidate set).
- H: selection determinism test (seed → same ranking).
- I: feature snapshot completeness predicate property test. Cardinality placeholder rule test.
- J: subprocess boundary test (assert no legacy module is imported into the FastAPI process; assert audit emission per call).
- K: risk gateway phase-order property test. Kill-switch persistence test. Duplicate-guard test. Live-block default-deny test.
- L: replay determinism test. Chain-walk test on every paper trade.
- M: per-trader paper-only invariant test.
- N: GO-input checklist test (each criterion individually toggleable in test fixtures).

## 3. Determinism guarantees enforced in tests
- UUIDv7 generation is seeded in tests; replay produces byte-identical responses.
- Idempotency: same `(key, actor, body_hash)` returns identical envelope.
- Replay runner: same input → same `(prediction_id, signal_id, decision_id)` chain.

## 4. Lint / type-check / import-cycle gates (milestone B mandatory)
- `ruff check v2/backend` — zero warnings.
- `mypy v2/backend --strict` — zero errors.
- `tsc --noEmit` over `v2/frontend` — zero errors.
- `eslint` over `v2/frontend` — zero warnings.
- `ops/ci/import_cycle_check.py` — runs `grimp` over backend and `madge` over frontend; fails on any cycle or forbidden edge listed in `02_PACKAGE_AND_MODULE_MAP.md` §3.
- `ops/ci/schema_drift_check.py` — diffs Alembic head vs SQLAlchemy metadata; non-zero diff fails CI starting milestone C.

## 5. CI workflow (planning view)
A single CI workflow under `ops/ci/` runs the matrix below. The workflow targets local-native execution per `CLAUDE.md` Local-Native First Runtime Constraints; Docker is optional and not required to pass CI.

| Stage | Command | Required from milestone |
|------|---------|--------------------------|
| lint | `ruff check`, `eslint` | B |
| type | `mypy --strict`, `tsc --noEmit` | B |
| import cycle | `python ops/ci/import_cycle_check.py` | B |
| schema drift | `python ops/ci/schema_drift_check.py` | C |
| unit | `pytest backend/tests/unit -q` | C |
| integration | `pytest backend/tests/integration -q` (testcontainers PG) | C |
| contract | `pytest backend/tests/contract -q` | D |
| frontend unit | `vitest run` | E |
| e2e | `playwright test` | E |
| a11y | `axe` (within Playwright) | E |
| coverage | `pytest --cov` ≥ 80% on `app/domain` | C |
| security audit | `pip-audit`, `npm audit --omit=dev` (advisory until G) | B advisory; H mandatory |
| secrets scan | `gitleaks` over the diff | B mandatory |

CI fails if any required stage fails. Codex review tasks are dispatched by the supervisor outside CI but are tracked alongside the CI run on each gate.

## 6. Coverage gates
- Domain coverage ≥ 80% line + ≥ 70% branch starting milestone C.
- Lineage validators 100% line coverage starting milestone D.
- Risk gateway phase code 100% line coverage starting milestone K.
- Audit-chain code 100% line coverage starting milestone D.

## 7. Determinism for replay tests
The replay runner (`backend/tests/integration/test_replay_determinism.py`) seeds UUIDv7, freezes `now()` via `freezegun`, and asserts identical outputs across runs. A test failure here reopens milestone L.

## 8. Test data policy
- Test data is synthetic. No legacy data, no production secrets, no scraped exchange data is committed.
- Fixtures under `backend/tests/fixtures/` are versioned. Updates require a comment line referencing the architecture/closure that drove the change.

## 9. Performance / load (out of milestone B; tracked here)
- Performance suites are not part of milestone B's gate. They are added at milestone L (replay throughput) and milestone M (paper fleet throughput) under separate validation artifacts.
- Performance is never traded against safety; a passing perf suite never overrides a failing risk-gateway test.

## 10. CI runtime constraints
- Local-native first per `CLAUDE.md`. Docker optional.
- CI must run within a single host with ephemeral Postgres + namespaced Redis. The legacy Redis is never touched by CI.
- The trainer venv is never invoked from CI. Trainer adapter tests use a stub subprocess that simulates `--mode read_only/status/export` outputs.

## 11. Status
TEST AND CI PLAN: DEFINED. CI WORKFLOW MATERIALIZES IN MILESTONE B. EVERY DOWNSTREAM MILESTONE EXTENDS THE PYRAMID.