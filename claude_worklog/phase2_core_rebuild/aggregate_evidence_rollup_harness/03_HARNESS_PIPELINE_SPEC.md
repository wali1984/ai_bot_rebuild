# Phase 2Q — Harness Pipeline Spec

## Harness module layout

The Phase 2Q harness is authored as a pure-function module under `v2/backend/tests/unit/aggregate_evidence_rollup_harness/harness.py`. The module exports exactly two entry points:

- `aggregate_evidence_rollup_harness(source_packs: tuple[AggregateRollupSourcePack, ...]) -> AggregateRollupHarnessResult`.
- `AggregateRollupHarnessResult` (frozen `dataclass(slots=True)` with fields `paper_mode_flag: PaperModeFlag`, `per_source_records: tuple[AggregateRollupPerSourceRecord, ...]`, `summary: AggregateRollupSummary`).

The harness module imports:

- `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` (read-only typed surface use; no instantiation).
- `PaperModeFlag` from `v2.backend.app.domain.paper_mode.flag` (read-only typed surface).
- `build_paper_mode_runtime` from `v2.backend.app.composition.paper_mode.runtime`.
- `assemble_paper_mode_flag` is reached through `build_paper_mode_runtime`'s return surface; it is NOT imported directly.

No other V2 domain / service / composition root symbol is imported by the harness module. No FastAPI surface, scheduler, background-loop adapter, persistence adapter, or Redis adapter is imported, instantiated, or called.

## Pipeline stages

The harness pipeline executes exactly the following ordered stages (no parallelism, no concurrency, no scheduling):

### Stage 1 — Build harness-level paper-mode flag (single invocation)

- Invoke `build_paper_mode_runtime(now_ms_clock=paper_mode_clock, mode="paper")` once at the harness level.
- The returned `PaperModeRuntime` instance is invoked once via its `assemble()` (or equivalent harness-level entry-point) to produce a single typed `PaperModeFlag` with `live_blocked is True` and `mode in {"paper", "live_blocked"}`.
- The single `PaperModeFlag` is carried through the entire pipeline as a harness-level attribute. Phase 2Q does NOT call `PaperModeRuntime` more than once.

### Stage 2 — Per-source iteration (3 source packs)

For each `source_pack` in `source_packs` (`paper_mode`, `shadow_mode`, `historical_pnl`):

#### Stage 2a — Per-input typed counting (12 typed input rows)

For each `input_row` in `source_pack.inputs`:

- Increment a per-source counter for `input_row.risk_reason`. Recognized counters: `allow_proceed_long_count`, `allow_proceed_short_count`, `deny_orchestrator_held_count`. Unrecognized reason values are forbidden by the fixture spec; the harness does not implement an "other" bucket.
- Increment a per-source per-symbol counter keyed by `input_row.symbol`.
- If `input_row.has_lab_pointer is True`, increment the per-source `lab_pointer_presence_count`.
- Verify (assertion in tests; no logging, no exception suppression) that `input_row.risk_decision_record` carries lineage fields `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id` matching the convention in `02_TYPED_INPUT_FIXTURE_SPEC.md`.

#### Stage 2b — Per-source roll-up record assembly

Assemble one typed `AggregateRollupPerSourceRecord` with fields:

- `source_id`: from `source_pack.source_id`.
- `total_inputs`: integer count of `source_pack.inputs` (must equal 12 per scenario × 4 scenarios; equals 12).
- `allow_proceed_long_count`: per-source counter (must equal 3).
- `allow_proceed_short_count`: per-source counter (must equal 6 = ETH 3 + LAB 3).
- `deny_orchestrator_held_count`: per-source counter (must equal 3).
- `per_symbol_counts`: tuple of `AggregateRollupPerSymbolCount` rows ordered by symbol ASCII ascending: `BTCUSDT`, `ETHUSDT`, `LABUSDT`, `SOLUSDT`. Each count must equal 3.
- `lab_pointer_presence_count`: per-source counter (must equal 3 = LAB scenario step count).

### Stage 3 — Cross-source summary assembly

Assemble one typed `AggregateRollupSummary` with fields:

- `paper_mode_flag`: the single `PaperModeFlag` produced in Stage 1.
- `per_source_records`: ordered tuple of three `AggregateRollupPerSourceRecord` rows in source-pack order.
- `total_inputs`: 36 (sum of per-source `total_inputs`).
- `total_allow_proceed_long_count`: 9 (3 × 3).
- `total_allow_proceed_short_count`: 18 (6 × 3).
- `total_deny_orchestrator_held_count`: 9 (3 × 3).
- `total_lab_pointer_presence_count`: 9 (3 × 3).
- `per_symbol_total_counts`: tuple of `AggregateRollupPerSymbolCount` rows (one per symbol, ASCII ascending) with each count equal to 9 (3 × 3).

### Stage 4 — Result assembly

Return `AggregateRollupHarnessResult(paper_mode_flag=..., per_source_records=..., summary=...)`. The harness does NOT persist the result. The harness does NOT serialize the result to disk, JSON, Parquet, SQL, SQLite, Redis, or any other store.

## Determinism guarantees

- Iteration order is deterministic: source packs are ordered by `(paper_mode, shadow_mode, historical_pnl)`; scenarios within a source pack are ordered by the table in `02_TYPED_INPUT_FIXTURE_SPEC.md`; steps within a scenario are ordered by 1-based ordinal.
- All counter operations are deterministic integer arithmetic on Python `int`.
- No random source is consulted. No `random` import is permitted. No `secrets` import is permitted.
- All clocks are deterministic monotonic counters; the harness does NOT consult wall-clock time at any stage.

## Forbidden in harness

The harness module must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics / ML import;
- any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row beyond the existing `PaperExecutionLedgerEntry` composition-root carried field;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed roll-up records;
- any flip of the live-readiness gate or any substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- any modification of placeholder file `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`;
- any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`;
- any open / read / write of `legacy_evidence_pointer` strings as filesystem paths;
- any `mock`, `patch`, or `monkeypatch` of `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `assemble_risk_decision_record`, or `build_risk_decision_evaluator`;
- any import of a test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, or `v2/backend/tests/unit/historical_pnl_replay_wiring/`;
- any standalone harness framing token marker (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_HARNESS_PIPELINE_SPEC_READY
END_FILE: claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/03_HARNESS_PIPELINE_SPEC.md
