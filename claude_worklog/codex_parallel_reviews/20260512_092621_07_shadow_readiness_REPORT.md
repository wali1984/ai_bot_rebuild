BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_092621_07_shadow_readiness_REPORT.md
# Shadow Mode Readiness Parallel Review

Verdict: BLOCKED for shadow-mode readiness as a legacy-vs-V2 operational comparison surface.

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

## Passing findings

- Live gate remains blocked. `v2/backend/app/api/middleware/live_block_guard.py` rejects `/api/v1/live` and `/api/v1/live/**` with HTTP 403 and `live.blocked_default`, and `v2/backend/app/api/v1/live_mode.py` is scaffold-only under `/live`.
- The live-readiness banner remains read-only and non-promotional. `v2/backend/app/api/v1/live_readiness.py` returns the online-readiness rollup and documents `live_gate_status="blocked_human_only"`.
- Shadow readiness flag cannot directly enable live. `v2/backend/app/domain/shadow_mode_readiness/flag.py` only permits `not_ready` and `ready`, and requires `live_blocked is True`.
- Shadow readiness assembly is pure and live-blocked. `v2/backend/app/services/shadow_mode_readiness/service.py` accepts only the two readiness states, rejects live-style state strings, calls the supplied clock once, and constructs `ShadowModeReadinessFlag(..., live_blocked=True)`.
- Composition root does not bind Redis, FastAPI, exchange, execution, paper ledger, or risk-gateway side effects. `v2/backend/app/composition/shadow_mode_readiness/runtime.py` only captures a clock and returns a callable wrapper around the assembler.
- Legacy readonly audit confirms shadow mode must compare legacy vs V2. `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` lists the required V2 impact: "shadow mode must compare legacy vs V2".

## Blockers

1. No same-symbol same-snapshot legacy-vs-V2 comparator is implemented in the shadow readiness surface.
   - `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py` defines `ShadowModeComparisonRecord` with only `legacy_action_evidence_pointer` and `v2_risk_decision_record`.
   - `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py` synthesizes V2 `OrchestratorDecisionRecord` rows with `symbol` and `feature_snapshot_id`, but the legacy side is only a string pointer. There is no legacy symbol, legacy snapshot id/hash, legacy action payload, or validation that both sides use the same market snapshot.
   - Existing harness tests assert pointer namespacing and V2 lineage carry-over, not same-symbol same-snapshot parity.

2. Divergence audit output is not tied to shadow readiness.
   - `v2/backend/app/proof/non_live_operational_proof.py` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` can emit separate fixture-style shadow comparison artifacts with `diverged` rows, but the 2K shadow readiness domain/service/composition stack emits only a readiness flag.
   - There is no typed shadow readiness audit artifact that records legacy action, V2 action, matched symbol, matched snapshot id/hash, divergence reason, and `live_gate_status`.

3. `ready` is caller-asserted rather than evidence-gated.
   - `assemble_shadow_mode_readiness_flag(requested_state="ready", ...)` emits `ready` after state and timestamp validation only.
   - It does not require a comparison summary, minimum matched comparison count, zero snapshot mismatches, a materialized divergence audit reference, or any upstream proof marker.

4. Legacy evidence pointers reference audit paths that are not in the current requested input set.
   - The shadow harness uses `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md#shadow_...` pointers.
   - This review was asked to inspect `claude_worklog/legacy_readonly_audit`, where the relevant files confirm requirements and process evidence but do not provide the per-row legacy action/snapshot payload needed for same-snapshot comparison.

## Proposed non-live autofix tasks

- Add a pure domain object for `ShadowModeComparisonRecord` with explicit fields: `symbol`, `feature_snapshot_id` or snapshot hash, `legacy_action`, `v2_action`, `legacy_evidence_pointer`, `v2_decision_id`, `v2_risk_decision_id`, `diverged`, `divergence_reason`, and `live_blocked=True`.
- Add a non-live comparator service that rejects symbol mismatch and snapshot mismatch before producing a comparison row.
- Add a non-live audit builder that emits deterministic JSON/Markdown divergence artifacts under test `tmp_path` or allowed worklog output only; it must not import Redis, exchange clients, execution routers, order placement, leverage/margin code, service restarters, or deployment code.
- Change readiness evaluation so `ready` requires an evidence summary: matched same-symbol same-snapshot rows, zero mismatch rejects, a divergence audit artifact reference, and `live_gate_status="blocked_human_only"`.
- Add focused tests for matched comparison, symbol mismatch rejection, snapshot mismatch rejection, divergence count output, ready blocked without evidence, live-blocked invariant, and absence of Redis/exchange/execution imports.

## Review result

Shadow decisions currently do not affect live execution, and the live gate remains blocked. The implementation is not ready for shadow-mode operational comparison because it lacks same-symbol same-snapshot legacy-vs-V2 comparison and a readiness-linked divergence audit.
END_FILE: claude_worklog/codex_parallel_reviews/20260512_092621_07_shadow_readiness_REPORT.md
