# Phase 2Y Test Plan

Domain tests cover valid `ProvenanceRecord`, negative source timestamp rejection, ingest-before-source rejection, freshness mismatch rejection, `live_blocked=False` rejection, Phase 2V trainer-field carriage, module import without Redis loading, valid dedupe states, unknown dedupe state rejection, duplicate pointer invariant rejection, dedupe `live_blocked=False` rejection, dedupe trainer-field carriage, no FastAPI lifespan registration, and public surface exports.

Service tests cover valid provenance assembly, non-record upstream rejection, keyword-only enforcement, trainer-field propagation, deterministic freshness, no Redis import, no FastAPI lifespan, valid dedupe assembly, non-record dedupe upstream rejection, dedupe keyword-only enforcement, dedupe trainer-field propagation, deterministic dedupe ID derivation, and public surface exports.

Composition tests cover runtime instance construction, zero clock calls for `provenance_now`, zero clock calls for `dedupe_decision_now`, keyword-only enforcement for both closures, no build-time clock call, invalid clock rejection, no Redis import, no FastAPI lifespan, and public surface exports.

The trainer-parity propagation fixture uses `model_version=hybrid_trainer_v2026_05`, `checkpoint_id=ckpt_duplicate_signal_blocked_2026_05`, `confidence_raw=0.71`, `confidence_calibrated=0.68`, and `trainer_worker_liveness=alive`.

PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TEST_PLAN_READY
