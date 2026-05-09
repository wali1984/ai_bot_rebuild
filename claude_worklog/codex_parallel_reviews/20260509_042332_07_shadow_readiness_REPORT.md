# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-09

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

No live path, Redis write/delete, service restart, exchange order, leverage/margin, deployment, or live-trading enablement action was performed.

## Passing Safety Evidence

- Live gate remains blocked at the shadow readiness flag boundary. `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-18` only defines `not_ready` and `ready`, and `v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55` rejects any flag where `live_blocked` is not the boolean `True`.
- The assembler only accepts the two non-live requested states and constructs flags with literal `live_blocked=True`: `v2/backend/app/services/shadow_mode_readiness/service.py:13-29` and `v2/backend/app/services/shadow_mode_readiness/service.py:47-51`.
- The composition root is a pure clock-bound wrapper around the assembler and exposes no Redis, exchange, execution, router, scheduler, or live-trading surface.
- Legacy audit evidence explicitly requires shadow mode to compare legacy versus V2: `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`.
- The non-live proof artifact has a blocked live gate marker, `LIVE_GATE_STATUS = "blocked_human_only"`, and emits a synthetic `shadow_comparison_result` containing `legacy_action`, `v2_action`, and `diverged`: `v2/backend/app/proof/non_live_operational_proof.py:26` and `v2/backend/app/proof/non_live_operational_proof.py:281-293`.

## Blockers

### Blocker 1 - The production shadow readiness implementation is only a readiness flag, not legacy-vs-V2 comparison readiness

The inspected production implementation proves that shadow readiness cannot enable live execution, but it does not implement a real legacy-vs-V2 comparison contract. `ShadowModeReadinessFlag` carries only `state`, `flag_emitted_ts_ms`, and `live_blocked`; the service maps `requested_state` to that flag; the composition root only binds the clock.

Impact: readiness for actual shadow comparison is not established. The system can say `ready`, but it cannot prove that a legacy decision and V2 decision were compared under a typed production comparison surface.

### Blocker 2 - Same-symbol same-snapshot comparison is not enforced against legacy evidence

The test-only shadow evidence harness pairs an opaque legacy pointer with a V2 risk decision record:

- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:59-65`

There is no typed legacy row with `legacy_symbol`, `legacy_feature_snapshot_id`, `legacy_action`, or legacy observation timestamp. Therefore the harness cannot reject mismatched legacy/V2 symbol or mismatched legacy/V2 snapshot before counting a comparison as ready.

Impact: the review requirement for same-symbol same-snapshot legacy-vs-V2 comparison is not met.

### Blocker 3 - Divergence audit output exists only as synthetic proof, not as a comparison/audit contract

`v2/backend/app/proof/non_live_operational_proof.py:281-293` emits deterministic synthetic comparison rows with `legacy_action`, `v2_action`, and `diverged`, which is useful operator proof. However, it derives all lineage from a single `ProofScenario` object (`v2/backend/app/proof/non_live_operational_proof.py:30-43`, `v2/backend/app/proof/non_live_operational_proof.py:166-184`) rather than independently validating legacy evidence against V2 evidence.

Impact: divergence is visible, but not audit-grade for readiness because the output does not prove that two independently sourced records were compared and validated on the same symbol/snapshot.

## Proposed Non-Live Autofix Tasks

1. Add a non-live `shadow_comparison` domain/test harness object with typed legacy evidence fields: `legacy_symbol`, `legacy_feature_snapshot_id`, `legacy_action`, `legacy_decision_ts_ms`, and `legacy_evidence_pointer`.
2. Extend the comparison record to include V2 symbol/snapshot/action, legacy symbol/snapshot/action, `comparison_status`, `diverged`, and `divergence_reason_code`.
3. Add unit tests that reject or mark not-ready when legacy and V2 symbols differ, or when legacy and V2 feature snapshot IDs differ.
4. Add deterministic in-memory audit rows for divergence output. Keep them file/test-only or pure-return-value only: no Redis, DB, exchange, background loop, service restart, or live execution.
5. Keep the current live gate invariant unchanged: no `live`, `live_enabled`, `enable_live`, order placement, leverage/margin, or live adapter activation in any shadow readiness path.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
