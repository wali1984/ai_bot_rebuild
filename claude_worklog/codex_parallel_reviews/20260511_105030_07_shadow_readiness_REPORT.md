# Shadow Mode Readiness Parallel Review

Review timestamp: 2026-05-11 10:50:30 America/New_York

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only constraints observed:
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not read/write Redis, delete Redis keys, restart services, deploy, place/cancel orders, alter leverage/margin, or enable live trading.
- Did not run pytest to avoid read-only-mode cache/output writes. This review is static plus committed worklog evidence.

## Pass Evidence

### Live gate remains blocked

- `v2/backend/app/api/middleware/live_block_guard.py` default-denies `/api/v1/live` and `/api/v1/live/**` with HTTP 403 and `live.blocked_default`.
- `v2/backend/app/api/v1/live_mode.py` is scaffold-only metadata; no live order/cancel handler body is exposed.
- `v2/backend/app/api/v1/live_readiness.py` documents and returns read-only banner state with `live_gate_status="blocked_human_only"`.
- Proof modules keep `LIVE_GATE_STATUS = "blocked_human_only"` in both `v2/backend/app/proof/non_live_operational_proof.py` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`.

### Shadow readiness flag does not enable live

- `v2/backend/app/domain/shadow_mode_readiness/flag.py` exposes only `not_ready` and `ready` states, validates state membership, and requires `live_blocked is True`.
- `v2/backend/app/services/shadow_mode_readiness/service.py` accepts only the two readiness states and always constructs the flag with `live_blocked=True`.
- `v2/backend/app/composition/shadow_mode_readiness/runtime.py` is only a captured-clock binder around the service.

### Offline audit/proof surfaces exist

- `v2/backend/app/proof/non_live_operational_proof.py` emits `shadow_comparison_result` rows with `legacy_action`, `v2_action`, `diverged`, `operator_note`, lineage IDs, and `live_gate_status`.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` emits `legacy_vs_v2_decision_comparison.json` and `shadow_comparison_30d.json`; its dashboard payload includes `shadow_summary.divergence_count`.
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py` pairs a legacy evidence pointer with a V2 `RiskDecisionRecord` and asserts the readiness flag remains live-blocked.

## Blockers

1. No production shadow-comparison domain/service/composition surface exists.

   The actual `v2/backend/app/domain/shadow_mode_readiness`, `services/shadow_mode_readiness`, and `composition/shadow_mode_readiness` implementation is only a readiness flag. The comparison record found under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py` is test harness code, not an app surface. The proof modules emit fixture artifacts, but they do not provide a reusable V2 runtime contract for shadow comparison.

2. Same-symbol same-snapshot comparison is not enforced for legacy-vs-V2 inputs.

   The offline harness stores `legacy_action_evidence_pointer` plus a V2 `RiskDecisionRecord`, but the legacy side is a pointer string, not a typed legacy decision/snapshot object with `symbol` and `feature_snapshot_id` fields. The proof rows carry one `symbol` and one `feature_snapshot_id`, but there is no validator that rejects mismatched legacy symbol vs V2 symbol or legacy snapshot vs V2 snapshot before producing a divergence row.

3. Shadow decisions are not modeled as non-live-only decision records.

   The readiness flag correctly blocks live, and later proof fixtures contain `shadow_decision_id`, but there is no app-layer `ShadowComparisonRecord` or `ShadowDecisionRecord` with an invariant like `live_blocked=True`, `non_live_only=True`, no execution intent dispatch, and no order-placement adapter dependency. Current evidence relies on fixture discipline rather than typed app invariants.

4. Audit output for divergence is fixture-ready, not runtime-ready.

   `non_live_operational_proof.py` and `historical_30d_replay_and_paper_proof.py` can emit divergence fields, but those outputs are deterministic fixtures/historical proof writers. There is no production audit writer contract that receives paired legacy/V2 records, validates lineage parity, emits divergence reason fields, and guarantees no live/Redis/order side effects.

## Proposed Non-Live Autofix Tasks

1. Add `v2/backend/app/domain/shadow_comparison/record.py` with frozen/slotted records:
   - `LegacyDecisionProjection(symbol, feature_snapshot_id, legacy_action, legacy_evidence_pointer, legacy_ts_ms)`
   - `ShadowComparisonRecord(shadow_comparison_id, legacy_projection, v2_risk_decision_record, diverged, divergence_reason_code, live_blocked, non_live_only)`
   - Reject any `legacy_projection.symbol != v2_risk_decision_record.symbol`.
   - Reject any `legacy_projection.feature_snapshot_id != v2_risk_decision_record.feature_snapshot_id`.
   - Require `live_blocked is True` and `non_live_only is True`.

2. Add `v2/backend/app/services/shadow_comparison/service.py`:
   - Assemble a comparison from one typed legacy projection and one V2 `RiskDecisionRecord`.
   - Compute `diverged` and a bounded divergence reason enum.
   - Do not import Redis, exchange clients, FastAPI routers, execution adapters, paper loops, schedulers, subprocess, or network clients.

3. Add `v2/backend/app/composition/shadow_comparison/runtime.py`:
   - Captured-clock/id-factory binder only.
   - No live side effects and no runtime writes.

4. Add focused unit tests:
   - Same symbol/same feature snapshot passes.
   - Symbol mismatch rejects.
   - Feature snapshot mismatch rejects.
   - `live_blocked=False` and `non_live_only=False` reject.
   - Divergence audit fields are emitted for action mismatch and not emitted for action match.
   - Forbidden import/token scans for Redis, exchange order methods, live-enable, leverage/margin, deployment, and network clients.

5. Wire proof modules to use the new non-live app-layer shadow comparison assembler rather than hand-built fixture dicts, while keeping artifact output paths under existing allowed worklog/frontend prefixes only.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
