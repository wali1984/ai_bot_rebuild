# Shadow Mode Readiness Parallel Review

Review timestamp: 2026-05-12 04:21:02 America/New_York

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only constraints observed:
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not read or write Redis, delete Redis keys, restart services, deploy, place/cancel orders, change leverage/margin, or enable live trading.
- Did not run pytest to avoid read-only review side effects such as cache writes. This review used static inspection plus committed implementation reports.

## Pass Evidence

### Live gate remains blocked

- `v2/backend/app/api/middleware/live_block_guard.py` default-denies `/api/v1/live` and `/api/v1/live/**` with HTTP 403 and the `live.blocked_default` envelope.
- `v2/backend/app/api/v1/live_mode.py` remains scaffold metadata only; no order, position, cancel, leverage, margin, or live-enable handler is implemented.
- `v2/backend/app/api/v1/live_readiness.py` exposes a read-only banner outside `/live/` and documents `live_gate_status="blocked_human_only"`.
- Proof modules inspected keep `LIVE_GATE_STATUS = "blocked_human_only"` in non-live, historical 30d, online-readiness, external-manual-position, and readonly market/exchange proof surfaces.

### Shadow readiness flag does not affect live

- `v2/backend/app/domain/shadow_mode_readiness/flag.py` exposes only `not_ready` and `ready`, rejects unknown/live-style states, and requires `live_blocked is True`.
- `v2/backend/app/services/shadow_mode_readiness/service.py` accepts only those two states, invokes an injected clock once, and always constructs `ShadowModeReadinessFlag(..., live_blocked=True)`.
- `v2/backend/app/composition/shadow_mode_readiness/runtime.py` only captures an injected clock and forwards `requested_state` to the service. It does not import Redis, exchange clients, execution adapters, paper ledgers, or live routers.

### Audit output for divergence exists as offline fixture/proof output

- `v2/backend/app/proof/non_live_operational_proof.py` emits `shadow_comparison_result.json/.md` with `legacy_action`, `v2_action`, `diverged`, `operator_note`, lineage IDs, and `live_gate_status`.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` emits `legacy_vs_v2_decision_comparison.json`, `shadow_comparison_30d.json`, and dashboard `shadow_summary.divergence_count`.
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py` exercises a non-live evidence pack and asserts the readiness flag remains live-blocked.

## Blockers

1. No production shadow-comparison domain/service/composition contract exists.

   The implemented `shadow_mode_readiness` app surface is a readiness flag only. The only `ShadowModeComparisonRecord` found is in `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py`, which is test harness code. The proof modules produce fixture dictionaries, not reusable app-layer records with enforced invariants.

2. Same-symbol same-snapshot comparison is not enforced.

   The test harness pairs `legacy_action_evidence_pointer` with a V2 `RiskDecisionRecord`; the legacy side is a pointer string, not a typed projection carrying `symbol` and `feature_snapshot_id`. The proof fixture rows contain a single `symbol` and `feature_snapshot_id`, but no validator rejects `legacy.symbol != v2.symbol` or `legacy.feature_snapshot_id != v2.feature_snapshot_id` before emitting a divergence row.

3. Shadow decisions are not modeled as non-live-only records.

   The readiness flag requires `live_blocked=True`, and fixture outputs contain `shadow_decision_id`/`non_live_only` fields in places, but there is no app-layer `ShadowComparisonRecord` or `ShadowDecisionRecord` that requires `live_blocked=True`, `non_live_only=True`, and no execution-intent/order adapter dependency.

4. Divergence audit output is fixture-ready, not runtime-ready.

   `non_live_operational_proof.py` and `historical_30d_replay_and_paper_proof.py` can write deterministic local artifacts, but there is no non-live app service that accepts paired legacy/V2 inputs, validates lineage parity, computes bounded divergence reason codes, and returns an audit payload suitable for operator review.

## Proposed Non-Live Autofix Tasks

1. Add `v2/backend/app/domain/shadow_comparison/record.py` with frozen/slotted records:
   - `LegacyDecisionProjection(symbol, feature_snapshot_id, legacy_action, legacy_evidence_pointer, legacy_ts_ms)`
   - `ShadowComparisonRecord(shadow_comparison_id, legacy_projection, v2_risk_decision_record, diverged, divergence_reason_code, live_blocked, non_live_only)`
   - Reject symbol mismatch, feature snapshot mismatch, `live_blocked=False`, and `non_live_only=False`.

2. Add `v2/backend/app/services/shadow_comparison/service.py`:
   - Assemble comparison from one typed legacy projection and one V2 `RiskDecisionRecord`.
   - Compute `diverged` and a bounded divergence reason enum.
   - Avoid Redis, exchange clients, FastAPI routers, live routers, execution adapters, paper loops, schedulers, subprocess, and network clients.

3. Add `v2/backend/app/composition/shadow_comparison/runtime.py`:
   - Captured clock/id-factory binder only.
   - No writes except returning in-memory records; no Redis, exchange, or live side effects.

4. Add focused unit tests:
   - Same symbol and same feature snapshot passes.
   - Symbol mismatch rejects.
   - Feature snapshot mismatch rejects.
   - `live_blocked=False` and `non_live_only=False` reject.
   - Action match emits non-divergent audit fields.
   - Action mismatch emits divergent audit fields and bounded reason code.
   - Forbidden import/token scans cover Redis, order placement/cancel, leverage/margin, live-enable, deployment, network clients, and process restart.

5. Wire offline proof builders to use the new non-live app-layer comparison assembler instead of hand-built comparison dictionaries, while keeping output paths under existing allowed worklog/frontend prefixes.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
