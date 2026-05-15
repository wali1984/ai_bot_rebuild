from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.composition.paper_expected_move_coverage import (
    EXPECTED_MOVE_COVERAGE_STATUS_MISSING,
    EXPECTED_MOVE_COVERAGE_STATUS_NATIVE,
    EXPECTED_MOVE_COVERAGE_STATUS_PROXY,
    EXPECTED_MOVE_SOURCE_MISSING,
    EXPECTED_MOVE_SOURCE_NATIVE_RISK,
    EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL,
    EXPECTED_MOVE_SOURCE_NATIVE_TRAINER,
    EXPECTED_MOVE_SOURCE_PROXY_CANDIDATE,
    LIVE_GATE_STATUS,
    evaluate_paper_expected_move_coverage,
    expected_move_bps_for_fill_gate,
)


COSTS = dict(fee_bps=4.0, spread_bps=1.0, slippage_bps=2.0, funding_bps=0.0)


def test_missing_expected_move_blocks_fill() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"raw_output": {"side": "long", "momentum_score": 0.02}},
        feature_snapshot={"features": {"return_5m": 0.001}},
        risk_payload={},
        signal_record={},
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_MISSING
    assert result["expected_move_coverage_status"] == EXPECTED_MOVE_COVERAGE_STATUS_MISSING
    assert result["expected_move_after_cost_bps_for_fill_gate"] is None
    assert result["expected_move_bps_for_fill_gate"] is None
    assert result["fill_eligible_from_expected_move"] is False
    assert "missing_expected_move_after_costs" in result["non_fill_reasons"]
    assert expected_move_bps_for_fill_gate(result) is None


def test_future_shadow_outcomes_cannot_permit_fills() -> None:
    # Future excursions / realized returns must never be treated as
    # expected-move evidence. They are not present in the documented
    # input contract, so the coverage module must classify the payload
    # as MISSING even when those keys are present.
    contaminated_trainer = {
        "raw_output": {"side": "long", "momentum_score": 0.04},
        "max_favorable_excursion_bps": 25.0,
        "realized_return_bps": 19.0,
        "shadow_observation_max_favorable_excursion_bps": 25.0,
    }
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction=contaminated_trainer,
        risk_payload={"max_favorable_excursion_bps": 25.0},
        signal_record={"realized_return_bps": 19.0},
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_MISSING
    assert result["fill_eligible_from_expected_move"] is False
    assert result["expected_move_after_cost_bps_for_fill_gate"] is None


def test_proxy_candidate_is_non_fill_eligible_even_when_above_costs() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={
            "raw_output": {"side": "long", "momentum_score": 0.05},
            "proxy_expected_move_bps": 50.0,
        },
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_PROXY_CANDIDATE
    assert result["expected_move_coverage_status"] == EXPECTED_MOVE_COVERAGE_STATUS_PROXY
    assert result["expected_move_bps"] == 50.0
    assert result["expected_move_after_cost_bps"] == pytest.approx(43.0)
    assert result["expected_move_bps_for_fill_gate"] is None
    assert result["expected_move_after_cost_bps_for_fill_gate"] is None
    assert result["fill_eligible_from_expected_move"] is False
    assert result["proxy_validation_approved"] is False
    assert "proxy_expected_move_unvalidated_cannot_permit_fill" in result["non_fill_reasons"]


def test_proxy_validation_flag_does_not_short_circuit_invariant() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"proxy_expected_move_bps": 50.0},
        proxy_validation_approved=True,
        **COSTS,
    )
    # The remediation deliberately keeps proxy non-fill-eligible even
    # if the operator passes proxy_validation_approved=True, until a
    # native source is also available. Validation surfacing is exposed
    # via the flag but the fill gate value remains None.
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_PROXY_CANDIDATE
    assert result["expected_move_bps_for_fill_gate"] is None
    assert result["expected_move_after_cost_bps_for_fill_gate"] is None
    assert result["fill_eligible_from_expected_move"] is False


def test_native_trainer_expected_move_passes() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"expected_move_bps": 25.0},
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_NATIVE_TRAINER
    assert result["expected_move_coverage_status"] == EXPECTED_MOVE_COVERAGE_STATUS_NATIVE
    assert result["expected_move_bps"] == 25.0
    assert result["expected_move_after_cost_bps"] == pytest.approx(18.0)
    assert result["expected_move_bps_for_fill_gate"] == 25.0
    assert result["expected_move_after_cost_bps_for_fill_gate"] == pytest.approx(18.0)
    assert result["fill_eligible_from_expected_move"] is True


def test_native_risk_after_cost_takes_priority() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"expected_move_bps": 10.0},
        risk_payload={"expected_move_after_cost_bps": 12.0},
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_NATIVE_RISK
    assert result["expected_move_after_cost_bps"] == 12.0
    assert result["expected_move_after_cost_bps_for_fill_gate"] == 12.0
    # Gross for the canary gate is reconstructed as after_cost + costs.
    assert result["expected_move_bps_for_fill_gate"] == pytest.approx(19.0)


def test_native_signal_expected_move_passes_when_others_missing() -> None:
    result = evaluate_paper_expected_move_coverage(
        signal_record={"expected_move_bps": 20.0},
        **COSTS,
    )
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_NATIVE_SIGNAL
    assert result["fill_eligible_from_expected_move"] is True
    assert result["expected_move_bps_for_fill_gate"] == 20.0


def test_native_value_does_not_alter_live_gate() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"expected_move_bps": 100.0},
        **COSTS,
    )
    assert result["live_gate_status"] == LIVE_GATE_STATUS
    assert LIVE_GATE_STATUS == "blocked_human_only"


def test_module_has_no_redis_or_exchange_imports() -> None:
    module_path = REPO_ROOT / "v2" / "backend" / "app" / "composition" / "paper_expected_move_coverage.py"
    text = module_path.read_text()
    forbidden = [
        "redis",
        "ccxt",
        "binance",
        "futures" + "_create" + "_order",
        "futures" + "_change" + "_leverage",
        "futures" + "_change" + "_margin_type",
        "create" + "_order",
        "cancel" + "_order",
    ]
    for token in forbidden:
        assert token not in text.lower(), f"forbidden token in coverage module: {token}"


def test_missing_returns_cost_bps_for_diagnostics() -> None:
    result = evaluate_paper_expected_move_coverage(**COSTS)
    assert result["cost_bps"] == pytest.approx(7.0)
    assert result["expected_move_source"] == EXPECTED_MOVE_SOURCE_MISSING


def test_native_with_zero_costs_emits_after_cost_equal_to_gross() -> None:
    result = evaluate_paper_expected_move_coverage(
        trainer_prediction={"expected_move_bps": 10.0},
    )
    assert result["expected_move_after_cost_bps"] == 10.0
    assert result["expected_move_bps_for_fill_gate"] == 10.0
