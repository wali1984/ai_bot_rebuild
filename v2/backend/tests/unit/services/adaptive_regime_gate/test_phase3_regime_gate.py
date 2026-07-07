from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.services.a_plus_trade_gate.service import APlusGateConfig, _regime_check
from v2.backend.app.services.adaptive_regime_gate.classifier import (
    REGIMES,
    REQUIRED_INPUT_FAMILIES,
    regime_classifier_behavioral_proofs,
)
from v2.backend.app.services.adaptive_regime_gate.permission_matrix import (
    permission_matrix_behavioral_proofs,
    permission_matrix_status,
    strategy_allowed_in_regime,
)


def test_regime_classifier_behavioral_proofs_cover_all_required_regimes() -> None:
    proof = regime_classifier_behavioral_proofs()

    assert proof["required_regimes"] == list(REGIMES)
    assert proof["required_input_families"] == list(REQUIRED_INPUT_FAMILIES)
    assert proof["all_required_regime_outputs_proven"] is True
    assert proof["all_proofs_passed"] is True
    assert set(proof["produced_regimes"]) == set(REGIMES)
    missing_case = next(row for row in proof["proofs"] if row["name"] == "missing_core_input_fail_closed")
    assert missing_case["actual_regime"] == "NO_TRADE"
    assert missing_case["fail_closed"] is True


def test_permission_matrix_behavioral_proofs_enforce_phase3_hard_rules() -> None:
    proof = permission_matrix_behavioral_proofs()
    status = permission_matrix_status()

    assert proof["all_proofs_passed"] is True
    assert status["hard_rules_proven"] is True
    by_name = {row["name"]: row for row in proof["proofs"]}
    assert by_name["no_trend_strategy_in_ranging_regime"]["actual_allowed"] is False
    assert by_name["mean_reversion_blocked_in_trend_without_reversal"]["actual_allowed"] is False
    assert by_name["mean_reversion_allowed_in_trend_with_reversal"]["actual_allowed"] is True
    assert by_name["volatile_expansion_blocks_without_tape_and_microstructure"]["actual_allowed"] is False
    assert by_name["volatile_expansion_allows_with_tape_and_microstructure"]["actual_allowed"] is True
    assert by_name["liquidity_sweep_blocks_entries"]["actual_allowed"] is False
    assert by_name["fakeout_risk_blocks_entries"]["actual_allowed"] is False
    assert by_name["no_trade_blocks_entries"]["actual_allowed"] is False
    assert by_name["unknown_strategy_deny_by_default"]["actual_allowed"] is False


def test_strategy_permission_matrix_denies_unknown_regime_by_default() -> None:
    verdict = strategy_allowed_in_regime(
        strategy_id="trend_mode",
        side="long",
        regime_decision={"regime": "NEW_UNKNOWN_REGIME", "confidence": 0.9},
    )

    assert verdict["allowed"] is False
    assert verdict["regime"] == "NO_TRADE"
    assert any("UNKNOWN_REGIME" in reason for reason in verdict["reasons"])


def test_a_plus_regime_check_surfaces_matrix_block_reasons() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    result = _regime_check(
        regime_decision={
            "regime": "RANGING",
            "confidence": 0.9,
            "generated_utc": "2026-07-06T12:00:00Z",
        },
        strategy_id="trend_mode",
        side="long",
        trade_tape={},
        microstructure_trust={},
        now=now,
        config=APlusGateConfig(),
    )

    assert result["passed"] is False
    assert "MATRIX_BLOCK:RANGING:trend_long" in result["reason"]
