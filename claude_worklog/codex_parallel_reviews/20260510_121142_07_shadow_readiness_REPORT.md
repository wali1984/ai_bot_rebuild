# Shadow Mode Readiness Parallel Review

Verdict: BLOCKED for shadow-mode readiness as an operational comparison surface.

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

## Passing Findings

- Live gate remains blocked. `/api/v1/live/**` is default-denied by `LiveBlockGuardMiddleware` with HTTP 403 and `live.blocked_default` (`v2/backend/app/api/middleware/live_block_guard.py:97-114`), and the live router is only mounted under that guarded prefix (`v2/backend/app/main.py:112-121`).
- Shadow readiness flag cannot directly enable live. `ShadowModeReadinessFlag` only allows `not_ready` / `ready` and requires `live_blocked is True` (`v2/backend/app/domain/shadow_mode_readiness/flag.py:8-55`).
- The assembler rejects non-readiness live synonyms by allowed-set membership and always returns `live_blocked=True` (`v2/backend/app/services/shadow_mode_readiness/service.py:13-50`).
- The composition root is pure and only returns the readiness flag closure; it does not import execution, Redis, FastAPI routes, or trading adapters (`v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-40`).

## Blockers

1. No same-symbol same-snapshot legacy-vs-V2 comparator exists in the shadow readiness implementation.
   - The test harness `ShadowModeComparisonRecord` contains only `legacy_action_evidence_pointer` and `v2_risk_decision_record` (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`).
   - The fixture creates synthetic V2 `OrchestratorDecisionRecord` rows with `symbol` and `feature_snapshot_id`, but the legacy side is only a string pointer, not a legacy action/snapshot payload (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:156-173`).
   - Current tests assert pointer pairing and V2 lineage carry-over, not that legacy and V2 were evaluated on the same symbol and same source snapshot (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py:141-190`).

2. Divergence audit output is not part of the shadow readiness surface.
   - Divergence output exists in separate proof fixture builders (`v2/backend/app/proof/non_live_operational_proof.py:316-331`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239`), but the 2K readiness runtime only emits a flag.
   - The broader explainability projection explicitly forbids `paper_shadow_legacy_comparison` and `audit_timeline` fields (`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:66-92`), so there is no typed audit output tied to shadow readiness.

3. `ready` is caller-asserted, not evidence-gated.
   - `assemble_shadow_mode_readiness_flag` accepts `requested_state="ready"` and emits ready after timestamp validation only (`v2/backend/app/services/shadow_mode_readiness/service.py:16-50`).
   - It does not require a comparison summary, matched snapshot count, divergence audit path, or upstream evidence marker before readiness can be asserted.

## Proposed Non-Live Autofix Tasks

- Add a pure non-live shadow comparison service/domain object with explicit fields: `symbol`, `feature_snapshot_id` or snapshot hash, `legacy_action`, `v2_action`, `legacy_evidence_pointer`, `v2_risk_decision_id`, `diverged`, and `live_blocked=True`.
- Add validation that rejects symbol mismatch and snapshot mismatch before producing a comparison row.
- Add a non-live audit artifact builder that emits divergence JSON/Markdown under allowed worklog or `tmp_path` test outputs only; no Redis, exchange, order, leverage, margin, service restart, or deployment behavior.
- Change readiness assembly or add a separate readiness evaluator so `ready` requires a comparison summary with matched same-symbol same-snapshot rows and a materialized divergence audit reference.
- Add focused tests for matched comparison, symbol mismatch rejection, snapshot mismatch rejection, divergence count output, live-blocked invariant, and absence of execution/order/Redis imports.
