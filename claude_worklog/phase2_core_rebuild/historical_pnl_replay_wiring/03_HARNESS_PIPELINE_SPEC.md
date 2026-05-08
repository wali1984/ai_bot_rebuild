# Phase 2P — Harness Pipeline Spec

## Public entry point

The harness module `v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py` exposes a single pure function:

```
def replay_historical_pnl_evidence_pack(
    *,
    evidence_pack: tuple[
        tuple[HistoricalPnLEvidenceRun, tuple[HistoricalPnLReplayInput, ...]],
        ...,
    ],
    requested_mode: str,
    paper_mode_clock: Callable[[], int],
    ledger_clock: Callable[[], int],
) -> tuple[PaperModeFlag, tuple[HistoricalPnLReplayEvidenceTrio, ...]]
```

Where `HistoricalPnLReplayComparisonRecord` and `HistoricalPnLReplayEvidenceTrio` are test-only frozen `dataclass(slots=True)` value classes defined entirely within the unit-test package:

```
@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayComparisonRecord:
    legacy_realized_trade_evidence_pointer: str
    v2_paper_execution_ledger_entry: PaperExecutionLedgerEntry

@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayEvidenceTrio:
    scenario_slug: str
    evidence_run: HistoricalPnLEvidenceRun
    comparisons: tuple[HistoricalPnLReplayComparisonRecord, ...]
```

Neither `HistoricalPnLReplayComparisonRecord` nor `HistoricalPnLReplayEvidenceTrio` is a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, or live-readiness gate. They are test-only typed value classes authored entirely inside the unit-test package.

`PaperModeFlag` is the existing typed surface from `v2/backend/app/domain/paper_mode/__init__.py` (re-exported from `v2/backend/app/domain/paper_mode/flag.py`). `PaperExecutionLedgerEntry` is the existing typed surface from `v2/backend/app/domain/paper_execution_ledger/__init__.py` (re-exported from `v2/backend/app/domain/paper_execution_ledger/record.py`).

## Pipeline behavior

The harness function:

1. Calls `build_paper_mode_runtime(now_ms_clock=paper_mode_clock)` and asserts the returned `PaperModeRuntime` is bound.
2. Calls `runtime.paper_mode_now(requested_mode=requested_mode)` and captures the typed `PaperModeFlag`.
3. Asserts `paper_mode_flag.live_blocked is True` and `paper_mode_flag.mode in {"paper", "live_blocked"}`.
4. Calls `build_paper_execution_ledger_recorder(now_ms_clock=ledger_clock)` and asserts the returned recorder is callable.
5. For each `(evidence_run, inputs)` in `evidence_pack`:
   - For each `HistoricalPnLReplayInput` in `inputs`, calls `recorder(decision=input.risk_decision_record)` to obtain a typed `PaperExecutionLedgerEntry` and constructs a typed `HistoricalPnLReplayComparisonRecord(legacy_realized_trade_evidence_pointer=input.legacy_realized_trade_evidence_pointer, v2_paper_execution_ledger_entry=...)`.
   - Constructs a typed `HistoricalPnLReplayEvidenceTrio(scenario_slug=evidence_run.scenario_slug, evidence_run=evidence_run, comparisons=tuple(per_step_records))` and appends to the trio tuple.
6. Returns `(paper_mode_flag, tuple(per_scenario_trios))` in the same scenario order as the input `evidence_pack`.

## Determinism / purity invariants

- The harness must NOT call any wall-clock helper; both clocks are passed in as arguments.
- The harness must NOT mutate any input tuple, fixture, or domain record.
- The harness must NOT touch the filesystem.
- The harness must NOT import `os`, `sys`, `pathlib`, `socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, `scikit-learn`, `time`, or `datetime` modules.
- The harness must NOT introduce any new domain type, service, composition root, adapter, or executor beyond the test-only value classes `HistoricalPnLReplayComparisonRecord` and `HistoricalPnLReplayEvidenceTrio`.
- The harness must NOT introduce any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row.
- The harness must NOT introduce PnL, size, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- The harness must NOT use `mock`, `patch`, or `monkeypatch` against `build_paper_mode_runtime`, `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, or any of their dependencies.
- The harness must NOT open, read, or write the `legacy_realized_trade_evidence_pointer` string as a filesystem path; the pointer is a deterministic string identifier only.
- The harness must NOT call any Binance read-only account-history endpoint or any other network client.
- The harness must NOT emit any standalone harness framing token marker (`BEGIN_FILE` or `END_FILE`) line in its file body.

## Error semantics

- If `build_paper_mode_runtime` raises `PaperModeRuntimeCompositionError`, the error propagates unchanged.
- If `build_paper_execution_ledger_recorder` raises `PaperExecutionLedgerCompositionError`, the error propagates unchanged.
- If `assemble_paper_mode_flag` raises `PaperModeDomainError`, the error propagates unchanged.
- If `assemble_paper_execution_ledger_entry` raises `PaperExecutionLedgerDomainError`, the error propagates unchanged.
- The harness must NOT catch, suppress, log, or relabel any composition-root or domain error. The harness is purely a fan-out / fan-in pipeline.

## Output projection invariants (per scenario)

For each scenario in the returned `tuple[HistoricalPnLReplayEvidenceTrio, ...]`:

- `len(trio.comparisons) == len(input_inputs)` for that scenario.
- For every comparison record `comparison[i]` and corresponding input `input[i]`:
  - `comparison.legacy_realized_trade_evidence_pointer == input.legacy_realized_trade_evidence_pointer`.
  - `comparison.v2_paper_execution_ledger_entry.risk_decision_id == input.risk_decision_record.risk_decision_id`.
  - `comparison.v2_paper_execution_ledger_entry.decision_id == input.risk_decision_record.decision_id`.
  - `comparison.v2_paper_execution_ledger_entry.prediction_id == input.risk_decision_record.prediction_id`.
  - `comparison.v2_paper_execution_ledger_entry.feature_snapshot_id == input.risk_decision_record.feature_snapshot_id`.
  - `comparison.v2_paper_execution_ledger_entry.symbol == input.risk_decision_record.symbol`.
  - `comparison.v2_paper_execution_ledger_entry.live_blocked is True`.
  - `comparison.v2_paper_execution_ledger_entry.input_risk_action == input.risk_decision_record.action`.
  - `comparison.v2_paper_execution_ledger_entry.input_risk_reason_code == input.risk_decision_record.reason_code`.
- `trio.scenario_slug == trio.evidence_run.scenario_slug`.
- `trio.evidence_run.symbol` matches the per-input `risk_decision_record.symbol` for every input in the scenario.

## Harness-level invariants

- `paper_mode_flag.live_blocked is True`.
- `paper_mode_flag.mode in {"paper", "live_blocked"}`.
- `len(returned_trios) == len(evidence_pack)`.
- `returned_trios` ordering matches `evidence_pack` ordering.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_PIPELINE_SPEC_READY
