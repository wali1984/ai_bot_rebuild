from __future__ import annotations

import ast
import inspect
from dataclasses import fields

from v2.backend.app.domain.paper_mode.flag import PaperModeFlag
from v2.backend.tests.unit.aggregate_evidence_rollup_harness import fixtures
from v2.backend.tests.unit.aggregate_evidence_rollup_harness.fixtures import (
    AggregateRollupPerSourceRecord,
    AggregateRollupPerSymbolCount,
    AggregateRollupSourceInput,
    AggregateRollupSourcePack,
    AggregateRollupSummary,
    build_aggregate_rollup_source_packs,
)
from v2.backend.tests.unit.aggregate_evidence_rollup_harness import harness
from v2.backend.tests.unit.aggregate_evidence_rollup_harness.harness import (
    aggregate_evidence_rollup_harness,
)


EXPECTED_SOURCE_IDS = ("paper_mode", "shadow_mode", "historical_pnl")
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "LABUSDT", "SOLUSDT")
DISALLOWED_RECORD_FIELDS = frozenset(
    {
        "shadow_decision_id",
        "execution_intent_id",
        "paper_trade_id",
        "pnl",
        "quantity",
        "price",
        "fees",
        "slippage",
        "funding_rate",
        "open_interest",
        "liquidation_cluster",
        "orderbook_depth",
        "hedge_state",
        "residual_exposure",
        "squeeze_risk",
    }
)


def test_harness_paper_mode_flag_live_blocked_invariant() -> None:
    result = _run_harness()

    assert isinstance(result.paper_mode_flag, PaperModeFlag)
    assert result.paper_mode_flag.live_blocked is True
    assert result.paper_mode_flag.mode in {"paper", "live_blocked"}


def test_source_pack_count_equals_three() -> None:
    source_packs = build_aggregate_rollup_source_packs()

    assert len(source_packs) == 3
    assert tuple(source_pack.source_id for source_pack in source_packs) == EXPECTED_SOURCE_IDS


def test_per_source_inputs_count_equals_twelve() -> None:
    source_packs = build_aggregate_rollup_source_packs()

    assert all(len(source_pack.inputs) == 12 for source_pack in source_packs)


def test_per_source_record_count_equals_three() -> None:
    result = _run_harness()

    assert len(result.per_source_records) == 3
    assert tuple(record.source_id for record in result.per_source_records) == EXPECTED_SOURCE_IDS


def test_per_source_total_inputs_equals_twelve() -> None:
    result = _run_harness()

    assert all(record.total_inputs == 12 for record in result.per_source_records)


def test_per_source_action_counts() -> None:
    result = _run_harness()

    for record in result.per_source_records:
        assert record.allow_proceed_long_count == 3
        assert record.allow_proceed_short_count == 6
        assert record.deny_orchestrator_held_count == 3


def test_per_source_per_symbol_counts() -> None:
    result = _run_harness()

    for record in result.per_source_records:
        assert tuple(row.symbol for row in record.per_symbol_counts) == EXPECTED_SYMBOLS
        assert tuple(row.count for row in record.per_symbol_counts) == (3, 3, 3, 3)


def test_per_source_lab_pointer_presence_count_equals_three() -> None:
    result = _run_harness()

    assert all(
        record.lab_pointer_presence_count == 3 for record in result.per_source_records
    )


def test_summary_total_inputs_equals_thirty_six() -> None:
    result = _run_harness()

    assert result.summary.total_inputs == 36


def test_summary_action_counts_equal_sum_of_per_source_counts() -> None:
    result = _run_harness()

    assert result.summary.total_allow_proceed_long_count == 9
    assert result.summary.total_allow_proceed_short_count == 18
    assert result.summary.total_deny_orchestrator_held_count == 9
    assert result.summary.total_allow_proceed_long_count == sum(
        record.allow_proceed_long_count for record in result.per_source_records
    )
    assert result.summary.total_allow_proceed_short_count == sum(
        record.allow_proceed_short_count for record in result.per_source_records
    )
    assert result.summary.total_deny_orchestrator_held_count == sum(
        record.deny_orchestrator_held_count for record in result.per_source_records
    )


def test_summary_total_lab_pointer_presence_count_equals_nine() -> None:
    result = _run_harness()

    assert result.summary.total_lab_pointer_presence_count == 9


def test_summary_per_symbol_total_counts() -> None:
    result = _run_harness()

    assert tuple(row.symbol for row in result.summary.per_symbol_total_counts) == (
        EXPECTED_SYMBOLS
    )
    assert tuple(row.count for row in result.summary.per_symbol_total_counts) == (
        9,
        9,
        9,
        9,
    )


def test_summary_paper_mode_flag_is_harness_level_flag() -> None:
    result = _run_harness()

    assert result.summary.paper_mode_flag is result.paper_mode_flag


def test_no_forbidden_lineage_or_market_fields() -> None:
    for record_class in (
        AggregateRollupSourceInput,
        AggregateRollupSourcePack,
        AggregateRollupPerSymbolCount,
        AggregateRollupPerSourceRecord,
        AggregateRollupSummary,
    ):
        assert {field.name for field in fields(record_class)}.isdisjoint(
            DISALLOWED_RECORD_FIELDS
        )


def test_legacy_evidence_pointer_is_string_not_path() -> None:
    source_packs = build_aggregate_rollup_source_packs()

    for source_pack in source_packs:
        for input_row in source_pack.inputs:
            assert isinstance(input_row.legacy_evidence_pointer, str)
            assert input_row.legacy_evidence_pointer.startswith("legacy_evidence__")


def test_no_forbidden_tokens_in_authored_files() -> None:
    forbidden_tokens = (
        "time." + "time",
        "time." + "monotonic",
        "datetime." + "now",
        "datetime." + "utcnow",
        "os." + "environ",
        "os." + "getenv",
        "op" + "en(",
        "pathlib." + "Path",
        "requ" + "ests",
        "ht" + "tpx",
        "url" + "lib",
        "sock" + "et",
        "red" + "is",
        "aiored" + "is",
        "cc" + "xt",
        "fast" + "api",
        "star" + "lette",
        "pyd" + "antic",
        "tor" + "ch",
        "num" + "py",
        "pan" + "das",
        "scikit" + "-learn",
        "mock" + "(",
        "patch" + "(",
        "monkey" + "patch",
        "FINAL_NON_LIVE_REBUILD_READY" + "_FOR_LIVE_GATE_REVIEW",
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    )
    modules = (fixtures, harness, inspect.getmodule(test_no_forbidden_tokens_in_authored_files))

    for module in modules:
        source_text = inspect.getsource(module)
        for token in forbidden_tokens:
            assert token not in source_text


def test_forbidden_import_scan() -> None:
    allowed_roots = {
        "__future__",
        "dataclasses",
        "v2.backend.app.composition.paper_mode.runtime",
        "v2.backend.app.domain.paper_mode.flag",
        "v2.backend.app.domain.risk_gateway",
        "v2.backend.tests.unit.aggregate_evidence_rollup_harness.fixtures",
    }
    tree = ast.parse(inspect.getsource(harness))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert imports <= allowed_roots


def _run_harness() -> harness.AggregateRollupHarnessResult:
    return aggregate_evidence_rollup_harness(build_aggregate_rollup_source_packs())
