# Phase 2Q — Test Plan

## Test module

A single pytest module is authored at `v2/backend/tests/unit/aggregate_evidence_rollup_harness/test_aggregate_evidence_rollup_harness.py`. The module imports the fixture pack and the harness from the sibling `fixtures` and `harness` modules. The module does NOT import any test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, or `v2/backend/tests/unit/historical_pnl_replay_wiring/`.

## Required pytest cases (15 total)

1. `test_harness_paper_mode_flag_live_blocked_invariant`. The single `PaperModeFlag` returned at the harness level has `live_blocked is True` and `mode in {"paper", "live_blocked"}`.

2. `test_source_pack_count_equals_three`. The fixture pack returns exactly three `AggregateRollupSourcePack` rows in order `(paper_mode, shadow_mode, historical_pnl)`.

3. `test_per_source_inputs_count_equals_twelve`. Each `AggregateRollupSourcePack.inputs` contains exactly 12 typed `AggregateRollupSourceInput` rows.

4. `test_per_source_record_count_equals_three`. The harness result contains exactly three `AggregateRollupPerSourceRecord` rows in source-pack order.

5. `test_per_source_total_inputs_equals_twelve`. Each `AggregateRollupPerSourceRecord.total_inputs` equals 12.

6. `test_per_source_action_counts`. For each per-source record:
   - `allow_proceed_long_count == 3`.
   - `allow_proceed_short_count == 6`.
   - `deny_orchestrator_held_count == 3`.

7. `test_per_source_per_symbol_counts`. Each per-source record's `per_symbol_counts` has four rows (`BTCUSDT`, `ETHUSDT`, `LABUSDT`, `SOLUSDT` ASCII ascending), each with `count == 3`.

8. `test_per_source_lab_pointer_presence_count_equals_three`. Each per-source record's `lab_pointer_presence_count` equals 3.

9. `test_summary_total_inputs_equals_thirty_six`. The harness result's `summary.total_inputs` equals 36.

10. `test_summary_action_counts_equal_sum_of_per_source_counts`. The harness result's `summary.total_allow_proceed_long_count == 9`, `summary.total_allow_proceed_short_count == 18`, and `summary.total_deny_orchestrator_held_count == 9`. Each total equals the sum of the corresponding per-source counters across the three per-source records.

11. `test_summary_total_lab_pointer_presence_count_equals_nine`. The harness result's `summary.total_lab_pointer_presence_count` equals 9.

12. `test_summary_per_symbol_total_counts`. The harness result's `summary.per_symbol_total_counts` has four rows (`BTCUSDT`, `ETHUSDT`, `LABUSDT`, `SOLUSDT` ASCII ascending), each with `count == 9`.

13. `test_summary_paper_mode_flag_is_harness_level_flag`. The `summary.paper_mode_flag` is the same `PaperModeFlag` instance as the harness-level flag returned by the harness result (identity, not equality).

14. `test_no_forbidden_lineage_or_market_fields`. None of the typed records (`AggregateRollupSourceInput`, `AggregateRollupSourcePack`, `AggregateRollupPerSymbolCount`, `AggregateRollupPerSourceRecord`, `AggregateRollupSummary`) carries a `shadow_decision_id`, `execution_intent_id`, standalone `paper_trade_id` (beyond fields carried by `RiskDecisionRecord` itself), or any of `pnl`, `quantity`, `price`, `fees`, `slippage`, `funding_rate`, `open_interest`, `liquidation_cluster`, `orderbook_depth`, `hedge_state`, `residual_exposure`, or `squeeze_risk` field. Verified by introspecting the `__dataclass_fields__` of each typed record class.

15. `test_legacy_evidence_pointer_is_string_not_path`. For each `AggregateRollupSourceInput.legacy_evidence_pointer`, the value is an instance of `str` and the test does NOT call `pathlib.Path(...)` on the value, does NOT call `open(...)` on the value, and does NOT call any read helper. Verified by absence of `pathlib`, `open`, and `Path` references in the test module body via a forbidden-token AST scan helper authored under the test package.

## Validation command

`python -m pytest v2/backend/tests/unit/aggregate_evidence_rollup_harness/test_aggregate_evidence_rollup_harness.py -v --no-header`. Expected outcome: 15 passed in under 1.0 seconds.

## Forbidden-token scan

Within `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`, a forbidden-token scan must return zero matches for: `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open(`, `pathlib.Path`, `requests`, `httpx`, `urllib`, `socket`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, `scikit-learn`, `mock(`, `patch(`, `monkeypatch`, `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`, the literal string `BEGIN` followed by `_FILE`, and the literal string `END` followed by `_FILE`. The scan is asserted by an additional pytest case authored as `test_no_forbidden_tokens_in_authored_files` (which makes the total 16 pytest cases). The scan reads the four authored files (`__init__.py`, `fixtures.py`, `harness.py`, `test_aggregate_evidence_rollup_harness.py`) via the standard test-package import-path resolution; the scan does NOT call `open`, `pathlib`, or any external file-system helper. The scan is implemented by reading the dunder `__file__` attribute of each module and using `inspect.getsource(module)` to obtain the source text deterministically. (Note: `inspect.getsource` is the only allowed source-introspection helper for the forbidden-token scan; `linecache`, `pkgutil.get_data`, and any other source-fetch helper are forbidden.)

## Forbidden-import scan

The pytest module additionally asserts via an `import` AST walk that the harness module's import set is restricted to:

- `dataclasses` (stdlib).
- `typing` / `collections.abc` (stdlib).
- `inspect` (stdlib, only inside the forbidden-token-scan helper).
- `v2.backend.app.domain.risk_gateway` (typed surface).
- `v2.backend.app.domain.paper_mode.flag` (typed surface).
- `v2.backend.app.composition.paper_mode.runtime` (composition root).
- the sibling test-package modules (`fixtures`).

Any other top-level module import is a test failure.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_TEST_PLAN_READY
END_FILE: claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/04_TEST_PLAN.md
