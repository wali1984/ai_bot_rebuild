from __future__ import annotations

import dataclasses
import inspect

from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    PaperExecutionLedgerEntry,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.tests.unit.decision_explainability_paper_ledger_projection import (
    fixtures as fixtures_module,
)
from v2.backend.tests.unit.decision_explainability_paper_ledger_projection import (
    harness as harness_module,
)
from v2.backend.tests.unit.decision_explainability_paper_ledger_projection.fixtures import (
    BASE_TS_MS,
    PAPER_LEDGER_CLOCK_START_MS,
    SCENARIO_BTC_SLUG,
    SCENARIO_ETH_SLUG,
    SCENARIO_LAB_SLUG,
    SCENARIO_SLUG_ORDER,
    SCENARIO_SOL_SLUG,
    PaperLedgerExplainabilityFixtureInput,
    build_paper_ledger_clock,
    build_paper_ledger_explainability_fixture_inputs,
)
from v2.backend.tests.unit.decision_explainability_paper_ledger_projection.harness import (
    PaperLedgerExplainabilityEnvelope,
    PaperLedgerExplainabilityHarnessResult,
    decision_explainability_paper_ledger_projection_harness,
)


EXPECTED_ENVELOPE_FIELDS = {
    "paper_trade_id",
    "risk_decision_id",
    "decision_id",
    "prediction_id",
    "feature_snapshot_id",
    "symbol",
    "ledger_entry_ts_ms",
    "ledger_action",
    "ledger_reason_code",
    "input_risk_action",
    "input_risk_reason_code",
    "live_blocked",
    "legacy_evidence_pointer",
    "source_scenario_slug",
    "step_index",
}

FORBIDDEN_ENVELOPE_FIELDS = {
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
    "shadow_decision_id",
    "execution_intent_id",
}


def _build_result() -> PaperLedgerExplainabilityHarnessResult:
    return decision_explainability_paper_ledger_projection_harness(
        build_paper_ledger_explainability_fixture_inputs()
    )


def test_harness_result_shape_and_typed_rows() -> None:
    inputs = build_paper_ledger_explainability_fixture_inputs()
    result = decision_explainability_paper_ledger_projection_harness(inputs)

    assert isinstance(result, PaperLedgerExplainabilityHarnessResult)
    assert len(result.envelopes) == 12
    assert len(result.ledger_entries) == 12
    assert all(isinstance(row, PaperLedgerExplainabilityFixtureInput) for row in inputs)
    assert all(isinstance(row, PaperLedgerExplainabilityEnvelope) for row in result.envelopes)
    assert all(isinstance(row, PaperExecutionLedgerEntry) for row in result.ledger_entries)
    assert all(
        isinstance(row.risk_decision_record, RiskDecisionRecord) for row in inputs
    )


def test_per_row_lineage_and_ledger_field_projection_is_exact() -> None:
    result = _build_result()

    for envelope, ledger_entry in zip(result.envelopes, result.ledger_entries, strict=True):
        assert envelope.paper_trade_id == ledger_entry.paper_trade_id
        assert envelope.risk_decision_id == ledger_entry.risk_decision_id
        assert envelope.decision_id == ledger_entry.decision_id
        assert envelope.prediction_id == ledger_entry.prediction_id
        assert envelope.feature_snapshot_id == ledger_entry.feature_snapshot_id
        assert envelope.symbol == ledger_entry.symbol
        assert envelope.ledger_action == ledger_entry.ledger_action
        assert envelope.ledger_reason_code == ledger_entry.ledger_reason_code
        assert envelope.input_risk_action == ledger_entry.input_risk_action
        assert envelope.input_risk_reason_code == ledger_entry.input_risk_reason_code
        assert envelope.live_blocked is True
        assert ledger_entry.live_blocked is True
        assert envelope.paper_trade_id == "pt_" + envelope.risk_decision_id


def test_ledger_clock_and_input_risk_timestamps_are_deterministic() -> None:
    inputs = build_paper_ledger_explainability_fixture_inputs()
    result = decision_explainability_paper_ledger_projection_harness(inputs)

    ledger_timestamps = tuple(row.ledger_entry_ts_ms for row in result.envelopes)
    assert ledger_timestamps == tuple(
        PAPER_LEDGER_CLOCK_START_MS + index * 19 for index in range(12)
    )
    assert ledger_timestamps == tuple(sorted(ledger_timestamps))
    assert len(set(ledger_timestamps)) == 12

    for index, input_row in enumerate(inputs):
        scenario_index = index // 3
        step_ordinal = (index % 3) + 1
        assert input_row.risk_decision_record.risk_decision_ts_ms == (
            BASE_TS_MS + scenario_index * 60_000 + step_ordinal * 100
        )


def test_per_scenario_action_reason_slug_step_and_symbol_invariants() -> None:
    result = _build_result()

    expected_ranges = (
        (0, 3, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PAPER_LEDGER_ACTION_RECORD_ALLOW),
        (3, 6, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT, PAPER_LEDGER_ACTION_RECORD_ALLOW),
        (6, 9, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT, PAPER_LEDGER_ACTION_RECORD_ALLOW),
        (9, 12, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, PAPER_LEDGER_ACTION_RECORD_DENY),
    )
    for start, stop, reason_code, action in expected_ranges:
        for envelope in result.envelopes[start:stop]:
            assert envelope.ledger_reason_code == reason_code
            assert envelope.ledger_action == action

    assert result.envelopes[0].source_scenario_slug == SCENARIO_BTC_SLUG
    assert result.envelopes[3].source_scenario_slug == SCENARIO_ETH_SLUG
    assert result.envelopes[6].source_scenario_slug == SCENARIO_LAB_SLUG
    assert result.envelopes[9].source_scenario_slug == SCENARIO_SOL_SLUG
    assert {row.symbol for row in result.envelopes} == {
        "BTCUSDT",
        "ETHUSDT",
        "LABUSDT",
        "SOLUSDT",
    }

    for index, envelope in enumerate(result.envelopes):
        assert envelope.source_scenario_slug == SCENARIO_SLUG_ORDER[index // 3]
        assert envelope.step_index == (index % 3) + 1


def test_lab_scenario_pointer_is_literal_metadata_only() -> None:
    result = _build_result()

    for envelope in result.envelopes[6:9]:
        assert envelope.legacy_evidence_pointer.startswith(
            "legacy_evidence__paper_ledger_explainability__"
            "lab_hedge_unwind_squeeze__step_"
        )
        assert envelope.source_scenario_slug == SCENARIO_LAB_SLUG


def test_envelope_has_only_allowed_projection_fields() -> None:
    envelope_fields = {field.name for field in dataclasses.fields(PaperLedgerExplainabilityEnvelope)}

    assert envelope_fields == EXPECTED_ENVELOPE_FIELDS
    assert envelope_fields.isdisjoint(FORBIDDEN_ENVELOPE_FIELDS)


def test_paper_ledger_clock_factory_is_deterministic() -> None:
    clock = build_paper_ledger_clock()

    assert [clock(), clock(), clock()] == [
        PAPER_LEDGER_CLOCK_START_MS,
        PAPER_LEDGER_CLOCK_START_MS + 19,
        PAPER_LEDGER_CLOCK_START_MS + 38,
    ]


def test_source_text_excludes_forbidden_runtime_and_persistence_surfaces() -> None:
    harness_source = inspect.getsource(harness_module)
    fixture_source = inspect.getsource(fixtures_module)
    test_source = inspect.getsource(inspect.getmodule(test_source_text_excludes_forbidden_runtime_and_persistence_surfaces))
    combined_source = "\n".join((harness_source, fixture_source, test_source))

    assert "build_paper_execution_ledger_recorder(" in harness_source
    assert harness_source.count("build_paper_execution_ledger_recorder(") == 1
    assert "v2.backend.app.composition.paper_execution_ledger.runtime import" in harness_source
    assert "build_paper_mode_runtime" not in harness_source
    assert "build_risk_decision_evaluator" not in harness_source
    assert "build_orchestrator_decision_router" not in harness_source
    assert "build_replay_backtest_runner" not in harness_source
    assert "assemble_paper_execution_ledger_entry" not in harness_source
    assert "assemble_risk_decision_record" not in harness_source
    assert "assemble_paper_mode_flag" not in harness_source

    forbidden_harness_tokens = (
        "open(",
        "pathlib",
        "sqlite3",
        "redis",
        "requests",
        "httpx",
        "socket",
        "urllib",
        "json.dump",
        "json.load",
        "pickle",
        "csv.writer",
        "csv.reader",
    )
    for token in forbidden_harness_tokens:
        assert token not in harness_source

    forbidden_import_tokens = (
        "import " + "time",
        "import " + "datetime",
        "os." + "environ",
        "os." + "getenv",
        "import " + "socket",
        "import " + "requests",
        "import " + "httpx",
        "import " + "urllib",
        "import " + "redis",
        "import " + "aioredis",
        "import " + "ccxt",
        "import " + "fastapi",
        "import " + "starlette",
        "import " + "pydantic",
        "import " + "torch",
        "import " + "numpy",
        "import " + "pandas",
        "import " + "scikit",
    )
    for token in forbidden_import_tokens:
        assert token not in combined_source

    forbidden_test_imports = (
        "from v2.backend.tests.unit." + "decision_explainability_data_contract",
        "from v2.backend.tests.unit." + "paper_mode_evidence_collection_harness",
        "from v2.backend.tests.unit." + "shadow_mode_evidence_collection_harness",
        "from v2.backend.tests.unit." + "historical_pnl_replay_wiring",
        "from v2.backend.tests.unit." + "aggregate_evidence_rollup_harness",
    )
    for token in forbidden_test_imports:
        assert token not in combined_source

    forbidden_marker_lines = {
        "BEGIN" + "_FILE",
        "END" + "_FILE",
    }
    for source_text in (harness_source, fixture_source, test_source):
        assert forbidden_marker_lines.isdisjoint(set(source_text.splitlines()))
