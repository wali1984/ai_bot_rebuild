# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-11

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only review constraints observed except for writing this requested report and GO/NO-GO artifact. I did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, deploy, or expose secrets.

## Check Results

- Legacy-vs-V2 comparison readiness: BLOCKED. The legacy audit requires shadow mode to compare legacy vs V2 (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`), but the implemented shadow-readiness production surface is a readiness flag, not a typed comparison pipeline.
- Shadow decisions do not affect live: PASS for inspected code. The shadow readiness domain rejects any flag where `live_blocked` is not exactly `True` (`v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55`), and the assembler always emits `live_blocked=True` (`v2/backend/app/services/shadow_mode_readiness/service.py:47-51`).
- Same-symbol same-snapshot comparison: BLOCKED. The V2 side carries `symbol` and `feature_snapshot_id`, but the shadow harness legacy side is only an opaque `legacy_action_evidence_pointer` (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`; `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`). There is no typed legacy symbol or snapshot field to validate.
- Audit output for divergence: PARTIAL/BLOCKED. Offline proof code emits fixture-derived `diverged` rows and counts (`v2/backend/app/proof/non_live_operational_proof.py:226-240`; `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:265-278`), but the audited `audit_writer` is only a placeholder (`v2/backend/app/services/audit_writer.py:1`) and readiness is not gated by typed divergence audit completeness.
- Live gate remains blocked: PASS for inspected shadow-readiness path. The execution router remains a placeholder that documents live order calls as blocked until a later milestone (`v2/backend/app/services/execution_router.py:1-4`), proof payloads retain `live_gate_status = "blocked_human_only"` (`v2/backend/app/proof/non_live_operational_proof.py:26`; `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:10-12`), and the shadow-readiness flag does not introduce a live-enable state.

## Concrete Blockers

1. Readiness can be asserted without comparison evidence. `assemble_shadow_mode_readiness_flag` accepts only `requested_state` and `now_ms_clock`; a caller can request `ready` and receive a ready flag without legacy evidence, V2 evidence, same-symbol validation, same-snapshot validation, or divergence audit output (`v2/backend/app/services/shadow_mode_readiness/service.py:16-51`).

2. The current evidence harness cannot prove same-symbol same-snapshot parity. `ShadowModeComparisonInput` stores a typed V2 orchestrator decision and an opaque legacy pointer only. `ShadowModeComparisonRecord` pairs that pointer with a V2 risk decision. Symbol and snapshot mismatches on the legacy side cannot be rejected (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`; `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`).

3. Divergence output exists only as fixture/proof output, not as an audit-grade readiness contract. The proof writers compare local fixture fields such as `legacy_action` and `v2_action` and emit `diverged`, but no production comparator consumes independently typed legacy and V2 records, validates pairing preconditions, emits audit rows through an audit service, or blocks readiness when audit output is incomplete.

4. Phase 2K intentionally scoped shadow readiness as a typed precondition flag. The implementation notes explicitly state that Phase 2K does not introduce a shadow-decision record, shadow-execution surface, persistent shadow-decision store, Redis read/write, FastAPI surface, router, background loop, scheduler, or live-execution surface (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md:47-51`). That is safe, but insufficient for the requested operational shadow-mode readiness checks.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with frozen typed records for legacy evidence, V2 evidence, comparison result, and divergence audit summary. Required fields should include legacy/V2 symbol, legacy/V2 feature snapshot id, action, reason, evidence ids or pointers, timestamps, `diverged`, comparison status, not-ready reason, and `live_blocked=True`.

2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects symbol mismatch, rejects feature snapshot mismatch, computes action/reason divergence, and returns audit-ready records without importing Redis, DB adapters, exchange clients, order routers, schedulers, subprocess runners, live routes, or environment URL config.

3. Add unit tests for same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, action parity, action divergence, required audit fields, immutability, `live_blocked=True`, and forbidden live-side-effect imports/tokens.

4. Add a non-live readiness aggregation service that can emit `ShadowModeReadinessFlag(state="ready", live_blocked=True)` only when valid comparison bundles exist, pair preconditions pass, and divergence audit output is present.

5. Extend `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/` to use typed legacy evidence instead of an opaque pointer while remaining fixture-only and avoiding Redis writes, DB writes, exchange calls, service restarts, live routes, order placement/cancellation, leverage/margin changes, deployment, or live enablement.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
