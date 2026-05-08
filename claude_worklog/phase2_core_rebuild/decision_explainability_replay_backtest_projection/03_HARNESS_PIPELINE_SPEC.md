# Phase 2T — Harness Pipeline Spec

## Overview

The Phase 2T harness is a **pure-function projection pipeline** that drives the existing composition roots once at harness level and produces typed envelope rows. The harness module exports a single public callable `run_replay_backtest_projection_harness()` that returns a frozen typed `ReplayBacktestProjectionHarnessResult`.

## Pipeline

```
1. Build clock factories at harness top:
     paper_ledger_clock = build_paper_ledger_clock()
     replay_clock       = build_replay_clock()
2. Build composition roots once:
     paper_recorder = build_paper_execution_ledger_recorder(now_ms_clock=paper_ledger_clock)
     runner         = build_replay_backtest_runner(now_ms_clock=replay_clock)
3. For each scenario in (BTC winner long, ETH winner short, LAB loser short, SOL orchestrator held):
   a. Build deterministic typed `ReplayBacktestRun` (replay_run_id derived from scenario slug; replay_run_started_ts_ms = BASE_RISK_TS_MS + scenario_index * 60_000).
   b. Per-step (3 rows):
        i.   Build typed RiskDecisionRecord from fixture row.
        ii.  ledger_entry = paper_recorder.record(risk_decision=...)         # build_once invariant: paper_recorder is the SAME closure across all 12 calls
        iii. step          = runner.assemble_step(paper_ledger_entry=ledger_entry, replay_run=replay_run)
        iv.  step_envelope = project_step_to_envelope(step, scenario_slug, step_index, legacy_evidence_pointer)
   c. summary           = runner.assemble_summary(replay_run=replay_run, steps=tuple(steps_collected))
   d. summary_envelope  = project_summary_to_envelope(summary, scenario_slug, legacy_evidence_pointer)
4. Return ReplayBacktestProjectionHarnessResult(
     step_envelopes    = tuple(all_step_envelopes),    # 12 entries
     summary_envelopes = tuple(all_summary_envelopes), # 4 entries
   )
```

## Build-once invariants

- `build_paper_execution_ledger_recorder` is called **exactly once** per harness invocation.
- `build_replay_backtest_runner` is called **exactly once** per harness invocation.
- `build_paper_ledger_clock` factory is called **exactly once** per harness invocation.
- `build_replay_clock` factory is called **exactly once** per harness invocation.
- The recorder closure is invoked **exactly 12 times** (once per step row).
- The `runner.assemble_step` closure is invoked **exactly 12 times** (once per step row).
- The `runner.assemble_summary` closure is invoked **exactly 4 times** (once per scenario).

## Per-row projection invariants

For each step `step_i` produced by the runner:

- `step_envelope.replay_step_id == step_i.replay_step_id`
- `step_envelope.replay_run_id == step_i.replay_run_id`
- `step_envelope.paper_trade_id == step_i.paper_trade_id`
- `step_envelope.risk_decision_id == step_i.risk_decision_id`
- `step_envelope.decision_id == step_i.decision_id`
- `step_envelope.prediction_id == step_i.prediction_id`
- `step_envelope.feature_snapshot_id == step_i.feature_snapshot_id`
- `step_envelope.symbol == step_i.symbol`
- `step_envelope.step_ts_ms == step_i.step_ts_ms`
- `step_envelope.step_action == step_i.step_action`
- `step_envelope.step_reason_code == step_i.step_reason_code`
- `step_envelope.input_paper_action == step_i.input_paper_action`
- `step_envelope.input_paper_reason_code == step_i.input_paper_reason_code`
- `step_envelope.live_blocked is True`
- `step_envelope.source_scenario_slug == fixture_input.source_scenario_slug`
- `step_envelope.step_index == fixture_input.step_index`
- `step_envelope.legacy_evidence_pointer == fixture_input.legacy_evidence_pointer`

For each summary `summary_s` produced by the runner:

- `summary_envelope.replay_summary_id == summary_s.replay_summary_id`
- `summary_envelope.replay_run_id == summary_s.replay_run_id`
- `summary_envelope.summary_emitted_ts_ms == summary_s.summary_emitted_ts_ms`
- All 8 partition counts mirror exactly.
- `summary_envelope.live_blocked is True`
- `summary_envelope.source_scenario_slug == scenario_slug`
- `summary_envelope.legacy_evidence_pointer` ends with `__summary`.

## Forbidden

The harness module must not:
- Import `mock`, `unittest.mock`, `pytest`, `monkeypatch`, or `patch`.
- Call `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow` (the only time source is the deterministic clock closures).
- Open, read, or write any file (the `legacy_evidence_pointer` is a string literal, never a path).
- Import `os`, `sys` (other than `__future__`), `pathlib`, `socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, `scikit-learn`.
- Read environment variables.
- Persist any data anywhere.
- Mutate the `PaperExecutionLedgerEntry`, `ReplayBacktestRun`, `ReplayBacktestStep`, or `ReplayBacktestSummary` instances returned by the composition roots.
- Invoke `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `build_risk_decision_evaluator`, `assemble_risk_decision_record`, `build_orchestrator_decision_router`, `assemble_paper_execution_ledger_entry`, `assemble_replay_backtest_step`, or `assemble_replay_backtest_summary` directly (the harness must invoke the closures produced by `build_paper_execution_ledger_recorder` and `build_replay_backtest_runner`).
- Import any test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.

PHASE2T_HARNESS_PIPELINE_SPEC_READY
