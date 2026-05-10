# Phase 2Y Provenance Dedupe Attribution Spec

`ProvenanceRecord` is a frozen, slotted dataclass with `provenance_id`, `source_id`, `ingestor_id`, `source_ts_ms`, `ingest_ts_ms`, `freshness_ms`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `risk_decision_id`, `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness`, and `live_blocked`.

Validation requires non-empty no-whitespace IDs, at-most-128-character lineage IDs, at-most-64-character source and ingestor IDs, non-bool nonnegative integer timestamps, `ingest_ts_ms >= source_ts_ms`, `freshness_ms == ingest_ts_ms - source_ts_ms`, float confidences in `[0.0, 1.0]`, trainer liveness in `{alive, degraded, worker_dead}`, and `live_blocked is True`.

`DedupeDecisionRecord` is a frozen, slotted dataclass with constants `DEDUPE_NEW`, `DEDUPE_DUPLICATE_OF_PRIOR`, and `DEDUPE_STALE_OUT_OF_ORDER`. It validates `dedupe_decision_id`, allowed dedupe state, the strict invariant that `duplicate_of_decision_id` is set iff the state is `DEDUPE_DUPLICATE_OF_PRIOR`, non-empty at-most-64-character `dedupe_reason`, mirrored lineage IDs, mirrored trainer-parity fields, and `live_blocked is True`.

`assemble_provenance_record` is keyword-only, accepts a `RiskDecisionRecord`, dedicated source fields, source/ingest timestamps, and the five Phase 2V trainer-parity inputs. It derives `provenance_id` as `f"prov:{decision_id}:{source_id}:{ingestor_id}"[:128]`, computes freshness, mirrors existing lineage IDs, and raises `ProvenanceServiceError` on invalid input.

`assemble_dedupe_decision_record` is keyword-only, accepts a `RiskDecisionRecord`, dedupe state inputs, dedupe reason, and the five Phase 2V trainer-parity inputs. It derives `dedupe_decision_id` as `f"dedupe:{decision_id}:{dedupe_state}"[:128]`, mirrors existing lineage IDs, enforces the duplicate pointer invariant, and raises `DedupeServiceError` on invalid input.

`build_provenance_dedupe_attribution_runtime` validates `now_ms_clock` is callable and never invokes it at build time or per call. The returned runtime exposes `provenance_now` and `dedupe_decision_now` closures that delegate to the pure assemblers. The captured clock is reserved for a future timestamp-emitting follow-up because current records carry authoritative source/ingest timestamps and deterministic dedupe IDs.

PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SPEC_READY
