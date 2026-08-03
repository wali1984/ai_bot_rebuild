"""Phase 2/3/4 gate tests.

Phase 2: feature family completeness gate blocks on missing critical families.
Phase 3: dynamic outcome-memory entry gate replaces static frozensets.
Phase 4: stricter high-precision gate thresholds enforced.

All tests are pure unit tests with no Redis or external I/O.
"""
from __future__ import annotations

import json
import sys
sys.path.insert(0, "")

import pytest

from v2.backend.app.services.paper_trade_management.feature_family_classifier import (
    CRITICAL_FEATURE_FAMILIES,
    HARD_CRITICAL_FAMILIES,
    classify_feature_families,
    classify_families_from_prediction,
    feature_family_coverage_summary,
)
from v2.backend.app.services.paper_trade_management.high_precision_gate import (
    HighPrecisionGateConfig,
    evaluate_high_precision_gate,
)
from v2.backend.app.services.paper_trade_management.entry_gate import (
    PaperEntryGateConfig,
    evaluate_entry_gate,
)
from v2.backend.app.services.paper_trade_management.outcome_memory import (
    OutcomeMemoryBucket,
    OutcomeMemoryThresholds,
    evaluate_outcome_memory_bucket,
    load_outcome_memory_bucket,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _all_critical_features() -> list[str]:
    """Minimal feature_names set covering all 12 critical families."""
    return [
        "mark_price", "open", "high", "low", "close",
        "volume", "atr",
        "ob_best_bid", "ob_spread_bps", "ob_imbalance",
        "funding_rate", "open_interest",
        "long_short_ratio", "taker_buy_ratio",
        "nearest_liquidation_level_above", "liquidation_cascade_risk",
        "depth_vs_tape_divergence",
        "paper_position_present",
        "surf_score",
    ]


def _all_critical_gate_kwargs() -> dict:
    return dict(
        action="long",
        confidence_calibrated=0.85,
        expected_move_after_cost_bps=20.0,
        data_coverage_pct=90.0,
        market_state_integrity_score=85.0,
        agreeing_timeframe_count=3,
        orderbook_imbalance_aligned=0.15,
        outcome_bucket_degraded=False,
        present_feature_families=set(_all_critical_features()),
        config=HighPrecisionGateConfig(
            require_multi_tf_agreement=True,
            require_orderbook_confirmation=True,
        ),
    )


# ── Phase 2: Feature family classifier ────────────────────────────────────────


def test_classify_all_critical_families_present() -> None:
    present, missing = classify_feature_families(feature_names=_all_critical_features())
    for family in CRITICAL_FEATURE_FAMILIES:
        assert family in present, f"Expected {family!r} in present"
    assert len(missing & set(CRITICAL_FEATURE_FAMILIES)) == 0


def test_classify_missing_liquidation_family() -> None:
    names = [f for f in _all_critical_features()
             if not any(f.startswith(m) for m in (
                 "nearest_liquidation", "liquidation_cascade", "liquidation_pressure",
                 "liquidation_count", "liquidity_zone", "distance_to_liquidity",
             ))]
    present, missing = classify_feature_families(feature_names=names)
    assert "liquidation_clusters" in missing


def test_classify_missing_public_intel_family() -> None:
    names = [f for f in _all_critical_features() if f not in ("surf_score",)]
    present, missing = classify_feature_families(feature_names=names)
    assert "public_intel" in missing


def test_classify_missing_sweep_spoof_wall_family() -> None:
    names = [f for f in _all_critical_features() if f not in ("depth_vs_tape_divergence",)]
    present, missing = classify_feature_families(feature_names=names)
    assert "sweep_spoof_wall" in missing


def test_classify_families_from_prediction_btcusdt() -> None:
    """Reproduces the BTCUSDT:1m prediction feature set from 2026-06-17 audit."""
    prediction = {
        "feature_names": [
            "last_price", "mark_price", "index_price", "basis_pct", "funding_rate",
            "open_interest", "oi_change_pct", "long_short_ratio", "long_account_ratio",
            "short_account_ratio", "quote_volume", "volume", "volatility", "volatility_pct",
            "open", "high", "low", "close", "num_trades", "taker_buy_base_vol",
            "taker_buy_quote_vol", "taker_sell_base_vol", "taker_sell_quote_vol",
            "taker_buy_ratio", "taker_sell_ratio", "ob_best_bid", "ob_best_ask",
            "ob_mid_price", "ob_spread_bps", "ob_imbalance",
        ],
        "missing_feature_names": [
            "depth_vs_tape_divergence", "nearest_liquidation_level_above",
            "nearest_liquidation_level_below", "liquidation_cascade_risk",
            "liquidation_pressure_direction", "liquidity_zone_above",
            "liquidity_zone_below", "distance_to_liquidity_zone_bps",
            "coinapi_wsds_tape_imbalance", "tape_imbalance", "order_flow_imbalance",
            "surf_score",
            "liquidation_count_5m", "paper_position_present", "paper_unrealized_bps",
            "risk_recent_allow_rate", "orchestrator_recent_allow_rate",
        ],
    }
    present, missing = classify_families_from_prediction(prediction)
    # These critical families ARE present in BTCUSDT 1m
    for family in ("mark_price", "candles", "volume", "atr", "orderbook", "oi_funding", "long_short_ratio"):
        assert family in present, f"{family!r} should be present in BTCUSDT 1m"
    # These critical families are MISSING
    for family in ("liquidation_clusters", "sweep_spoof_wall", "public_intel", "paper_context"):
        assert family in missing, f"{family!r} should be missing in BTCUSDT 1m"


def test_coverage_summary_not_all_critical() -> None:
    names = _all_critical_features()[:5]  # only mark_price/candles
    present, missing = classify_feature_families(feature_names=names)
    summary = feature_family_coverage_summary(present, missing)
    assert summary["all_critical_present"] is False
    assert len(summary["critical_families_missing"]) > 0


# ── Phase 2: High-precision gate blocks on missing families ───────────────────


def test_gate_blocks_when_missing_liquidation_clusters() -> None:
    kwargs = _all_critical_gate_kwargs()
    # Remove liquidation-related features
    present = {f for f in kwargs["present_feature_families"]
               if f not in ("nearest_liquidation_level_above", "liquidation_cascade_risk")}
    # Liquidation clusters family still absent
    present.discard("liquidation_clusters")
    kwargs["present_feature_families"] = present
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("MISSING_FEATURE_FAMILIES" in r for r in result["reasons"])
    assert "liquidation_clusters" in " ".join(result["reasons"])


def test_gate_blocks_when_missing_public_intel() -> None:
    kwargs = _all_critical_gate_kwargs()
    present = kwargs["present_feature_families"] - {"surf_score"}
    present.discard("public_intel")
    kwargs["present_feature_families"] = present
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert "public_intel" in " ".join(result["reasons"])


def test_gate_passes_with_all_critical_families() -> None:
    kwargs = _all_critical_gate_kwargs()
    # Build a present set that includes family labels (as the classifier would produce)
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is True, f"Expected allow, got reasons: {result['reasons']}"


# ── Phase 4: Stricter thresholds ──────────────────────────────────────────────


def test_gate_default_confidence_is_0_75() -> None:
    cfg = HighPrecisionGateConfig()
    assert cfg.min_confidence == 0.75


def test_gate_default_edge_is_15_bps() -> None:
    cfg = HighPrecisionGateConfig()
    assert cfg.min_edge_bps == 15.0


def test_gate_default_coverage_is_85_pct() -> None:
    cfg = HighPrecisionGateConfig()
    assert cfg.min_data_coverage_pct == 85.0


def test_gate_default_requires_multi_tf_agreement() -> None:
    cfg = HighPrecisionGateConfig()
    assert cfg.require_multi_tf_agreement is True


def test_gate_default_requires_orderbook_confirmation() -> None:
    cfg = HighPrecisionGateConfig()
    assert cfg.require_orderbook_confirmation is True


def test_gate_blocks_at_old_permissive_confidence_0_60() -> None:
    """Old threshold 0.60 no longer passes the new gate at 0.75."""
    kwargs = _all_critical_gate_kwargs()
    kwargs["confidence_calibrated"] = 0.62
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("CONFIDENCE_BELOW_THRESHOLD" in r for r in result["reasons"])


def test_gate_blocks_at_old_permissive_edge_8_bps() -> None:
    """Old threshold 8bps no longer passes the new gate at 15bps."""
    kwargs = _all_critical_gate_kwargs()
    kwargs["expected_move_after_cost_bps"] = 10.0
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("EDGE_BELOW_THRESHOLD" in r for r in result["reasons"])


def test_gate_blocks_insufficient_multi_tf_agreement() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["agreeing_timeframe_count"] = 1
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("MULTI_TF_AGREEMENT" in r for r in result["reasons"])


def test_gate_blocks_missing_multi_tf_argument() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["agreeing_timeframe_count"] = None
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("MULTI_TF_AGREEMENT_NOT_PROVIDED" in r for r in result["reasons"])


def test_gate_blocks_orderbook_imbalance_not_provided() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["orderbook_imbalance_aligned"] = None
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("ORDERBOOK_IMBALANCE_NOT_PROVIDED" in r for r in result["reasons"])


def test_gate_blocks_on_degraded_outcome_bucket() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["outcome_bucket_degraded"] = True
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("OUTCOME_BUCKET_DEGRADED" in r for r in result["reasons"])


def test_gate_blocks_below_85_pct_coverage() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["data_coverage_pct"] = 77.0  # current BTCUSDT level
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["allow"] is False
    assert any("COVERAGE_BELOW_THRESHOLD" in r for r in result["reasons"])


def test_gate_places_no_real_order() -> None:
    kwargs = _all_critical_gate_kwargs()
    kwargs["present_feature_families"] = set(CRITICAL_FEATURE_FAMILIES)
    result = evaluate_high_precision_gate(**kwargs)
    assert result["places_real_order"] is False
    assert result["live_gate"] == "blocked_human_only"


# ── Phase 3: Outcome-memory entry gate ────────────────────────────────────────


def test_outcome_memory_blocks_zero_win_rate_bucket() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="BCHUSDT", timeframe="15m",
        trade_count=50, rolling_win_rate=0.0,
        drawdown_contribution_usd=-8.0,
    )
    result = evaluate_outcome_memory_bucket(bucket)
    assert result["blocked"] is True
    assert any("WIN_RATE_DEGRADED" in r for r in result["reasons"])


def test_outcome_memory_blocks_high_slippage_failure() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="ETHUSDT", timeframe="1h",
        trade_count=30, rolling_win_rate=0.50,
        slippage_failure_rate=0.55,
    )
    result = evaluate_outcome_memory_bucket(bucket)
    assert result["blocked"] is True
    assert any("SLIPPAGE_FAILURE_RATE_HIGH" in r for r in result["reasons"])


def test_outcome_memory_insufficient_sample_allows_through() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="NEWCOINUSDT", timeframe="1h",
        trade_count=5, rolling_win_rate=0.0,  # bad WR but tiny sample
    )
    result = evaluate_outcome_memory_bucket(bucket)
    assert result["allowed"] is True
    assert result["source"] == "INSUFFICIENT_SAMPLE_CURRENT_OUTCOME_MEMORY"


def test_outcome_memory_lifetime_loss_dollars_are_not_a_standalone_block() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="XYZUSDT", timeframe="4h",
        trade_count=25, rolling_win_rate=0.60,
        drawdown_contribution_usd=-15.0,
        max_drawdown_bps=20.0,
        drawdown_evidence_policy=(
            "ROLLING_PEAK_TO_TROUGH_DIAGNOSTIC_NO_LIFETIME_USD_HARD_BLOCK"
        ),
    )
    result = evaluate_outcome_memory_bucket(bucket)
    assert result["allowed"] is True
    assert result["max_drawdown_bps"] == 20.0
    assert not any("DRAWDOWN_EXCEEDED" in r for r in result["reasons"])


def test_outcome_memory_blocks_negative_rolling_ev() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="XYZUSDT", timeframe="4h",
        trade_count=25, rolling_win_rate=0.60,
        rolling_ev_bps=-8.0,
        drawdown_contribution_usd=-2.0,
    )
    result = evaluate_outcome_memory_bucket(bucket)
    assert result["blocked"] is True
    assert any("ROLLING_EV_DEGRADED" in r for r in result["reasons"])


def test_entry_gate_does_not_block_symbol_from_static_fallback() -> None:
    """Static soak evidence is advisory only; current outcome memory must block."""
    bucket = load_outcome_memory_bucket("BCHUSDT", "15m", redis_client=None)
    assert bucket.degraded is False
    assert bucket.data_source == "NO_CURRENT_OUTCOME_MEMORY_ADVISORY_BASELINE"
    assert bucket.baseline_advisory_reasons
    result = evaluate_entry_gate(
        symbol="BCHUSDT", timeframe="15m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
    )
    assert result["allowed"] is True
    assert not any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_does_not_block_timeframe_from_static_fallback() -> None:
    """1m/5m are eligible by default; outcome memory handles dynamic quarantine."""
    bucket = load_outcome_memory_bucket("BTCUSDT", "1m", redis_client=None)
    assert bucket.degraded is False
    assert bucket.baseline_advisory_reasons
    result = evaluate_entry_gate(
        symbol="BTCUSDT", timeframe="1m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
    )
    assert result["allowed"] is True
    assert not any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_blocks_current_degraded_outcome_memory() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="BCHUSDT",
        timeframe="15m",
        trade_count=40,
        rolling_win_rate=0.10,
        rolling_ev_bps=-12.0,
        data_source="REDIS",
    )
    result = evaluate_entry_gate(
        symbol="BCHUSDT",
        timeframe="15m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
    )
    assert result["allowed"] is False
    assert any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_blocks_degraded_timeframe_aggregate_when_exact_bucket_missing() -> None:
    class RedisStub:
        def get(self, key: str) -> str | None:
            if key == "v2:paper:outcome_memory:__ALL__:5m":
                return json.dumps({
                    "symbol": "__ALL__",
                    "timeframe": "5m",
                    "trade_count": 30,
                    "rolling_win_rate": 0.20,
                    "rolling_ev_bps": -12.0,
                    "drawdown_contribution_usd": -18.0,
                    "degraded": True,
                    "block_reason": "WIN_RATE_DEGRADED:20.00%<35.00%",
                    "data_source": "REDIS",
                    "trust_evidence_status": "TRUSTED_OUTCOME_MEMORY",
                    "outcome_memory_can_block_entries": True,
                    "trusted_trade_count": 30,
                    "untrusted_trade_count": 0,
                })
            return None

    result = evaluate_entry_gate(
        symbol="NEWCOINUSDT",
        timeframe="5m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        redis_client=RedisStub(),
    )
    assert result["allowed"] is False
    assert result["outcome_memory_source"] == "REDIS_TIMEFRAME_AGGREGATE"
    assert any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_treats_legacy_degraded_timeframe_aggregate_as_advisory() -> None:
    class RedisStub:
        def get(self, key: str) -> str | None:
            if key == "v2:paper:outcome_memory:__ALL__:5m":
                return json.dumps({
                    "symbol": "__ALL__",
                    "timeframe": "5m",
                    "trade_count": 30,
                    "rolling_win_rate": 0.20,
                    "rolling_ev_bps": -12.0,
                    "drawdown_contribution_usd": -18.0,
                    "degraded": True,
                    "block_reason": "WIN_RATE_DEGRADED:20.00%<35.00%",
                    "data_source": "REDIS",
                })
            return None

    result = evaluate_entry_gate(
        symbol="NEWCOINUSDT",
        timeframe="5m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        redis_client=RedisStub(),
    )

    assert result["allowed"] is True
    assert result["outcome_memory_source"] == "REDIS_TIMEFRAME_AGGREGATE"
    assert result["outcome_memory_result"]["trust_evidence_status"] == "LEGACY_UNVERIFIED_OUTCOME_MEMORY"
    assert not any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_allows_healthy_bucket() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="BTCUSDT", timeframe="15m",
        trade_count=50, rolling_win_rate=0.65,
        drawdown_contribution_usd=10.0,
        data_source="REDIS",
    )
    result = evaluate_entry_gate(
        symbol="BTCUSDT", timeframe="15m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
    )
    assert result["allowed"] is True


def test_entry_gate_allows_reduce_size_mode_by_default() -> None:
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="15m",
        strategy_mode="reduce_size_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=15.0,
        redis_client=None,
    )

    assert result["allowed"] is True
    assert result["reasons"] == []


def test_entry_gate_allows_short_when_after_cost_move_is_down() -> None:
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="15m",
        side="short",
        strategy_mode="mean_reversion_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=-15.0,
        redis_client=None,
    )

    assert result["allowed"] is True
    assert result["reasons"] == []


def test_entry_gate_blocks_wrong_signed_expected_move_for_side() -> None:
    short_result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="15m",
        side="short",
        strategy_mode="mean_reversion_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=15.0,
        redis_client=None,
    )
    long_result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="15m",
        side="long",
        strategy_mode="trend_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=-15.0,
        redis_client=None,
    )

    assert short_result["allowed"] is False
    assert "EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:short:15.0bps" in short_result["reasons"]
    assert long_result["allowed"] is False
    assert "EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:long:-15.0bps" in long_result["reasons"]


def test_entry_gate_operator_config_can_block_strategy_mode() -> None:
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="15m",
        strategy_mode="reduce_size_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=15.0,
        redis_client=None,
        config=PaperEntryGateConfig(blocked_strategy_modes=frozenset({"reduce_size_mode"})),
    )

    assert result["allowed"] is False
    assert "STRATEGY_MODE_BLOCKED:reduce_size_mode" in result["reasons"]


def test_entry_gate_records_outcome_memory_source() -> None:
    bucket = OutcomeMemoryBucket(
        symbol="BTCUSDT", timeframe="15m",
        trade_count=50, rolling_win_rate=0.65,
        data_source="REDIS",
    )
    result = evaluate_entry_gate(
        symbol="BTCUSDT", timeframe="15m",
        strategy_mode=None, confidence_calibrated=0.9,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
    )
    assert result["outcome_memory_source"] == "REDIS"


def test_entry_gate_no_static_frozensets_in_gate_code() -> None:
    """Static symbol frozensets must not drive blocks; only operator exclusion and outcome-memory."""
    # A soak-blocked symbol with a healthy Redis bucket should be ALLOWED
    bucket = OutcomeMemoryBucket(
        symbol="BCHUSDT", timeframe="15m",
        trade_count=100, rolling_win_rate=0.70,
        drawdown_contribution_usd=5.0,
        data_source="REDIS",
    )
    result = evaluate_entry_gate(
        symbol="BCHUSDT", timeframe="15m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        outcome_memory_bucket=bucket,
        config=PaperEntryGateConfig(symbol_exclusion_list=frozenset()),
    )
    # Healthy Redis bucket should override static soak block
    assert result["allowed"] is True


def test_entry_gate_places_no_real_order() -> None:
    result = evaluate_entry_gate(
        symbol="BTCUSDT", timeframe="15m",
        strategy_mode=None,
        confidence_calibrated=0.9,
        expected_move_after_cost_bps=20.0,
        redis_client=None,
    )
    assert result["places_real_order"] is False


# ── Phase 2 inference mode: feature_names absent, missing_feature_names present ─


def _production_missing_features() -> list[str]:
    """Represents the 40-feature missing set from live 2026-06-17 production rows."""
    return [
        "depth_vs_tape_divergence",
        "nearest_liquidation_level_above", "nearest_liquidation_level_below",
        "liquidation_cascade_risk", "liquidation_pressure_direction",
        "liquidity_zone_above", "liquidity_zone_below", "distance_to_liquidity_zone_bps",
        "liquidation_count_5m",
        "coinapi_wsds_tape_imbalance", "tape_imbalance", "order_flow_imbalance",
        "surf_score",
        "paper_position_present", "paper_unrealized_bps",
        "risk_recent_allow_rate", "orchestrator_recent_allow_rate",
    ]


def test_inference_mode_hard_critical_families_present() -> None:
    """Hard-critical families (mark_price/candles/volume/atr/orderbook/oi_funding/long_short)
    must be PRESENT when their features are not in missing_feature_names."""
    present, missing = classify_feature_families(
        feature_names=None,
        missing_feature_names=_production_missing_features(),
    )
    for family in ("mark_price", "candles", "volume", "atr", "orderbook", "oi_funding", "long_short_ratio"):
        assert family in present, f"Hard-critical {family!r} should be present_inferred"


def test_inference_mode_fully_absent_families_missing() -> None:
    """Families whose ALL members are in missing_feature_names must be MISSING."""
    present, missing = classify_feature_families(
        feature_names=None,
        missing_feature_names=_production_missing_features(),
    )
    for family in ("liquidation_clusters", "public_intel", "paper_context"):
        assert family in missing, f"Fully-absent {family!r} should be missing_confirmed"


def test_inference_mode_partial_family_counted_as_present() -> None:
    """microstructure and sweep_spoof_wall have some members NOT in missing_feature_names;
    they must be counted as present_inferred (conservative gate)."""
    present, missing = classify_feature_families(
        feature_names=None,
        missing_feature_names=_production_missing_features(),
    )
    # taker_buy_ratio/taker_sell_ratio are not missing → microstructure = present
    assert "microstructure" in present
    # sweep_up_detected etc. are not missing → sweep_spoof_wall = present
    assert "sweep_spoof_wall" in present


def test_inference_mode_empty_missing_list_all_present() -> None:
    """When both feature_names and missing_feature_names are empty, no family can be
    confirmed missing — all families are considered present_inferred."""
    present, missing = classify_feature_families(feature_names=None, missing_feature_names=[])
    assert len(missing) == 0
    assert len(present) == len(
        __import__(
            "v2.backend.app.services.paper_trade_management.feature_family_classifier",
            fromlist=["FAMILY_FEATURE_PREFIXES"],
        ).FAMILY_FEATURE_PREFIXES
    )


def test_inference_mode_coverage_summary_records_mode() -> None:
    """coverage_summary must record classification_mode=inference_missing_names_only."""
    present, missing = classify_feature_families(
        feature_names=None,
        missing_feature_names=_production_missing_features(),
    )
    summary = feature_family_coverage_summary(
        present, missing, classification_mode="inference_missing_names_only"
    )
    assert summary["classification_mode"] == "inference_missing_names_only"


def test_gate_inference_mode_blocks_fully_absent_critical_family() -> None:
    """High-precision gate must block via prediction dict when feature_names=[] and
    a critical family is fully absent from missing_feature_names inference."""
    prediction = {
        "feature_names": [],
        "missing_feature_names": _production_missing_features(),
    }
    result = evaluate_high_precision_gate(
        action="long",
        confidence_calibrated=0.85,
        expected_move_after_cost_bps=20.0,
        data_coverage_pct=90.0,
        market_state_integrity_score=85.0,
        agreeing_timeframe_count=3,
        orderbook_imbalance_aligned=0.15,
        prediction=prediction,
        config=HighPrecisionGateConfig(
            require_multi_tf_agreement=True,
            require_orderbook_confirmation=True,
        ),
    )
    assert result["allow"] is False
    reasons_str = " ".join(result["reasons"])
    assert "MISSING_FEATURE_FAMILIES" in reasons_str
    # All three fully-absent critical families must appear in block reasons
    for family in ("liquidation_clusters", "paper_context", "public_intel"):
        assert family in reasons_str, f"Expected {family!r} in block reasons"


def test_gate_inference_mode_does_not_block_hard_critical_when_present() -> None:
    """Hard-critical families (mark_price, candles, etc.) must NOT appear in
    MISSING_FEATURE_FAMILIES block reason when they are present_inferred."""
    prediction = {
        "feature_names": [],
        "missing_feature_names": _production_missing_features(),
    }
    result = evaluate_high_precision_gate(
        action="long",
        confidence_calibrated=0.85,
        expected_move_after_cost_bps=20.0,
        data_coverage_pct=90.0,
        market_state_integrity_score=85.0,
        agreeing_timeframe_count=3,
        orderbook_imbalance_aligned=0.15,
        prediction=prediction,
        config=HighPrecisionGateConfig(
            require_multi_tf_agreement=True,
            require_orderbook_confirmation=True,
        ),
    )
    reasons_str = " ".join(result["reasons"])
    for family in ("mark_price", "candles", "volume", "atr", "orderbook", "oi_funding", "long_short_ratio"):
        assert family not in reasons_str, f"Hard-critical {family!r} must not appear as missing"


def test_gate_inference_records_classification_mode_in_coverage() -> None:
    """When gate classifies via inference, feature_coverage must record the mode."""
    prediction = {
        "feature_names": [],
        "missing_feature_names": _production_missing_features(),
    }
    result = evaluate_high_precision_gate(
        action="long",
        confidence_calibrated=0.85,
        expected_move_after_cost_bps=20.0,
        data_coverage_pct=90.0,
        market_state_integrity_score=85.0,
        agreeing_timeframe_count=3,
        orderbook_imbalance_aligned=0.15,
        prediction=prediction,
        config=HighPrecisionGateConfig(
            require_multi_tf_agreement=True,
            require_orderbook_confirmation=True,
        ),
    )
    assert result["feature_coverage"].get("classification_mode") == "inference_missing_names_only"


def test_entry_gate_fresh_degraded_aggregate_still_blocks() -> None:
    import datetime as _dt

    _now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    class RedisStub:
        def get(self, key: str) -> str | None:
            if key == "v2:paper:outcome_memory:__ALL__:5m":
                return json.dumps({
                    "symbol": "__ALL__",
                    "timeframe": "5m",
                    "trade_count": 30,
                    "rolling_win_rate": 0.20,
                    "rolling_ev_bps": -12.0,
                    "drawdown_contribution_usd": -18.0,
                    "degraded": True,
                    "block_reason": "WIN_RATE_DEGRADED:20.00%<35.00%",
                    "data_source": "REDIS",
                    "trust_evidence_status": "TRUSTED_OUTCOME_MEMORY",
                    "outcome_memory_can_block_entries": True,
                    "trusted_trade_count": 30,
                    "untrusted_trade_count": 0,
                    "last_outcome_available_at": _now,
                    "last_updated": _now,
                })
            return None

    result = evaluate_entry_gate(
        symbol="NEWCOINUSDT",
        timeframe="5m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        redis_client=RedisStub(),
    )
    assert result["allowed"] is False
    assert any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])


def test_entry_gate_stale_degraded_aggregate_decays_to_advisory() -> None:
    """Evidence-cannot-refresh valve (2026-07-17): a degraded timeframe

    aggregate whose last outcome is older than 90 minutes must stop
    hard-blocking — its own blocking prevents the outcomes that would roll
    its window. The stale block decays to an annotated advisory and re-arms
    on any fresh outcome.
    """
    import datetime as _dt

    _stale = (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _processed_now = _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    class RedisStub:
        def get(self, key: str) -> str | None:
            if key == "v2:paper:outcome_memory:__ALL__:5m":
                return json.dumps({
                    "symbol": "__ALL__",
                    "timeframe": "5m",
                    "trade_count": 30,
                    "rolling_win_rate": 0.20,
                    "rolling_ev_bps": -12.0,
                    "drawdown_contribution_usd": -18.0,
                    "degraded": True,
                    "block_reason": "WIN_RATE_DEGRADED:20.00%<35.00%",
                    "data_source": "REDIS",
                    "trust_evidence_status": "TRUSTED_OUTCOME_MEMORY",
                    "outcome_memory_can_block_entries": True,
                    "trusted_trade_count": 30,
                    "untrusted_trade_count": 0,
                    "last_outcome_available_at": _stale,
                    "last_updated": _processed_now,
                })
            return None

    result = evaluate_entry_gate(
        symbol="NEWCOINUSDT",
        timeframe="5m",
        strategy_mode=None,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=20.0,
        redis_client=RedisStub(),
    )
    assert result["allowed"] is True
    assert not any("OUTCOME_MEMORY_BLOCK" in r for r in result["reasons"])
