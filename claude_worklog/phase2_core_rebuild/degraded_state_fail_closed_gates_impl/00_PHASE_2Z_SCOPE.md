```
# Phase 2Z — Degraded-State Fail-Closed Gates Domain Scope

## Lane

- Primary: legacy_parity
- Secondary: paper_backtest_mvp

## Consolidated typed-contract scope

This milestone authors the third of three REQ_0013 phase-order prerequisites
that gate SMC/liquidity feature shadow mode. Phase 2X authored
`ManualPositionFlag` / `ExternalPositionQuarantineRecord`. Phase 2Y authored
`ProvenanceRecord` / `DedupeDecisionRecord`. Phase 2Z authors:

1. Module-level constants `DEGRADED_SOURCE_OK`, `DEGRADED_SOURCE_STALE`,
   `DEGRADED_SOURCE_MISSING`, `DEGRADED_SOURCE_UNUSED`.
2. Typed value object `DegradedStateRecord` with:
   - `degraded_state_id` deterministically derived from upstream
     `decision_id` via `f"degraded_state:{decision_id}"[:128]`.
   - Per-source state and age fields covering the four REQ_0013 §
     "Required freshness / DQ gates" sources: `smc_state`, `smc_age_ms`,
     `liq_state`, `liq_age_ms`, `oi_state`, `oi_age_ms`,
     `orderbook_state`, `orderbook_age_ms`.
   - Derived invariant `fail_closed: bool` equal to `True` iff any
     per-source state is `DEGRADED_SOURCE_STALE` or
     `DEGRADED_SOURCE_MISSING` (and `False` otherwise).
   - Existing four lineage IDs `decision_id` / `prediction_id` /
     `feature_snapshot_id` / `risk_decision_id` mirrored from upstream.
   - The five Phase 2V trainer-parity fields `model_version`,
     `checkpoint_id`, `confidence_raw`, `confidence_calibrated`,
     `trainer_worker_liveness`.
   - `live_blocked` is `True`.
3. Pure-function service `assemble_degraded_state_record` validating
   inputs and constructing the record.
4. Composition root `build_degraded_state_fail_closed_gates_runtime`
   exposing a `degraded_state_now` closure that invokes the captured
   `now_ms_clock` zero times per call (clock reserved for a future
   Phase 2Z-follow-up where the runtime emits its own typed timestamp).
5. Non-live unit tests across domain / services / composition layers.
6. Documentation 00–07 under
   `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/`.

## Explicit non-actions

- No execution-side surface (no paper trader, paper executor, shadow
  trader, shadow executor, live trader, replay engine, scheduler,
  background loop, FastAPI surface, Redis adapter, GPU runner,
  model-loading subsystem, or strategy library).
- No new lineage ID — `degraded_state_id` is a deterministic derivation
  of an existing `decision_id`.
- No live-gate flip; live trading remains blocked and human-only.
- No prior-milestone byte mutation.
- No Redis import; no FastAPI lifespan registration.
- No SMC/liquidity feature work — Phase 2Z is prerequisite 3 only.

PHASE_2Z_SCOPE_READY
```
