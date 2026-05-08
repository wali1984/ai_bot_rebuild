# Phase 2Q — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by source id, scenario slug, and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. One `paper_mode_clock` is required at the harness level for the single `PaperModeRuntime` invocation. No other composition root is invoked by the Phase 2Q harness.
- All `live_blocked` flags are `True`.
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.
- No fixture invocation calls any Binance read-only account-history endpoint.
- No fixture imports any test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, or `v2/backend/tests/unit/historical_pnl_replay_wiring/`. The Phase 2Q fixture pack is self-contained and re-states the deterministic typed-row structure produced by those prior milestones.

## Source-pack scenarios

The Phase 2Q evidence pack defines exactly three deterministic source packs, each defining four deterministic scenarios. Each scenario is a triplet of typed `AggregateRollupSourceInput` rows. The fixture module exposes one factory function per source pack plus an aggregator `build_aggregate_rollup_source_packs()` returning the ordered tuple of all three source packs.

| Source id | Mirrors prior milestone | Scenarios | Steps per scenario | Total typed input rows |
| --- | --- | --- | --- | --- |
| `paper_mode` | Phase 2N paper-mode evidence-collection harness | 4 | 3 | 12 |
| `shadow_mode` | Phase 2O shadow-mode evidence-collection harness | 4 | 3 | 12 |
| `historical_pnl` | Phase 2P historical-PnL replay wiring | 4 | 3 | 12 |

Total source packs: 3. Total scenarios: 12. Total typed `AggregateRollupSourceInput` rows: 36.

Per-source scenario set (identical scenario slug / symbol / risk-action / risk-reason mapping for each source):

| Scenario slug suffix | Symbol | Step count | `risk_action` | `risk_reason` | `has_lab_pointer` |
| --- | --- | --- | --- | --- | --- |
| `pack_btc_winner_long` | `BTCUSDT` | 3 | `allow` | `allow_proceed_long` | `False` |
| `pack_eth_winner_short` | `ETHUSDT` | 3 | `allow` | `allow_proceed_short` | `False` |
| `pack_lab_loser_short` | `LABUSDT` | 3 | `allow` | `allow_proceed_short` | `True` |
| `pack_sol_orchestrator_held` | `SOLUSDT` | 3 | `deny` | `deny_orchestrator_held` | `False` |

Per-source per-scenario step count: 3. Per-source total scenarios: 4. Per-source total typed input rows: 12.

The full scenario slug is namespaced by source id: `aggregate_rollup_<source_id>_<scenario slug suffix>` (e.g., `aggregate_rollup_paper_mode_pack_btc_winner_long`).

The `pack_lab_loser_short` scenario carries a deterministic `legacy_evidence_pointer` literal pointing into `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (LAB hedge-unwind / squeeze legacy-failure evidence). Phase 2Q does NOT model PnL, hedge state, residual exposure, or squeeze risk; the LAB scenario contributes only to the `lab_pointer_presence_count` typed counter.

## Identifier conventions

For source id `X`, scenario slug suffix `Y`, and 1-based step ordinal `N` (e.g., `001`):

- `risk_decision_id` = `risk_decision_X_Y_N`.
- `decision_id` = `decision_X_Y_N`.
- `prediction_id` = `prediction_X_Y_N`.
- `feature_snapshot_id` = `feature_snapshot_X_Y_N`.

All identifiers fit the existing 128-character constraint with no whitespace per the typed surface validations in `v2/backend/app/domain/risk_gateway/record.py`.

## Legacy evidence pointer convention

For source id `X`, scenario slug suffix `Y`, and 1-based step ordinal `N`:

- `legacy_evidence_pointer` = `legacy_evidence__X__Y__step_N` for `pack_btc_winner_long`, `pack_eth_winner_short`, and `pack_sol_orchestrator_held`.
- `legacy_evidence_pointer` = `legacy_evidence__X__lab_hedge_unwind_squeeze__step_N` for `pack_lab_loser_short`.

The pointer is a deterministic string identifier; the harness does NOT resolve it as a filesystem path, does NOT open it as a file, and does NOT read its target. The `forbidden_actions` list of the supervisor task explicitly forbids opening, reading, or writing the pointer string as a filesystem path.

## Typed input record shape

The fixture module defines test-only frozen `dataclass(slots=True)` value classes under `v2/backend/tests/unit/aggregate_evidence_rollup_harness/fixtures.py`:

```
@dataclass(frozen=True, slots=True)
class AggregateRollupSourceInput:
    source_id: str
    scenario_slug: str
    symbol: str
    risk_action: str
    risk_reason: str
    legacy_evidence_pointer: str
    has_lab_pointer: bool
    risk_decision_record: RiskDecisionRecord

@dataclass(frozen=True, slots=True)
class AggregateRollupSourcePack:
    source_id: str
    inputs: tuple[AggregateRollupSourceInput, ...]
```

`AggregateRollupSourceInput` and `AggregateRollupSourcePack` are test-only value classes. They are NOT V2 `app/domain` types, services, adapters, persistence models, API surfaces, schedulers, paper-mode trader processes, or live-readiness gates. They are authored entirely inside the unit-test package under `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.

`RiskDecisionRecord` is the existing typed surface from `v2/backend/app/domain/risk_gateway/record.py`. The fixture module imports `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` only; no other domain symbol is imported by the fixture module.

The fixture module constructs each `RiskDecisionRecord` via the existing `assemble_risk_decision_record(decision=..., now_ms_clock=...)` service or via the existing `RiskDecisionRecord` direct constructor with deterministic inputs. The fixture module does NOT mock, patch, or monkeypatch `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `build_paper_mode_runtime`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, or any of their dependencies.

## Run timestamp invariants

Per typed input row, the `risk_decision_record.decision_ts_ms` field is computed as:

- `risk_decision_record.decision_ts_ms = BASE_TS_MS + source_index * 600_000 + scenario_index * 60_000 + step_ordinal * 100`.

Where `source_index` is the zero-based ordinal of the source pack in the harness pack tuple (0 for `paper_mode`, 1 for `shadow_mode`, 2 for `historical_pnl`), `scenario_index` is the zero-based ordinal of the scenario in the source pack (0 for `pack_btc_winner_long`, 1 for `pack_eth_winner_short`, 2 for `pack_lab_loser_short`, 3 for `pack_sol_orchestrator_held`), and `step_ordinal` is the 1-based ordinal of the step. All timestamps are `int`. No `bool` is used for any timestamp field.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics import;
- any new domain type, service, composition root, adapter, or test-harness adapter beyond the test-only value classes `AggregateRollupSourceInput`, `AggregateRollupSourcePack`, `AggregateRollupPerSymbolCount`, `AggregateRollupPerSourceRecord`, and `AggregateRollupSummary`;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk field;
- any `live_blocked = False` value;
- any Binance read-only account-history client invocation;
- any standalone harness framing token marker (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body;
- any import of a test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, or `v2/backend/tests/unit/historical_pnl_replay_wiring/`;
- any read or write of `claude_worklog/historical_pnl_audit/` as a runtime input.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_TYPED_INPUT_FIXTURE_SPEC_READY
END_FILE: claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/02_TYPED_INPUT_FIXTURE_SPEC.md
