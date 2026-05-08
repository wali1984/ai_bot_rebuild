from __future__ import annotations

import ast
import inspect
from dataclasses import fields

from v2.backend.app.domain.paper_mode.flag import PaperModeFlag
from v2.backend.tests.unit.decision_explainability_data_contract import fixtures
from v2.backend.tests.unit.decision_explainability_data_contract import harness
from v2.backend.tests.unit.decision_explainability_data_contract.fixtures import (
    DecisionExplainabilityFixtureInput,
    build_decision_explainability_fixture_inputs,
)
from v2.backend.tests.unit.decision_explainability_data_contract.harness import (
    DecisionExplainabilityEnvelope,
    DecisionExplainabilityHarnessResult,
    decision_explainability_data_contract_harness,
)


EXPECTED_SCENARIO_SLUGS = (
    "decision_explainability_pack_btc_winner_long",
    "decision_explainability_pack_eth_winner_short",
    "decision_explainability_pack_lab_loser_short",
    "decision_explainability_pack_sol_orchestrator_held",
)
EXPECTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "LABUSDT", "SOLUSDT"})
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
        "top_positive_feature_contributors",
        "top_negative_feature_contributors",
        "feature_freshness_flags",
        "stale_missing_unused_feature_flags",
        "confidence",
        "previous_confidence",
        "confidence_delta",
        "confidence_calibration",
        "model_version",
        "checkpoint_version",
        "regime_context",
        "position_sizing_reason",
        "risk_check_list",
        "blocked_trade_reason",
        "paper_shadow_legacy_comparison",
        "audit_timeline",
    }
)


def test_harness_paper_mode_flag_live_blocked_invariant() -> None:
    result = _run_harness()

    assert isinstance(result.paper_mode_flag, PaperModeFlag)
    assert result.paper_mode_flag.live_blocked is True
    assert result.paper_mode_flag.mode in {"paper", "live_blocked"}


def test_fixture_input_count_equals_twelve() -> None:
    inputs = build_decision_explainability_fixture_inputs()

    assert len(inputs) == 12
    expected_slugs = tuple(slug for slug in EXPECTED_SCENARIO_SLUGS for _ in range(3))
    assert tuple(row.scenario_slug for row in inputs) == expected_slugs
    assert tuple(row.step_index for row in inputs) == (1, 2, 3) * 4


def test_envelope_count_equals_twelve() -> None:
    result = _run_harness()

    assert len(result.envelopes) == 12


def test_envelope_lineage_carry_over() -> None:
    inputs = build_decision_explainability_fixture_inputs()
    result = _run_harness_from(inputs)

    for input_row, envelope in zip(inputs, result.envelopes, strict=True):
        record = input_row.risk_decision_record
        assert envelope.feature_snapshot_id == record.feature_snapshot_id
        assert envelope.prediction_id == record.prediction_id
        assert envelope.decision_id == record.decision_id
        assert envelope.risk_decision_id == record.risk_decision_id
        assert envelope.symbol == record.symbol


def test_envelope_action_reason_mirror() -> None:
    inputs = build_decision_explainability_fixture_inputs()
    result = _run_harness_from(inputs)

    for input_row, envelope in zip(inputs, result.envelopes, strict=True):
        record = input_row.risk_decision_record
        assert envelope.input_decision_action == record.input_decision_action
        assert envelope.input_decision_reason_code == record.input_decision_reason_code
        assert envelope.risk_action == record.risk_action
        assert envelope.risk_reason_code == record.risk_reason_code


def test_envelope_per_row_paper_mode_flag_mirror() -> None:
    result = _run_harness()

    for envelope in result.envelopes:
        assert envelope.paper_mode_live_blocked is True
        assert envelope.paper_mode_mode == result.paper_mode_flag.mode


def test_envelope_decision_ts_ms_mirror() -> None:
    inputs = build_decision_explainability_fixture_inputs()
    result = _run_harness_from(inputs)

    for input_row, envelope in zip(inputs, result.envelopes, strict=True):
        assert envelope.risk_decision_ts_ms == input_row.risk_decision_record.risk_decision_ts_ms


def test_envelope_risk_live_blocked_mirror() -> None:
    inputs = build_decision_explainability_fixture_inputs()
    result = _run_harness_from(inputs)

    for input_row, envelope in zip(inputs, result.envelopes, strict=True):
        assert envelope.risk_live_blocked is True
        assert envelope.risk_live_blocked == input_row.risk_decision_record.live_blocked


def test_envelope_legacy_evidence_pointer_is_string_not_path() -> None:
    result = _run_harness()

    for envelope in result.envelopes:
        assert isinstance(envelope.legacy_evidence_pointer, str)
        assert envelope.legacy_evidence_pointer.startswith("legacy_evidence__")


def test_envelope_lab_scenario_pointer_literal_match() -> None:
    result = _run_harness()
    lab_slug = "decision_explainability_pack_lab_loser_short"

    lab_envelopes = [
        envelope for envelope in result.envelopes if envelope.source_scenario_slug == lab_slug
    ]
    assert len(lab_envelopes) == 3
    for envelope in lab_envelopes:
        assert envelope.legacy_evidence_pointer == (
            f"legacy_evidence__decision_explainability__"
            f"lab_hedge_unwind_squeeze__step_{envelope.step_index}"
        )


def test_envelope_source_scenario_slug_namespacing() -> None:
    result = _run_harness()
    allowed = set(EXPECTED_SCENARIO_SLUGS)

    for envelope in result.envelopes:
        assert envelope.source_scenario_slug.startswith("decision_explainability_")
        assert envelope.source_scenario_slug in allowed


def test_envelope_step_index_one_based() -> None:
    result = _run_harness()

    for envelope in result.envelopes:
        assert envelope.step_index in {1, 2, 3}


def test_envelope_symbols_are_uppercase_binance_usdm() -> None:
    result = _run_harness()

    for envelope in result.envelopes:
        assert envelope.symbol in EXPECTED_SYMBOLS
        assert envelope.symbol == envelope.symbol.upper()


def test_no_forbidden_lineage_or_market_fields() -> None:
    for record_class in (
        DecisionExplainabilityFixtureInput,
        DecisionExplainabilityEnvelope,
        DecisionExplainabilityHarnessResult,
    ):
        names = {field.name for field in fields(record_class)}
        assert names.isdisjoint(DISALLOWED_RECORD_FIELDS)


def test_harness_paper_mode_flag_is_singleton_identity() -> None:
    result = _run_harness()
    flag = result.paper_mode_flag

    for envelope in result.envelopes:
        assert envelope.paper_mode_mode == flag.mode
        assert envelope.paper_mode_live_blocked == flag.live_blocked


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
    modules = (
        fixtures,
        harness,
        inspect.getmodule(test_no_forbidden_tokens_in_authored_files),
    )

    for module in modules:
        source_text = inspect.getsource(module)
        for token in forbidden_tokens:
            assert token not in source_text

    allowed_roots = {
        "__future__",
        "dataclasses",
        "v2.backend.app.composition.paper_mode.runtime",
        "v2.backend.app.domain.paper_mode.flag",
        "v2.backend.app.domain.risk_gateway",
        "v2.backend.tests.unit.decision_explainability_data_contract.fixtures",
    }
    tree = ast.parse(inspect.getsource(harness))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert imports <= allowed_roots


def _run_harness() -> DecisionExplainabilityHarnessResult:
    return decision_explainability_data_contract_harness(
        build_decision_explainability_fixture_inputs()
    )


def _run_harness_from(
    inputs: tuple[DecisionExplainabilityFixtureInput, ...],
) -> DecisionExplainabilityHarnessResult:
    return decision_explainability_data_contract_harness(inputs)
