# 04 — API Route Scaffold Plan

## 1. Authority
`claude_worklog/v2_architecture/05_API_CONTRACTS.md` and `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` are the canonical contract sources. This plan defines how milestone D materializes them as FastAPI handlers, validators, and middleware. Milestone B scaffolds the *empty* router and middleware files; milestone D fills them.

## 2. Route prefix and versioning conventions (frozen here per Codex remediation §15)
- Base prefix: `/api/v1`.
- All routes pluralized resource form: `/api/v1/feature-snapshots`, `/api/v1/predictions`, `/api/v1/signals`, etc.
- Health and meta routes under `/api/v1/_meta/{health,build,readiness}`.
- Public-surface routes under `/public/v1/`. Public surface is read-only and never exposes lineage IDs of internal-only resources without RBAC mapping.
- Live-mode routes nested under `/api/v1/live/` and ALL default-deny via `live_block_guard` middleware until L5 approval.

## 3. Universal middleware order
The middleware stack is deterministic. Per `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` §middleware-order, the order is:

1. `request_id` (assigns/validates `X-Request-Id` UUIDv7)
2. `ip_allowlist` (rejects non-allowlisted IPs on admin surface)
3. `rate_limit` (per-actor token bucket)
4. `auth_session` (resolves session → actor subject)
5. `step_up_mfa` (forces step-up assertion for L3+ routes)
6. `rbac` (route-level role check)
7. `idempotency` (deduplicates `POST/PUT/PATCH/DELETE` by `(key, actor, body_hash)`)
8. `lineage_validator` (per §1.3.1 of API contracts)
9. `approval_gate` (single-use consumption of `L4`/`L5` approval tokens)
10. `live_block_guard` (refuses `live`-marked actions when `live_readiness_state != active`)
11. `db_error_translator` (maps PG IntegrityError → `lineage.*` / `feature_snapshot.*` / `confidence.*` taxonomy)
12. router/handler
13. response envelope writer

The order is enforced by a startup assertion that introspects `app.user_middleware`. Any reorder fails startup.

## 4. Error taxonomy materialized
The error taxonomy module `app/api/errors/taxonomy.py` enumerates the closed set of error classes. The minimum set required for milestone D:

- Schema: `schema.unknown_field`, `schema.type_mismatch`, `schema.required_missing`.
- RBAC: `rbac.forbidden`, `rbac.role_unbound`.
- Approval: `approval.required`, `approval.consumed`, `approval.expired`, `approval.subject_mismatch`.
- Idempotency: `idempotency.replay_mismatch`, `idempotency.key_required`.
- Concurrency: `concurrency.etag_mismatch`, `concurrency.etag_required`.
- Lineage (seven classes per §3.2/§3.3): `lineage.malformed`, `lineage.missing_required`, `lineage.cross_symbol`, `lineage.cross_timeframe`, `lineage.parent_unknown`, `lineage.gap_reason_missing`, `lineage.downstream_set_too_early`.
- Feature snapshot (eleven classes per `12C` §6 / `11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md` §7.3): `feature_snapshot.source_grounding_missing`, `feature_snapshot.freshness_missing`, `feature_snapshot.feature_value_orphan`, `feature_snapshot.completeness_invalid`, `feature_snapshot.checkpoint_unknown`, `feature_snapshot.symbol_unknown`, `feature_snapshot.timeframe_unknown`, `feature_snapshot.duplicate_id`, `feature_snapshot.manifest_unknown`, `feature_snapshot.placeholder_misuse`, `feature_snapshot.cardinality_invalid`.
- Confidence (nine classes per `12C` §7 / `11` §7.4–7.5): `confidence.block_missing`, `confidence.contributor_count_low`, `confidence.placeholder_misuse`, `confidence.calibration_missing`, `confidence.calibration_stale`, `confidence.model_version_mismatch`, `confidence.checkpoint_mismatch`, `confidence.score_out_of_range`, `confidence.contributor_orphan`.
- Live: `live.blocked_default`, `live.readiness_not_active`, `live.dangerous_setting_unauthorized`.
- Audit: `audit.chain_break`, `audit.append_only_violation`.

Every error class maps to a fixed HTTP status (400/403/404/409/412/422 as per the contract document) and to a deterministic envelope under `response.error.class`.

## 5. Lineage validator (pre-handler)
`app/api/middleware/lineage_validator.py` implements the §9.1 nine validators:

1. Lineage block presence on every prediction/signal/decision/risk/intent payload.
2. Required upstream IDs by stage (table in `05_API_CONTRACTS.md` §1.3.2).
3. Downstream IDs explicit `null` (omission = `lineage.malformed`).
4. `lineage_gap_reason` enum value when any null is present where it should be filled.
5. Cross-symbol rejection (`lineage.cross_symbol`).
6. Cross-timeframe rejection (`lineage.cross_timeframe`).
7. Parent existence pre-check via repository read (`lineage.parent_unknown`).
8. `policy_version`, `model_version`, `checkpoint_id`, `config_version` carriage when the route's stage requires them.
9. UUIDv7 well-formedness on every chain field.

The validator's nine rules are individually testable. Each validator emits exactly one error class on failure.

## 6. DB error translator
`app/api/middleware/db_error_translator.py` maps Postgres errors to taxonomy:

- FK violation on `feature_snapshot_id` -> `lineage.parent_unknown`.
- Unique violation on `idempotency_keys` -> `idempotency.replay_mismatch`.
- Check violation on `policy_bundle_state` -> `risk.policy_state_invalid`.
- Append-only trigger violation on `audit_events` -> `audit.append_only_violation`.
- Constraint name conventions are agreed in the migration plan so the translator can route by constraint name without parsing free text.

## 7. Endpoint groups (route surface frozen for milestone D)
- `/_meta/` — health, build info, readiness.
- `/auth/` — login, logout, MFA, step-up, session refresh, token revocation.
- `/accounts/` — user, role binding (admin only).
- `/exchanges/` — connectors, capabilities, health (read), credential management (admin, L4).
- `/universe/` — versions, members, scoring, overrides, hot-reload triggers (admin).
- `/discovery/` — passive market discovery feed.
- `/selection/` — adaptive selection what-if and outputs.
- `/feature-snapshots/`, `/predictions/`, `/signals/`, `/decisions/`, `/risk-decisions/`, `/execution-intents/`, `/paper-trades/` — lineage chain endpoints.
- `/risk/` — policy bundles, kill switch (admin, L4), live readiness (admin, L4).
- `/replay/` — deterministic replay.
- `/fleet/` — multi-trader fleet (paper-only).
- `/monitor/` — packets, validation runs, dimension statuses.
- `/evidence/` — packet retrieval.
- `/audit/` — audit ledger queries.
- `/governance/` — approvals lifecycle.
- `/claude-admin/`, `/codex/`, `/ollama/` — AI supervision endpoints.
- `/live/` — default-deny, L5-gated.

Each endpoint group is one router file per §1 of `02_PACKAGE_AND_MODULE_MAP.md`. In milestone B these files exist as empty routers with `prefix=...` and a single `OPTIONS` shim that returns the route's contract metadata; the actual handlers are written in milestone D.

## 8. Test vector fixtures
Milestone D imports the §13 test vectors from `05_API_CONTRACTS.md` as `backend/tests/contract/vectors/*.yaml`. Each file declares input + expected `status` + expected `error.class` (or success shape). The contract test runner asserts:

- HTTP status matches.
- `error.class` matches.
- Response envelope conforms to the JSON Schema.
- Audit event was emitted with the expected `event_class`.

A pass matrix is appended to `claude_worklog/v2_build/D_API_VALIDATION.md`. Any vector failure reopens `12B`.

## 9. Idempotency / concurrency contracts
- `X-Idempotency-Key` required on every mutating method. Replay returns the prior response byte-identical.
- `If-Match: <etag>` required on every mutation of a versioned resource. Mismatch returns `concurrency.etag_mismatch` 412.

## 10. Live-block guard
`app/api/middleware/live_block_guard.py` enforces the default-deny invariant per `12_RISK_GATEWAY_ARCHITECTURE.md`. Any route bound to a `live`-mode action MUST be wrapped by this guard. The guard reads `live_readiness_state.state` and the active `approvals` chain at request time. The default response is `live.blocked_default` with HTTP 403 and the banner-state echoed in the response envelope.

## 11. Status
API ROUTE SCAFFOLD: PLANNED. ROUTE FILES MATERIALIZE EMPTY IN MILESTONE B; HANDLERS, VALIDATORS, AND TEST VECTORS MATERIALIZE IN MILESTONE D.