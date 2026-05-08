# Phase 2S — Harness Pipeline Spec

## Composition-root build (once at harness level)

The harness builds exactly one composition root at harness level:

- `paper_execution_ledger_recorder = build_paper_execution_ledger_recorder(now_ms_clock=build_paper_ledger_clock())`.

`build_paper_execution_ledger_recorder` is imported from `v2.backend.app.composition.paper_execution_ledger.runtime`. The harness imports neither `PaperModeRuntime` nor `RiskDecisionEvaluator` nor `OrchestratorDecisionRouter` nor `ReplayBacktestRunner` and does NOT build or invoke them. The harness does NOT call `assemble_paper_execution_ledger_entry` directly; it always invokes the recorder closure produced by `build_paper_execution_ledger_recorder`. The harness does NOT call `assemble_risk_decision_record` or `assemble_paper_mode_flag` (the typed `RiskDecisionRecord` rows are built directly by the fixture module via the typed surface constructor; the harness consumes them as inputs).

## Per-row recorder invocation

For each typed `PaperLedgerExplainabilityFixtureInput` row in the deterministic order returned by `build_paper_ledger_explainability_fixture_inputs()`, the harness invokes:

- `paper_execution_ledger_entry = paper_execution_ledger_recorder(decision=input_row.risk_decision_record)`.

This produces a typed `PaperExecutionLedgerEntry` per the existing recorder invariants (`paper_trade_id == "pt_" + risk_decision_id`, `live_blocked == True`, ledger-side action / reason mirrored from the input `risk_reason_code`, `ledger_entry_ts_ms` produced by the harness-level deterministic clock).

## Per-row envelope projection

For each produced typed `PaperExecutionLedgerEntry`, the harness lifts a typed `PaperLedgerExplainabilityEnvelope` row defined as a frozen `dataclass(slots=True)` under `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/harness.py`:

```
@dataclass(frozen=True, slots=True)
class PaperLedgerExplainabilityEnvelope:
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    ledger_entry_ts_ms: int
    ledger_action: str
    ledger_reason_code: str
    input_risk_action: str
    input_risk_reason_code: str
    live_blocked: bool
    legacy_evidence_pointer: str
    source_scenario_slug: str
    step_index: int
```

`PaperLedgerExplainabilityEnvelope` is a test-only value class. It is NOT a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, or live-readiness gate. It is authored entirely inside the unit-test package under `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/`.

The projection function is pure (no side effects, no I/O) and copies field-by-field from the typed `PaperExecutionLedgerEntry` and the typed `PaperLedgerExplainabilityFixtureInput` row. No field is computed, transformed, hashed, normalized, formatted, padded, truncated, or otherwise mutated; every envelope field is exactly equal to the corresponding source field on the typed `PaperExecutionLedgerEntry` or the per-row test-only metadata.

## Harness result shape

The harness exposes a single public entry point `decision_explainability_paper_ledger_projection_harness(inputs)` returning a typed result class:

```
@dataclass(frozen=True, slots=True)
class PaperLedgerExplainabilityHarnessResult:
    envelopes: tuple[PaperLedgerExplainabilityEnvelope, ...]
    ledger_entries: tuple[PaperExecutionLedgerEntry, ...]
```

The `envelopes` and `ledger_entries` tuples have identical length (12) and matching positional order; for each index `i`, `envelopes[i]` is the projection of `ledger_entries[i]` carrying the test-only metadata of `inputs[i]`.

## Forbidden in harness

The harness must NOT:

- build or invoke any composition root other than `build_paper_execution_ledger_recorder`;
- call `assemble_paper_execution_ledger_entry` directly (must invoke the recorder closure);
- call `assemble_risk_decision_record`, `assemble_paper_mode_flag`, `build_risk_decision_evaluator`, `build_paper_mode_runtime`, `build_orchestrator_decision_router`, or `build_replay_backtest_runner`;
- emit, persist, dump, log, print, write, send, publish, or otherwise produce any side effect outside of the returned typed result;
- introduce any wall-clock helper, file I/O helper, network client, environment-variable reader, or heavyweight numerics / ML import;
- introduce any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- introduce any `shadow_decision_id` or `execution_intent_id` lineage row;
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- introduce any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed envelope rows or ledger entries;
- flip the live-readiness gate or substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- open, read, or write any `legacy_evidence_pointer` string as a filesystem path;
- mock, patch, or monkeypatch `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_mode_runtime`, or `assemble_paper_mode_flag`;
- emit a standalone harness framing-token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_HARNESS_PIPELINE_SPEC_READY
