# Phase 2U — Harness Pipeline Spec

## Composition-root build (once at harness level)

The harness builds exactly one composition root at harness level:

- `orchestrator_decision_evaluator = build_orchestrator_decision_evaluator(low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD, now_ms_clock=build_orchestrator_clock())`.

`build_orchestrator_decision_evaluator` is imported from `v2.backend.app.composition.orchestrator_decision.runtime`. The harness imports neither `build_paper_mode_runtime` nor `build_risk_decision_evaluator` nor `build_paper_execution_ledger_recorder` nor `build_replay_backtest_runner` nor `build_shadow_mode_readiness_runtime` and does NOT build or invoke them. The harness does NOT call `assemble_orchestrator_decision_record` directly; it always invokes the evaluator closure produced by `build_orchestrator_decision_evaluator`.

## Per-row evaluator invocation

For each typed `OrchestratorDecisionExplainabilityFixtureInput` row in the deterministic order returned by `build_orchestrator_decision_explainability_fixture_inputs()`, the harness:

1. Constructs a typed `TrainerPredictionRecord` from the fixture row's fields using the public dataclass constructor (no factory; no service builder; no mock; no patch).
2. Invokes `decision_record = orchestrator_decision_evaluator(prediction=trainer_prediction_record)`.

This produces a typed `OrchestratorDecisionRecord` per the existing evaluator invariants (`decision_id` deterministic per the evaluator closure's id-derivation logic, `live_blocked == True`, `decision_ts_ms` produced by the harness-level deterministic clock, `decision_action` / `decision_reason_code` decided per the threshold and the input prediction direction / freshness / worker health).

## Per-row envelope projection

For each produced typed `OrchestratorDecisionRecord`, the harness lifts a typed `OrchestratorDecisionExplainabilityEnvelope` row defined as a frozen `dataclass(slots=True)` under `v2/backend/tests/unit/decision_explainability_orchestrator_decision_projection/harness.py`:

```
@dataclass(frozen=True, slots=True)
class OrchestratorDecisionExplainabilityEnvelope:
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    decision_ts_ms: int
    decision_action: str
    decision_reason_code: str
    input_prediction_direction: str
    input_prediction_confidence_calibrated: float
    input_prediction_freshness_flag: str
    input_worker_health_status: str
    live_blocked: bool
    legacy_evidence_pointer: str
    source_scenario_slug: str
    step_index: int
```

`OrchestratorDecisionExplainabilityEnvelope` is a test-only value class. It is NOT a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, shadow trader process, or live-readiness gate. It is authored entirely inside the unit-test package under `v2/backend/tests/unit/decision_explainability_orchestrator_decision_projection/`.

The projection function is pure (no side effects, no I/O) and copies field-by-field from the typed `OrchestratorDecisionRecord` and the typed `OrchestratorDecisionExplainabilityFixtureInput` row. No field is computed, transformed, hashed, normalized, formatted, padded, truncated, or otherwise mutated; every envelope field is exactly equal to the corresponding source field on the typed `OrchestratorDecisionRecord` or the per-row test-only metadata.

## Harness result shape

The harness exposes a single public entry point `decision_explainability_orchestrator_decision_projection_harness(inputs)` returning a typed result class:

```
@dataclass(frozen=True, slots=True)
class OrchestratorDecisionProjectionHarnessResult:
    envelopes: tuple[OrchestratorDecisionExplainabilityEnvelope, ...]
    decision_records: tuple[OrchestratorDecisionRecord, ...]
```

The `envelopes` and `decision_records` tuples have identical length (12) and matching positional order; for each index `i`, `envelopes[i]` is the projection of `decision_records[i]` carrying the test-only metadata of `inputs[i]`.

## Forbidden in harness

The harness must NOT:

- build or invoke any composition root other than `build_orchestrator_decision_evaluator`;
- call `assemble_orchestrator_decision_record` directly (must invoke the evaluator closure);
- call `assemble_risk_decision_record`, `assemble_paper_mode_flag`, `assemble_paper_execution_ledger_entry`, `assemble_replay_backtest_step`, `assemble_replay_backtest_summary`, `assemble_shadow_mode_readiness_flag`, `build_paper_mode_runtime`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `build_replay_backtest_runner`, or `build_shadow_mode_readiness_runtime`;
- emit, persist, dump, log, print, write, send, publish, or otherwise produce any side effect outside of the returned typed result;
- introduce any wall-clock helper, file I/O helper, network client, environment-variable reader, or heavyweight numerics / ML import;
- introduce any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- introduce any `shadow_decision_id`, `execution_intent_id`, `risk_decision_id`, `paper_trade_id`, `replay_step_id`, `replay_run_id`, or `replay_summary_id` lineage row at the Phase 2U layer;
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- introduce any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed envelope rows or decision records;
- flip the live-readiness gate or substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- open, read, or write any `legacy_evidence_pointer` string as a filesystem path;
- mock, patch, or monkeypatch `build_orchestrator_decision_evaluator`, `assemble_orchestrator_decision_record`, or any other production composition root or service callable;
- emit a standalone harness framing-token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_HARNESS_PIPELINE_SPEC_READY
