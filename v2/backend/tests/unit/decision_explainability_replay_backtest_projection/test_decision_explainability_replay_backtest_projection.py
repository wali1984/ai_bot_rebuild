from __future__ import annotations

import dataclasses
import inspect
import re

from v2.backend.tests.unit.decision_explainability_replay_backtest_projection import (
    fixtures as fixtures_module,
)
from v2.backend.tests.unit.decision_explainability_replay_backtest_projection import (
    harness as harness_module,
)
from v2.backend.tests.unit.decision_explainability_replay_backtest_projection.fixtures import (
    REPLAY_CLOCK_START_MS,
    SCENARIO_BTC_SLUG,
    SCENARIO_ETH_SLUG,
    SCENARIO_LAB_SLUG,
    SCENARIO_SOL_SLUG,
    build_replay_backtest_explainability_fixture_inputs,
)
from v2.backend.tests.unit.decision_explainability_replay_backtest_projection.harness import (
    ReplayBacktestProjectionHarnessResult,
    ReplayBacktestStepExplainabilityEnvelope,
    ReplayBacktestSummaryExplainabilityEnvelope,
    run_replay_backtest_projection_harness,
)


STEP_FIELDS = (
    "replay_step_id",
    "replay_run_id",
    "paper_trade_id",
    "risk_decision_id",
    "decision_id",
    "prediction_id",
    "feature_snapshot_id",
    "symbol",
    "step_ts_ms",
    "step_action",
    "step_reason_code",
    "input_paper_action",
    "input_paper_reason_code",
    "live_blocked",
    "source_scenario_slug",
    "step_index",
    "legacy_evidence_pointer",
)

SUMMARY_FIELDS = (
    "replay_summary_id",
    "replay_run_id",
    "summary_emitted_ts_ms",
    "total_steps_count",
    "record_allow_steps_count",
    "record_deny_steps_count",
    "mirror_allow_proceed_long_steps_count",
    "mirror_allow_proceed_short_steps_count",
    "mirror_deny_orchestrator_held_steps_count",
    "mirror_deny_orchestrator_abstained_steps_count",
    "mirror_deny_default_steps_count",
    "live_blocked",
    "source_scenario_slug",
    "legacy_evidence_pointer",
)

FORBIDDEN_FIELDS = {
    "pnl",
    "quantity",
    "price",
    "fee",
    "funding",
    "oi",
    "liquidation_distance",
    "orderbook_depth",
    "hedge_state",
    "residual_exposure",
    "squeeze_score",
    "confidence",
    "top_positive_feature_contributors",
    "top_negative_feature_contributors",
    "feature_freshness_flags",
    "regime_context",
    "model_version",
    "checkpoint_version",
    "position_sizing_reason",
    "risk_check_list",
    "blocked_trade_reason",
    "paper_shadow_legacy_comparison",
    "audit_timeline",
    "shadow_decision_id",
    "execution_intent_id",
}


def _by_slug(slug: str) -> tuple[ReplayBacktestStepExplainabilityEnvelope, ...]:
    result = run_replay_backtest_projection_harness()
    return tuple(row for row in result.step_envelopes if row.source_scenario_slug == slug)


def test_harness_returns_frozen_result_with_12_steps_and_4_summaries() -> None:
    result = run_replay_backtest_projection_harness()

    assert isinstance(result, ReplayBacktestProjectionHarnessResult)
    assert len(result.step_envelopes) == 12
    assert len(result.summary_envelopes) == 4
    assert type(result.step_envelopes) is tuple
    assert type(result.summary_envelopes) is tuple
    assert dataclasses.is_dataclass(result)
    assert result.__dataclass_params__.frozen is True


def test_per_row_lineage_carry_over() -> None:
    result = run_replay_backtest_projection_harness()
    inputs = build_replay_backtest_explainability_fixture_inputs()

    for envelope, input_row in zip(result.step_envelopes, inputs, strict=True):
        assert envelope.risk_decision_id == input_row.risk_decision_id
        assert envelope.decision_id == input_row.decision_id
        assert envelope.prediction_id == input_row.prediction_id
        assert envelope.feature_snapshot_id == input_row.feature_snapshot_id
        assert envelope.paper_trade_id == "pt_" + input_row.risk_decision_id
        assert envelope.replay_step_id
        assert envelope.replay_run_id


def test_per_row_action_reason_mirror_per_scenario() -> None:
    expected = {
        SCENARIO_BTC_SLUG: (
            "step_record_allow",
            "step_mirror_allow_proceed_long",
            "record_allow",
            "mirror_allow_proceed_long",
        ),
        SCENARIO_ETH_SLUG: (
            "step_record_allow",
            "step_mirror_allow_proceed_short",
            "record_allow",
            "mirror_allow_proceed_short",
        ),
        SCENARIO_LAB_SLUG: (
            "step_record_allow",
            "step_mirror_allow_proceed_short",
            "record_allow",
            "mirror_allow_proceed_short",
        ),
        SCENARIO_SOL_SLUG: (
            "step_record_deny",
            "step_mirror_deny_orchestrator_held",
            "record_deny",
            "mirror_deny_orchestrator_held",
        ),
    }

    for slug, expected_values in expected.items():
        for row in _by_slug(slug):
            assert (
                row.step_action,
                row.step_reason_code,
                row.input_paper_action,
                row.input_paper_reason_code,
            ) == expected_values


def test_per_row_symbol_mirror_per_scenario() -> None:
    expected = {
        SCENARIO_BTC_SLUG: "BTCUSDT",
        SCENARIO_ETH_SLUG: "ETHUSDT",
        SCENARIO_LAB_SLUG: "LABUSDT",
        SCENARIO_SOL_SLUG: "SOLUSDT",
    }

    for slug, symbol in expected.items():
        assert {row.symbol for row in _by_slug(slug)} == {symbol}


def test_per_row_step_ts_ms_strictly_monotonic_and_within_replay_clock_window() -> None:
    result = run_replay_backtest_projection_harness()
    step_timestamps = tuple(row.step_ts_ms for row in result.step_envelopes)

    assert step_timestamps == tuple(sorted(step_timestamps))
    assert len(set(step_timestamps)) == 12
    assert step_timestamps[0] == REPLAY_CLOCK_START_MS
    assert step_timestamps[-1] <= REPLAY_CLOCK_START_MS + 15 * 23
    assert all(type(value) is int and value > 0 for value in step_timestamps)


def test_summary_partition_counts_match_per_scenario_action_reason_distribution() -> None:
    result = run_replay_backtest_projection_harness()
    summaries = {row.source_scenario_slug: row for row in result.summary_envelopes}

    for summary in summaries.values():
        assert summary.total_steps_count == 3
        assert summary.live_blocked is True

    assert summaries[SCENARIO_BTC_SLUG].record_allow_steps_count == 3
    assert summaries[SCENARIO_BTC_SLUG].mirror_allow_proceed_long_steps_count == 3
    assert summaries[SCENARIO_ETH_SLUG].record_allow_steps_count == 3
    assert summaries[SCENARIO_ETH_SLUG].mirror_allow_proceed_short_steps_count == 3
    assert summaries[SCENARIO_LAB_SLUG].record_allow_steps_count == 3
    assert summaries[SCENARIO_LAB_SLUG].mirror_allow_proceed_short_steps_count == 3
    assert summaries[SCENARIO_SOL_SLUG].record_deny_steps_count == 3
    assert summaries[SCENARIO_SOL_SLUG].mirror_deny_orchestrator_held_steps_count == 3

    assert summaries[SCENARIO_BTC_SLUG].record_deny_steps_count == 0
    assert summaries[SCENARIO_ETH_SLUG].record_deny_steps_count == 0
    assert summaries[SCENARIO_LAB_SLUG].record_deny_steps_count == 0
    assert summaries[SCENARIO_SOL_SLUG].record_allow_steps_count == 0


def test_lab_scenario_legacy_evidence_pointer_literal() -> None:
    result = run_replay_backtest_projection_harness()
    lab_rows = tuple(
        row for row in result.step_envelopes if row.source_scenario_slug == SCENARIO_LAB_SLUG
    )
    lab_summary = next(
        row for row in result.summary_envelopes if row.source_scenario_slug == SCENARIO_LAB_SLUG
    )

    pattern = re.compile(
        "^legacy_evidence__replay_step_explainability__"
        "lab_hedge_unwind_squeeze__step_[0-2]$"
    )
    assert all(pattern.match(row.legacy_evidence_pointer) for row in lab_rows)
    assert lab_summary.legacy_evidence_pointer == (
        "legacy_evidence__replay_step_explainability__"
        "lab_hedge_unwind_squeeze__summary"
    )
    assert {row.step_index for row in lab_rows} == {0, 1, 2}


def test_envelope_allowed_fields_only() -> None:
    step_fields = tuple(
        field.name for field in dataclasses.fields(ReplayBacktestStepExplainabilityEnvelope)
    )
    summary_fields = tuple(
        field.name
        for field in dataclasses.fields(ReplayBacktestSummaryExplainabilityEnvelope)
    )

    assert step_fields == STEP_FIELDS
    assert summary_fields == SUMMARY_FIELDS
    assert not hasattr(ReplayBacktestStepExplainabilityEnvelope, "__slots__")
    assert not hasattr(ReplayBacktestSummaryExplainabilityEnvelope, "__slots__")
    assert ReplayBacktestStepExplainabilityEnvelope.__dataclass_params__.frozen is True
    assert ReplayBacktestSummaryExplainabilityEnvelope.__dataclass_params__.frozen is True
    assert set(step_fields).isdisjoint(FORBIDDEN_FIELDS)
    assert set(summary_fields).isdisjoint(FORBIDDEN_FIELDS)


def test_replay_clock_and_paper_ledger_clock_factory_determinism() -> None:
    first = run_replay_backtest_projection_harness()
    second = run_replay_backtest_projection_harness()

    assert first.step_envelopes == second.step_envelopes
    assert first.summary_envelopes == second.summary_envelopes


def test_forbidden_token_and_forbidden_import_scan() -> None:
    combined_source = "\n".join(
        (
            inspect.getsource(harness_module),
            inspect.getsource(fixtures_module),
        )
    )

    forbidden_tokens = (
        "time.time",
        "time.monotonic",
        "datetime.now",
        "datetime.utcnow",
        "os.environ",
        "os.getenv",
        "os.path",
        "pathlib",
        "Path(",
        "redis",
        "aioredis",
        "ccxt",
        "fastapi",
        "starlette",
        "pydantic",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "torch",
        "numpy",
        "pandas",
        "scikit-learn",
        "sklearn",
        "mock(",
        "Mock(",
        "MagicMock(",
        "patch(",
        "monkeypatch",
        "mocker",
        "pnl",
        "quantity",
        "price",
        "fee",
        "funding",
        "oi_",
        "liquidation",
        "orderbook",
        "hedge_state",
        "residual_exposure",
        "squeeze",
        "confidence",
        "top_positive",
        "top_negative",
        "feature_freshness",
        "regime_context",
        "model_version",
        "checkpoint_version",
        "position_sizing",
        "risk_check_list",
        "blocked_trade_reason",
        "paper_shadow_legacy_comparison",
        "audit_timeline",
        "shadow_decision_id",
        "execution_intent_id",
        "assemble_paper_execution_ledger_entry(",
        "assemble_replay_backtest_step(",
        "assemble_replay_backtest_summary(",
        "build_paper_mode_runtime",
        "assemble_paper_mode_flag",
        "build_risk_decision_evaluator",
        "assemble_risk_decision_record",
        "build_orchestrator_decision_router",
    )
    for token in forbidden_tokens:
        assert token not in combined_source

    forbidden_import_fragments = (
        "decision_explainability_data_contract",
        "decision_explainability_paper_ledger_projection",
        "paper_mode_evidence_collection_harness",
        "shadow_mode_evidence_collection_harness",
        "historical_pnl_replay_wiring",
        "aggregate_evidence_rollup_harness",
    )
    import_lines = tuple(
        line for line in combined_source.splitlines() if line.startswith("import ")
    )
    import_lines += tuple(
        line for line in combined_source.splitlines() if line.startswith("from ")
    )
    for fragment in forbidden_import_fragments:
        assert all(fragment not in line for line in import_lines)
