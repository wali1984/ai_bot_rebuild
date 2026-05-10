# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-10

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

## Summary

Shadow readiness remains safe from live execution, but it is not ready as a legacy-vs-V2 shadow comparison gate. The implemented `shadow_mode_readiness` production path is still a pure readiness flag boundary: `ShadowModeReadinessFlag(state, flag_emitted_ts_ms, live_blocked)`, a service assembler for `ready` / `not_ready`, and a composition root that binds an injected clock. It does not perform, persist, or audit legacy-vs-V2 comparison.

Newer proof modules add deterministic non-live `legacy_action` vs `v2_action` comparisons with `diverged` fields, but these are fixture proof artifacts, not an app audit output or enforced same-symbol same-snapshot comparator. Focused validation also failed one non-live proof safety test.

## Checks

### legacy-vs-V2 comparison readiness

BLOCKED. `v2/backend/app/proof/non_live_operational_proof.py` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` build fixture comparison rows containing `legacy_action`, `v2_action`, `symbol`, `feature_snapshot_id`, and `diverged`. This is useful operator proof evidence, but the production shadow readiness service/runtime does not expose a comparator. The Phase 2O shadow harness still pairs a legacy evidence pointer with a V2 `RiskDecisionRecord`, not a typed legacy decision row.

### shadow decisions do not affect live

PASS with residual test gap. The shadow readiness flag enforces `live_blocked is True`; the assembler rejects `live` / `live_enabled` requested states; `/api/v1/live/**` remains default-denied by `LiveBlockGuardMiddleware`; proof artifacts carry `live_gate_status = "blocked_human_only"`. No inspected shadow path places orders, writes Redis, restarts services, changes leverage/margin, or enables live trading.

### same-symbol same-snapshot comparison

BLOCKED. Fixture proof rows contain one shared `symbol` and `feature_snapshot_id`, but there is no typed legacy row with independent `legacy_symbol` and `legacy_feature_snapshot_id`, and no validator that refuses or flags mismatched legacy/V2 symbol or snapshot before a comparison is counted as ready.

### audit output for divergence

BLOCKED. Deterministic proof JSON/Markdown can report `diverged`, but `v2/backend/app/services/audit_writer.py` and `v2/backend/app/adapters/db/repositories/audit_events.py` are placeholders, and `/api/v1/audit` is scaffold-only. There is no append-only audit event or in-app audit envelope for shadow divergence.

### live gate remains blocked

PASS. `v2/backend/app/api/middleware/live_block_guard.py` still returns HTTP 403 for `/api/v1/live` and `/api/v1/live/**` with `live.blocked_default`, and `v2/backend/app/api/v1/live_mode.py` remains scaffold-blocked.

## Validation

- `.venv/bin/python -m pytest v2/backend/tests/unit/services/shadow_mode_readiness v2/backend/tests/unit/composition/shadow_mode_readiness v2/backend/tests/unit/domain/shadow_mode_readiness v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q`
- Result: `104 passed, 1 failed`.
- Failure: `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py::test_harness_does_not_use_live_side_effect_terms`.
- Cause: the test scans all `v2/backend/app/proof/*.py` files and finds `create_order`, `cancel_order`, `change_leverage`, and `change_margin` in `v2/backend/app/proof/readonly_market_exchange_data_plane.py`.

## Concrete Blockers

1. No production or test-only typed legacy-vs-V2 comparator enforces matching legacy/V2 symbol and feature snapshot.
2. No append-only audit envelope exists for shadow divergence; proof output is deterministic artifact output, not audit output.
3. The focused proof safety test currently fails because the proof package contains forbidden live-side-effect method names in the read-only market exchange data plane proof.
4. The shadow readiness production surface can emit `ready`, but that state is not tied to successful legacy-vs-V2 comparison completeness or divergence audit generation.

## Proposed Non-Live Autofix Tasks

1. Add a non-live typed shadow comparison fixture/model with explicit `legacy_symbol`, `legacy_feature_snapshot_id`, `legacy_action`, `v2_symbol`, `v2_feature_snapshot_id`, `v2_action`, `comparison_status`, `diverged`, and `divergence_reason_code`.
2. Add comparator tests that reject or mark not-ready on legacy/V2 symbol mismatch and feature-snapshot mismatch before any comparison is counted as ready.
3. Add deterministic in-memory shadow divergence audit envelope tests; do not write Redis, DB, exchange, live services, or external files outside test temp paths.
4. Wire shadow readiness `ready` in tests to successful comparison/audit artifact generation, while keeping production live gate blocked and avoiding execution-intent/order surfaces.
5. Fix the non-live proof safety scan by narrowing the scan to the intended proof module or by renaming the read-only stub mutation method tokens without adding any live behavior.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
