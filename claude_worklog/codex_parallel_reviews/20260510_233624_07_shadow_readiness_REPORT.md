# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-10

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

No live service, Redis state, legacy tree, exchange order, leverage/margin setting, deployment, or live-trading enablement path was touched. Only this report and the requested GO/NO-GO marker were written.

## Passing Safety Evidence

- The shadow readiness domain exposes only `not_ready` and `ready`, and `ShadowModeReadinessFlag` requires `live_blocked is True`: `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-18`, `v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55`.
- The assembler accepts only `requested_state` plus an injected clock and always returns `live_blocked=True`: `v2/backend/app/services/shadow_mode_readiness/service.py:16-51`.
- The composition root only binds the injected clock to the assembler and does not introduce Redis, exchange, execution, scheduler, persistence, router, or live-trading behavior: `v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-41`.
- `/api/v1/live` and `/api/v1/live/**` remain default-denied with HTTP 403 and `x-live-blocked: default`: `v2/backend/app/api/middleware/live_block_guard.py:40-56`; the live router remains mounted behind that guarded prefix in `v2/backend/app/main.py:112-121`.
- Legacy audit sentinel is present: `claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md:1`.

## Check Results

- Legacy-vs-V2 comparison readiness: BLOCKED. Legacy audit requires shadow mode to compare legacy vs V2 (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`), but the production shadow readiness surface is a flag only.
- Shadow decisions do not affect live: PASS for inspected code. The shadow readiness path preserves `live_blocked=True` and exposes no order, cancel, leverage, margin, Redis write, service restart, deployment, or live-enable behavior.
- Same-symbol same-snapshot comparison: BLOCKED. The current test harness stores the legacy side as an opaque pointer string and the V2 side as a `RiskDecisionRecord`; it cannot validate legacy symbol or legacy feature snapshot identity.
- Audit output for divergence: PARTIAL/BLOCKED. Proof modules emit fixture-derived `diverged` rows, but there is no typed comparator/audit contract that validates independently sourced legacy and V2 records before marking readiness.
- Live gate remains blocked: PASS.

## Concrete Blockers

### Blocker 1 - Readiness can be asserted without comparison evidence

`assemble_shadow_mode_readiness_flag` can emit `state="ready"` after only validating the requested string and clock (`v2/backend/app/services/shadow_mode_readiness/service.py:16-51`). It does not require legacy decision evidence, V2 decision evidence, a matched symbol, a matched snapshot, or a divergence audit bundle.

Impact: the system can represent shadow readiness without satisfying the legacy audit requirement that shadow mode compare legacy vs V2.

### Blocker 2 - Same-symbol same-snapshot validation is impossible with current legacy input

The shadow evidence harness defines `ShadowModeComparisonRecord` with only `legacy_action_evidence_pointer` and `v2_risk_decision_record` (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`). Inputs likewise store `legacy_action_evidence_pointer` as a string beside a typed V2 orchestrator decision (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:156-173`).

Impact: BTC-vs-ETH, stale-vs-fresh, or snapshot-A-vs-snapshot-B legacy/V2 pairings cannot be rejected because the legacy side has no typed `symbol`, `feature_snapshot_id`, action, reason, or decision timestamp.

### Blocker 3 - Divergence output is fixture-derived, not audit-grade readiness output

`v2/backend/app/proof/non_live_operational_proof.py:316-330` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239` emit `diverged` rows by comparing fields on local proof fixtures. Those outputs are useful non-live proof artifacts, but they do not validate two independently sourced records and are not consumed by the shadow readiness flag.

Impact: divergence can be displayed in proof output, but shadow readiness is not gated by audit completeness, comparison preconditions, or divergence classification.

### Blocker 4 - Phase 2K explicitly scoped out the comparator

The Phase 2K evidence review says this milestone introduced a typed precondition flag and did not introduce a shadow-decision-record affordance (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md:47-51`). The 2K.C spec also forbids expanding the composition root with symbol filters, persistence, replay/ledger, and shadow decision lineage (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/18_PHASE_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_SPEC.md:99-129`).

Impact: the implementation passes its narrow milestone, but it does not satisfy operational shadow-mode comparison readiness.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with frozen records for typed legacy evidence, typed V2 evidence, comparison result, and divergence audit summary. Required fields should include legacy/V2 symbol, legacy/V2 feature snapshot id, legacy/V2 action, reason fields, ids or evidence pointers, decision timestamps, `diverged`, comparison status, not-ready reason, and `live_blocked=True`.
2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects symbol mismatch, rejects snapshot mismatch, computes action/reason divergence, and returns audit-ready records without importing Redis, DB adapters, exchange clients, order routers, schedulers, subprocess runners, or live routes.
3. Add unit tests for same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, action divergence, action parity, required audit fields, immutable records, live-blocked invariant, and forbidden live-side-effect tokens.
4. Add a read-only readiness aggregation service that can emit `ShadowModeReadinessFlag(state="ready", live_blocked=True)` only when valid comparison bundles exist, all pair-precondition checks pass, and divergence audit output is present.
5. Extend the existing shadow evidence harness to use typed legacy evidence instead of an opaque pointer while preserving fixture-only/non-live operation and avoiding Redis writes, DB writes, exchange calls, service restarts, live routes, order placement/cancellation, leverage/margin changes, deployment, or live enablement.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
