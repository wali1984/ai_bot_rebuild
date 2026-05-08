# Phase 2R — Harness Pipeline Spec

## Harness module layout

The Phase 2R harness is authored as a pure-function module under `v2/backend/tests/unit/decision_explainability_data_contract/harness.py`. The module exports exactly two entry points:

- `decision_explainability_data_contract_harness(inputs: tuple[DecisionExplainabilityFixtureInput, ...]) -> DecisionExplainabilityHarnessResult`.
- `DecisionExplainabilityHarnessResult` (frozen `dataclass(slots=True)` with fields `paper_mode_flag: PaperModeFlag`, `envelopes: tuple[DecisionExplainabilityEnvelope, ...]`).

The harness module additionally exports the test-only typed value class `DecisionExplainabilityEnvelope` (frozen `dataclass(slots=True)`) with the field set defined below.

The harness module imports:

- `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` (read-only typed surface use; no instantiation).
- `PaperModeFlag` from `v2.backend.app.domain.paper_mode.flag` (read-only typed surface).
- `build_paper_mode_runtime` from `v2.backend.app.composition.paper_mode.runtime`.
- `assemble_paper_mode_flag` is reached through `build_paper_mode_runtime`'s return surface; it is NOT imported directly.

No other V2 domain / service / composition root symbol is imported by the harness module. No FastAPI surface, scheduler, background-loop adapter, persistence adapter, or Redis adapter is imported, instantiated, or called.

## DecisionExplainabilityEnvelope field set

```
@dataclass(frozen=True, slots=True)
class DecisionExplainabilityEnvelope:
    feature_snapshot_id: str
    prediction_id: str
    decision_id: str
    risk_decision_id: str
    symbol: str
    input_decision_action: str
    input_decision_reason_code: str
    risk_action: str
    risk_reason_code: str
    risk_live_blocked: bool
    risk_decision_ts_ms: int
    paper_mode_live_blocked: bool
    paper_mode_mode: str
    legacy_evidence_pointer: str
    source_scenario_slug: str
    step_index: int
```

All sixteen fields are derived strictly from the source `RiskDecisionRecord`, the harness-level `PaperModeFlag`, and the deterministic test-only metadata carried on the `DecisionExplainabilityFixtureInput`. No field is fabricated, randomly generated, or sourced from a wall-clock helper, environment variable, file read, or network call. The envelope class is test-only; it is NOT a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, or live-readiness gate.

## Pipeline stages

The harness pipeline executes exactly the following ordered stages (no parallelism, no concurrency, no scheduling):

### Stage 1 — Build harness-level paper-mode flag (single invocation)

- Invoke `build_paper_mode_runtime(now_ms_clock=paper_mode_clock, mode="paper")` once at the harness level.
- The returned `PaperModeRuntime` instance is invoked once via its existing harness-level entry point to produce a single typed `PaperModeFlag` with `live_blocked is True` and `mode in {"paper", "live_blocked"}`.
- The single `PaperModeFlag` is carried through the entire pipeline as a harness-level attribute. Phase 2R does NOT call `PaperModeRuntime` more than once.

### Stage 2 — Per-input typed projection (12 typed input rows)

For each `input_row` in `inputs`:

- Read the source `RiskDecisionRecord` carried by `input_row.risk_decision_record`.
- Construct exactly one typed `DecisionExplainabilityEnvelope` row populating each field as follows:
  - `feature_snapshot_id` ← `input_row.risk_decision_record.feature_snapshot_id`.
  - `prediction_id` ← `input_row.risk_decision_record.prediction_id`.
  - `decision_id` ← `input_row.risk_decision_record.decision_id`.
  - `risk_decision_id` ← `input_row.risk_decision_record.risk_decision_id`.
  - `symbol` ← `input_row.risk_decision_record.symbol`.
  - `input_decision_action` ← `input_row.risk_decision_record.input_decision_action`.
  - `input_decision_reason_code` ← `input_row.risk_decision_record.input_decision_reason_code`.
  - `risk_action` ← `input_row.risk_decision_record.risk_action`.
  - `risk_reason_code` ← `input_row.risk_decision_record.risk_reason_code`.
  - `risk_live_blocked` ← `input_row.risk_decision_record.live_blocked`.
  - `risk_decision_ts_ms` ← `input_row.risk_decision_record.risk_decision_ts_ms`.
  - `paper_mode_live_blocked` ← `paper_mode_flag.live_blocked`.
  - `paper_mode_mode` ← `paper_mode_flag.mode`.
  - `legacy_evidence_pointer` ← `input_row.legacy_evidence_pointer` (string copy; no path resolution; no file open; no read).
  - `source_scenario_slug` ← `input_row.scenario_slug`.
  - `step_index` ← `input_row.step_index`.

The harness does NOT perform any other read or write per input row; no logging; no exception suppression; no warning emission.

### Stage 3 — Result assembly

Assemble one typed `DecisionExplainabilityHarnessResult` with:

- `paper_mode_flag`: the single `PaperModeFlag` produced in Stage 1.
- `envelopes`: ordered tuple of twelve `DecisionExplainabilityEnvelope` rows in input-pack order.

Return the result. The harness does NOT persist the result. The harness does NOT serialize the result to disk, JSON, Parquet, SQL, SQLite, Redis, or any other store.

## Determinism guarantees

- Iteration order is deterministic: scenarios are ordered by the table in `02_TYPED_INPUT_FIXTURE_SPEC.md`; steps within a scenario are ordered by 1-based ordinal.
- All projection operations are deterministic field-copy operations on Python primitives (`str`, `int`, `bool`).
- No random source is consulted. No `random` import is permitted. No `secrets` import is permitted.
- All clocks are deterministic monotonic counters; the harness does NOT consult wall-clock time at any stage.

## Forbidden in harness

The harness module must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics / ML import;
- any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row beyond the fields carried by `RiskDecisionRecord`;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed envelope rows;
- any flip of the live-readiness gate or any substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- any modification of placeholder file `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`;
- any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`;
- any open / read / write of `legacy_evidence_pointer` strings as filesystem paths;
- any `mock`, `patch`, or `monkeypatch` of `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `build_orchestrator_decision_router`, or `build_replay_backtest_runner`;
- any invocation of `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `build_risk_decision_evaluator`, `build_orchestrator_decision_router`, or `build_replay_backtest_runner` from the harness module;
- any import of a test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`;
- any standalone harness framing token marker (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

## Out-of-scope explainability fields

The following REQ_0009 § "Required UI visibility" fields are explicitly OUT OF SCOPE at Phase 2R and must NOT be added to `DecisionExplainabilityEnvelope`:

- `top_positive_feature_contributors` / `top_negative_feature_contributors` (require a feature contributor projection subsystem that does not exist at consolidation HEAD).
- `feature_freshness_flags` / `stale_missing_unused_feature_flags` (require a feature-freshness projection subsystem that does not exist at consolidation HEAD).
- `confidence` / `previous_confidence` / `confidence_delta` / `confidence_calibration` (require a confidence-attribution subsystem that does not exist at consolidation HEAD).
- `model_version` / `checkpoint_version` (require a model / checkpoint version projection subsystem that does not exist at consolidation HEAD).
- `regime_context` (requires a regime-detection subsystem that does not exist at consolidation HEAD).
- `position_sizing_reason` / `quantity` / `price` / `fees` / `slippage` / `funding_rate` / `open_interest` / `liquidation_cluster` / `orderbook_depth` / `hedge_state` / `residual_exposure` / `squeeze_risk` (require execution-side / market-data subsystems that are explicitly out of scope per the Phase 2H ledger and Phase 2I replay milestones).
- `paper_trade_id` (only the existing field carried by `PaperExecutionLedgerEntry` is allowed; Phase 2R does not invoke the ledger recorder, so it does not surface `paper_trade_id`).
- `shadow_decision_id` / `execution_intent_id` (do not exist at consolidation HEAD).
- `risk_check_list` / `blocked_trade_reason` / `paper_shadow_legacy_comparison` / `audit_timeline` (require subsystems that do not exist at consolidation HEAD; downstream Lane B milestones).

These fields become eligible only after their underlying subsystems are built in separately scoped, downstream Lane A or Lane B milestones.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_HARNESS_PIPELINE_SPEC_READY
END_FILE: claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/03_HARNESS_PIPELINE_SPEC.md
