from __future__ import annotations

import fnmatch
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v2.backend.app.cli.v2_a_plus_candidate_inventory import (
    EXPLORATION_MATERIALIZATION_QUEUE_KEY,
    PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY,
    _blocker_class,
    _build_materialization_queue_row,
    _canonical_materialization_no_fill_reason,
    _prequeue_materialization_no_fill_reason,
    _publish_materialization_queue,
    build_inventory,
)
from v2.backend.app.services.paper_exploration import policy as paper_exploration_policy
from v2.backend.app.services.paper_exploration import (
    classify_timestamp_integrity,
    evaluate_paper_risk_controller_exploration,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _past_iso(*, minutes: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _future_iso(*, seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_blocker_class_does_not_default_guardian_or_regime_to_expected_edge() -> None:
    assert _blocker_class("EXPECTED_NET_EDGE_NON_POSITIVE") == "EXPECTED_NET_EDGE_BLOCKER"
    assert _blocker_class("SPREAD_SLIPPAGE_FUNDING_COST_MISSING") == "EXPECTED_NET_EDGE_BLOCKER"
    assert _blocker_class("GUARDIAN_HALTED_OR_MISSING") == "RISK_GATEWAY_BLOCKER"
    assert _blocker_class("ALTDATA_HEDGE_REQUIRED") == "RISK_GATEWAY_BLOCKER"
    assert _blocker_class("BUCKET_EVIDENCE_INSUFFICIENT") == "TRAINER_CONFIDENCE_BLOCKER"
    assert _blocker_class("REGIME_COMPATIBILITY_LOW") == "TRAINER_CONFIDENCE_BLOCKER"
    assert _blocker_class("SHORT_IN_BREAKOUT_TREND_REGIME_REQUIRES_CONFIRMATION") == "TRAINER_CONFIDENCE_BLOCKER"
    assert _blocker_class("FVG_CONFLUENCE_WITHOUT_POSITIVE_AFTER_COST_EDGE") == "EXPECTED_NET_EDGE_BLOCKER"
    assert _blocker_class("FVG_NOT_ALIGNED_WITH_CANDIDATE_SIDE") == "TRAINER_CONFIDENCE_BLOCKER"


def test_materialization_prequeue_bucket_quarantine_reports_canonical_no_fill_reason() -> None:
    exact_reason = _prequeue_materialization_no_fill_reason(
        {
            "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:confidence_regime:0.7-0.8|MICROSTRUCTURE_MOMENTUM": 2,
            "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:side_timeframe:short|4h": 1,
        }
    )

    assert exact_reason == "ALL_CURRENT_ROWS_TRUE_BUCKET_QUARANTINE"
    assert (
        _canonical_materialization_no_fill_reason(exact_reason)
        == "ALL_ROWS_TRUE_BUCKET_QUARANTINE"
    )


class FakeRedis:
    def __init__(self) -> None:
        self.data = {
            "v2:paper:preemptive_edge_control_status": {
                "candidate_count": 2,
                "accepted_count": 1,
            },
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:preemptive_candidate_decision_matrix": {
                "generated_utc": _now_iso(),
                "candidate_count": 2,
                "rows": [
                    {
                        "candidate_id": "cand-good",
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "side": "long",
                        "strategy_id": "trend",
                        "prediction_id": "pred-good",
                        "signal_id": "sig-good",
                        "preemptive_decision_id": "pec-good",
                        "preemptive_decision": "ALLOW",
                        "preemptive_action": "ALLOW_A_PLUS_CANDIDATE",
                        "pre_trade_loss_probability": 0.20,
                        "current_price": 65000.0,
                        "expected_move_after_cost_bps": 12.0,
                        "expected_net_pnl_usd": 3.5,
                        "expected_max_loss_usd": 1.2,
                        "expected_liquidation_buffer_usd": 25.0,
                        "risk_decision": "PASS",
                        "orchestrator_decision": "PASS",
                        "allocator_decision": "ALLOW_WITH_SIZE",
                        "microstructure_trust_state": "TRUSTED",
                        "live_dry_run_packet_complete": True,
                    },
                    {
                        "candidate_id": "cand-blocked",
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "side": "short",
                        "strategy_id": "trend",
                        "prediction_id": "pred-blocked",
                        "signal_id": "sig-blocked",
                        "preemptive_decision_id": "pec-blocked",
                        "preemptive_decision": "NO_TRADE",
                        "preemptive_action": "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
                        "pre_trade_loss_probability": 0.91,
                        "current_price": 3200.0,
                        "expected_move_after_cost_bps": -1.0,
                        "expected_net_pnl_usd": 0.0,
                        "preemptive_block_reasons": ["EXPECTED_EDGE_NON_POSITIVE"],
                    },
                ],
            },
            "v2:prediction:BTCUSDT:1m": _prediction("BTCUSDT", "1m", "pred-good", "hash-good"),
            "v2:prediction:ETHUSDT:5m": _prediction("ETHUSDT", "5m", "pred-blocked", "hash-blocked"),
        }

    def get(self, key: str):
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None

    def set(self, key: str, value: str, ex: int | None = None):
        del ex
        try:
            self.data[key] = json.loads(value)
        except (TypeError, ValueError):
            self.data[key] = value
        return True

    def scan_iter(self, match: str, count: int = 500):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key


class StrategySupplyRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:continuous_edge_guardian:a_grade_execution_gate"] = {
            "status": "ACTIVE",
            "a_grade_new_entries_allowed": True,
            "new_entries_allowed": True,
            "failure_reasons": [],
        }
        self.data["v2:strategy_supply:hypotheses:BTCUSDT:1m"] = {
            "rows": [
                {
                    "hypothesis_id": "hyp-test-positive-usd",
                    "strategy_id": "hyp-test-positive-usd",
                    "strategy_family": "funding_squeeze",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "side": "short",
                    "generated_utc": _now_iso(),
                    "entry_zone": {
                        "price": 65000.0,
                        "source": "binance_usdm_wss_orderbook_top",
                        "available_at": _past_iso(minutes=1),
                    },
                    "reference_notional_usd": 200.0,
                    "expected_gross_pnl_usd": 4.0,
                    "expected_cost_usd": 0.32,
                    "expected_net_pnl_usd": 3.68,
                    "fees_usd": 0.08,
                    "slippage_usd": 0.20,
                    "funding_usd": 0.02,
                    "latency_reserve_usd": 0.02,
                    "expected_max_loss_usd": 1.90,
                    "loss_probability": 0.35,
                    "loss_probability_calibration": {
                        "adjusted_loss_probability": 0.35,
                        "base_loss_probability": 0.42,
                        "penalties": {
                            "microstructure_trust_below_allocator_minimum": 0.02,
                        },
                        "reductions": {
                            "reward_to_risk_margin": 0.09,
                        },
                    },
                    "expected_exit_depth_usd": 25000.0,
                    "exit_feasible": True,
                    "exit_feasibility_score": 0.9,
                    "microstructure_trust_score": 0.91,
                    "trade_tape_confirmation_score": 0.88,
                    "debug_target_move_bps": 20.0,
                    "debug_cost_bps": 1.6,
                    "debug_stop_move_bps": 9.5,
                    "debug_spread_bps": 0.4,
                    "debug_slippage_bps": 1.0,
                    "debug_fee_bps": 0.4,
                    "debug_funding_bps": 0.1,
                    "ta_context": {"atr_bps": 16.0},
                    "microstructure_context": False,
                    "orderbook_context": False,
                    "advanced_indicator_context": {"compression_break": True},
                    "fvg_context": {"valid": True},
                    "liquidity_context": {"sweep_clear": True},
                    "coinglass_context": {"funding_squeeze": True},
                    "moralis_context": {"exchange_flow_confirms": True},
                    "coinank_context": {"liquidation_heatmap_confirms": True},
                    "provider_features_used": ["binance_wss", "coinglass", "moralis", "coinank"],
                    "provider_feature_hashes": {
                        "coinglass": "hash-coinglass",
                        "coinank": "hash-coinank",
                    },
                }
            ]
        }


class StrategySupplyStageRejectedRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:continuous_edge_guardian:a_grade_execution_gate"] = {
            "status": "ACTIVE",
            "a_grade_new_entries_allowed": True,
            "new_entries_allowed": True,
            "failure_reasons": [],
        }
        self.data["v2:strategy_supply:hypotheses:RENDERUSDT:4h"] = {
            "rows": [
                {
                    "hypothesis_id": "hyp-positive-usd-low-trust",
                    "strategy_id": "hyp-positive-usd-low-trust",
                    "strategy_family": "trend_continuation",
                    "symbol": "RENDERUSDT",
                    "timeframe": "4h",
                    "side": "short",
                    "generated_utc": _now_iso(),
                    "why_rejected": "MICROSTRUCTURE_TRUST_BELOW_ALLOCATOR_MINIMUM",
                    "entry_zone": {
                        "price": 3.25,
                        "source": "binance_usdm_wss_orderbook_top",
                        "available_at": _past_iso(minutes=1),
                    },
                    "reference_notional_usd": 200.0,
                    "expected_gross_pnl_usd": 6.0,
                    "expected_cost_usd": 0.20,
                    "expected_net_pnl_usd": 1.25,
                    "fees_usd": 0.08,
                    "slippage_usd": 0.108,
                    "funding_usd": 0.0,
                    "latency_reserve_usd": 0.012,
                    "expected_max_loss_usd": 3.20,
                    "loss_probability": 0.48,
                    "expected_exit_depth_usd": 50000.0,
                    "exit_feasible": True,
                    "exit_feasibility_score": 0.9,
                    "microstructure_trust_score": 0.59,
                    "composite_microstructure_trust_score": 0.59,
                    "market_state_integrity_score": 59.0,
                    "market_state_integrity_minimum_score": 70.0,
                    "market_state_integrity_source": "v2:microstructure:trust_score:RENDERUSDT:1m",
                    "trade_tape_confirmation_score": 0.65,
                    "debug_target_move_bps": 300.0,
                    "debug_cost_bps": 10.0,
                    "debug_stop_move_bps": 160.0,
                    "debug_spread_bps": 0.6,
                    "debug_slippage_bps": 5.4,
                    "debug_fee_bps": 4.0,
                    "debug_funding_bps": 0.0,
                    "debug_atr_bps": 180.0,
                    "ta_context": {"atr_bps": 180.0},
                    "microstructure_context": True,
                    "orderbook_context": True,
                    "advanced_indicator_context": {"trend_continuation": True},
                    "fvg_context": {"valid": True},
                    "liquidity_context": {"sweep_clear": True},
                    "coinglass_context": {"funding_context": True},
                    "coinank_context": {"liquidation_heatmap_confirms": True},
                    "provider_features_used": ["binance_wss", "coinglass", "coinank"],
                    "provider_feature_hashes": {
                        "coinglass": "hash-coinglass-low-trust",
                        "coinank": "hash-coinank-low-trust",
                    },
                }
            ]
        }


class SelectedSideEconomicsRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:paper:preemptive_candidate_decision_matrix"] = {
            "generated_utc": _now_iso(),
            "candidate_count": 1,
            "rows": [
                {
                    "candidate_id": "cand-selected-short-net",
                    "symbol": "ARPAUSDT",
                    "timeframe": "15m",
                    "side": "short",
                    "selected_action": "short",
                    "prediction_id": "pred-selected-short-net",
                    "signal_id": "sig-selected-short-net",
                    "preemptive_decision_id": "pec-selected-short-net",
                    "preemptive_decision": "NO_TRADE",
                    "preemptive_action": "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
                    "pre_trade_loss_probability": 0.20,
                    "current_price": 0.0087,
                    "current_price_can_size_trade": True,
                    "expected_net_pnl_usd": 0.0,
                    "short_expected_net_pnl_usd": 0.42,
                    "short_expected_cost_usd": 0.08,
                    "short_expected_gross_pnl_usd": 0.50,
                    "expected_short_net_edge_bps": 42.0,
                    "expected_move_after_cost_bps": -42.0,
                    "expected_max_loss_usd": 0.20,
                    "expected_liquidation_buffer_usd": 3.0,
                    "risk_decision": "PASS",
                    "orchestrator_decision": "PASS",
                }
            ],
        }
        self.data["v2:prediction:ARPAUSDT:15m"] = _prediction(
            "ARPAUSDT",
            "15m",
            "pred-selected-short-net",
            "hash-selected-short-net",
        )


class PaperExplorationRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:continuous_edge_guardian:a_grade_execution_gate"] = {
            "status": "HALTED_AFTER_PIT_THRESHOLD_MET",
            "a_grade_new_entries_allowed": False,
            "new_entries_allowed": False,
            "failure_reasons": ["GUARDIAN_HALTED_AFTER_PIT_THRESHOLD_MET"],
        }
        self.data["v2:paper:preemptive_candidate_decision_matrix"] = {
            "generated_utc": _now_iso(),
            "candidate_count": 1,
            "rows": [
                {
                    "candidate_id": "cand-paper-explore",
                    "symbol": "SOLUSDT",
                    "timeframe": "5m",
                    "side": "long",
                    "selected_action": "long",
                    "strategy_id": "trend-explore",
                    "prediction_id": "pred-paper-explore",
                    "signal_id": "sig-paper-explore",
                    "preemptive_decision_id": "pec-paper-explore",
                    "preemptive_decision": "NO_TRADE",
                    "preemptive_action": "GUARDIAN_HALTED_AFTER_PIT_THRESHOLD_MET",
                    "pre_trade_loss_probability": 0.24,
                    "current_price": 150.0,
                    "current_price_can_size_trade": True,
                    "expected_move_after_cost_bps": 18.0,
                    "expected_net_pnl_usd": 2.8,
                    "long_expected_net_pnl_usd": 2.8,
                    "long_expected_gross_pnl_usd": 3.2,
                    "long_expected_cost_usd": 0.4,
                    "expected_cost_usd": 0.4,
                    "expected_max_loss_usd": 1.1,
                    "expected_liquidation_buffer_usd": 24.0,
                    "exit_feasible": True,
                    "exit_feasibility_score": 0.86,
                    "microstructure_trust_score": 0.91,
                    "composite_microstructure_trust_score": 0.91,
                    "market_state_integrity_score": 91.0,
                    "trade_tape_confirmation_score": 0.87,
                    "provider_feature_hashes": {"binance": "hash-binance", "coinank": "hash-coinank"},
                    "provider_features_used": ["binance", "coinank"],
                    "bucket_evidence_count": 35,
                    "bucket_profit_factor": 1.3,
                    "risk_decision": "PASS",
                    "risk_decision_id": "risk-paper-explore",
                    "orchestrator_decision": "PASS",
                    "orchestrator_decision_id": "orch-paper-explore",
                    "allocator_decision": "ALLOW_WITH_SIZE",
                    "allocator_decision_id": "alloc-paper-explore",
                    "recommended_leverage": 0.25,
                    "recommended_margin_mode": "isolated_paper",
                }
            ],
        }
        self.data["v2:prediction:SOLUSDT:5m"] = {
            **_prediction("SOLUSDT", "5m", "pred-paper-explore", "hash-paper-explore"),
            "selected_action": "long",
            "action_probabilities": {"hold": 0.08, "long": 0.84, "short": 0.08},
            "confidence_raw": 0.86,
            "confidence_calibrated": 0.84,
        }


class PaperExplorationStaleSourceRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        stale_available_at = _past_iso(minutes=10)
        stale_decision_time = _past_iso(minutes=10)
        stale_feature_cutoff = _past_iso(minutes=11)
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "available_at": stale_available_at,
                "decision_time": stale_decision_time,
                "generated_utc": stale_decision_time,
                "feature_cutoff": stale_feature_cutoff,
            }
        )
        prediction = self.data["v2:prediction:SOLUSDT:5m"]
        prediction.update(
            {
                "available_at": stale_available_at,
                "decision_time": stale_decision_time,
                "generated_at": stale_decision_time,
                "feature_cutoff": stale_feature_cutoff,
            }
        )


class PaperExplorationFutureSourceRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        future_available_at = _future_iso(seconds=30)
        future_decision_time = _future_iso(seconds=30)
        feature_cutoff = _past_iso(minutes=1)
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "available_at": future_available_at,
                "decision_time": future_decision_time,
                "generated_utc": future_decision_time,
                "feature_cutoff": feature_cutoff,
            }
        )
        prediction = self.data["v2:prediction:SOLUSDT:5m"]
        prediction.update(
            {
                "available_at": future_available_at,
                "decision_time": future_decision_time,
                "generated_at": future_decision_time,
                "feature_cutoff": feature_cutoff,
            }
        )


class PaperExplorationMissingDecisionRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:continuous_edge_guardian:a_grade_execution_gate"] = {
            "status": "HALTED_AFTER_PIT_THRESHOLD_MET",
            "a_grade_new_entries_allowed": False,
            "new_entries_allowed": False,
            "failure_reasons": ["GUARDIAN_HALTED_AFTER_PIT_THRESHOLD_MET"],
        }
        self.data["v2:paper:preemptive_candidate_decision_matrix"] = {
            "generated_utc": _now_iso(),
            "candidate_count": 1,
            "rows": [
                {
                    "candidate_id": "cand-missing-risk-orch",
                    "symbol": "LTCUSDT",
                    "timeframe": "15m",
                    "side": "long",
                    "selected_action": "long",
                    "prediction_id": "pred-missing-risk-orch",
                    "signal_id": "sig-missing-risk-orch",
                    "preemptive_decision_id": "pec-missing-risk-orch",
                    "preemptive_decision": "NO_TRADE",
                    "preemptive_action": "GUARDIAN_HALTED_AFTER_PIT_THRESHOLD_MET",
                    "preemptive_block_reasons": [
                        "BUCKET_QUARANTINE_MATCH",
                        "MICROSTRUCTURE_TRUST_FAIL_CLOSED",
                    ],
                    "current_price": 44.2,
                    "current_price_can_size_trade": True,
                    "expected_move_after_cost_bps": 20.0,
                    "expected_net_pnl_usd": 1.1,
                    "long_expected_net_pnl_usd": 1.1,
                    "long_expected_gross_pnl_usd": 1.4,
                    "long_expected_cost_usd": 0.3,
                    "expected_cost_usd": 0.3,
                    "expected_max_loss_usd": 0.5,
                    "expected_liquidation_buffer_usd": 8.0,
                    "exit_feasible": True,
                    "exit_feasibility_score": 0.9,
                    "microstructure_trust_score": 0.59,
                    "composite_microstructure_trust_score": 0.59,
                    "provider_feature_hashes": {"binance": "hash-binance"},
                    "provider_features_used": ["binance"],
                    "bucket_evidence_count": 40,
                    "bucket_profit_factor": 1.2,
                    "allocator_decision": "PASS",
                    "allocator_decision_id": "alloc-missing-risk-orch",
                }
            ],
        }
        self.data["v2:prediction:LTCUSDT:15m"] = {
            **_prediction("LTCUSDT", "15m", "pred-missing-risk-orch", "hash-missing-risk-orch"),
            "selected_action": "long",
            "action_probabilities": {"hold": 0.02, "long": 0.96, "short": 0.02},
            "confidence_raw": 0.96,
            "confidence_calibrated": 0.94,
        }


class PaperExplorationShortUnfavorableRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "candidate_id": "cand-paper-explore-short-unfavorable",
                "symbol": "CRVUSDT",
                "timeframe": "4h",
                "side": "short",
                "selected_action": "short",
                "strategy_id": "trend-short-unfavorable",
                "prediction_id": "pred-paper-explore-short-unfavorable",
                "signal_id": "sig-paper-explore-short-unfavorable",
                "expected_move_after_cost_bps": 256.9,
                "expected_net_pnl_usd": 0.82,
                "long_expected_net_pnl_usd": 0.0,
                "short_expected_net_pnl_usd": 0.82,
                "risk_decision_id": "risk-paper-explore-short-unfavorable",
                "orchestrator_decision_id": "orch-paper-explore-short-unfavorable",
                "allocator_decision_id": "alloc-paper-explore-short-unfavorable",
            }
        )
        self.data.pop("v2:prediction:SOLUSDT:5m", None)
        self.data["v2:prediction:CRVUSDT:4h"] = {
            **_prediction(
                "CRVUSDT",
                "4h",
                "pred-paper-explore-short-unfavorable",
                "hash-paper-explore-short-unfavorable",
            ),
            "selected_action": "short",
            "action_probabilities": {"hold": 0.08, "long": 0.08, "short": 0.84},
            "confidence_raw": 0.86,
            "confidence_calibrated": 0.84,
        }


class PaperExplorationOperatorExcludedRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "candidate_id": "cand-paper-explore-operator-excluded",
                "symbol": "TIAUSDT",
                "timeframe": "1h",
                "side": "long",
                "selected_action": "long",
                "strategy_id": "trend-operator-excluded",
                "prediction_id": "pred-paper-explore-operator-excluded",
                "signal_id": "sig-paper-explore-operator-excluded",
                "expected_move_after_cost_bps": 18.0,
                "expected_net_pnl_usd": 0.82,
                "long_expected_net_pnl_usd": 0.82,
                "short_expected_net_pnl_usd": 0.0,
                "risk_decision_id": "risk-paper-explore-operator-excluded",
                "orchestrator_decision_id": "orch-paper-explore-operator-excluded",
                "allocator_decision_id": "alloc-paper-explore-operator-excluded",
            }
        )
        self.data.pop("v2:prediction:SOLUSDT:5m", None)
        self.data["v2:prediction:TIAUSDT:1h"] = {
            **_prediction(
                "TIAUSDT",
                "1h",
                "pred-paper-explore-operator-excluded",
                "hash-paper-explore-operator-excluded",
            ),
            "selected_action": "long",
            "action_probabilities": {"hold": 0.08, "long": 0.84, "short": 0.08},
            "confidence_raw": 0.86,
            "confidence_calibrated": 0.84,
        }


class PaperExplorationNoTradeStrategyRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "candidate_id": "cand-paper-explore-no-trade-strategy",
                "symbol": "JUPUSDT",
                "timeframe": "4h",
                "side": "long",
                "selected_action": "long",
                "strategy_id": "no_trade_mode",
                "strategy_family": "no_trade_mode",
                "strategy_selected_mode": "no_trade_mode",
                "strategy_router_selected_mode": "no_trade_mode",
                "entry_reason": "no_trade_mode",
                "strategy_regime_labels": ["NO_TRADE"],
                "prediction_id": "pred-paper-explore-no-trade-strategy",
                "signal_id": "sig-paper-explore-no-trade-strategy",
                "expected_move_after_cost_bps": 18.0,
                "expected_net_pnl_usd": 0.82,
                "long_expected_net_pnl_usd": 0.82,
                "short_expected_net_pnl_usd": 0.0,
                "risk_decision_id": "risk-paper-explore-no-trade-strategy",
                "orchestrator_decision_id": "orch-paper-explore-no-trade-strategy",
                "allocator_decision_id": "alloc-paper-explore-no-trade-strategy",
            }
        )
        self.data.pop("v2:prediction:SOLUSDT:5m", None)
        self.data["v2:prediction:JUPUSDT:4h"] = {
            **_prediction(
                "JUPUSDT",
                "4h",
                "pred-paper-explore-no-trade-strategy",
                "hash-paper-explore-no-trade-strategy",
            ),
            "selected_action": "long",
            "action_probabilities": {"hold": 0.08, "long": 0.84, "short": 0.08},
            "confidence_raw": 0.86,
            "confidence_calibrated": 0.84,
        }


class PaperExplorationPerformanceQuarantineRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:paper:performance_circuit_breaker_status"] = {
            "schema_version": "paper_performance_circuit_breaker_status_v1",
            "state": "HALTED_PERFORMANCE",
            "new_entries_allowed": False,
            "block_reasons": [
                "BUCKET_QUARANTINE_ACTIVE",
                "HIGH_CONFIDENCE_LOSS_CLUSTER",
            ],
            "blocked_bucket_keys": ["side_timeframe:long|5m"],
            "bucket_quarantine_status": {
                "negative_bucket_min_count": 2,
                "quarantined_buckets": [
                    {
                        "bucket_key": "side_timeframe:long|5m",
                        "bucket_type": "side_timeframe",
                        "state": "QUARANTINED",
                        "candidate_blocking": True,
                        "block_reasons": [
                            "HIGH_CONFIDENCE_LOSS_RATE_ABOVE_ADAPTIVE_BOUND",
                            "NEGATIVE_PROFIT_FACTOR_SIDE_TIMEFRAME_BUCKET",
                        ],
                        "closed_outcome_count": 3,
                        "profit_factor": 0.0,
                        "notional_weighted_expectancy_bps": -18.5,
                        "high_confidence_loss_rate": 1.0,
                        "high_confidence_loss_count": 3,
                        "high_confidence_outcome_count": 3,
                        "ATR_stop_loss_count": 1,
                    }
                ],
            },
            "recovery_high_confidence_loss_cluster_status": {
                "cluster_detected": True,
                "affected_symbols": ["SOLUSDT"],
                "quarantined_sides": ["long"],
                "quarantined_timeframes": [],
                "quarantined_strategy_modes": [],
            },
        }


class PaperExplorationBroadGlobalHaltRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        self.data["v2:paper:performance_circuit_breaker_status"] = {
            "schema_version": "paper_performance_circuit_breaker_status_v1",
            "state": "HALTED_PERFORMANCE",
            "new_entries_allowed": False,
            "block_reasons": [
                "BUCKET_QUARANTINE_ACTIVE",
                "ROLLING_50_PROFIT_FACTOR_BELOW_1",
            ],
            "blocked_bucket_keys": ["side:long"],
            "recovery_high_confidence_loss_cluster_status": {
                "cluster_detected": True,
                "affected_symbols": [],
                "quarantined_sides": ["long"],
                "quarantined_timeframes": [],
                "quarantined_strategy_modes": [],
            },
        }


class PaperExplorationImmatureConfidenceRegimeHaltRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row["market_regime"] = "MICROSTRUCTURE_MOMENTUM"
        self.data["v2:paper:performance_circuit_breaker_status"] = {
            "schema_version": "paper_performance_circuit_breaker_status_v1",
            "state": "HALTED_PERFORMANCE",
            "new_entries_allowed": False,
            "block_reasons": [
                "BUCKET_QUARANTINE_ACTIVE",
                "ROLLING_50_PROFIT_FACTOR_BELOW_1",
            ],
            "blocked_bucket_keys": [
                "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
            ],
            "bucket_quarantine_status": {
                "negative_bucket_min_count": 2,
                "quarantined_buckets": [
                    {
                        "bucket_key": (
                            "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
                        ),
                        "bucket_type": "confidence_regime",
                        "state": "WATCH_ONLY_SIZE_CAP",
                        "candidate_blocking": True,
                        "block_reasons": ["IMMATURE_CONFIDENCE_REGIME_BUCKET"],
                        "closed_outcome_count": 1,
                        "profit_factor": 0.0,
                        "notional_weighted_expectancy_bps": 2.5,
                    }
                ],
            },
        }


class PaperExplorationMatureConfidenceRegimeHaltRedis(PaperExplorationRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row["market_regime"] = "MICROSTRUCTURE_MOMENTUM"
        self.data["v2:paper:performance_circuit_breaker_status"] = {
            "schema_version": "paper_performance_circuit_breaker_status_v1",
            "state": "HALTED_PERFORMANCE",
            "new_entries_allowed": False,
            "block_reasons": [
                "BUCKET_QUARANTINE_ACTIVE",
                "HIGH_CONFIDENCE_LOSS_CLUSTER",
            ],
            "blocked_bucket_keys": [
                "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
            ],
            "bucket_quarantine_status": {
                "negative_bucket_min_count": 2,
                "quarantined_buckets": [
                    {
                        "bucket_key": (
                            "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
                        ),
                        "bucket_type": "confidence_regime",
                        "state": "QUARANTINED",
                        "candidate_blocking": True,
                        "block_reasons": [
                            "HIGH_CONFIDENCE_LOSS_RATE_ABOVE_ADAPTIVE_BOUND",
                            "NEGATIVE_PROFIT_FACTOR_CONFIDENCE_REGIME_BUCKET",
                        ],
                        "closed_outcome_count": 2,
                        "profit_factor": 0.0,
                        "notional_weighted_expectancy_bps": -20.0,
                    }
                ],
            },
        }


def _prediction(symbol: str, timeframe: str, prediction_id: str, feature_hash: str) -> dict[str, object]:
    feature_names = [
        "funding_rate",
        "open_interest",
        "long_short_ratio",
        "ta_RSI",
        "orderbook_depth_usd",
        "trade_tape_confirmation_score",
        "bullish_fvg_present",
        "nearest_liquidity_above",
    ]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "prediction_id": prediction_id,
        "signal_id": f"sig-{prediction_id}",
        "feature_vector_hash": feature_hash,
        "generated_at": _now_iso(),
        "feature_cutoff": _past_iso(minutes=2),
        "available_at": _past_iso(minutes=1),
        "decision_time": _now_iso(),
        "current_price": 50000.0,
        "expected_move_after_cost_bps": 8.0,
        "confidence_raw": 0.84,
        "confidence_calibrated": 0.8,
        "feature_names": feature_names,
        "source_labels": [
            "v2:features:ta",
            "v2:market:orderbook",
            "v2:market:liquidation_levels",
            "v2:market:fvg",
        ],
        "entry_feature_snapshot": {
            "feature_cutoff": _past_iso(minutes=2),
            "available_at": _past_iso(minutes=1),
            "features": {name: 1.0 for name in feature_names},
        },
    }


class StaleTrustedMicrostructureReasonRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        row = self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
        row.update(
            {
                "candidate_id": "cand-stale-micro-trust-reasons",
                "preemptive_decision": "NO_TRADE",
                "preemptive_action": "BLOCK_MICROSTRUCTURE_UNSAFE",
                "preemptive_block_reasons": [
                    "MICROSTRUCTURE_TRUST_MISSING",
                    "MICROSTRUCTURE_TRUST_LOW",
                    "MICROSTRUCTURE_TRUST_FAIL_CLOSED",
                    "HIGH_CONFIDENCE_WITHOUT_MICROSTRUCTURE_TRUST_EVIDENCE",
                    "FVG_CONFLUENCE_WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST",
                    "FVG_CONFLUENCE_WITHOUT_TAPE_CONFIRMATION",
                ],
                "microstructure_trust_state": "TRUSTED",
                "microstructure_trust_score": 0.91,
                "composite_microstructure_trust_score": 0.91,
            }
        )
        self.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"] = [row]
        self.data["v2:prediction:BTCUSDT:1m"] = _prediction(
            "BTCUSDT",
            "1m",
            "pred-good",
            "hash-good",
        )


def _paper_exploration_policy_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": "cand-timestamp",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "selected_action": "long",
        "confidence_executable_trade": 0.82,
        "current_price": 50000.0,
        "expected_net_pnl_usd": 1.2,
        "expected_max_loss_usd": 0.4,
        "feature_cutoff": "2026-07-10T02:00:00Z",
        "available_at": "2026-07-10T02:00:01Z",
        "decision_time": "2026-07-10T02:00:01Z",
        "feature_vector_hash": "hash-timestamp",
        "provider_feature_hashes": {"binance": "hash-binance"},
        "provider_features_used": ["binance"],
        "preemptive_decision_id": "pec-timestamp",
        "preemptive_decision": "NO_TRADE",
        "preemptive_action": "PAPER_RISK_CONTROLLER_EXPLORATION",
        "risk_decision": "PASS",
        "orchestrator_decision": "PASS",
        "allocator_decision": "PASS",
        "exit_feasible": True,
        "exit_feasibility_score": 0.9,
        "expected_liquidation_buffer_usd": 10.0,
        "microstructure_trust_score": 0.91,
        "bucket_evidence_count": 40,
        "bucket_profit_factor": 1.3,
    }
    row.update(overrides)
    return row


def test_available_at_after_decision_real_lookahead_blocks() -> None:
    row = _paper_exploration_policy_row(
        feature_cutoff="2026-07-10T02:00:05Z",
        available_at="2026-07-10T02:00:06Z",
        decision_time="2026-07-10T02:00:01Z",
    )

    timestamp = classify_timestamp_integrity(row)
    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert timestamp["timestamp_integrity_status"] == "REAL_LOOKAHEAD_BLOCK"
    assert timestamp["real_lookahead_block"] is True
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME_LOOKAHEAD" in timestamp["timestamp_integrity_reasons"]
    assert evaluation["eligible"] is False
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME_LOOKAHEAD" in evaluation["eligibility_block_reasons"]


def test_available_at_after_decision_timestamp_plumbing_requeues() -> None:
    row = _paper_exploration_policy_row(
        feature_cutoff="2026-07-10T02:00:00Z",
        available_at="2026-07-10T02:00:05Z",
        decision_time="2026-07-10T02:00:01Z",
    )

    timestamp = classify_timestamp_integrity(row)
    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert timestamp["timestamp_integrity_status"] == "TIMESTAMP_PLUMBING_REQUEUE"
    assert timestamp["requeue_for_next_cycle"] is True
    assert timestamp["earliest_eligible_decision_time"] == "2026-07-10T02:00:05.000Z"
    assert timestamp["decision_time_backdated"] is False
    assert evaluation["eligible"] is False
    assert "TIMESTAMP_PLUMBING_REQUEUE_NEXT_CYCLE" in evaluation["eligibility_block_reasons"]
    assert "AVAILABLE_AT_AFTER_DECISION_TIME_LOOKAHEAD" not in evaluation["eligibility_block_reasons"]


def test_available_at_equal_decision_allowed() -> None:
    row = _paper_exploration_policy_row(
        feature_cutoff="2026-07-10T02:00:00Z",
        available_at="2026-07-10T02:00:01Z",
        decision_time="2026-07-10T02:00:01Z",
    )

    timestamp = classify_timestamp_integrity(row)
    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert timestamp["timestamp_integrity_status"] == "PASS"
    assert timestamp["available_at_minus_decision_ms"] == 0
    assert evaluation["eligible"] is True


def test_future_feature_cutoff_never_allowed() -> None:
    row = _paper_exploration_policy_row(
        feature_cutoff="2026-07-10T02:00:02Z",
        available_at="2026-07-10T02:00:01Z",
        decision_time="2026-07-10T02:00:01Z",
    )

    timestamp = classify_timestamp_integrity(row)
    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert timestamp["real_lookahead_block"] is True
    assert evaluation["eligible"] is False
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME_LOOKAHEAD" in evaluation["eligibility_block_reasons"]


def test_paper_exploration_policy_treats_global_halt_quarantine_as_advisory_only() -> None:
    row = _paper_exploration_policy_row(
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
        confidence_executable_trade=0.92,
        strategy_router_block_reason="PAPER_LOSS_BUCKET_QUARANTINE",
        paper_performance_circuit_global_halt_only=True,
        high_confidence_loss_cluster_active=True,
        paper_performance_circuit_breaker_advisory_bucket_keys=["side:long"],
        paper_performance_circuit_breaker_advisory_loss_cluster_keys=[
            "loss_cluster_side:long",
            "loss_cluster_timeframe:1m",
        ],
        paper_performance_circuit_breaker_matched_blocked_bucket_keys=[],
        paper_performance_circuit_breaker_matched_loss_cluster_keys=[],
    )

    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert evaluation["bootstrap_exploration"] is False
    assert evaluation["eligible"] is True
    assert evaluation["floor_inputs"]["loss_cluster_quarantine"] is False
    assert "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE" not in evaluation[
        "eligibility_block_reasons"
    ]


def test_paper_exploration_policy_treats_broad_atr_cluster_as_advisory_only() -> None:
    row = _paper_exploration_policy_row(
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
        confidence_executable_trade=0.92,
        strategy_router_block_reason="PAPER_LOSS_BUCKET_QUARANTINE",
        paper_performance_circuit_global_halt_only=True,
        atr_stop_cluster_active=True,
        bucket_quarantine_active=True,
        paper_exploration_exact_blocked_bucket_keys=[],
        paper_exploration_regime_advisory_buckets=[
            {
                "bucket_key": "side:long",
                "classification": "ADVISORY_SIZE_CAP_FOR_PAPER_EXPLORATION",
            }
        ],
        paper_performance_circuit_breaker_advisory_bucket_keys=["side:long"],
        paper_performance_circuit_breaker_advisory_loss_cluster_keys=[
            "loss_cluster_side:long",
        ],
        paper_performance_circuit_breaker_matched_blocked_bucket_keys=[
            "side:long"
        ],
        paper_performance_circuit_breaker_matched_loss_cluster_keys=[
            "loss_cluster_side:long"
        ],
    )

    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert evaluation["eligible"] is True
    assert evaluation["floor_inputs"]["loss_cluster_quarantine"] is False
    assert "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE" not in evaluation[
        "eligibility_block_reasons"
    ]


def test_paper_exploration_policy_blocks_exact_cluster_even_when_global_halt_is_advisory() -> None:
    row = _paper_exploration_policy_row(
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
        confidence_executable_trade=0.92,
        strategy_router_block_reason="PAPER_LOSS_BUCKET_QUARANTINE",
        paper_performance_circuit_global_halt_only=True,
        high_confidence_loss_cluster_active=True,
        paper_performance_circuit_breaker_advisory_loss_cluster_keys=[
            "loss_cluster_side:long",
        ],
        paper_performance_circuit_breaker_matched_loss_cluster_keys=[
            "loss_cluster_symbol:BTCUSDT",
        ],
    )

    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert evaluation["eligible"] is False
    assert evaluation["floor_inputs"]["loss_cluster_quarantine"] is True
    assert "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE" in evaluation[
        "eligibility_block_reasons"
    ]


def test_paper_exploration_policy_recognizes_queue_tier_for_advisory_only_context() -> None:
    row = _paper_exploration_policy_row(
        paper_opportunity_tier=None,
        tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
        confidence_executable_trade=0.72,
        block_reasons=[
            "BUCKET_QUARANTINE_MATCH",
            "HIGH_CONFIDENCE_LOSS_RATE_FORMING",
        ],
        strategy_router_block_reason="PAPER_LOSS_BUCKET_QUARANTINE",
        paper_performance_circuit_global_halt_only=True,
        paper_performance_circuit_breaker_advisory_loss_cluster_keys=[
            "loss_cluster_side:short",
            "loss_cluster_timeframe:4h",
        ],
        paper_performance_circuit_breaker_matched_blocked_bucket_keys=[],
        paper_performance_circuit_breaker_matched_loss_cluster_keys=[],
    )

    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert evaluation["eligible"] is True
    assert evaluation["floor_inputs"]["loss_cluster_quarantine"] is False
    assert "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE" not in evaluation[
        "eligibility_block_reasons"
    ]


def test_paper_exploration_confidence_floor_bootstrap_requires_explicit_opt_in(
    monkeypatch,
) -> None:
    row = _paper_exploration_policy_row(
        confidence_executable_trade=0.42,
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
    )

    monkeypatch.setattr(
        paper_exploration_policy,
        "BOOTSTRAP_EXPLORATION_ENABLED",
        False,
    )
    default_evaluation = evaluate_paper_risk_controller_exploration(row)

    assert default_evaluation["eligible"] is False
    assert default_evaluation["bootstrap_exploration"] is False
    assert (
        "CONFIDENCE_EXECUTABLE_TRADE_BELOW_DYNAMIC_EXPLORATION_FLOOR"
        in default_evaluation["eligibility_block_reasons"]
    )

    monkeypatch.setattr(
        paper_exploration_policy,
        "BOOTSTRAP_EXPLORATION_ENABLED",
        True,
    )
    opt_in_evaluation = evaluate_paper_risk_controller_exploration(row)

    assert opt_in_evaluation["eligible"] is True
    assert opt_in_evaluation["bootstrap_exploration"] is True
    assert opt_in_evaluation["bootstrap_overridden_blockers"] == [
        "CONFIDENCE_EXECUTABLE_TRADE_BELOW_DYNAMIC_EXPLORATION_FLOOR"
    ]


def test_bootstrap_overrides_allocator_low_confidence_but_not_other_allocator_blocks(
    monkeypatch,
) -> None:
    # The allocator's BLOCK_LOW_CONFIDENCE is the same untrained-model confidence
    # signal as the dynamic floor; the bootstrap lane may override it. Any OTHER
    # allocator hard block (e.g. BLOCK_NO_EDGE) must stay hard even with the
    # bootstrap lever on.
    monkeypatch.setattr(paper_exploration_policy, "BOOTSTRAP_EXPLORATION_ENABLED", True)

    low_conf_row = _paper_exploration_policy_row(
        confidence_executable_trade=0.42,
        allocator_decision="BLOCK_LOW_CONFIDENCE",
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
    )
    low_conf = evaluate_paper_risk_controller_exploration(low_conf_row)
    assert low_conf["eligible"] is True
    assert low_conf["bootstrap_exploration"] is True
    assert "ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE" in low_conf["bootstrap_overridden_blockers"]

    no_edge_row = _paper_exploration_policy_row(
        confidence_executable_trade=0.42,
        allocator_decision="BLOCK_NO_EDGE",
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
    )
    no_edge = evaluate_paper_risk_controller_exploration(no_edge_row)
    assert no_edge["eligible"] is False
    assert no_edge["bootstrap_exploration"] is False
    assert "ALLOCATOR_HARD_BLOCK:BLOCK_NO_EDGE" in no_edge["eligibility_block_reasons"]


def test_paper_exploration_policy_keeps_specific_loss_cluster_blocking() -> None:
    row = _paper_exploration_policy_row(
        paper_opportunity_tier="PAPER_RISK_CONTROLLER_EXPLORATION",
        paper_risk_controller_exploration=True,
        paper_only=True,
        routes_to_live=False,
        places_real_order=False,
        counts_as_A_plus=False,
        counts_as_final_a_plus=False,
        counts_as_live_ready=False,
        strategy_router_block_reason="PAPER_LOSS_BUCKET_QUARANTINE",
        paper_performance_circuit_global_halt_only=True,
        paper_performance_circuit_breaker_advisory_bucket_keys=["side:long"],
        paper_performance_circuit_breaker_advisory_loss_cluster_keys=[
            "loss_cluster_side:long",
        ],
        paper_performance_circuit_breaker_matched_blocked_bucket_keys=[],
        paper_performance_circuit_breaker_matched_loss_cluster_keys=[
            "loss_cluster_symbol:LINKUSDT",
        ],
    )

    evaluation = evaluate_paper_risk_controller_exploration(row)

    assert evaluation["eligible"] is False
    assert evaluation["floor_inputs"]["loss_cluster_quarantine"] is True
    assert "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE" in evaluation[
        "eligibility_block_reasons"
    ]


def test_inventory_writes_required_outputs_and_classifies_blockers(tmp_path: Path) -> None:
    result = build_inventory(client=FakeRedis(), output_dir=tmp_path, max_prediction_keys=20)

    assert result["summary"]["total_candidate_count"] == 2
    assert result["summary"]["a_plus_candidate_count"] == 1
    assert result["summary"]["live_ready_candidate_count"] == 1
    assert result["summary"]["final_state"] == "A_PLUS_CANDIDATE_PRESENT_LIVE_BLOCKED_HUMAN_ONLY"
    assert result["summary"]["exact_no_A_plus_reason"] is None
    assert result["rejection_matrix"]["unknown_rejection_reason_count"] == 0
    assert result["rejection_matrix"]["blocker_class_counts"]["EXPECTED_NET_EDGE_BLOCKER"] >= 1
    assert (tmp_path / "candidate_inventory.jsonl").exists()
    assert (tmp_path / "candidate_inventory_summary.json").exists()
    assert (tmp_path / "candidate_rejection_matrix.json").exists()
    assert (tmp_path / "a_plus_candidate_rows.jsonl").exists()
    assert (tmp_path / "near_a_plus_candidate_rows.jsonl").exists()

    good = result["a_plus_rows"][0]
    assert good["preemptive_decision_id"] == "pec-good"
    assert good["feature_vector_hash"] == "hash-good"
    assert good["allocator_decision_id"].startswith("allocsim_")
    assert good["allocator_decision"] == "PASS"
    assert good["recommended_leverage_source"] == "adaptive_simulation"
    assert good["recommended_margin_mode_source"] == "adaptive_simulation"
    assert good["current_price"] == 65000.0
    assert good["price_missing_reason"] is None
    assert good["expected_move"] == 12.0
    assert good["expected_gross_pnl_usd"] == 3.5
    assert good["expected_cost_usd"] == 0.0
    assert good["confidence_raw"] == 0.84
    assert good["confidence_calibrated"] == 0.8
    assert good["max_loss_usd"] == 1.2
    assert good["liquidation_buffer_usd"] == 25.0
    assert good["counts_as_probation"] is False
    assert good["counts_as_reconstructed"] is False

    blocked = next(row for row in result["rows"] if row["candidate_id"] == "cand-blocked")
    assert blocked["allocator_decision_id"].startswith("allocsim_")
    assert blocked["allocator_decision"] == "REJECT"
    assert "ALLOCATOR_PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND" in blocked["allocator_block_reasons"]
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE" not in blocked["allocator_block_reasons"]
    assert result["summary"]["allocator_decision_missing_count"] == 0


def test_inventory_summary_persists_guardian_failure_reasons(tmp_path: Path) -> None:
    client = FakeRedis()
    client.data["v2:continuous_edge_guardian:a_grade_execution_gate"] = {
        "status": "A_GRADE_HALTED_PERFORMANCE",
        "a_grade_new_entries_allowed": False,
        "new_entries_allowed": False,
        "generated_utc": "2026-07-12T06:36:08.942Z",
        "failure_reasons": [
            {
                "reason": "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS",
                "observed": 455,
                "required": 50000,
            }
        ],
    }

    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    guardian = result["summary"]["continuous_edge_guardian_gate_status"]
    assert guardian["status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert guardian["a_grade_new_entries_allowed"] is False
    assert result["summary"]["continuous_edge_guardian_top_reason"] == (
        "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"
    )
    assert guardian["failure_reasons"][0]["observed"] == 455
    assert guardian["failure_reasons"][0]["required"] == 50000


def test_inventory_drops_stale_microstructure_reasons_when_trust_is_explicit(
    tmp_path: Path,
) -> None:
    result = build_inventory(
        client=StaleTrustedMicrostructureReasonRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = result["rows"][0]
    assert row["microstructure_trust_score"] == 0.91
    assert "MICROSTRUCTURE_TRUST_MISSING" not in row["block_reasons"]
    assert "MICROSTRUCTURE_TRUST_LOW" not in row["block_reasons"]
    assert "MICROSTRUCTURE_TRUST_FAIL_CLOSED" not in row["block_reasons"]
    assert "HIGH_CONFIDENCE_WITHOUT_MICROSTRUCTURE_TRUST_EVIDENCE" not in row[
        "block_reasons"
    ]
    assert "FVG_CONFLUENCE_WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST" not in row[
        "block_reasons"
    ]
    assert "FVG_CONFLUENCE_WITHOUT_TAPE_CONFIRMATION" in row["block_reasons"]
    assert "PREEMPTIVE_ACTION_NOT_A_PLUS_ALLOW" in row["block_reasons"]


def test_inventory_keeps_microstructure_reasons_when_state_is_fail_closed(
    tmp_path: Path,
) -> None:
    client = StaleTrustedMicrostructureReasonRedis()
    row = client.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
    row["microstructure_trust_state"] = "FAIL_CLOSED"

    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    normalized = result["rows"][0]
    assert normalized["microstructure_trust_score"] == 0.91
    assert "MICROSTRUCTURE_TRUST_FAIL_CLOSED" in normalized["block_reasons"]
    assert "FVG_CONFLUENCE_WITHOUT_SUFFICIENT_MICROSTRUCTURE_TRUST" in normalized[
        "block_reasons"
    ]


def test_current_session_filters_stale_matrix_rows(tmp_path: Path) -> None:
    client = FakeRedis()
    stale_prediction = client.data["v2:prediction:BTCUSDT:1m"]
    stale_prediction["generated_at"] = _past_iso(minutes=420)
    stale_prediction["decision_time"] = _past_iso(minutes=420)

    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    assert result["summary"]["stale_current_session_rows_filtered_count"] == 1
    assert all(row["candidate_id"] != "cand-good" for row in result["rows"])
    assert result["summary"]["a_plus_candidate_count"] == 0
    assert result["summary"]["final_state"] != "OPERATOR_REVIEW_READY_FIRST_LIVE_CANARY"
    assert result["summary"]["final_state"] != "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON"
    assert result["summary"]["exact_no_A_plus_reason"]


def test_matrix_row_does_not_borrow_latest_prediction_when_id_differs(
    tmp_path: Path,
) -> None:
    client = FakeRedis()
    matrix_row = client.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0]
    matrix_row.update(
        {
            "candidate_id": "cand-old-matrix-row",
            "prediction_id": "pred-old-matrix-row",
            "signal_id": "sig-old-matrix-row",
            "decision_time": _past_iso(minutes=3),
            "available_at": _past_iso(minutes=4),
            "feature_cutoff": _past_iso(minutes=5),
            "feature_vector_hash": "row-owned-feature-hash",
            "feature_snapshot_id": "row-owned-snapshot",
        }
    )
    latest_prediction = client.data["v2:prediction:BTCUSDT:1m"]
    latest_prediction.update(
        {
            "prediction_id": "pred-new-runtime",
            "signal_id": "sig-new-runtime",
            "decision_time": _now_iso(),
            "available_at": _past_iso(minutes=1),
            "feature_cutoff": _past_iso(minutes=2),
            "feature_vector_hash": "latest-runtime-feature-hash",
        }
    )

    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    matrix_normalized = next(
        row for row in result["rows"] if row["candidate_id"] == "cand-old-matrix-row"
    )
    runtime_normalized = next(
        row for row in result["rows"] if row["prediction_id"] == "pred-new-runtime"
    )

    assert matrix_normalized["prediction_id"] == "pred-old-matrix-row"
    assert matrix_normalized["feature_vector_hash"] == "row-owned-feature-hash"
    assert matrix_normalized["feature_snapshot_id"] == "row-owned-snapshot"
    assert matrix_normalized["feature_cutoff"] != latest_prediction["feature_cutoff"]
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME_LOOKAHEAD" not in matrix_normalized[
        "paper_risk_controller_exploration_block_reasons"
    ]
    assert runtime_normalized["feature_vector_hash"] == "latest-runtime-feature-hash"


def test_counts_as_final_a_plus_false_blocks_a_plus_governance(tmp_path: Path) -> None:
    client = FakeRedis()
    client.data["v2:paper:preemptive_candidate_decision_matrix"]["rows"][0][
        "counts_as_final_A_plus"
    ] = False

    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    row = next(item for item in result["rows"] if item["candidate_id"] == "cand-good")
    assert row["A_plus_candidate"] is False
    assert row["live_ready_candidate"] is False
    assert "COUNTS_AS_FINAL_A_PLUS_FALSE" in row["block_reasons"]
    assert result["summary"]["a_plus_candidate_count"] == 0
    assert result["summary"]["live_ready_candidate_count"] == 0
    assert result["summary"]["final_state"] == "A_PLUS_BLOCKERS_ACTIVE_LIVE_BLOCKED"
    assert result["summary"]["exact_no_A_plus_reason"]


def test_strategy_supply_hypothesis_preserves_positive_usd_economics(tmp_path: Path) -> None:
    result = build_inventory(client=StrategySupplyRedis(), output_dir=tmp_path, max_prediction_keys=20)

    row = next(row for row in result["rows"] if row.get("prediction_id") == "hyp-test-positive-usd")
    assert row["strategy_supply_hypothesis"] is True
    assert row["strategy_supply_hypothesis_id"] == "hyp-test-positive-usd"
    assert row["strategy_family"] == "funding_squeeze"
    assert row["strategy_selected_mode"] == "funding_squeeze"
    assert row["source_tier"] == "STRATEGY_SUPPLY_HYPOTHESIS"
    assert row["gross_notional_usd"] > 0.0
    assert row["target_notional_usd"] > 0.0
    assert row["expected_gross_pnl_usd"] == 4.0
    assert row["expected_cost_usd"] == 0.32
    assert row["expected_net_pnl_usd"] > 0.0
    assert row["expected_move_bps"] == -20.0
    assert row["expected_move_after_cost_bps"] == -18.4
    assert row["expected_short_net_edge_bps"] == 18.4
    assert row["short_expected_net_pnl_usd"] == 3.68
    assert "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE" not in row["block_reasons"]
    assert "EXPECTED_EDGE_NON_POSITIVE" not in row["block_reasons"]
    assert "EXPECTED_MOVE_DOES_NOT_COVER_COST" not in row["block_reasons"]
    assert row["paper_exploration_selected_side_economics_consistency"]["status"] == "CONSISTENT"
    assert row["expected_max_loss_usd"] == 1.9
    assert row["current_price"] == 65000.0
    assert row["pre_trade_loss_probability"] == 0.35
    assert row["loss_probability_reason"] == "STRATEGY_SUPPLY_CALIBRATED_LOSS_PROBABILITY"
    assert row["loss_probability_reasons"] == [
        "STRATEGY_SUPPLY_CALIBRATED_LOSS_PROBABILITY",
        "CALIBRATION_PENALTY:microstructure_trust_below_allocator_minimum",
    ]
    assert row["loss_probability_calibration"]["adjusted_loss_probability"] == 0.35
    assert row["microstructure_trust_score"] == 0.91
    assert row["market_state_integrity_score"] == 91.0
    assert row["market_state_integrity_minimum_score"] == 70.0
    assert row["allocator_packet"]["market_state_integrity_score"] == 91.0
    assert row["trade_tape_confirmation_score"] == 0.88
    assert row["expected_exit_depth_usd"] == 25000.0
    assert row["exit_feasible"] is True
    assert row["exit_feasibility_score"] == 0.9
    assert row["microstructure_features_present"] is True
    assert "FEATURE_COVERAGE_MICROSTRUCTURE_MISSING" not in row["block_reasons"]
    assert "GUARDIAN_HALTED_OR_MISSING" not in row["block_reasons"]
    assert row["orchestrator_decision"] == "PASS"
    assert row["orchestrator_action"] == "open_short"
    assert row["orchestrator_decision_id"] == "dec_hyp-test-positive-usd"
    assert row["orchestrator_live_blocked"] is True
    assert row["risk_decision"] == "PASS"
    assert row["risk_action"] == "allow"
    assert row["risk_decision_id"] == "rd_dec_hyp-test-positive-usd"
    assert row["risk_live_blocked"] is True
    assert row["risk_orchestrator_projection_source"] == "strategy_supply_inventory_dry_run"
    assert row["risk_orchestrator_projection_live_blocked"] is True
    assert "RISK_GATEWAY_NOT_PASS" not in row["block_reasons"]
    assert "ORCHESTRATOR_NOT_PASS" not in row["block_reasons"]
    assert "ALLOCATOR_TARGET_NOTIONAL_USD_NON_POSITIVE" not in row["allocator_block_reasons"]
    assert row["provider_feature_hashes"] == {
        "coinglass": "hash-coinglass",
        "coinank": "hash-coinank",
    }
    assert row["source_hashes"] == row["provider_feature_hashes"]
    queue_row = _build_materialization_queue_row(row, accepted_at=_now_iso())
    assert queue_row["pre_trade_loss_probability"] == 0.35
    assert queue_row["loss_probability_reason"] == "STRATEGY_SUPPLY_CALIBRATED_LOSS_PROBABILITY"
    assert queue_row["loss_probability_reasons"] == [
        "STRATEGY_SUPPLY_CALIBRATED_LOSS_PROBABILITY",
        "CALIBRATION_PENALTY:microstructure_trust_below_allocator_minimum",
    ]
    assert queue_row["paper_signal"]["loss_probability_calibration"][
        "adjusted_loss_probability"
    ] == 0.35


def test_strategy_supply_positive_usd_stage_reject_still_reaches_inventory(tmp_path: Path) -> None:
    result = build_inventory(
        client=StrategySupplyStageRejectedRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row.get("prediction_id") == "hyp-positive-usd-low-trust")
    assert row["strategy_supply_hypothesis"] is True
    assert row["strategy_supply_hypothesis_id"] == "hyp-positive-usd-low-trust"
    assert row["strategy_supply_positive_net_usd"] is True
    assert row["strategy_supply_gate_clean"] is False
    assert row["strategy_supply_stage_rejected_reason"] == "MICROSTRUCTURE_TRUST_BELOW_ALLOCATOR_MINIMUM"
    assert row["expected_net_pnl_usd"] == 1.25
    assert row["market_state_integrity_score"] == 59.0
    assert row["market_state_integrity_minimum_score"] == 70.0
    assert row["A_plus_candidate"] is False
    assert row["counts_as_A_plus"] is False
    # 2026-07-16 adaptive gating: low microstructure trust reduces size
    # instead of hard-rejecting (paper learning mode), so the allocator
    # decision is PASS while the stage-reject reason stays visible above and
    # the row can never count as A+.
    assert row["allocator_decision"] == "PASS"
    assert row["provider_feature_hashes"]["coinglass"] == "hash-coinglass-low-trust"


def test_directional_row_promotes_selected_side_usd_economics(tmp_path: Path) -> None:
    result = build_inventory(client=SelectedSideEconomicsRedis(), output_dir=tmp_path, max_prediction_keys=20)

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-selected-short-net")
    assert row["side"] == "short"
    assert row["expected_net_pnl_usd"] == 0.42
    assert row["expected_cost_usd"] == 0.08
    assert row["expected_gross_pnl_usd"] == 0.50
    assert row["short_expected_net_pnl_usd"] == 0.42
    assert "EXPECTED_NET_EDGE_NON_POSITIVE" not in row["block_reasons"]
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE" not in row["allocator_block_reasons"]
    assert result["summary"]["order_submitted"] is False


def test_paper_risk_controller_exploration_inventory_is_paper_only(tmp_path: Path) -> None:
    result = build_inventory(
        client=PaperExplorationRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert row["paper_exploration_risk_controller_input_written"] is True
    assert row["paper_exploration_orchestrator_input_written"] is True
    assert row["paper_exploration_allocator_input_written"] is True
    assert row["paper_exploration_paper_fill_allowed"] is True
    assert row["counts_as_A_plus"] is False
    assert row["counts_as_live_ready"] is False
    assert row["paper_exploration_counts_as_A_plus"] is False
    assert row["paper_exploration_counts_as_live_ready"] is False
    assert row["paper_exploration_routes_to_live"] is False
    assert row["paper_exploration_places_real_order"] is False
    assert row["dynamic_exploration_floor"] < row["confidence_executable_trade"]
    assert result["summary"]["paper_risk_controller_exploration_eligible_count"] == 1
    assert result["summary"]["paper_risk_controller_exploration_risk_controller_seen_rows"] == 1
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 1


def test_paper_exploration_short_unfavorable_signed_move_not_queued(tmp_path: Path) -> None:
    result = build_inventory(
        client=PaperExplorationShortUnfavorableRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(
        row
        for row in result["rows"]
        if row["candidate_id"] == "cand-paper-explore-short-unfavorable"
    )
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert (
        "MATERIALIZATION_PREQUEUE_EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:short:256.9"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert (
        "MATERIALIZATION_PREQUEUE_SELECTED_SIDE_ECONOMICS_CONFLICT:"
        "short:SELECTED_SIDE_NET_USD_POSITIVE_WHILE_SIGNED_MOVE_UNFAVORABLE"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert (
        "MATERIALIZATION_PREQUEUE_SELECTED_SIDE_ECONOMICS_CONFLICT:"
        "short:SELECTED_SIDE_NET_USD_POSITIVE_WHILE_EDGE_BPS_NON_POSITIVE"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    consistency = row["paper_exploration_selected_side_economics_consistency"]
    assert consistency["status"] == "CONFLICT"
    assert consistency["selected_side_expected_net_pnl_usd"] == 0.82
    assert consistency["selected_side_expected_net_edge_bps"] < 0
    assert row["paper_exploration_prequeue_block_reasons"] == (
        row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_status"][
        "accepted_dry_run_rows"
    ] == 0


def test_paper_exploration_operator_excluded_symbol_not_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-07-16 policy: no hardcoded symbol lists — the DEFAULT operator
    exclusion set is empty (symbol universe is fully adaptive). The operator
    override MECHANISM must keep working: when an operator explicitly
    excludes a symbol, exploration candidates on it must not queue.
    """
    import v2.backend.app.cli.v2_a_plus_candidate_inventory as inventory_module

    # Policy: shipped default exclusion list is empty.
    assert inventory_module.PAPER_EXPLORATION_MATERIALIZATION_SYMBOL_EXCLUSION_LIST == frozenset()

    # Mechanism: an explicit operator exclusion still blocks queuing.
    monkeypatch.setattr(
        inventory_module,
        "PAPER_EXPLORATION_MATERIALIZATION_SYMBOL_EXCLUSION_LIST",
        frozenset({"TIAUSDT"}),
    )
    result = build_inventory(
        client=PaperExplorationOperatorExcludedRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(
        row
        for row in result["rows"]
        if row["candidate_id"] == "cand-paper-explore-operator-excluded"
    )
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert (
        "MATERIALIZATION_PREQUEUE_ENTRY_GATE:"
        "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:TIAUSDT"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert row["paper_exploration_prequeue_block_reasons"] == (
        row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_status"][
        "accepted_dry_run_rows"
    ] == 0


def test_paper_exploration_no_trade_strategy_not_queued(tmp_path: Path) -> None:
    result = build_inventory(
        client=PaperExplorationNoTradeStrategyRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(
        row
        for row in result["rows"]
        if row["candidate_id"] == "cand-paper-explore-no-trade-strategy"
    )
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert (
        "MATERIALIZATION_PREQUEUE_LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert (
        "MATERIALIZATION_PREQUEUE_NO_TRADE_ENTRY_EVIDENCE:strategy_id=NO_TRADE"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert (
        "MATERIALIZATION_PREQUEUE_NO_TRADE_ENTRY_EVIDENCE:strategy_regime_labels_include_NO_TRADE"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert row["paper_exploration_prequeue_block_reasons"] == (
        row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_status"][
        "accepted_dry_run_rows"
    ] == 0


def test_paper_exploration_performance_quarantine_not_queued(tmp_path: Path) -> None:
    client = PaperExplorationPerformanceQuarantineRedis()
    client.data[PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY] = [
        {
            "trainer_feedback_id": "cf_existing_prequeue",
            "paper_exploration_candidate_id": "existing-candidate",
            "future_label_pending": True,
            "trainer_consumable": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_A_plus": False,
            "counts_as_live_ready": False,
        }
    ]
    result = build_inventory(
        client=client,
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert (
        "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:side_timeframe:long|5m"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert (
        "MATERIALIZATION_PREQUEUE_HIGH_CONFIDENCE_LOSS_CLUSTER:loss_cluster_symbol:SOLUSDT"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert row["paper_performance_circuit_breaker_matched_blocked_bucket_keys"] == [
        "side_timeframe:long|5m"
    ]
    assert row["paper_performance_circuit_breaker_matched_blocked_bucket_proof"] == [
        {
            "bucket_key": "side_timeframe:long|5m",
            "bucket_type": "side_timeframe",
            "state": "QUARANTINED",
            "candidate_blocking": True,
            "block_reasons": [
                "HIGH_CONFIDENCE_LOSS_RATE_ABOVE_ADAPTIVE_BOUND",
                "NEGATIVE_PROFIT_FACTOR_SIDE_TIMEFRAME_BUCKET",
            ],
            "closed_outcome_count": 3,
            "profit_factor": 0.0,
            "notional_weighted_expectancy_bps": -18.5,
            "high_confidence_loss_rate": 1.0,
            "high_confidence_loss_count": 3,
            "high_confidence_outcome_count": 3,
            "ATR_stop_loss_count": 1,
            "negative_bucket_min_count": 2,
            "proof_status": "BUCKET_METADATA_PRESENT",
            "classification": "HARD_BLOCK_FOR_PAPER_EXPLORATION",
        }
    ]
    assert row["paper_performance_circuit_breaker_matched_loss_cluster_keys"] == [
        "loss_cluster_symbol:SOLUSDT"
    ]
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_status"][
        "accepted_dry_run_rows"
    ] == 0
    assert result["summary"][
        "paper_risk_controller_exploration_prequeue_performance_block_counts"
    ][
        "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:side_timeframe:long|5m"
    ] == 1
    queue_status = result["summary"]["paper_exploration_materialization_queue_status"]
    assert queue_status["prequeue_rejected_count"] == 1
    assert queue_status["prequeue_counterfactual_count"] == 1
    rejected_status_row = queue_status["prequeue_rejected_rows"][0]
    assert rejected_status_row[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ] == ["side_timeframe:long|5m"]
    assert rejected_status_row[
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
    ][0]["closed_outcome_count"] == 3
    assert rejected_status_row[
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
    ][0]["classification"] == "HARD_BLOCK_FOR_PAPER_EXPLORATION"
    feedback_rows = client.data[PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY]
    assert len(feedback_rows) == 2
    assert {row["trainer_feedback_id"] for row in feedback_rows} == {
        "cf_existing_prequeue",
        "cf_materialization_prequeue_cand-paper-explore",
    }
    feedback = next(
        row
        for row in feedback_rows
        if row["trainer_feedback_id"] == "cf_materialization_prequeue_cand-paper-explore"
    )
    assert feedback["feedback_type"] == (
        "PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_PREQUEUE_NO_FILL"
    )
    assert feedback["block_reason_if_rejected"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert (
        "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:side_timeframe:long|5m"
        in feedback["exact_reasons"]
    )
    assert feedback[
        "paper_performance_circuit_breaker_matched_blocked_bucket_keys"
    ] == ["side_timeframe:long|5m"]
    assert feedback[
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
    ][0]["profit_factor"] == 0.0
    assert feedback[
        "paper_performance_circuit_breaker_matched_blocked_bucket_proof"
    ][0]["proof_status"] == "BUCKET_METADATA_PRESENT"
    assert feedback["paper_exploration_candidate_id"] == "cand-paper-explore"
    assert feedback["trainer_consumable"] is False
    assert feedback["future_label_pending"] is True
    assert feedback["paper_only"] is True
    assert feedback["routes_to_live"] is False
    assert feedback["places_real_order"] is False
    assert feedback["counts_as_A_plus"] is False
    assert feedback["counts_as_live_ready"] is False
    assert feedback["raw_safety_fields"]["routes_to_live"] is False
    assert feedback["invariant_checks"]["routes_to_live_is_false"] is True


def test_paper_exploration_broad_global_halt_stays_advisory(tmp_path: Path) -> None:
    client = PaperExplorationBroadGlobalHaltRedis()
    result = build_inventory(
        client=client,
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "PAPER_FILL_ALLOWED"
    assert row["paper_exploration_paper_fill_allowed"] is True
    assert row["paper_performance_circuit_breaker_matched_blocked_bucket_keys"] == []
    assert row["paper_performance_circuit_breaker_matched_loss_cluster_keys"] == []
    assert row["paper_performance_circuit_breaker_advisory_bucket_keys"] == [
        "side:long"
    ]
    assert row["paper_performance_circuit_breaker_advisory_loss_cluster_keys"] == [
        "loss_cluster_side:long"
    ]
    assert (
        row["paper_risk_controller_exploration_global_halt_bucket_clean_allowed"]
        is True
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 1
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 1
    assert result["summary"][
        "paper_risk_controller_exploration_prequeue_performance_advisory_rows"
    ] == 1
    assert row["recommended_notional_usd"] > 0.0
    assert row["recommended_notional_usd"] == row["target_notional_usd"]
    assert row["recommended_notional_usd"] == row["gross_notional_usd"]
    assert row["allocated_margin_usd"] > 0.0
    assert row["risk_budget_usd"] > 0.0
    assert row["allocator_packet"]["recommended_notional_usd"] == row["recommended_notional_usd"]
    assert row["allocator_packet"]["risk_budget_usd"] == row["risk_budget_usd"]
    queue_status = result["summary"]["paper_exploration_materialization_queue_status"]
    assert queue_status["prequeue_rejected_count"] == 0
    assert queue_status["prequeue_counterfactual_count"] == 0
    assert queue_status["active_count"] == 1
    assert len(queue_status["active_rows"]) == 1
    assert queue_status["active_rows"][0]["candidate_id"] == "cand-paper-explore"
    assert queue_status["active_rows"][0]["tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert queue_status["active_rows"][0]["paper_risk_controller_exploration_above_floor"] is True
    assert queue_status["active_rows"][0]["paper_risk_controller_exploration_eligible"] is True
    assert queue_status["active_rows"][0]["risk_decision_record_resolved"] is True
    assert queue_status["active_rows"][0]["orchestrator_decision_record_resolved"] is True
    assert queue_status["active_rows"][0]["decision_record_missing_reasons"] == []
    assert queue_status["active_rows"][0]["recommended_notional_usd"] == row["recommended_notional_usd"]
    assert queue_status["active_rows"][0]["allocated_margin_usd"] == row["allocated_margin_usd"]
    assert queue_status["active_rows"][0]["risk_budget_usd"] == row["risk_budget_usd"]
    assert queue_status["active_rows"][0]["paper_signal"]["recommended_notional_usd"] == row["recommended_notional_usd"]
    assert queue_status["active_rows"][0]["raw_safety_fields"]["routes_to_live"] is False
    assert queue_status["active_rows"][0]["invariant_checks"]["routes_to_live_is_false"] is True
    per_id_store = queue_status["per_id_decision_store"]
    assert per_id_store["implemented"] is True
    assert per_id_store["risk_records_written"] == 1
    assert per_id_store["risk_records_resolved"] == 1
    assert per_id_store["orchestrator_records_written"] == 1
    assert per_id_store["orchestrator_records_resolved"] == 1
    assert per_id_store["missing_record_count"] == 0
    risk_key = "v2:decision:risk:risk-paper-explore"
    orchestrator_key = "v2:decision:orchestrator:orch-paper-explore"
    assert queue_status["active_rows"][0]["risk_decision_record_key"] == risk_key
    assert (
        queue_status["active_rows"][0]["orchestrator_decision_record_key"]
        == orchestrator_key
    )
    risk_record = client.data[risk_key]
    assert risk_record["candidate_id"] == "cand-paper-explore"
    assert risk_record["signal_id"] == "sig-paper-explore"
    assert risk_record["symbol"] == "SOLUSDT"
    assert risk_record["routes_to_live"] is False
    assert risk_record["places_real_order"] is False
    orchestrator_record = client.data[orchestrator_key]
    assert orchestrator_record["candidate_id"] == "cand-paper-explore"
    assert orchestrator_record["signal_id"] == "sig-paper-explore"
    assert orchestrator_record["symbol"] == "SOLUSDT"
    assert orchestrator_record["routes_to_live"] is False
    assert orchestrator_record["places_real_order"] is False
    by_candidate = client.data["v2:decision:index:by_candidate:cand-paper-explore"]
    assert by_candidate["risk_decision_record_key"] == risk_key
    assert by_candidate["orchestrator_decision_record_key"] == orchestrator_key
    by_signal = client.data["v2:decision:index:by_signal:sig-paper-explore"]
    assert by_signal["risk_decision_id"] == "risk-paper-explore"
    assert by_signal["orchestrator_decision_id"] == "orch-paper-explore"
    assert PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY not in client.data


def test_paper_exploration_immature_confidence_regime_halt_stays_advisory(
    tmp_path: Path,
) -> None:
    client = PaperExplorationImmatureConfidenceRegimeHaltRedis()
    result = build_inventory(
        client=client,
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "PAPER_FILL_ALLOWED"
    assert row["paper_exploration_paper_fill_allowed"] is True
    assert row["paper_performance_circuit_breaker_matched_blocked_bucket_keys"] == []
    assert row["paper_performance_circuit_breaker_advisory_bucket_keys"] == [
        "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
    ]
    assert (
        row["paper_risk_controller_exploration_global_halt_bucket_clean_allowed"]
        is True
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 1
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 1


def test_paper_exploration_mature_confidence_regime_halt_blocks_prequeue(
    tmp_path: Path,
) -> None:
    client = PaperExplorationMatureConfidenceRegimeHaltRedis()
    result = build_inventory(
        client=client,
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is True
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert row["paper_performance_circuit_breaker_matched_blocked_bucket_keys"] == [
        "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
    ]
    assert row["paper_performance_circuit_breaker_advisory_bucket_keys"] == []
    assert (
        "MATERIALIZATION_PREQUEUE_ACTIVE_BUCKET_QUARANTINE:"
        "confidence_regime:0.8-0.9|MICROSTRUCTURE_MOMENTUM"
        in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    assert result["summary"]["paper_risk_controller_exploration_paper_accepted_rows"] == 0
    assert result["summary"]["paper_exploration_materialization_queue_rows"] == 0


def test_materialization_queue_preserves_unresolved_previous_rows(tmp_path: Path) -> None:
    client = PaperExplorationBroadGlobalHaltRedis()
    preserved_row = {
        "queue_id": "paper_exploration_materialize_preserved-candidate",
        "candidate_id": "preserved-candidate",
        "prediction_id": "preserved-candidate",
        "signal_id": "preserved-candidate",
        "symbol": "LINKUSDT",
        "timeframe": "4h",
        "side": "long",
        "tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
        "accepted_at": _now_iso(),
        "available_at": _past_iso(minutes=1),
        "decision_time": _past_iso(minutes=1),
        "expires_at": _future_iso(seconds=600),
        "adaptive_stale_seconds": 900,
        "confidence_executable_trade": 0.72,
        "dynamic_exploration_floor": 0.66,
        "paper_risk_controller_exploration_above_floor": True,
        "paper_risk_controller_exploration_eligible": True,
        "risk_decision_id": "rd-preserved-candidate",
        "orchestrator_decision_id": "dec-preserved-candidate",
        "allocator_decision_id": "alloc-preserved-candidate",
        "preemptive_decision_id": "pec-preserved-candidate",
        "expected_net_pnl_usd": 0.8,
        "expected_max_loss_usd": 0.4,
        "current_price": 12.0,
        "recommended_notional_usd": 10.0,
        "recommended_leverage": 1.0,
        "recommended_margin_mode": "isolated",
        "liquidation_buffer_usd": 20.0,
        "feature_vector_hash": "hash-preserved-candidate",
        "provider_hashes": {"latest": "provider-preserved"},
        "source_freshness_pending": False,
        "source_freshness_hard_fail": False,
        "safety_hard_fail": False,
        "raw_safety_fields": {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "test_order": False,
            "live_order": False,
            "counts_as_A_plus": False,
            "counts_as_final_A_plus": False,
            "counts_as_live_ready": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        },
        "invariant_checks": {
            "paper_only_is_true": True,
            "routes_to_live_is_false": True,
            "places_real_order_is_false": True,
            "test_order_is_false": True,
            "live_order_is_false": True,
            "counts_as_A_plus_is_false": True,
            "counts_as_final_A_plus_is_false": True,
            "counts_as_live_ready_is_false": True,
            "order_submitted_is_false": True,
            "test_order_submitted_is_false": True,
            "leverage_mutated_is_false": True,
            "margin_mutated_is_false": True,
        },
    }
    client.data[EXPLORATION_MATERIALIZATION_QUEUE_KEY] = {
        "schema_version": "paper_exploration_materialization_queue_v1",
        "generated_utc": _past_iso(minutes=1),
        "rows": [preserved_row],
        "pending_source_rows": [],
        "expired_rows": [],
        "unsafe_rows": [],
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }

    result = build_inventory(
        client=client,
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    queue_status = result["summary"]["paper_exploration_materialization_queue_status"]
    queue_payload = client.data[EXPLORATION_MATERIALIZATION_QUEUE_KEY]

    assert queue_status["accepted_dry_run_rows"] == 1
    assert queue_status["preserved_previous_queue_count"] == 1
    assert queue_status["queued_count"] == 2
    assert queue_status["per_id_decision_store"]["risk_records_resolved"] == 2
    assert queue_status["per_id_decision_store"]["orchestrator_records_resolved"] == 2
    assert queue_status["per_id_decision_store"]["missing_record_count"] == 0
    assert {row["candidate_id"] for row in queue_status["active_rows"]} == {
        "cand-paper-explore",
        "preserved-candidate",
    }
    preserved_status = next(
        row
        for row in queue_status["active_rows"]
        if row["candidate_id"] == "preserved-candidate"
    )
    assert (
        preserved_status["materialization_queue_preserved_from_previous_queue"]
        is True
    )
    assert preserved_status["raw_safety_fields"]["routes_to_live"] is False
    assert preserved_status["invariant_checks"]["routes_to_live_is_false"] is True
    assert preserved_status["risk_decision_record_resolved"] is True
    assert preserved_status["orchestrator_decision_record_resolved"] is True
    assert {row["candidate_id"] for row in queue_payload["rows"]} == {
        "cand-paper-explore",
        "preserved-candidate",
    }
    assert client.data["v2:decision:risk:rd-preserved-candidate"][
        "candidate_id"
    ] == "preserved-candidate"
    assert client.data["v2:decision:orchestrator:dec-preserved-candidate"][
        "candidate_id"
    ] == "preserved-candidate"


def test_paper_exploration_materialization_queue_does_not_extend_source_expiry() -> None:
    row = {
        "candidate_id": "hyp-stale-source-fresh-queue",
        "prediction_id": "hyp-stale-source-fresh-queue",
        "signal_id": "hyp-stale-source-fresh-queue",
        "symbol": "ORDIUSDT",
        "timeframe": "1m",
        "side": "long",
        "available_at": "2026-07-10T03:00:00.000Z",
        "decision_time": "2026-07-10T03:00:01.000Z",
        "generated_utc": "2026-07-10T03:00:01.000Z",
        "feature_cutoff": "2026-07-10T02:59:59.999Z",
        "feature_snapshot_id": "snap_strategy_supply_test",
        "market_state_integrity_score": 91.0,
        "confidence_executable_trade": 0.82,
        "dynamic_exploration_floor": 0.66,
        "dynamic_exploration_floor_formula": "formula-test",
        "exploration_floor_inputs": {"loss_cluster_quarantine": False},
        "exploration_floor_range": {"min": 0.58, "max": 0.88},
        "paper_risk_controller_exploration_eligible": True,
        "paper_risk_controller_exploration_above_floor": True,
        "expected_net_pnl_usd": 1.2,
        "expected_max_loss_usd": 0.4,
        "recommended_notional_usd": 100.0,
        "current_price": 8.1,
    }

    queued = _build_materialization_queue_row(
        row,
        accepted_at="2026-07-10T03:28:29.000Z",
    )

    assert queued["queue_freshness_basis"] == "source_time"
    assert queued["source_freshness_basis"] == "decision_time"
    assert queued["source_freshness_time"] == "2026-07-10T03:00:01.000Z"
    assert queued["source_expires_at"] == "2026-07-10T03:02:01.000Z"
    assert queued["expires_at"] == "2026-07-10T03:02:01.000Z"
    assert queued["source_stale_at_acceptance"] is True
    assert queued["source_age_seconds_at_acceptance"] == 1708
    assert queued["source_freshness_reasons"] == [
        "MATERIALIZATION_PREQUEUE_SOURCE_STALE:1708>120:decision_time"
    ]
    assert queued["source_available_at"] == "2026-07-10T03:00:00.000Z"
    assert queued["source_decision_time"] == "2026-07-10T03:00:01.000Z"
    assert queued["confidence_executable_trade"] == 0.82
    assert queued["dynamic_exploration_floor"] == 0.66
    assert queued["exploration_floor_inputs"] == {"loss_cluster_quarantine": False}
    assert queued["paper_risk_controller_exploration_eligible"] is True
    assert queued["paper_risk_controller_exploration_above_floor"] is True
    assert queued["paper_signal"]["generated_utc"] == "2026-07-10T03:28:29.000Z"
    assert queued["paper_signal"]["available_at"] == "2026-07-10T03:00:00.000Z"
    assert queued["paper_signal"]["confidence_executable_trade"] == 0.82
    assert queued["paper_signal"]["dynamic_exploration_floor"] == 0.66
    assert queued["paper_signal"]["exploration_floor_inputs"] == {
        "loss_cluster_quarantine": False
    }
    assert queued["paper_signal"]["paper_risk_controller_exploration_eligible"] is True
    assert queued["paper_signal"]["paper_risk_controller_exploration_above_floor"] is True
    assert queued["paper_signal"]["source_generated_utc"] == "2026-07-10T03:00:01.000Z"
    assert queued["paper_signal"]["source_prediction_status"] == "CURRENT_RUNTIME_PAPER_SIGNAL"
    assert queued["paper_signal"]["market_state_id"] == (
        "strategy_supply_market_state:snap_strategy_supply_test"
    )
    assert queued["paper_signal"]["valid_for_paper"] is True
    assert queued["paper_signal"]["entry_feature_snapshot_id"] == "snap_strategy_supply_test"
    assert queued["paper_signal"]["entry_feature_available_at"] == "2026-07-10T03:00:00.000Z"
    assert queued["paper_signal"]["entry_feature_generated_at"] == "2026-07-10T03:00:01.000Z"
    assert queued["paper_signal"]["entry_feature_cutoff"] == "2026-07-10T02:59:59.999Z"
    assert queued["paper_signal"]["entry_feature_decision_time"] == "2026-07-10T03:00:01.000Z"
    assert queued["paper_signal"]["paper_only"] is True
    assert queued["paper_signal"]["routes_to_live"] is False
    assert queued["paper_signal"]["places_real_order"] is False
    assert queued["exit_plan"]["status"] == "INTERNAL_PAPER_EXIT_PLAN_ACTIVE"
    assert queued["exit_plan"]["paper_only"] is True
    assert queued["exit_plan"]["routes_to_live"] is False
    assert queued["exit_plan"]["places_real_order"] is False
    assert queued["exit_plan"]["stop_loss_price"] < row["current_price"]
    assert queued["paper_signal"]["exit_plan"] == queued["exit_plan"]


def test_materialization_queue_accepts_at_publish_time_without_extending_source_expiry() -> None:
    client = FakeRedis()
    inventory_generated_utc = "2026-07-10T03:00:10.000Z"
    queue_published_at = "2026-07-10T03:00:40.000Z"
    row = {
        "candidate_id": "hyp-visible-queue-time",
        "prediction_id": "hyp-visible-queue-time",
        "signal_id": "sig-visible-queue-time",
        "symbol": "ORDIUSDT",
        "timeframe": "1m",
        "side": "long",
        "selected_action": "long",
        "available_at": "2026-07-10T03:00:00.000Z",
        "decision_time": "2026-07-10T03:00:01.000Z",
        "generated_utc": "2026-07-10T03:00:01.000Z",
        "feature_cutoff": "2026-07-10T02:59:59.999Z",
        "risk_decision": "PASS",
        "risk_decision_id": "rd-visible-queue-time",
        "orchestrator_decision": "PASS",
        "orchestrator_decision_id": "dec-visible-queue-time",
        "allocator_decision": "PASS",
        "allocator_decision_id": "alloc-visible-queue-time",
        "feature_vector_hash": "feature-hash-visible-queue-time",
        "provider_feature_hashes": {"binance": "hash-binance"},
        "market_state_integrity_score": 91.0,
        "confidence_executable_trade": 0.82,
        "dynamic_exploration_floor": 0.66,
        "paper_risk_controller_exploration_eligible": True,
        "paper_risk_controller_exploration_above_floor": True,
        "paper_exploration_paper_fill_allowed": True,
        "expected_net_pnl_usd": 1.2,
        "expected_max_loss_usd": 0.4,
        "recommended_notional_usd": 100.0,
        "recommended_leverage": 0.25,
        "recommended_margin_mode": "isolated_paper",
        "liquidation_buffer_usd": 24.0,
        "current_price": 8.1,
    }

    status = _publish_materialization_queue(
        client,
        [row],
        generated_utc=inventory_generated_utc,
        queue_published_at=queue_published_at,
    )
    queue_payload = client.data[EXPLORATION_MATERIALIZATION_QUEUE_KEY]
    queued = queue_payload["rows"][0]

    assert status["generated_utc"] == queue_published_at
    assert status["queue_published_at"] == queue_published_at
    assert status["inventory_generated_utc"] == inventory_generated_utc
    assert status["accepted_at_semantics"] == "QUEUE_PUBLISH_TIME_SOURCE_EXPIRY_UNCHANGED"
    assert queue_payload["generated_utc"] == queue_published_at
    assert queue_payload["inventory_generated_utc"] == inventory_generated_utc
    assert queued["accepted_at"] == queue_published_at
    assert queued["queue_published_at"] == queue_published_at
    assert queued["inventory_generated_utc"] == inventory_generated_utc
    assert queued["accepted_at_semantics"] == "QUEUE_PUBLISH_TIME_SOURCE_EXPIRY_UNCHANGED"
    assert queued["source_freshness_time"] == "2026-07-10T03:00:01.000Z"
    assert queued["source_expires_at"] == "2026-07-10T03:02:01.000Z"
    assert queued["expires_at"] == "2026-07-10T03:02:01.000Z"
    assert queued["source_stale_at_acceptance"] is False
    assert queued["source_age_seconds_at_acceptance"] == 39
    assert status["per_id_decision_store"]["risk_records_resolved"] == 1
    assert status["per_id_decision_store"]["orchestrator_records_resolved"] == 1
    assert client.data["v2:decision:risk:rd-visible-queue-time"][
        "generated_utc"
    ] == queue_published_at
    assert client.data["v2:decision:orchestrator:dec-visible-queue-time"][
        "generated_utc"
    ] == queue_published_at


def test_paper_exploration_stale_source_not_queued_and_gets_counterfactual(
    tmp_path: Path,
) -> None:
    client = PaperExplorationStaleSourceRedis()
    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")

    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert row["paper_exploration_current_blocker"] == "MATERIALIZATION_PREQUEUE_BLOCKED"
    assert any(
        reason.startswith("MATERIALIZATION_PREQUEUE_SOURCE_STALE:")
        for reason in row["paper_exploration_materialization_prequeue_block_reasons"]
    )
    queue_status = result["summary"]["paper_exploration_materialization_queue_status"]
    assert queue_status["accepted_dry_run_rows"] == 0
    assert queue_status["queued_count"] == 0
    assert queue_status["prequeue_rejected_count"] == 1
    assert queue_status["prequeue_counterfactual_count"] == 1
    feedback_rows = client.data[PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY]
    assert len(feedback_rows) == 1
    feedback = feedback_rows[0]
    assert feedback["paper_only"] is True
    assert feedback["routes_to_live"] is False
    assert feedback["places_real_order"] is False
    assert feedback["counts_as_A_plus"] is False
    assert feedback["counts_as_live_ready"] is False
    assert feedback["trainer_consumable"] is False
    assert feedback["future_label_pending"] is True
    assert any(
        reason.startswith("MATERIALIZATION_PREQUEUE_SOURCE_STALE:")
        for reason in feedback["block_reasons_if_rejected"]
    )


def test_paper_exploration_future_source_is_queued_pending_without_counterfactual(
    tmp_path: Path,
) -> None:
    client = PaperExplorationFutureSourceRedis()
    result = build_inventory(client=client, output_dir=tmp_path, max_prediction_keys=20)

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-paper-explore")
    queue_status = result["summary"]["paper_exploration_materialization_queue_status"]
    queue_payload = client.data["v2:paper:exploration:materialization_queue"]

    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_exploration_paper_fill_allowed"] is True
    assert row["paper_exploration_materialization_queue_ready"] is True
    assert row["paper_exploration_materialization_prequeue_block_reasons"] == []
    assert queue_status["accepted_dry_run_rows"] == 1
    assert queue_status["queued_count"] == 1
    assert queue_status["active_count"] == 0
    assert queue_status["pending_source_time_count"] == 1
    assert queue_status["prequeue_rejected_count"] == 0
    assert queue_status["prequeue_counterfactual_count"] == 0
    assert len(queue_status["pending_source_rows"]) == 1
    assert (
        queue_status["pending_source_rows"][0]["earliest_eligible_decision_time"]
        is not None
    )
    assert len(queue_payload["rows"]) == 1
    assert queue_payload["rows"][0]["source_freshness_pending"] is True
    assert queue_payload["rows"][0]["source_freshness_hard_fail"] is False
    assert queue_payload["rows"][0]["earliest_eligible_decision_time"] is not None
    assert PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_KEY not in client.data


def test_materialization_queue_uses_safe_generated_at_and_derives_funding_bps() -> None:
    row = {
        "candidate_id": "hyp-safe-timestamp",
        "prediction_id": "hyp-safe-timestamp",
        "signal_id": "hyp-safe-timestamp",
        "symbol": "ORDIUSDT",
        "timeframe": "15m",
        "side": "long",
        "available_at": "2026-07-10T03:00:00.000Z",
        "decision_time": "2026-07-10T03:00:01.000Z",
        "generated_utc": "2026-07-10T03:00:05.000Z",
        "feature_cutoff": "2026-07-10T02:59:59.999Z",
        "feature_snapshot_id": "snap_safe_timestamp",
        "market_state_integrity_score": 91.0,
        "expected_net_pnl_usd": 1.2,
        "expected_max_loss_usd": 0.4,
        "expected_funding_usd": 0.01,
        "recommended_notional_usd": 100.0,
        "current_price": 8.1,
    }

    queued = _build_materialization_queue_row(
        row,
        accepted_at="2026-07-10T03:28:29.000Z",
    )

    signal = queued["paper_signal"]
    assert signal["entry_feature_generated_at"] == "2026-07-10T03:00:00.000Z"
    assert signal["entry_feature_generated_at_source"] == (
        "entry_feature_available_at_fallback"
    )
    assert "source_generated_utc_after_entry_feature_decision_time" in signal[
        "entry_feature_generated_at_rejections"
    ]
    assert signal["expected_funding_bps"] == 1.0
    assert signal["expected_funding_bps_source"] == (
        "strategy_supply_expected_funding_usd_to_bps"
    )
    assert signal["expected_funding_bps_fallback"] is False
    assert queued["exit_plan"]["status"] == "INTERNAL_PAPER_EXIT_PLAN_ACTIVE"
    assert queued["exit_plan"]["time_exit_at"] == "2026-07-10T04:13:29.000Z"


def test_paper_exploration_above_floor_missing_decisions_get_row_level_blocks(tmp_path: Path) -> None:
    result = build_inventory(
        client=PaperExplorationMissingDecisionRedis(),
        output_dir=tmp_path,
        max_prediction_keys=20,
    )

    row = next(row for row in result["rows"] if row["candidate_id"] == "cand-missing-risk-orch")
    assert row["paper_risk_controller_exploration_above_floor"] is True
    assert row["paper_risk_controller_exploration_eligible"] is False
    assert row["paper_exploration_risk_controller_input_written"] is True
    assert row["paper_exploration_orchestrator_input_written"] is True
    assert row["risk_decision"] == "BLOCKED"
    assert row["orchestrator_decision"] == "BLOCKED"
    assert row["paper_exploration_risk_controller_decision"] == "BLOCKED"
    assert row["paper_exploration_orchestrator_decision"] == "BLOCKED"
    assert row["paper_exploration_current_blocker"] == "ACTIVE_QUARANTINE_BLOCK_BEFORE_RISK"
    assert row["paper_exploration_paper_fill_allowed"] is False
    assert "RISK_CONTROLLER_DECISION_NOT_FILL_ELIGIBLE:BLOCKED" in row["paper_exploration_paper_fill_block_reasons"]
    assert row["paper_exploration_counts_as_A_plus"] is False
    assert row["paper_exploration_counts_as_live_ready"] is False
    assert row["paper_exploration_routes_to_live"] is False
    assert row["paper_exploration_places_real_order"] is False
    assert result["summary"]["paper_risk_controller_exploration_above_floor_count"] == 1
    assert result["summary"]["paper_risk_controller_exploration_risk_controller_seen_rows"] == 1
    assert result["summary"]["paper_risk_controller_exploration_orchestrator_seen_rows"] == 1
    assert result["summary"]["paper_risk_controller_exploration_unknown_rows"] == 0
