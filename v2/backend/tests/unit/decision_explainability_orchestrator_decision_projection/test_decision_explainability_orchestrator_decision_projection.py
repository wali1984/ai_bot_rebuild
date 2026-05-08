from __future__ import annotations

import dataclasses
import inspect
import re

from v2.backend.tests.unit.decision_explainability_orchestrator_decision_projection import (
    fixtures as fixtures_module,
)
from v2.backend.tests.unit.decision_explainability_orchestrator_decision_projection import (
    harness as harness_module,
)
from v2.backend.tests.unit.decision_explainability_orchestrator_decision_projection.fixtures import (
    ORCHESTRATOR_CLOCK_START_MS,
    SCENARIO_BTC_SLUG,
    SCENARIO_ETH_SLUG,
    SCENARIO_LAB_SLUG,
    SCENARIO_SOL_SLUG,
    build_orchestrator_decision_explainability_fixture_inputs,
)
from v2.backend.tests.unit.decision_explainability_orchestrator_decision_projection.harness import (
    OrchestratorDecisionExplainabilityEnvelope,
    OrchestratorDecisionProjectionHarnessResult,
    decision_explainability_orchestrator_decision_projection_harness,
)


ENVELOPE_FIELDS = (
    "decision_id",
    "prediction_id",
    "feature_snapshot_id",
    "symbol",
    "decision_ts_ms",
    "decision_action",
    "decision_reason_code",
    "input_prediction_direction",
    "input_prediction_confidence_calibrated",
    "input_prediction_freshness_flag",
    "input_worker_health_status",
    "live_blocked",
    "legacy_evidence_pointer",
    "source_scenario_slug",
    "step_index",
)

FORBIDDEN_FIELDS = {
    "risk_decision_id",
    "paper_trade_id",
    "replay_step_id",
    "replay_run_id",
    "replay_summary_id",
    "shadow_decision_id",
    "execution_intent_id",
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
    "top_positive_feature_codes",
    "top_negative_feature_codes",
    "feature_freshness_flags",
    "regime_context",
    "model_version",
    "checkpoint_id",
    "confidence_raw",
    "previous_confidence",
    "confidence_delta",
    "confidence_calibration",
    "position_sizing_reason",
    "risk_check_list",
    "blocked_trade_reason",
    "paper_shadow_legacy_comparison",
    "audit_timeline",
}


def run_orchestrator_decision_projection_harness() -> (
    OrchestratorDecisionProjectionHarnessResult
):
    inputs = build_orchestrator_decision_explainability_fixture_inputs()
    return decision_explainability_orchestrator_decision_projection_harness(inputs)


def _by_slug(slug: str) -> tuple[OrchestratorDecisionExplainabilityEnvelope, ...]:
    result = run_orchestrator_decision_projection_harness()
    return tuple(row for row in result.envelopes if row.source_scenario_slug == slug)


def test_harness_returns_frozen_result_with_12_envelopes_and_12_decision_records() -> None:
    result = run_orchestrator_decision_projection_harness()

    assert isinstance(result, OrchestratorDecisionProjectionHarnessResult)
    assert len(result.envelopes) == 12
    assert len(result.decision_records) == 12
    assert type(result.envelopes) is tuple
    assert type(result.decision_records) is tuple
    assert dataclasses.is_dataclass(result)
    assert result.__dataclass_params__.frozen is True
    assert hasattr(OrchestratorDecisionProjectionHarnessResult, "__slots__")


def test_per_row_lineage_carry_over() -> None:
    result = run_orchestrator_decision_projection_harness()
    inputs = build_orchestrator_decision_explainability_fixture_inputs()

    for envelope, decision_record, input_row in zip(
        result.envelopes, result.decision_records, inputs, strict=True
    ):
        assert envelope.prediction_id == decision_record.prediction_id
        assert envelope.prediction_id == input_row.prediction_id
        assert envelope.feature_snapshot_id == decision_record.feature_snapshot_id
        assert envelope.feature_snapshot_id == input_row.feature_snapshot_id
        assert envelope.decision_id == decision_record.decision_id
        assert isinstance(envelope.decision_id, str)
        assert 1 <= len(envelope.decision_id) <= 128
        assert not any(character.isspace() for character in envelope.decision_id)


def test_per_row_action_reason_mirror_per_scenario() -> None:
    expected = {
        SCENARIO_BTC_SLUG: ("open_long", "proceed_long"),
        SCENARIO_ETH_SLUG: ("open_short", "proceed_short"),
        SCENARIO_LAB_SLUG: ("open_short", "proceed_short"),
        SCENARIO_SOL_SLUG: ("abstain", "abstain_low_confidence"),
    }

    for slug, expected_values in expected.items():
        for row in _by_slug(slug):
            assert (row.decision_action, row.decision_reason_code) == expected_values


def test_per_row_symbol_mirror_per_scenario() -> None:
    expected = {
        SCENARIO_BTC_SLUG: "BTCUSDT",
        SCENARIO_ETH_SLUG: "ETHUSDT",
        SCENARIO_LAB_SLUG: "LABUSDT",
        SCENARIO_SOL_SLUG: "SOLUSDT",
    }

    for slug, symbol in expected.items():
        assert {row.symbol for row in _by_slug(slug)} == {symbol}


def test_per_row_input_prediction_field_mirror_per_scenario() -> None:
    expected = {
        SCENARIO_BTC_SLUG: ("long", 0.85, "fresh", "HEALTHY"),
        SCENARIO_ETH_SLUG: ("short", 0.82, "fresh", "HEALTHY"),
        SCENARIO_LAB_SLUG: ("short", 0.83, "fresh", "HEALTHY"),
        SCENARIO_SOL_SLUG: ("long", 0.40, "fresh", "HEALTHY"),
    }

    for slug, expected_values in expected.items():
        for row in _by_slug(slug):
            assert (
                row.input_prediction_direction,
                row.input_prediction_confidence_calibrated,
                row.input_prediction_freshness_flag,
                row.input_worker_health_status,
            ) == expected_values
            assert type(row.input_prediction_confidence_calibrated) is float


def test_per_row_decision_ts_ms_strictly_monotonic_within_orchestrator_clock_window() -> None:
    result = run_orchestrator_decision_projection_harness()
    timestamps = tuple(row.decision_ts_ms for row in result.envelopes)

    assert timestamps == tuple(sorted(timestamps))
    assert len(set(timestamps)) == 12
    assert timestamps[0] == ORCHESTRATOR_CLOCK_START_MS
    assert timestamps[-1] <= ORCHESTRATOR_CLOCK_START_MS + 17 * 11
    assert all(type(value) is int and value > 0 for value in timestamps)


def test_per_row_live_blocked_invariant_true() -> None:
    result = run_orchestrator_decision_projection_harness()

    for envelope, decision_record in zip(
        result.envelopes, result.decision_records, strict=True
    ):
        assert envelope.live_blocked is True
        assert decision_record.live_blocked is True
        assert type(envelope.live_blocked) is bool


def test_lab_scenario_legacy_evidence_pointer_literal() -> None:
    lab_rows = _by_slug(SCENARIO_LAB_SLUG)
    pattern = re.compile(
        "^legacy_evidence__orchestrator_decision_explainability__"
        "lab_hedge_unwind_squeeze__step_[0-2]$"
    )

    assert all(pattern.match(row.legacy_evidence_pointer) for row in lab_rows)
    assert {row.step_index for row in lab_rows} == {0, 1, 2}
    assert {row.symbol for row in lab_rows} == {"LABUSDT"}
    assert {row.decision_action for row in lab_rows} == {"open_short"}


def test_envelope_allowed_fields_only() -> None:
    fields = tuple(
        field.name for field in dataclasses.fields(OrchestratorDecisionExplainabilityEnvelope)
    )

    assert fields == ENVELOPE_FIELDS
    assert OrchestratorDecisionExplainabilityEnvelope.__dataclass_params__.frozen is True
    assert hasattr(OrchestratorDecisionExplainabilityEnvelope, "__slots__")
    assert set(fields).isdisjoint(FORBIDDEN_FIELDS)


def test_evaluator_build_once_factory_determinism() -> None:
    first = run_orchestrator_decision_projection_harness()
    second = run_orchestrator_decision_projection_harness()

    assert first.envelopes == second.envelopes
    assert first.decision_records == second.decision_records


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
        "previous_confidence",
        "confidence_delta",
        "confidence_calibration",
        "top_positive_feature_contributors",
        "top_negative_feature_contributors",
        "feature_freshness",
        "regime_context",
        "model_version_change",
        "checkpoint_version",
        "position_sizing",
        "risk_check_list",
        "blocked_trade_reason",
        "paper_shadow_legacy_comparison",
        "audit_timeline",
        "shadow_decision_id",
        "execution_intent_id",
        "risk_decision_id",
        "paper_trade_id",
        "replay_step_id",
        "replay_run_id",
        "replay_summary_id",
        "assemble_orchestrator_decision_record(",
        "assemble_paper_mode_flag(",
        "assemble_risk_decision_record(",
        "assemble_paper_execution_ledger_entry(",
        "assemble_replay_backtest_step(",
        "assemble_replay_backtest_summary(",
        "build_paper_mode_runtime",
        "build_risk_decision_evaluator",
        "build_paper_execution_ledger_recorder",
        "build_replay_backtest_runner",
        "build_shadow_mode_readiness_runtime",
    )
    for token in forbidden_tokens:
        assert token not in combined_source

    forbidden_import_fragments = (
        "decision_explainability_data_contract",
        "decision_explainability_paper_ledger_projection",
        "decision_explainability_replay_backtest_projection",
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
