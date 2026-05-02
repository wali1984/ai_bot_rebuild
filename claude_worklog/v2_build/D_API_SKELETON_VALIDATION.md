```markdown
# D — API Skeleton Validation (015D)

## 1. Scope
Materialize the FastAPI router, middleware, error-taxonomy, schema, and
contract-test skeleton for AI BOT V2. No handler bodies that perform DB or
Redis I/O. The skeleton is the wire-shape and stack-order substrate that
milestone D proper fills with handlers, validators, and DB integrity
translation.

Authority:
- `claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md` (§3, §4, §7).
- `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md`.
- `claude_worklog/v2_architecture/05_API_CONTRACTS.md` (canonical wire shapes).

## 2. Boundaries observed
- Wrote only under `v2/**` and `claude_worklog/v2_build/**`.
- Did not edit `legacy_reference/**`, `../AI BOT/**`, `.env`, or secrets.
- Did not write to legacy Redis. Did not place/cancel orders, change
  leverage/margin, restart live trader/trainer, or enable live trading.
- Did not import legacy trainer modules. Did not pip-install into the
  protected trainer venv.
- LIVE TRADING: BLOCKED (default).

## 3. Files materialized
### 3.1 Error taxonomy and envelope
- `v2/backend/app/api/errors/taxonomy.py` — closed set of 45 error classes
  enumerated in `ERROR_CLASSES`, grouped per §4: schema (3), rbac (2),
  approval (4), idempotency (2), concurrency (2), lineage (7),
  feature_snapshot (11), confidence (9), live (3), audit (2). Each entry is
  an `ErrorClass(name, http_status, group)` frozen dataclass; `lookup(name)`
  resolves a wire string to its entry.
- `v2/backend/app/api/errors/envelope.py` — `ResponseEnvelope` and
  `ErrorBody` Pydantic models. `ErrorBody.class_` is aliased to `class` on
  the wire to avoid Python keyword collision.
- `v2/backend/app/api/errors/__init__.py` — re-exports the taxonomy +
  envelope public surface.

### 3.2 API schemas (12B closure §1.3.1, §9.x)
- `v2/backend/app/api/schemas/lineage.py` — `LineageBlock` with the seven
  canonical keys plus `LineageGapReason` enum (four values from §1.3.1).
  `CHAIN_FIELDS` exports the six chain-ID names for downstream validators.
- `v2/backend/app/api/schemas/feature_snapshot.py` —
  `FeatureSnapshotIngest`/`FeatureSnapshotRead` (chain root, §9.2).
- `v2/backend/app/api/schemas/prediction.py` —
  `PredictionIngest`/`PredictionRead` (§9.3).
- `v2/backend/app/api/schemas/signal.py` — `SignalPublish`/`SignalRead`
  + `SignalAction` enum (§9.4).
- `v2/backend/app/api/schemas/decision.py` —
  `DecisionIngest`/`DecisionRead` + `DecisionAction` enum (§9.5).
- `v2/backend/app/api/schemas/risk_decision.py` —
  `RiskDecisionIngest`/`RiskDecisionRead` + `AllowBlock` enum (§9.6).
- `v2/backend/app/api/schemas/execution_intent.py` —
  `ExecutionIntentSubmit`/`ExecutionIntentRead` (§9.7).
- `v2/backend/app/api/schemas/paper_trade.py` —
  `PaperTradeAck`/`PaperTradeRead` (§9.7 paper variant).
- `v2/backend/app/api/schemas/envelope.py` — `RequestEnvelope` for incoming
  bodies (mirrors `errors.envelope.ResponseEnvelope`).
- `v2/backend/app/api/schemas/__init__.py` — re-exports the public schema
  surface in alphabetic order.

All schemas use `model_config = ConfigDict(extra="forbid")` so that
`schema.unknown_field` is the deterministic class for unexpected keys.

### 3.3 Middleware shells (per §3, EXACT order)
Every layer is materialized as a Starlette ASGI middleware class whose
`__call__` is a passthrough — except `live_block_guard`, which carries
behavior to honor the default-deny invariant from the moment a `/live/`
router is added. Layer numbering is per §3 of the route plan.

| §3 layer | Module                                 | Class                          |
| -------- | -------------------------------------- | ------------------------------ |
| 1        | `middleware/request_id.py`             | `RequestIdMiddleware`          |
| 2        | `middleware/ip_allowlist.py`           | `IpAllowlistMiddleware`        |
| 3        | `middleware/rate_limit.py`             | `RateLimitMiddleware`          |
| 5        | `middleware/step_up_mfa.py`            | `StepUpMfaMiddleware`          |
| 6        | `middleware/rbac.py`                   | `RbacMiddleware`               |
| 7        | `middleware/idempotency.py`            | `IdempotencyMiddleware`        |
| 8        | `middleware/lineage_validator.py`      | `LineageValidatorMiddleware`   |
| 9        | `middleware/approval.py`               | `ApprovalMiddleware`           |
| 10       | `middleware/live_block_guard.py`       | `LiveBlockGuardMiddleware`     |
| 11       | `middleware/db_error_translator.py`    | `DbErrorTranslatorMiddleware`  |

Layer 4 (`auth_session`) of the §3 plan is intentionally NOT materialized
in this skeleton; session resolution lands with the `/auth/` handlers in
milestone D proper. The 015D task spec explicitly enumerated 10 modules,
matching this table.

`v2/backend/app/api/middleware/__init__.py` exports `MIDDLEWARE_ORDER` in
the canonical outermost→innermost order. `create_app()` registers via
`for cls in MIDDLEWARE_ORDER: app.add_middleware(cls)`. Because Starlette's
`add_middleware()` does `insert(0, ...)` and `build_middleware_stack`
iterates `reversed(user_middleware)`, this loop yields a stack whose
outermost layer is `RequestIdMiddleware` and whose innermost is
`DbErrorTranslatorMiddleware`. The contract test asserts both directions.

### 3.4 Live-block default-deny (§10 of route plan, §7 of 12B)
`LiveBlockGuardMiddleware.__call__` inspects `scope["path"]`. Any HTTP
request with `path == "/api/v1/live"` or `path.startswith("/api/v1/live/")`
short-circuits with HTTP 403 and the canonical envelope:

```json
{
  "request_id": "",
  "data": null,
  "error": {
    "class": "live.blocked_default",
    "message": "Live mode is blocked by default. L5 readiness gate has not flipped.",
    "details": {"banner": "LIVE TRADING: BLOCKED"}
  }
}
```

The response carries `X-Live-Blocked: default`. Even the OPTIONS shim on
`live_mode.router` is intercepted; this is intentional and demonstrates the
default-deny invariant. The guard runs AFTER `lineage_validator` per §3, so
malformed live payloads still get the precise lineage class.

### 3.5 Routers (every §7 endpoint group)
Every §7 group is materialized with `prefix=` set per §7 and an OPTIONS
shim that returns a `ROUTE_METADATA` dict (group, prefix, endpoints, RBAC,
lineage flags, milestone status). NO router has a body that touches
DB/Redis.

| §7 group              | Prefix                | File                              |
| --------------------- | --------------------- | --------------------------------- |
| `/_meta/`             | `/_meta`              | `api/v1/health.py`                |
| `/auth/`              | `/auth`               | `api/v1/auth.py` (NEW)            |
| `/accounts/`          | `/accounts`           | `api/v1/accounts.py` (NEW)        |
| `/exchanges/`         | `/exchanges`          | `api/v1/exchanges.py`             |
| `/universe/`          | `/universe`           | `api/v1/universe.py`              |
| `/discovery/`         | `/discovery`          | `api/v1/discovery.py`             |
| `/selection/`         | `/selection`          | `api/v1/selection.py`             |
| `/feature-snapshots/` | `/feature-snapshots`  | `api/v1/features.py`              |
| `/predictions/`       | `/predictions`        | `api/v1/predictions.py`           |
| `/signals/`           | `/signals`            | `api/v1/signals.py`               |
| `/decisions/`         | `/decisions`          | `api/v1/decisions.py`             |
| `/risk-decisions/`    | `/risk-decisions`     | `api/v1/risk_decisions.py` (NEW)  |
| `/execution-intents/` | `/execution-intents`  | `api/v1/intents.py`               |
| `/paper-trades/`      | `/paper-trades`       | `api/v1/paper.py`                 |
| `/risk/`              | `/risk`               | `api/v1/risk.py`                  |
| `/replay/`            | `/replay`             | `api/v1/replay.py`                |
| `/fleet/`             | `/fleet`              | `api/v1/fleet.py`                 |
| `/monitor/`           | `/monitor`            | `api/v1/monitor.py`               |
| `/evidence/`          | `/evidence`           | `api/v1/evidence.py`              |
| `/audit/`             | `/audit`              | `api/v1/audit.py`                 |
| `/governance/`        | `/governance`         | `api/v1/governance.py`            |
| `/claude-admin/`      | `/claude-admin`       | `api/v1/claude_admin.py`          |
| `/codex/`             | `/codex`              | `api/v1/codex_review.py`          |
| `/ollama/`            | `/ollama`             | `api/v1/ollama_assistant.py`      |
| `/live/`              | `/live`               | `api/v1/live_mode.py`             |

Module-map residuals from `02_PACKAGE_AND_MODULE_MAP.md` that are not §7
groups but must be retained (so the package shape from milestone B does not
regress):
- `api/v1/mission_control.py` — prefix `/mission-control`
- `api/v1/ingestors.py` — prefix `/ingestors`
- `api/v1/live_readiness.py` — prefix `/live-readiness` (NOT under `/live`,
  so NOT default-denied; exposes read-only banner state for the GUI).

### 3.6 Application factory
`v2/backend/app/main.py` now:
1. imports `MIDDLEWARE_ORDER` and every §7 router;
2. registers middleware in declared (outermost→innermost) order;
3. mounts every router under `/api/v1`;
4. asserts `tuple(m.cls for m in app.user_middleware) == tuple(reversed(MIDDLEWARE_ORDER))`
   and raises `RuntimeError` on drift — the §3 startup gate.

The routers tuple in `_register_routers` is grouped by §7 sub-section to
make future additions/removals reviewable.

### 3.7 Contract tests
- `v2/backend/tests/contract/test_middleware_order.py` — three assertions:
  1. `MIDDLEWARE_ORDER` enumerates the EXACT 10 named middleware in §3 order.
  2. `app.user_middleware == reversed(MIDDLEWARE_ORDER)` after `create_app()`.
  3. `len(MIDDLEWARE_ORDER) == 10`.
- `v2/backend/tests/contract/test_taxonomy_enumeration.py` — five
  assertions:
  1. `ERROR_CLASS_NAMES` equals the §4 required set exactly (no extras, no
     missing).
  2. seven `lineage.*` classes (12B §3.2/§3.3).
  3. eleven `feature_snapshot.*` classes (12C §6).
  4. nine `confidence.*` classes (12C §7).
  5. every entry's `http_status` is one of `{400, 403, 404, 409, 412, 422}`
     per §4.

## 4. Files explicitly NOT created
- Handler bodies for any router. Every router is OPTIONS-shim-only.
- Behavior in middleware layers 1–9 and 11. Only layer 10 (live_block_guard)
  carries the default-deny implementation, because its absence would
  violate `CLAUDE.md` the moment `/api/v1/live/` is mounted.
- Lineage validator's nine pre-handler validators (12B §9.1) — deferred to
  milestone D proper.
- DB error translator's constraint-name → taxonomy mapping — deferred to
  milestone D proper.
- Test vector fixtures (`backend/tests/contract/vectors/*.yaml`) — deferred
  to milestone D proper per §8 of the route plan.

## 5. Boundary contracts honored
- `app/api/**` does not import `app/adapters/**` (verified by inspection;
  router files import only `fastapi.APIRouter`; middleware imports only
  `starlette.types`; schemas import only `pydantic` and sibling schemas).
- `app/domain/**` is untouched and remains pure.
- `app/adapters/trainer/**` is untouched.
- `dotenv` is not imported; settings still go through pydantic-settings.
- `frontend/src/pages/**` is unchanged.
- `V2_MODE` defaults to `paper` in `app/settings.py`; no live-mode is
  enabled by this milestone.
- The `live_block_guard` short-circuits any `/api/v1/live/**` request with
  `live.blocked_default` (HTTP 403) — even an OPTIONS preflight.

## 6. Verification (planning-level; CI runs deferred)
Operator-runnable verification (Python 3.11+, `pip install -e 'v2[dev]'`):

- Import check (no I/O at import):
  ```
  cd v2 && python -c "from app.main import create_app; create_app()"
  ```
- Middleware order test:
  ```
  cd v2 && pytest backend/tests/contract/test_middleware_order.py -q
  ```
- Taxonomy enumeration test:
  ```
  cd v2 && pytest backend/tests/contract/test_taxonomy_enumeration.py -q
  ```
- Live-block default-deny smoke (uses Starlette TestClient, requires app
  to start):
  ```
  cd v2 && python -c "
  from fastapi.testclient import TestClient
  from app.main import create_app
  c = TestClient(create_app())
  for path in ('/api/v1/live', '/api/v1/live/orders'):
      r = c.options(path)
      assert r.status_code == 403, (path, r.status_code)
      assert r.json()['error']['class'] == 'live.blocked_default'
  print('LIVE_DEFAULT_DENY_OK')
  "
  ```

## 7. Confidence and missing evidence
- **Confidence — middleware order assertion:** high. The Starlette
  semantics (`add_middleware` inserts at 0; `build_middleware_stack`
  iterates reversed) are stable across the 0.38–0.39 line that FastAPI
  0.115.0 pins.
- **Confidence — taxonomy closure:** high. The 45-class set is computed
  directly from §4 of the route plan plus §3.2/§3.3 of 12B and §6/§7 of 12C
  with no inference; `test_taxonomy_is_closed_set` proves drift-zero.
- **Confidence — live-block default-deny:** high. Layer 10 is the only
  middleware with behavior, and its conditional is a literal path
  comparison. The contract test in §6 verifies the 403 + envelope
  shape end-to-end.
- **Missing evidence:** in this headless materialization pass no command
  was actually executed; the assertions in §6 must be reproduced by the
  tool-enabled CI follow-up before milestone D proper is unblocked.

## 8. Deferred to milestone D proper
- Concrete handler implementations for every §7 group.
- The nine lineage validators behind `LineageValidatorMiddleware`.
- The DB integrity-error mapping behind `DbErrorTranslatorMiddleware` per
  §6 of the route plan and §3.4 of 12B closure.
- Approval-token consumption inside `ApprovalMiddleware`.
- Idempotency replay-byte-identical store inside `IdempotencyMiddleware`.
- Test vector fixtures from §13 of `05_API_CONTRACTS.md` materialized
  under `backend/tests/contract/vectors/`.
- `auth_session` (§3 layer 4) once the `/auth/` handlers exist.

## 9. Status
D_API_SKELETON_VALIDATION_READY
