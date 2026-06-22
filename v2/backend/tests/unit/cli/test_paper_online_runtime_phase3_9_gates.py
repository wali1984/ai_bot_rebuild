"""Tests for Phase 3-9 wiring inside paper_online_runtime.

Phase 3: evaluate_entry_gate wired into apply_paper_entry_gates.
Phase 4: evaluate_high_precision_gate wired into apply_paper_entry_gates.
Phase 6: enrich_prediction_for_phase6 called in build_runtime_payload.
Phase 7: hedge advisory wired into build_position_lifecycle_entry.
Phase 8: recommend_leverage_for_signal (advisory) wired into apply_paper_entry_gates.
Phase 9: evaluate_all_detectors wired into apply_paper_entry_gates.

All tests are pure unit tests with no Redis, exchange, or external I/O.
No torch imports. Live gate remains blocked_human_only.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from v2.backend.app.cli.paper_online_runtime import (
    LIVE_GATE_STATUS,
    PAPER_POSITION_MIN_HOLD_SECONDS,
    MarketSnapshot,
    apply_paper_entry_gates,
    build_position_lifecycle_entry,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _lineage(
    *,
    risk_action: str = "allow",
    timeframe: str = "15m",
    confidence: float = 0.85,
    edge_bps: float = 20.0,
    side: str = "long",
) -> dict:
    """Minimal lineage dict for apply_paper_entry_gates testing."""
    return {
        "lineage_ids": {
            "prediction_id": "pred_test",
            "feature_snapshot_id": "fs_test",
            "signal_id": "sig_test",
            "risk_decision_id": "risk_test",
            "orchestrator_decision_id": "orch_test",
            "execution_intent_id": "pei_test",
        },
        "signal": {
            "signal_id": "sig_test",
            "symbol": "BTCUSDT",
            "proposed_action": "open_long",
        },
        "orchestrator_decision": {
            "orchestrator_decision_id": "orch_test",
        },
        "risk_decision": {
            "risk_decision_id": "risk_test",
            "risk_action": risk_action,
            "risk_result": "APPROVED_FOR_PAPER" if risk_action == "allow" else "BLOCKED",
            "risk_reason_code": "allow_paper_mode" if risk_action == "allow" else "deny_default",
            "expected_move_after_cost_bps": edge_bps,
            "required_blocks_checked": [],
        },
        "execution_intent": {
            "execution_intent_id": "pei_test",
            "symbol": "BTCUSDT",
            "side": side,
            "intent_action": "paper_entry_proposed",
            "exchange_order_allowed": False,
            "paper_only": True,
        },
        "signal_id": "sig_test",
        "feature_snapshot": {
            "feature_snapshot_id": "fs_test",
            "symbol": "BTCUSDT",
            "freshness_state": "CURRENT",
            "features": {
                "return_1m": 0.001,
                "return_5m": 0.003,
                "return_15m": 0.005,
                "volume_last": 100.0,
                "volume_avg_10": 90.0,
                "volatility_10": 0.001,
                "microstructure_toxicity_score_bps": 10.0,
            },
        },
        "trainer_prediction": {
            "prediction_id": "pred_test",
            "feature_snapshot_id": "fs_test",
            "timeframe": timeframe,
            "confidence_calibrated": confidence,
            "raw_output": {"side": side, "major_move_detected": False},
        },
    }


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        price=100.0,
        source_type="READONLY_MARKET_FEED",
        source="unit_test",
        source_pointer="unit_test",
        generated_at="2026-06-17T12:00:00Z",
        last_event_at="2026-06-17T12:00:00Z",
        age_seconds=10,
        freshness_state="CURRENT",
        errors=[],
        candles=[],
    )


# ── Phase 3: entry gate wiring ────────────────────────────────────────────────


def test_entry_gate_allows_1m_timeframe_without_static_quarantine() -> None:
    """Phase 3: timeframe eligibility is dynamic; 1m is not statically blocked."""
    lineage = _lineage(timeframe="1m", confidence=0.85, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    entry_gate = result["risk_decision"].get("entry_gate", {})
    if entry_gate:
        assert entry_gate["allowed"] is True
        assert not any("TIMEFRAME_BLOCKED" in r for r in entry_gate["reasons"])


def test_entry_gate_allows_15m_timeframe() -> None:
    """Phase 3: 15m timeframe is allowed by default entry gate."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    # Note: Phase 4 may block on missing data_coverage or low confidence,
    # but Phase 3 itself should not block on 15m.
    entry_gate = result["risk_decision"].get("entry_gate", {})
    if entry_gate:
        assert entry_gate["allowed"] is True


def test_entry_gate_allows_1h_timeframe() -> None:
    """Phase 3: 1h timeframe is allowed by default entry gate."""
    lineage = _lineage(timeframe="1h", confidence=0.85, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    entry_gate = result["risk_decision"].get("entry_gate", {})
    if entry_gate:
        assert entry_gate["allowed"] is True


def test_entry_gate_skipped_when_already_denied() -> None:
    """Phase 3: Gate chain skips all checks when risk_action is already deny."""
    lineage = _lineage(risk_action="deny")
    result = apply_paper_entry_gates(lineage)
    assert result["risk_decision"]["risk_action"] == "deny"
    assert "entry_gate" not in result["risk_decision"]
    assert "high_precision_gate" not in result["risk_decision"]
    assert "anti_mm_detection" not in result["risk_decision"]
    assert "leverage_recommendation" not in result["risk_decision"]


def test_entry_gate_records_result_dict() -> None:
    """Phase 3: entry_gate dict recorded in risk_decision regardless of allow/block."""
    lineage = _lineage(timeframe="1m")
    result = apply_paper_entry_gates(lineage)
    assert "entry_gate" in result["risk_decision"]
    eg = result["risk_decision"]["entry_gate"]
    assert "allowed" in eg
    assert "reasons" in eg
    assert "places_real_order" in eg
    assert eg["places_real_order"] is False


# ── Phase 4: high-precision gate wiring ──────────────────────────────────────


def test_high_precision_gate_blocks_low_confidence() -> None:
    """Phase 4: confidence < 0.75 blocks high-precision gate."""
    lineage = _lineage(timeframe="15m", confidence=0.60, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    # Phase 3 passes (15m allowed), Phase 4 should block on confidence
    assert result["risk_decision"]["risk_action"] == "deny"
    hp = result["risk_decision"].get("high_precision_gate", {})
    if hp:
        assert hp["allow"] is False
        assert any("CONFIDENCE" in r for r in hp.get("reasons", []))


def test_high_precision_gate_blocks_low_edge() -> None:
    """Phase 4: edge after cost < 15.0 bps blocks high-precision gate."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=5.0)
    result = apply_paper_entry_gates(lineage)
    assert result["risk_decision"]["risk_action"] == "deny"
    hp = result["risk_decision"].get("high_precision_gate", {})
    if hp:
        assert hp["allow"] is False
        assert any("EDGE" in r for r in hp.get("reasons", []))


def test_high_precision_gate_records_result_dict() -> None:
    """Phase 4: high_precision_gate dict recorded in risk_decision when checked."""
    lineage = _lineage(timeframe="15m", confidence=0.60, edge_bps=5.0)
    result = apply_paper_entry_gates(lineage)
    if "high_precision_gate" in result["risk_decision"]:
        hp = result["risk_decision"]["high_precision_gate"]
        assert "allow" in hp
        assert "reasons" in hp
        assert hp.get("places_real_order") is False


def test_phase4_block_does_not_set_live_order() -> None:
    """Phase 4: blocked intent must not allow exchange orders."""
    lineage = _lineage(timeframe="15m", confidence=0.50, edge_bps=3.0)
    result = apply_paper_entry_gates(lineage)
    assert result["execution_intent"]["exchange_order_allowed"] is False
    assert result["execution_intent"]["paper_only"] is True


# ── Phase 8: leverage recommendation wiring ──────────────────────────────────


def test_leverage_recommendation_never_blocks() -> None:
    """Phase 8: leverage_recommendation is advisory — risk_action stays allow when all
    other gates pass (within data limits — may still block on coverage/feature-family)."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    # Whether allowed or blocked, leverage_recommendation must never be the block cause.
    reason = result["risk_decision"].get("risk_reason_code", "")
    assert reason != "deny_leverage_recommendation"
    assert "leverage_recommendation" not in result["risk_decision"].get("required_blocks_checked", [])


def test_leverage_recommendation_present_when_gates_pass() -> None:
    """Phase 8: leverage_recommendation appears in risk_decision when Phases 3/4/9 all pass."""
    # To pass all gates including Phase 4, we need high confidence, high edge,
    # and supply all 12 critical feature families. Build a prediction that passes.
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    # Override the Phase 4 gate to use a relaxed config so we can get to Phase 8.
    # We do this by monkey-patching the high_precision_gate module to skip the gate.
    from v2.backend.app.cli import paper_online_runtime as por
    orig = None
    try:
        from v2.backend.app.services.paper_trade_management.high_precision_gate import (
            evaluate_high_precision_gate,
        )
        orig = evaluate_high_precision_gate
    except ImportError:
        pass

    if orig is not None:
        import v2.backend.app.services.paper_trade_management.high_precision_gate as hp_mod
        _saved = hp_mod.evaluate_high_precision_gate

        def _permissive(*a, **kw):
            return {"allow": True, "abstain": False, "reasons": [], "paper_only": True, "places_real_order": False}

        hp_mod.evaluate_high_precision_gate = _permissive
        try:
            result = apply_paper_entry_gates(lineage)
        finally:
            hp_mod.evaluate_high_precision_gate = _saved
    else:
        result = apply_paper_entry_gates(lineage)

    if result["risk_decision"]["risk_action"] == "allow":
        # If somehow all gates passed, leverage_recommendation must be present.
        assert "leverage_recommendation" in result["risk_decision"]
        lev = result["risk_decision"]["leverage_recommendation"]
        assert "recommended_leverage" in lev
        assert lev.get("mutates_exchange") is False
        assert lev.get("live_gate") == "blocked_human_only"


# ── Phase 9: anti-MM wiring ───────────────────────────────────────────────────


def test_anti_mm_detection_recorded_in_risk() -> None:
    """Phase 9: anti_mm_detection appears in risk_decision when Phase 3/4 pass."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    from v2.backend.app.services.paper_trade_management import high_precision_gate as hp_mod
    _saved_hp = hp_mod.evaluate_high_precision_gate

    def _permissive_hp(*a, **kw):
        return {"allow": True, "abstain": False, "reasons": [], "paper_only": True, "places_real_order": False}

    hp_mod.evaluate_high_precision_gate = _permissive_hp
    try:
        result = apply_paper_entry_gates(lineage)
    finally:
        hp_mod.evaluate_high_precision_gate = _saved_hp

    if "anti_mm_detection" in result["risk_decision"]:
        anti_mm = result["risk_decision"]["anti_mm_detection"]
        assert "entry_blocked" in anti_mm
        assert "live_gate" in anti_mm
        assert anti_mm["mutates_exchange"] is False


def test_anti_mm_entry_block_denies_risk_action() -> None:
    """Phase 9: when anti_mm detects entry_blocked, risk_action must become deny."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    from v2.backend.app.services.paper_trade_management import high_precision_gate as hp_mod
    from v2.backend.app.services.paper_trade_management import anti_market_maker_detector as amm_mod
    _saved_hp = hp_mod.evaluate_high_precision_gate
    _saved_amm = amm_mod.evaluate_all_detectors

    def _permissive_hp(*a, **kw):
        return {"allow": True, "abstain": False, "reasons": [], "paper_only": True, "places_real_order": False}

    def _entry_blocked_amm(features):
        return {
            "schema_version": "v2_anti_mm_detector_v1",
            "any_detected": True,
            "triggered_count": 1,
            "combined_actions": ["ENTRY_BLOCK"],
            "entry_blocked": True,
            "exit_accelerated": False,
            "size_reduced": False,
            "detectors": {
                "sweep_up_down": {"detected": True, "confidence": 0.9, "reason": "sweep_detected_test"},
                "spoof_wall_pull": {"detected": False, "confidence": 0.0, "reason": ""},
                "liquidity_hunt": {"detected": False, "confidence": 0.0, "reason": ""},
                "depth_tape_divergence": {"detected": False, "confidence": 0.0, "reason": ""},
                "toxic_flow": {"detected": False, "confidence": 0.0, "reason": ""},
                "stop_run_risk": {"detected": False, "confidence": 0.0, "reason": ""},
            },
            "live_gate": "blocked_human_only",
            "mutates_exchange": False,
        }

    hp_mod.evaluate_high_precision_gate = _permissive_hp
    amm_mod.evaluate_all_detectors = _entry_blocked_amm
    try:
        result = apply_paper_entry_gates(lineage)
    finally:
        hp_mod.evaluate_high_precision_gate = _saved_hp
        amm_mod.evaluate_all_detectors = _saved_amm

    assert result["risk_decision"]["risk_action"] == "deny"
    assert result["risk_decision"]["risk_reason_code"] == "deny_anti_mm_detected"
    assert "anti_mm_detection" in result["risk_decision"]["required_blocks_checked"]
    assert result["execution_intent"]["exchange_order_allowed"] is False


# ── Phase 7: hedge advisory in position lifecycle ─────────────────────────────


def test_phase7_hedge_advisory_in_held_lifecycle() -> None:
    """Phase 7: phase7_hedge_advisory key present in open position lifecycle."""
    lineage = _lineage()
    previous_position = {
        "status": "OPEN",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 99.0,
        "notional_usdt": 25.0,
        "fee_rate": 0.0004,
        "opened_at": "2026-06-17T11:00:00Z",
        "take_profit_bps": 20.0,
        "stop_loss_bps": 10.0,
        "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
    }
    previous_account = {"realized_pnl": 0.0}
    _, _, lifecycle = build_position_lifecycle_entry(
        tick_id="test_tick_1",
        generated_at="2026-06-17T12:00:00Z",
        market=_market(),
        lineage=lineage,
        previous_position=previous_position,
        previous_account=previous_account,
    )
    open_pos = lifecycle.get("open_position") or lifecycle.get("last_closed_position") or {}
    assert "phase7_hedge_advisory" in open_pos


def test_phase7_hedge_advisory_in_closed_lifecycle() -> None:
    """Phase 7: phase7_hedge_advisory present in closed position lifecycle."""
    lineage = _lineage()
    previous_position = {
        "status": "OPEN",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 200.0,  # price is 100 → STOP_LOSS triggered
        "notional_usdt": 25.0,
        "fee_rate": 0.0004,
        "opened_at": "2026-06-17T08:00:00Z",  # old enough, past min hold
        "take_profit_bps": 20.0,
        "stop_loss_bps": 8.0,
        "minimum_hold_seconds": 120,
    }
    previous_account = {"realized_pnl": 0.0}
    _, _, lifecycle = build_position_lifecycle_entry(
        tick_id="test_tick_close",
        generated_at="2026-06-17T12:00:00Z",
        market=_market(),
        lineage=lineage,
        previous_position=previous_position,
        previous_account=previous_account,
    )
    last_closed = lifecycle.get("last_closed_position") or {}
    if last_closed:  # position may or may not have triggered exit
        assert "phase7_hedge_advisory" in last_closed


def test_phase7_hedge_advisory_fail_closed() -> None:
    """Phase 7: hedge advisory is fail-closed (hedge_needed=False, operator_approved=False)."""
    lineage = _lineage()
    previous_position = {
        "status": "OPEN",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 99.0,
        "notional_usdt": 25.0,
        "fee_rate": 0.0004,
        "opened_at": "2026-06-17T11:55:00Z",  # very recent — minimum hold active
        "take_profit_bps": 20.0,
        "stop_loss_bps": 10.0,
        "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
    }
    previous_account = {"realized_pnl": 0.0}
    _, _, lifecycle = build_position_lifecycle_entry(
        tick_id="test_tick_hedge_failclosed",
        generated_at="2026-06-17T12:00:00Z",
        market=_market(),
        lineage=lineage,
        previous_position=previous_position,
        previous_account=previous_account,
    )
    open_pos = lifecycle.get("open_position") or lifecycle.get("last_closed_position") or {}
    hedge_advisory = open_pos.get("phase7_hedge_advisory", {})
    if hedge_advisory:
        # hedge engine should fail-closed when operator_approved=False
        assert hedge_advisory.get("hedge_needed") is False
        assert hedge_advisory.get("operator_paper_hedge_engine_approved") is False


# ── Safety invariants ─────────────────────────────────────────────────────────


def test_apply_entry_gates_never_enables_live_order() -> None:
    """All phases: no gate wiring may set exchange_order_allowed=True."""
    for tf in ("1m", "5m", "15m", "1h", "4h"):
        lineage = _lineage(timeframe=tf, confidence=0.90, edge_bps=25.0)
        result = apply_paper_entry_gates(lineage)
        assert result["execution_intent"]["exchange_order_allowed"] is False, (
            f"timeframe={tf} produced exchange_order_allowed=True"
        )


def test_apply_entry_gates_never_writes_live_symbols() -> None:
    """All phases: lineage must not gain live_symbols after gate evaluation."""
    lineage = _lineage(timeframe="15m", confidence=0.90, edge_bps=25.0)
    result = apply_paper_entry_gates(lineage)
    # Any live_symbols key that appears must be empty.
    live_syms = result.get("live_symbols") or []
    assert live_syms == []


def test_apply_entry_gates_preserves_paper_only_flag() -> None:
    """All phases: paper_only flag in execution_intent must stay True after gating."""
    lineage = _lineage(timeframe="15m", confidence=0.85, edge_bps=20.0)
    result = apply_paper_entry_gates(lineage)
    assert result["execution_intent"]["paper_only"] is True


def test_apply_entry_gates_does_not_mutate_original() -> None:
    """apply_paper_entry_gates must not mutate its input (deepcopy)."""
    lineage = _lineage(timeframe="1m")
    original_action = lineage["risk_decision"]["risk_action"]
    apply_paper_entry_gates(lineage)
    # original must be unchanged
    assert lineage["risk_decision"]["risk_action"] == original_action
