"""Phase 9 — Anti-market-maker detector tests.

Validates all 6 detectors:
 1. sweep_up_down: blocks entry + accelerates exit on detected sweep
 2. spoof_wall_pull: blocks entry + reduces size on high spoof_score
 3. liquidity_hunt: blocks entry on high liquidation count or proximity
 4. depth_tape_divergence: blocks entry when ob_imbalance vs taker flow diverge
 5. toxic_flow: blocks entry + reduces size on high toxicity_proxy
 6. stop_run_risk: blocks entry + accelerates exit on multiple stop-run signs

Also validates composite evaluate_all_detectors() combining actions correctly.
"""
from __future__ import annotations

import pytest

from app.services.paper_trade_management.anti_market_maker_detector import (
    ACTION_ENTRY_BLOCK,
    ACTION_EXIT_ACCELERATE,
    ACTION_SIZE_REDUCE,
    detect_depth_tape_divergence,
    detect_liquidity_hunt,
    detect_spoof_wall_pull,
    detect_stop_run_risk,
    detect_sweep,
    detect_toxic_flow,
    evaluate_all_detectors,
)


# ── Detector 1: Sweep ─────────────────────────────────────────────────────────

def test_sweep_detected_from_feature_flag() -> None:
    result = detect_sweep(price_change_bps=None, sweep_up_detected=True)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions
    assert ACTION_EXIT_ACCELERATE in result.actions


def test_sweep_detected_from_price_and_volume() -> None:
    result = detect_sweep(price_change_bps=80.0, volume_spike_ratio=4.0)
    assert result.detected is True


def test_sweep_not_detected_without_volume_spike() -> None:
    result = detect_sweep(price_change_bps=80.0, volume_spike_ratio=1.5)
    # Price is above threshold but volume spike not confirmed
    assert result.detected is False


def test_sweep_not_detected_with_no_data() -> None:
    result = detect_sweep(price_change_bps=None, sweep_up_detected=None)
    assert result.detected is False
    assert result.reason == "INSUFFICIENT_DATA"


def test_sweep_down_detected() -> None:
    result = detect_sweep(price_change_bps=None, sweep_down_detected=True)
    assert result.detected is True


# ── Detector 2: Spoof / Wall Pull ────────────────────────────────────────────

def test_spoof_detected_from_flag() -> None:
    result = detect_spoof_wall_pull(spoof_detected=True)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions


def test_spoof_detected_from_high_score() -> None:
    result = detect_spoof_wall_pull(spoof_score=0.85)
    assert result.detected is True


def test_spoof_not_detected_low_score() -> None:
    result = detect_spoof_wall_pull(spoof_score=0.20)
    assert result.detected is False


def test_wall_pull_detected_from_flag() -> None:
    result = detect_spoof_wall_pull(wall_pull_detected=True)
    assert result.detected is True
    assert ACTION_SIZE_REDUCE in result.actions


# ── Detector 3: Liquidity Hunt ────────────────────────────────────────────────

def test_liquidity_hunt_detected_from_flag() -> None:
    result = detect_liquidity_hunt(liquidity_hunt_detected=True)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions


def test_liquidity_hunt_detected_from_high_liquidation_count() -> None:
    result = detect_liquidity_hunt(liquidation_count_5m=10)
    assert result.detected is True


def test_liquidity_hunt_not_detected_low_count() -> None:
    result = detect_liquidity_hunt(liquidation_count_5m=2)
    assert result.detected is False


def test_liquidity_hunt_detected_from_proximity() -> None:
    result = detect_liquidity_hunt(
        mark_price=100_000.0,
        nearest_liquidation_level_above=100_400.0,  # 0.4% away (within 0.5%)
    )
    assert result.detected is True


def test_liquidity_hunt_not_detected_far_from_liquidation() -> None:
    result = detect_liquidity_hunt(
        mark_price=100_000.0,
        nearest_liquidation_level_above=102_000.0,  # 2% away
    )
    assert result.detected is False


# ── Detector 4: Depth/Tape Divergence ────────────────────────────────────────

def test_depth_tape_divergence_from_feature() -> None:
    result = detect_depth_tape_divergence(depth_vs_tape_divergence=0.60)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions


def test_depth_tape_divergence_from_ob_vs_tape() -> None:
    # ob_imbalance=0.6 (bid heavy) but taker_buy_ratio=0.25 (sell pressure) → divergence
    result = detect_depth_tape_divergence(ob_imbalance=0.6, taker_buy_ratio=0.25)
    assert result.detected is True


def test_depth_tape_no_divergence_when_aligned() -> None:
    # ob_imbalance=0.2, taker_buy=0.55 → no divergence
    result = detect_depth_tape_divergence(ob_imbalance=0.2, taker_buy_ratio=0.55)
    assert result.detected is False


def test_depth_tape_no_data_returns_not_detected() -> None:
    result = detect_depth_tape_divergence()
    assert result.detected is False
    assert result.reason == "INSUFFICIENT_DATA"


# ── Detector 5: Toxic Flow ────────────────────────────────────────────────────

def test_toxic_flow_detected_high_proxy() -> None:
    result = detect_toxic_flow(toxicity_proxy=0.80)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions
    assert ACTION_SIZE_REDUCE in result.actions


def test_toxic_flow_not_detected_low_proxy() -> None:
    result = detect_toxic_flow(toxicity_proxy=0.30)
    assert result.detected is False


def test_toxic_flow_detected_from_order_flow_imbalance() -> None:
    result = detect_toxic_flow(order_flow_imbalance=0.75)
    assert result.detected is True


def test_toxic_flow_no_data_returns_not_detected() -> None:
    result = detect_toxic_flow()
    assert result.detected is False
    assert result.reason == "INSUFFICIENT_DATA"


# ── Detector 6: Stop-Run Risk ─────────────────────────────────────────────────

def test_stop_run_detected_from_score() -> None:
    result = detect_stop_run_risk(stop_run_risk_score=0.70)
    assert result.detected is True
    assert ACTION_ENTRY_BLOCK in result.actions
    assert ACTION_EXIT_ACCELERATE in result.actions


def test_stop_run_detected_from_two_signs() -> None:
    result = detect_stop_run_risk(
        recent_wick_ratio=0.80,
        price_touched_round_number=True,
        liquidation_count_1m=1,
    )
    assert result.detected is True


def test_stop_run_not_detected_single_sign() -> None:
    result = detect_stop_run_risk(recent_wick_ratio=0.80)
    assert result.detected is False


def test_stop_run_three_signs_higher_confidence() -> None:
    result = detect_stop_run_risk(
        recent_wick_ratio=0.80,
        price_touched_round_number=True,
        liquidation_count_1m=5,
    )
    assert result.detected is True
    assert result.confidence > 0.6


# ── Composite evaluation ──────────────────────────────────────────────────────

def test_evaluate_all_detectors_entry_block_on_sweep() -> None:
    result = evaluate_all_detectors({"sweep_up_detected": True})
    assert result["any_detected"] is True
    assert result["entry_blocked"] is True
    assert result["exit_accelerated"] is True


def test_evaluate_all_detectors_no_detection_clean_features() -> None:
    result = evaluate_all_detectors({
        "toxicity_proxy": 0.10,
        "ob_imbalance": 0.10,
        "taker_buy_ratio": 0.55,
    })
    assert result["any_detected"] is False
    assert result["entry_blocked"] is False
    assert result["exit_accelerated"] is False


def test_evaluate_all_detectors_has_all_6_detector_keys() -> None:
    result = evaluate_all_detectors({})
    detectors = result["detectors"]
    expected = {
        "sweep_up_down", "spoof_wall_pull", "liquidity_hunt",
        "depth_tape_divergence", "toxic_flow", "stop_run_risk"
    }
    assert set(detectors.keys()) == expected


def test_evaluate_all_detectors_never_mutates_exchange() -> None:
    result = evaluate_all_detectors({"sweep_up_detected": True, "spoof_score": 0.90})
    assert result["mutates_exchange"] is False


def test_evaluate_all_detectors_live_gate_blocked() -> None:
    result = evaluate_all_detectors({})
    assert result["live_gate"] == "blocked_human_only"
