# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-11

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only review only. I did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, deploy, or expose secrets.

## Check Results

- Legacy-vs-V2 comparison readiness: BLOCKED. The legacy audit requires shadow mode to compare legacy vs V2 (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`), but the implemented production surface is only a readiness flag.
- Shadow decisions do not affect live: PASS for inspected code. The readiness flag requires `live_blocked is True` (`v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55`) and the assembler always emits `live_blocked=True` (`v2/backend/app/services/shadow_mode_readiness/service.py:47-51`).
- Same-symbol same-snapshot comparison: BLOCKED. The harness keeps the legacy side as only `legacy_action_evidence_pointer`, with no typed legacy symbol, feature snapshot id, action, reason, or timestamp (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`; `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`).
- Audit output for divergence: BLOCKED/PARTIAL. Proof output has fixture-derived `diverged` fields (`v2/backend/app/proof/non_live_operational_proof.py:316-330`), but there is no typed comparator/audit contract validating independently sourced legacy and V2 records before readiness can be asserted.
- Live gate remains blocked: PASS. `/api/v1/live` and `/api/v1/live/**` are default-denied with HTTP 403 and `x-live-blocked: default` (`v2/backend/app/api/middleware/live_block_guard.py:40-56`).

## Concrete Blockers

1. Readiness can be asserted without comparison evidence. `assemble_shadow_mode_readiness_flag` accepts only `requested_state` and `now_ms_clock`, then emits `state="ready"` when requested (`v2/backend/app/services/shadow_mode_readiness/service.py:16-51`). It does not require legacy evidence, V2 evidence, same-symbol validation, same-snapshot validation, or divergence audit output.

2. Current shadow evidence cannot prove same-symbol same-snapshot parity. `ShadowModeComparisonInput` stores a typed V2 orchestrator decision but only an opaque legacy pointer (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`). `ShadowModeComparisonRecord` likewise pairs that pointer with a V2 risk record (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`). Symbol or snapshot mismatches on the legacy side cannot be rejected.

3. Divergence output is not audit-grade readiness evidence. The non-live proof compares fixture fields (`legacy_action` vs `expected_v2_action`) and emits `diverged` (`v2/backend/app/proof/non_live_operational_proof.py:316-330`), but this is not consumed by the readiness flag and does not validate independently sourced legacy/V2 records.

4. Phase 2K intentionally scoped out the comparison surface. The implementation notes define Phase 2K as a typed precondition flag and explicitly state that no shadow-decision record, shadow-execution surface, Redis read/write, FastAPI surface, router, background loop, scheduler, or persistent shadow-decision store is introduced (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md:47-51`). That is safe, but insufficient for operational shadow-mode readiness.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with frozen typed records for legacy evidence, V2 evidence, comparison result, and divergence audit summary. Include symbol, feature snapshot id, action, reason, evidence ids/pointers, decision timestamp, `diverged`, comparison status, not-ready reason, and `live_blocked=True`.

2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects symbol mismatch and snapshot mismatch, computes action/reason divergence, and returns audit-ready records without importing Redis, DB adapters, exchange clients, order routers, schedulers, subprocess runners, live routes, or environment URL config.

3. Add unit tests for same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, action parity, action divergence, required audit fields, immutability, `live_blocked=True`, and forbidden live-side-effect tokens.

4. Add a non-live readiness aggregation service that can emit `ShadowModeReadinessFlag(state="ready", live_blocked=True)` only when valid comparison bundles exist, pair preconditions pass, and divergence audit output is present.

5. Extend `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/` to use typed legacy evidence instead of an opaque pointer while remaining fixture-only and avoiding Redis writes, DB writes, exchange calls, service restarts, live routes, order placement/cancellation, leverage/margin changes, deployment, or live enablement.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
