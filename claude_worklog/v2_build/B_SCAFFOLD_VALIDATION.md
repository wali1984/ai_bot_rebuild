# B — Scaffold Validation (015A)

## 1. Scope
Materialize the V2 repo/package skeleton EXACTLY as specified by the embedded
canonical map from `claude_worklog/v2_scaffold_planning/02_PACKAGE_AND_MODULE_MAP.md`.
No runtime behavior. No router handlers. No Alembic versions. Frontend limited
to `package.json`, `tsconfig.json`, `vite.config.ts` per 015A directive.

## 2. Boundaries observed
- Wrote only under `v2/**` and `claude_worklog/v2_build/**`.
- Did not edit `legacy_reference/**`, `../AI BOT/**`, `.env`, or secrets.
- Did not place/cancel orders, change leverage/margin, write to legacy Redis,
  restart live trader/trainer, or enable live trading.
- Did not import legacy trainer modules into the FastAPI process; the trainer
  adapter exposes a subprocess boundary only.
- Did not pip install into the trainer venv.
- LIVE TRADING: BLOCKED (default).

## 3. Top-level artifacts produced under `v2/`
- `pyproject.toml` (Python project + dev deps; pinned versions, no ranges).
- `package.json` (root workspace declaration referencing `frontend`).
- `tsconfig.json` (root, references frontend).
- `alembic.ini` (script_location = `backend/migrations`; zero versions).
- `README.md` (planning-only stub).

## 4. Backend package tree (every path required by the embedded map)
- `backend/app/__init__.py`
- `backend/app/main.py` — FastAPI factory `create_app()`; registers v1 routers; no I/O at import; no startup events.
- `backend/app/settings.py` — `pydantic-settings` only; no `dotenv_values`; no I/O at import.
- `backend/app/logging.py` — placeholder; no I/O at import.

### 4.1 `app/api/v1` (router stubs only; no handler bodies)
`__init__.py`, `health.py`, `mission_control.py`, `universe.py`, `discovery.py`,
`selection.py`, `exchanges.py`, `ingestors.py`, `features.py`, `predictions.py`,
`signals.py`, `decisions.py`, `risk.py`, `intents.py`, `paper.py`, `replay.py`,
`fleet.py`, `monitor.py`, `evidence.py`, `audit.py`, `governance.py`,
`claude_admin.py`, `codex_review.py`, `ollama_assistant.py`,
`live_readiness.py`, `live_mode.py` (default-deny).

### 4.2 `app/api/middleware`
`__init__.py`, `request_id.py`, `idempotency.py`, `rbac.py`, `approval.py`,
`lineage_validator.py`, `live_block_guard.py`, `db_error_translator.py`,
`rate_limit.py`, `ip_allowlist.py`, `step_up_mfa.py`.

### 4.3 `app/api/errors`
`__init__.py`, `envelope.py`, `taxonomy.py` (placeholder for lineage.*,
feature_snapshot.*, confidence.*, schema.*, rbac.*, approval.* classes).

### 4.4 `app/api/schemas`
`__init__.py`, `lineage.py`, `feature_snapshot.py`, `prediction.py`,
`signal.py`, `decision.py`, `risk_decision.py`, `execution_intent.py`,
`paper_trade.py`, `envelope.py`.

### 4.5 `app/domain` (pure modules; no I/O imports)
- `__init__.py`
- `lineage/` — `__init__.py`, `ids.py`, `chain.py`, `validators.py`
- `features/` — `__init__.py`, `snapshot.py`, `completeness.py`, `source_grounding.py`, `manifest.py`
- `predictions/__init__.py`, `signals/__init__.py`, `decisions/__init__.py`
- `risk/` — `__init__.py`, `policy_bundle.py`, `phases.py`, `kill_switch.py`, `live_readiness_state.py`
- `execution/` — `__init__.py`, `intent.py`, `paper.py`
- `universe/` — `__init__.py`, `version.py`, `members.py`, `scoring.py`
- `hot_reload/` — `__init__.py`, `rollout.py`, `state_machine.py`, `quorum.py`, `rollback.py`
- `governance/` — `__init__.py`, `levels.py`, `approvals.py`, `audit_chain.py`
- `connectors/` — `__init__.py`, `base.py`, `capabilities.py`, `health.py`
- `traders/` — `__init__.py`, `fleet.py`, `trader.py`
- `monitor/` — `__init__.py`, `dimensions.py`, `packets.py`, `rejection.py`
- `replay/` — `__init__.py`, `deterministic.py`

### 4.6 `app/adapters` (only place that performs I/O — but stubs only here)
- `__init__.py`
- `db/` — `__init__.py`, `engine.py`, `session.py`,
  `repositories/{__init__.py, feature_snapshots.py, predictions.py, signals.py, decisions.py, risk_decisions.py, execution_intents.py, audit_events.py, evidence_packets.py, universe_versions.py, symbol_overrides.py, governance_approvals.py, sessions.py, accounts.py}`
- `redis_v2/` — `__init__.py`, `client.py`, `streams.py`, `retention.py`
- `trainer/` — `__init__.py`, `subprocess_adapter.py`, `modes.py`, `audit_emitter.py`
- `orchestrator/` — `__init__.py`, `adapter.py`
- `exchanges/` — `__init__.py`, `binance/__init__.py`, `bybit/__init__.py`, `okx/__init__.py`, `generic_ccxt/__init__.py` (no SDK imports at module load)
- `ollama/` — `__init__.py`, `client.py`, `prompt_loader.py`
- `codex/` — `__init__.py`, `review_client.py`
- `claude_admin/` — `__init__.py`, `client.py`
- `evidence/` — `__init__.py`, `packet_writer.py`, `packet_reader.py`

### 4.7 `app/services`
`__init__.py`, `feature_assembly.py`, `prediction_ingest.py`,
`signal_publisher.py`, `orchestrator_decision.py`, `risk_gateway.py`,
`execution_router.py`, `replay_runner.py`, `paper_loop.py`,
`discovery_runner.py`, `selection_runner.py`, `hot_reload_orchestrator.py`,
`monitor_runner.py`, `audit_writer.py`.

### 4.8 `app/jobs`
`__init__.py`, `scheduler.py`, `tasks/{__init__.py, packet_emitter.py, retention_sweeper.py, freshness_check.py}`.

### 4.9 `app/cli`
`__init__.py`, `v2ctl.py` (diagnostics-only placeholder; no live actions).

### 4.10 `backend/migrations` (harness only; no versions)
- `env.py` (offline + online entry points; no model metadata bound yet)
- `alembic_revision_template.mako`
- `versions/.gitkeep` (zero version scripts)

### 4.11 `backend/tests`
`__init__.py` plus subpackages `unit/`, `integration/`, `contract/`,
`property/`, `fixtures/` each with `__init__.py`.

## 5. Frontend artifacts (015A scope: 3 files only)
- `frontend/package.json` (React 18.3.1, Vite 5.4.8, TS 5.6.2; pinned).
- `frontend/vite.config.ts` (React plugin; strictPort 5173; sourcemap on).
- `frontend/tsconfig.json` (strict; noEmit; React JSX; bundler resolution).

The `frontend/src/**` page tree from §1 of the canonical map is intentionally
NOT materialized in 015A per the 015A execution clarification. It is deferred
to milestone E.

## 6. Ops artifacts
- `ops/ci/lint.sh` — placeholder shell stub.
- `ops/ci/type_check.sh` — placeholder shell stub.
- `ops/ci/test.sh` — placeholder shell stub.
- `ops/ci/import_cycle_check.py` — placeholder; will enforce §3 forbidden-import rules.
- `ops/ci/schema_drift_check.py` — placeholder; wired in milestone C+.

## 7. Docs
- `docs/INDEX.md` — links to canonical planning artifacts and to this validation file.

## 8. Boundary contracts honored in scaffold
- `app/api/**` does not import `app/adapters/**` directly (router files import
  only `fastapi.APIRouter`).
- `app/domain/**` modules contain no `requests`, `redis`, `sqlalchemy`,
  `httpx`, `psycopg`, `asyncpg`, or `ccxt` imports. They are pure.
- `app/adapters/trainer/**` does not import any module from
  `legacy_reference/**` or `../AI BOT/**`. Subprocess boundary preserved.
- `dotenv` is not imported anywhere; settings use pydantic-settings only.
- `frontend/src/pages/**` is not present yet, so the rule "pages must not
  import `api/client.ts` directly" is trivially satisfied.

## 9. Default-deny posture
- `V2_MODE` defaults to `paper` in `app/settings.py`.
- `app/api/v1/live_mode.py` exists as a router stub with no handlers; live
  trading remains BLOCKED until the milestone O gates and L5 approvals.
- Execution router service file documents `LiveBlockedError` until milestone O.
- No exchange SDK imports at module load.

## 10. Deferred (intentionally NOT done in 015A)
- Concrete handlers, services, repositories, schemas, errors.
- Alembic version scripts (milestone C).
- Frontend `src/**` page tree, theme, auth, hooks, PWA, mobile bridge (milestone E).
- CI commands inside the `ops/ci/*.sh` stubs (milestone B+).
- Concrete `import_cycle_check.py` and `schema_drift_check.py` logic.

## 11. Verification (planning-level for 015A; concrete CI runs deferred)
Files listed in §3–§7 above are the exact set required by the embedded
canonical map for this scaffold pass. The map's §1 frontend `src/**` subtree
is deferred per 015A directive and is the only documented deviation.

No tools were invoked; this artifact was emitted as BEGIN_FILE blocks per the
015A headless contract. CI-driven proof of lint/type-check/import-cycle/test
passing is the gate for promoting this artifact to `READY` in a tool-enabled
follow-up.

## 12. Status
B_SCAFFOLD_VALIDATION_READY