# Phase 2N — Harness Pipeline Spec

## Public entry point

The harness module `v2/backend/tests/unit/paper_mode_evidence_collection_harness/harness.py` exposes a single pure function:

```
def replay_paper_mode_evidence_pack(
    *,
    evidence_pack: tuple[tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]], ...],
    requested_mode: str,
    paper_mode_clock: Callable[[], int],
    replay_clock: Callable[[], int],
) -> tuple[PaperModeFlag, tuple[PaperModeEvidenceTrio, ...]]
```

Where `PaperModeEvidenceTrio` is a frozen `dataclass(slots=True)` defined within `harness.py` carrying:

- `replay_run: ReplayBacktestRun`.
- `steps: tuple[ReplayBacktestStep, ...]`.
- `summary: ReplayBacktestSummary`.

`PaperModeEvidenceTrio` is a test-only value class. It is not a domain type and is not exported from `v2/backend/app/`.

## Pipeline order

The harness must execute the following ordered steps for a single invocation:

1. Build the paper-mode runtime: `paper_mode_runtime = build_paper_mode_runtime(now_ms_clock=paper_mode_clock)`.
2. Build the replay-backtest runtime: `replay_runner = build_replay_backtest_runner(now_ms_clock=replay_clock)`.
3. Emit the paper-mode flag: `paper_mode_flag = paper_mode_runtime.paper_mode_now(requested_mode=requested_mode)`. The harness asserts `paper_mode_flag.live_blocked is True` and that `paper_mode_flag.mode in {"paper", "live_blocked"}`.
4. For each `(replay_run, ledger_entries)` in `evidence_pack`:
   - For each `entry` in `ledger_entries`, call `replay_runner.assemble_step(paper_ledger_entry=entry, replay_run=replay_run)` and collect the resulting `ReplayBacktestStep` in declaration order.
   - Call `replay_runner.assemble_summary(replay_run=replay_run, steps=tuple(collected_steps))` to obtain the per-scenario `ReplayBacktestSummary`.
   - Construct the per-scenario `PaperModeEvidenceTrio(replay_run=replay_run, steps=tuple(collected_steps), summary=summary)`.
5. Return `(paper_mode_flag, tuple(per_scenario_trios))` in the same scenario order as the input `evidence_pack`.

## Determinism / purity invariants

- The harness must NOT call any wall-clock helper; both clocks are passed in as arguments.
- The harness must NOT mutate any input tuple, fixture, or domain record.
- The harness must NOT touch the filesystem.
- The harness must NOT import `os`, `sys`, `pathlib`, `socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, `scikit-learn`, or `time` / `datetime` modules.
- The harness must NOT introduce any new domain type, service, composition root, adapter, or executor beyond `PaperModeEvidenceTrio` (test-only value class).
- The harness must NOT introduce any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row.
- The harness must NOT introduce PnL, size, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- The harness must NOT use `mock`, `patch`, or `monkeypatch` against `build_paper_mode_runtime`, `build_replay_backtest_runner`, `assemble_replay_backtest_step`, `assemble_replay_backtest_summary`, `assemble_paper_mode_flag`, or any of their dependencies.
- The harness must NOT emit any standalone harness framing token marker (`BEGIN_FILE` or `END_FILE`) line in its file body.

## Error semantics

- If `build_paper_mode_runtime` raises `PaperModeRuntimeCompositionError`, the error propagates unchanged.
- If `build_replay_backtest_runner` raises `ReplayBacktestRunnerCompositionError`, the error propagates unchanged.
- If `assemble_paper_mode_flag` raises `PaperModeDomainError`, the error propagates unchanged.
- If `assemble_replay_backtest_step` raises `ReplayBacktestRunnerDomainError`, the error propagates unchanged.
- If `assemble_replay_backtest_summary` raises `ReplayBacktestRunnerDomainError`, the error propagates unchanged.
- The harness must NOT catch, suppress, log, or relabel any composition-root or domain error. The harness is purely a fan-out / fan-in pipeline.

## Output projection invariants (per scenario)

For each scenario in the returned `tuple[PaperModeEvidenceTrio, ...]`:

- `len(trio.steps) == len(input_ledger_entries)` for that scenario.
- For every step `step[i]` and corresponding ledger entry `entry[i]`:
  - `step.replay_run_id == trio.replay_run.replay_run_id`.
  - `step.paper_trade_id == entry.paper_trade_id`.
  - `step.risk_decision_id == entry.risk_decision_id`.
  - `step.decision_id == entry.decision_id`.
  - `step.prediction_id == entry.prediction_id`.
  - `step.feature_snapshot_id == entry.feature_snapshot_id`.
  - `step.symbol == entry.symbol`.
  - `step.input_paper_action == entry.ledger_action`.
  - `step.input_paper_reason_code == entry.ledger_reason_code`.
  - `step.live_blocked is True`.
- `trio.summary.replay_run_id == trio.replay_run.replay_run_id`.
- `trio.summary` aggregates the produced step tuple per `v2/backend/app/services/replay_backtest_runner/`'s existing `assemble_replay_backtest_summary` contract.

PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_PIPELINE_SPEC_READY
