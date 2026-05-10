# Phase 2Y Scope

Phase 2Y authors the non-live typed contract for provenance freshness and deterministic duplicate attribution.

In scope:
- `ProvenanceRecord`, a frozen value object with deterministic `provenance_id`, source and ingest timestamps, computed freshness, the four existing lineage IDs, the five Phase 2V trainer-parity fields, and `live_blocked=True`.
- `DedupeDecisionRecord`, a frozen value object with deterministic `dedupe_decision_id`, dedupe state, strict duplicate pointer invariant, the four existing lineage IDs, the five Phase 2V trainer-parity fields, and `live_blocked=True`.
- Pure service functions `assemble_provenance_record` and `assemble_dedupe_decision_record`.
- Composition factory `build_provenance_dedupe_attribution_runtime` exposing zero-clock-invocation closures.
- Unit tests under the new provenance_dedupe_attribution test directories.

Out of scope:
- No execution-side surface, paper executor, shadow executor, live executor, scheduler, background loop, API, adapter, Redis client, FastAPI surface, model loader, or strategy subsystem.
- No new lineage IDs; `provenance_id` and `dedupe_decision_id` are deterministic derivations of existing `decision_id` context.
- No live-gate flip, Phase 2Z implementation, or SMC/liquidity feature shadow-mode work.

PHASE_2Y_SCOPE_READY
