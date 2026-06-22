# Codex Review: V2 Website Rebuild Phase 1 Structure And Data Contracts

Generated: `2026-05-23T04:30:12Z`

GO/NO-GO: `V2_WEBSITE_REBUILD_PHASE_1_CODEX_PASS`

## Decision

Codex passes `V2_WEBSITE_REBUILD_PHASE_1_STRUCTURE_AND_DATA_CONTRACTS_READY`
after the route-reconciliation remediation. The prior blocker is closed:
backend Phase 1 page contracts now reconcile with actual frontend route
registration, aliases are registered, placeholder/data-contract routes
render, and the regression tests now compare declared routes against the
frontend route files/registry instead of only validating the contract
registry against itself.

This review does not approve live trading, canary trading, exchange
mutation, leverage/margin changes, Redis trim, approval creation,
checkpoint compatibility, policy architecture parity, production
equivalence, external feed adoption, automatic Symbol Universe adoption,
or legacy shutdown.

## Remediation Verified

Reviewed:

- `v2/backend/app/services/website/page_contracts.py`
- `v2/backend/app/services/website/redis_bridge_contracts.py`
- `v2/backend/app/cli/v2_website_contracts_status.py`
- `v2/backend/tests/unit/services/website/test_website_contracts.py`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/market/`
- `v2/frontend/src/pages/markets/`
- `v2/frontend/src/pages/config-admin/`
- `v2/frontend/src/pages/config/`
- `v2/frontend/src/pages/ai-brain/`
- `v2/frontend/src/pages/trader/`
- `v2/frontend/src/pages/history/`
- `v2/frontend/src/pages/report-center/`
- `v2/frontend/src/pages/signals/`
- `v2/frontend/src/pages/market-intelligence/`
- `v2/frontend/src/pages/positions/`
- `v2/frontend/src/pages/system-health/`
- refreshed Phase 1 worklog/public payloads

Current refreshed route reconciliation:

- page contracts: `12`
- declared canonical/alias routes: `15`
- frontend registered routes discovered: `45`
- `frontend_registered=true`
- `missing_frontend_routes=[]`
- `/market` registered as `market`
- `/markets` registered as `markets`
- `/admin/config-admin` registered as `config-admin`
- `/admin/config` registered as `config`
- `/ai-brain`, `/trader`, and `/history` registered
- `/admin/report-center` registered

## Route And Placeholder Checks

Codex verified:

- `/market` remains the canonical Market page and `/markets` is a
  registered alias route.
- `/admin/config-admin` remains the canonical Config Admin page and
  `/admin/config` is a registered alias route.
- `/ai-brain`, `/trader`, and `/history` render
  `PLACEHOLDER_WITH_CONTRACT` pages through `Phase1ContractPage`.
- The placeholder pages expose explicit states including
  `MISSING_PAYLOAD`, `STALE`, `V2_NATIVE_NOT_READY`,
  `LEGACY_BRIDGE_SOURCE`, and `DISPLAY_ONLY` where applicable.
- `/admin/report-center` remains available.
- `Signals`, `Market Intelligence`, `Positions`, and `System Health`
  are not empty hidden stubs; they use public payload hooks and show
  stale/missing placeholders rather than fake values.
- Refreshed payload state includes `MISSING_PAYLOAD=4` and `STALE=1`,
  proving missing/stale data remains visible in the contract layer.

## Data Boundary

Frontend pages consume public JSON payload paths through `usePayloadFile`
or existing public-payload hooks. Codex found no frontend Redis client,
Redis URL, `ioredis`, or direct Redis connection in the reviewed Phase 1
pages/hooks.

The backend website bridge contract is read-only and allowlisted. Its
Redis helper uses read operations only (`ping`, `type`, `get`, `hgetall`,
`lrange`, `sscan_iter`, `xrevrange`) and rejects non-allowlisted or
secret-like keys. V2-native, V2 bridge-from-legacy Redis, legacy
reference-only, and placeholder-not-ready source labels are explicit.

The prediction-key resolution contract still prefers
`v2:prediction:{symbol}:1m` before legacy bridge candidates and does not
label a legacy fallback as V2-native.

## Safety

Codex verified:

- no live, order, shutdown, or adopt-symbol control in the remediated
  alias/placeholder pages;
- the Market page has chart symbol selector buttons only, not trading or
  adoption controls;
- Config Admin metadata lists dangerous control ids for classification,
  but the rendered table is read-only and exposes no inputs/buttons;
- no direct frontend Redis read;
- no old Redis write path in the reviewed website contract/bridge code;
- no exchange order, cancel, leverage, margin, `/fapi/`, or mutation path
  in the reviewed website contract/route code;
- no approval creation or live/canary/shutdown/Redis-trim approval drift;
- no raw API key or secret exposure in Phase 1 public/worklog payloads
  or reviewed source paths;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for `.local_secrets` and secret terms are negative
redaction/safety text or forbidden-key patterns, not exposed secrets.

## Validation

- Website contracts refresh: PASS, `page_count=12`, `route_count=15`.
- Route reconciliation: PASS, `missing_frontend_routes=[]`.
- Website contract tests: PASS, `27 passed`.
- New route reconciliation tests: PASS.
- Backend `py_compile`: PASS.
- Frontend typecheck: PASS.
- Frontend production build: PASS.
- `/admin/report-center` route presence: PASS.
- Missing/stale placeholder visibility: PASS.
- V2-native vs legacy-bridge source labels: PASS.
- Direct frontend Redis scan: PASS.
- Website contract/bridge Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Secret scan: PASS.

## Final Decision

`V2_WEBSITE_REBUILD_PHASE_1_CODEX_PASS`
