"""Integration tests for V2 native RL/MASA/PPO CUDA trainer package."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    ACTION_LABELS,
    LIVE_GATE_BLOCKED,
    TRAINER_SOURCE,
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.environment import (
    V2PaperShadowHybridEnv,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    native_risk_decision_from_orchestrator,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    default_paths,
    run_hybrid_trainer_cycle,
    write_runtime_artifacts,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record,
)

REPO = Path(__file__).resolve().parents[5]

_CLEAN_TRUST_FEATURES = {
    "last_price": 101.0,
    "open": 100.0,
    "high": 102.0,
    "low": 99.0,
    "close": 101.0,
    "volume": 1000.0,
    "mark_price": 101.0,
    "index_price": 100.8,
    "basis_pct": 0.002,
    "quote_volume": 101000.0,
    "num_trades": 120.0,
    "taker_buy_base_vol": 600.0,
    "taker_buy_quote_vol": 60600.0,
    "taker_sell_base_vol": 400.0,
    "taker_sell_quote_vol": 40400.0,
    "taker_buy_ratio": 0.6,
    "taker_sell_ratio": 0.4,
    "ob_best_bid": 100.9,
    "ob_best_ask": 101.1,
    "ob_mid_price": 101.0,
    "best_bid_size": 12.5,
    "best_ask_size": 11.8,
    "orderbook_depth_usd": 500000.0,
    "depth_total_usd": 500000.0,
    "depth_usd": 500000.0,
    "estimated_price_impact_bps": 1.7,
    "update_age_ms": 75.0,
    "source_latency_ms": 42.0,
    "depth_vs_tape_divergence": 0.05,
    "feed_latency_ms": 38.0,
    "cancel_pressure": 0.14,
    "book_trade_divergence": 0.04,
    "cross_venue_confirmation": 0.88,
    "sweep_risk": 0.16,
    "post_sweep_reversal_probability": 0.24,
    "realized_slippage_error": 0.02,
    "ATR": 1.2,
    "bollinger_upper": 103.0,
    "bollinger_middle": 101.0,
    "bollinger_lower": 99.0,
    "liquidation_long_level": 95.0,
    "liquidation_short_level": 107.0,
    "liquidation_distance_pct": 0.06,
    "liquidation_strength": 0.4,
    "last_liq_bps_24h": 12.0,
    "liquidation_is_stale": 0.0,
    "tape_imbalance": 0.1,
    "order_flow_imbalance": 0.08,
    "surf_score": 0.52,
    "defillama_score": 0.48,
    "fear_greed_context": 0.5,
    "mempool_context": 0.35,
    "coingecko_liquidity_score": 0.62,
    "coingecko_momentum_score": 0.58,
    "surf_market_price_signal_score": 0.57,
    "coinglass_derivatives_score": 0.54,
    "defillama_tvl_momentum_score": 0.45,
    "news_attention_score": 0.33,
    "news_sentiment_score": 0.29,
    "fear_greed_score": 0.51,
    "btc_mempool_pressure_score": 0.21,
    "whale_ask_pressure_score": 0.22,
    "whale_wall_imbalance_score": 0.63,
    "whale_wall_count_score": 0.58,
    "whale_wall_event_count": 3.0,
    "whale_bid_wall_notional_usd": 250000.0,
    "whale_ask_wall_notional_usd": 220000.0,
    "whale_total_wall_notional_usd": 470000.0,
    "nearest_bid_wall_distance_bps": 8.0,
    "nearest_ask_wall_distance_bps": 9.0,
}


class _MemoryClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str):
        self.store[key] = value
        return True


def _closed_candle_row(
    *,
    symbol: str,
    timeframe: str,
    open_time_ms: int,
    close_time_ms: int,
    price: float = 101.0,
    volume: float = 1000.0,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "exchange": "binance",
        "timeframe": timeframe,
        "candle_id": f"{symbol}_{timeframe}_{open_time_ms}",
        "candle_open_time": open_time_ms,
        "candle_close_time": close_time_ms,
        "open_time": open_time_ms,
        "close_time": close_time_ms,
        "event_time": close_time_ms,
        "ingested_at": close_time_ms + 1_000,
        "available_at": close_time_ms + 1_000,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "source": "pytest_seed",
        "raw_payload_hash": f"hash_{symbol}_{timeframe}_{open_time_ms}",
        "open": price,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price,
        "volume": volume,
        "quote_volume": price * volume,
        "num_trades": 120,
        "taker_buy_base_vol": volume * 0.6,
        "taker_buy_quote_vol": price * volume * 0.6,
    }


def _seed(client: _MemoryClient, *, symbols=("BTCUSDT",), timeframes=("1m",)) -> None:
    decision_time = "2026-06-11T12:05:00Z"
    generated_at = "2026-06-11T12:05:00Z"
    available_at = "2026-06-11T12:04:59Z"
    causal_source_clock = {"available_at": available_at}
    candle_open_time = "2026-06-11T12:04:00Z"
    candle_close_time = "2026-06-11T12:04:00Z"
    base_close_times = {
        "1m": (1_781_179_440_000, 1_781_179_499_000),
        "5m": (1_781_179_200_000, 1_781_179_499_000),
        "15m": (1_781_178_300_000, 1_781_179_199_000),
        "1h": (1_781_175_600_000, 1_781_179_199_000),
        "4h": (1_781_164_800_000, 1_781_179_199_000),
    }
    for symbol in symbols:
        for snapshot_tf in REQUIRED_DECISION_TIMEFRAMES:
            open_ms, close_ms = base_close_times[snapshot_tf]
            rows = [
                _closed_candle_row(
                    symbol=symbol,
                    timeframe=snapshot_tf,
                    open_time_ms=open_ms,
                    close_time_ms=close_ms,
                )
            ]
            client.set(
                f"v2:market:ohlcv_closed:binance:{symbol}:{snapshot_tf}",
                json.dumps(rows),
            )
        for tf in timeframes:
            client.set(
                f"v2:features:latest:{symbol}:{tf}",
                json.dumps(
                    {
                        "feature_snapshot_id": f"v2_fsnap_{symbol}_{tf}_native_hybrid_test",
                        "feature_freshness_state": "CURRENT",
                        "freshness_state": "FRESH",
                        "features": {
                            "ret_pct": 0.001,
                            "log_return": 0.001,
                            "range_pct": 0.004,
                            "body_pct": 0.001,
                            "true_range_pct": 0.005,
                            "ema_12": 101.0,
                            "ema_26": 100.0,
                            "rsi_14": 56.0,
                            "macd": 0.08,
                            "macd_signal": 0.04,
                            "macd_hist": 0.04,
                            "bb_width_pct": 0.012,
                            "htf_ret_pct": 0.002,
                            "htf_rsi_14": 58.0,
                            "bid_ask_spread_bps": 3.0,
                            "depth_imbalance": 0.15,
                            "micro_price": 101.0,
                            "toxicity_proxy": 0.1,
                            "paper_position_present": 0,
                            **_CLEAN_TRUST_FEATURES,
                        },
                        "missing_feature_flags": [],
                        "stale_feature_flags": [],
                        "generated_at": generated_at,
                        "generated_utc": generated_at,
                        "decision_time": decision_time,
                        "decision_cutoff": decision_time,
                        "feature_cutoff": candle_close_time,
                        "available_at": available_at,
                        "source_available_time": available_at,
                        "source_received_time_est": available_at,
                        "source_event_time": available_at,
                        "candle_closed_confirmed": True,
                        "candle_open_time": candle_open_time,
                        "candle_close_time": candle_close_time,
                        "latency_ms": 50,
                        "price_disagreement_bps": 0.0,
                        "duplicate_event_count": 0,
                        "out_of_order_event_count": 0,
                        "missing_candle_count": 0,
                        "backfilled": False,
                        "is_backfilled": False,
                        "source_mode": "paper",
                        "replay_snapshot_id": f"replay_{symbol}_{tf}",
                        "replay_snapshot_key": f"v2:replay:snapshots:{symbol}:{tf}",
                    }
                ),
            )
            feature_snapshot = json.loads(client.store[f"v2:features:latest:{symbol}:{tf}"])
            feature_snapshot["symbol"] = symbol
            feature_snapshot["timeframe"] = tf
            archived_feature_snapshot = build_archive_record(
                snapshot_id=feature_snapshot["feature_snapshot_id"],
                symbol=symbol,
                timeframe=tf,
                feature_cutoff=feature_snapshot["feature_cutoff"],
                decision_time=feature_snapshot["decision_time"],
                available_at=feature_snapshot["available_at"],
                mtf_snapshot_id=f"mtf_{symbol}_{tf}",
                features=dict(feature_snapshot["features"]),
                missing_mask={
                    name: False for name in feature_snapshot["features"]
                },
                stale_mask={
                    name: False for name in feature_snapshot["features"]
                },
                source_availability={
                    name: True for name in feature_snapshot["features"]
                },
                source_hashes={"feature_vector_hash": f"hash_{symbol}_{tf}"},
                created_at=feature_snapshot["generated_at"],
                extra={
                    "candle_open_time": feature_snapshot["candle_open_time"],
                    "candle_close_time": feature_snapshot["candle_close_time"],
                    "candle_closed_confirmed": True,
                    "feature_freshness_state": "CURRENT",
                },
            )
            client.set(
                f"v2:features:snapshot:{feature_snapshot['feature_snapshot_id']}",
                json.dumps(archived_feature_snapshot),
            )

            client.set(
                f"v2:features:ta:{symbol}:{tf}",
                json.dumps({"indicators": {"ema_12": 101.0, "ema_26": 100.0, "rsi_14": 56.0}}),
            )
            client.set(
                f"v2:market:prices:{symbol}",
                json.dumps(
                    {
                        "price": 101.0,
                        "last_price": 101.0,
                        "mark_price": 101.0,
                        "index_price": 100.8,
                        "ticker_24hr": {
                            "lastPrice": 101.0,
                            "quoteVolume": 101000.0,
                        },
                        "funding": {
                            "markPrice": 101.0,
                            "indexPrice": 100.8,
                            "basis_pct": 0.002,
                        },
                    }
                ),
            )
            client.set(
                f"v2:market:ohlcv:binance:{symbol}:{tf}",
                json.dumps({"close": 101.0, "volume": 1000.0}),
            )
            client.set(
                f"v2:market:orderbook:{symbol}",
                json.dumps(
                    {
                        "spread_bps": 3.0,
                        "depth_imbalance": 0.15,
                        "orderbook_depth_usd": 500000.0,
                        "depth_total_usd": 500000.0,
                        "depth_usd": 500000.0,
                        "bids": [["100.9", "1200"]],
                        "asks": [["101.1", "1100"]],
                    }
                ),
            )
            client.set(f"v2:market:funding:{symbol}", json.dumps({"funding_rate": 0.0001}))
            client.set(f"v2:market:open_interest:{symbol}", json.dumps({"open_interest": 1000000.0}))
            client.set(f"v2:market:open_interest_hist:{symbol}:5m", json.dumps({"change_pct": 0.01}))
            client.set(
                f"v2:market:long_short:{symbol}",
                json.dumps(
                    {
                        **causal_source_clock,
                        "long_short_ratio": 1.5,
                        "long_account_ratio": 0.6,
                        "short_account_ratio": 0.4,
                    }
                ),
            )
            client.set(
                f"v2:market:microstructure:{symbol}",
                json.dumps(
                    {
                        "micro_price": 101.0,
                        "toxicity_proxy": 0.1,
                        "tape_imbalance": 0.1,
                        "order_flow_imbalance": 0.08,
                        "depth_vs_tape_divergence": 0.05,
                    }
                ),
            )
            client.set(
                f"v2:market:liquidation_levels:{symbol}",
                json.dumps(
                    {
                        "nearest_distance_bps": 150.0,
                        "long_level": 95.0,
                        "short_level": 107.0,
                        "distance_pct": 0.06,
                        "strength": 0.4,
                        "is_stale": 0.0,
                    }
                ),
            )
            client.set(f"v2:altdata:public_intel:symbol:{symbol}", json.dumps({"public_intel_score": 0.5}))
            client.set(
                f"v2:altdata:public_intel:symbol:{symbol}",
                json.dumps(
                    {
                        **causal_source_clock,
                        "score": 0.5,
                        "public_intel_score": 0.5,
                        "defillama_score": 0.48,
                        "fear_greed_context": 0.5,
                        "mempool_context": 0.35,
                        "defillama_liquidity_score": 0.4,
                        "defillama_tvl_momentum_score": 0.45,
                        "news_attention_score": 0.33,
                        "news_sentiment_score": 0.29,
                        "fear_greed_score": 0.51,
                        "btc_mempool_pressure_score": 0.21,
                    }
                ),
            )
            client.set(
                f"v2:altdata:whale_walls:symbol:{symbol}",
                json.dumps(
                    {
                        **causal_source_clock,
                        "whale_wall_score": 0.8,
                        "whale_bid_pressure_score": 0.85,
                        "whale_ask_pressure_score": 0.22,
                        "whale_wall_imbalance_score": 0.63,
                        "whale_wall_count_score": 0.58,
                        "whale_wall_event_count": 3.0,
                        "whale_bid_wall_notional_usd": 250000.0,
                        "whale_ask_wall_notional_usd": 220000.0,
                        "whale_total_wall_notional_usd": 470000.0,
                        "nearest_bid_wall_distance_bps": 8.0,
                        "nearest_ask_wall_distance_bps": 9.0,
                    }
                ),
            )
            client.set(
                f"v2:altdata:symbol_score:{symbol}",
                json.dumps(
                    {
                        **causal_source_clock,
                        "altdata_symbol_score": 0.5,
                        "provider_availability_score": 1.0,
                        "altdata_freshness_score": 1.0,
                        "public_intel_score": 0.5,
                        "coingecko_discovery_score": 0.6,
                        "defillama_liquidity_score": 0.4,
                        "whale_wall_score": 0.8,
                        "whale_bid_pressure_score": 0.85,
                        "surf_score": 0.52,
                        "coingecko_liquidity_score": 0.62,
                        "coingecko_momentum_score": 0.58,
                        "surf_market_price_signal_score": 0.57,
                        "coinglass_derivatives_score": 0.54,
                        "defillama_tvl_momentum_score": 0.45,
                        "news_attention_score": 0.33,
                        "news_sentiment_score": 0.29,
                        "fear_greed_score": 0.51,
                        "btc_mempool_pressure_score": 0.21,
                        "whale_ask_pressure_score": 0.22,
                        "whale_wall_imbalance_score": 0.63,
                        "whale_wall_count_score": 0.58,
                        "whale_wall_event_count": 3.0,
                        "whale_bid_wall_notional_usd": 250000.0,
                        "whale_ask_wall_notional_usd": 220000.0,
                        "whale_total_wall_notional_usd": 470000.0,
                        "nearest_bid_wall_distance_bps": 8.0,
                        "nearest_ask_wall_distance_bps": 9.0,
                    }
                ),
            )
    client.set("v2:liquidations:events", json.dumps({"count_5m": 1}))
    client.set("v2:risk:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:orchestrator:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:paper:positions", json.dumps({"position_present": 0, "unrealized_bps": 0.0}))
    client.set("v2:paper:ledger", json.dumps({"entries": []}))
    client.set("v2:paper:position_history", json.dumps({"entries": []}))


def _trainer_feedback_row(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    realized_pnl_bps: float = 25.0,
) -> dict[str, object]:
    return {
        "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": "pipeline_trust_v3_20260612",
        "producer": "pytest",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": "2026-06-11T12:05:00Z",
        "generated_utc": "2026-06-11T12:05:00Z",
        "generated_at": "2026-06-11T12:05:00Z",
        "trainer_feedback_source": "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE",
        "trainer_consumable": True,
        "accepted_for_training": True,
        "valid_for_training": True,
        "missing_feedback_fields": [],
        "symbol": symbol,
        "timeframe": timeframe,
        "prediction_id": f"pred_{symbol}_{timeframe}",
        "entry_prediction_id": f"pred_{symbol}_{timeframe}",
        "exit_prediction_id": f"pred_exit_{symbol}_{timeframe}",
        "signal_id": f"signal_{symbol}_{timeframe}",
        "decision_id": f"decision_{symbol}_{timeframe}",
        "entry_signal_id": f"signal_{symbol}_{timeframe}",
        "exit_signal_id": f"signal_exit_{symbol}_{timeframe}",
        "feature_snapshot_id": f"v2_fsnap_{symbol}_{timeframe}_native_hybrid_test",
        "entry_feature_snapshot_id": f"v2_fsnap_{symbol}_{timeframe}_native_hybrid_test",
        "mtf_snapshot_id": f"mtf_{symbol}_{timeframe}",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "replay_snapshot_id": f"replay_{symbol}_{timeframe}",
        "replay_snapshot_key": f"v2:replay:snapshots:{symbol}:{timeframe}",
        "feature_cutoff": "2026-06-11T12:04:00Z",
        "decision_cutoff": "2026-06-11T12:04:00Z",
        "decision_cutoff_time_est": "2026-06-11T12:05:00Z",
        "decision_time": "2026-06-11T12:05:00Z",
        "decision_time_est": "2026-06-11T12:05:00Z",
        "available_at": "2026-06-11T12:04:59Z",
        "source_available_time": "2026-06-11T12:04:59Z",
        "source_received_time_est": "2026-06-11T12:04:59Z",
        "source_event_time_est": "2026-06-11T12:04:00Z",
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-11T12:04:00Z",
        "candle_close_time": "2026-06-11T12:04:00Z",
        "latency_ms": 50,
        "feature_freshness_state": "CURRENT",
        "market_state_integrity_score": 96.25,
        "selected_action": "long" if realized_pnl_bps >= 0 else "short",
        "model_version": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        "checkpoint_id": "ckpt_pytest",
        "source_hashes": {
            "feature_vector_hash": f"hash_{symbol}_{timeframe}",
            "input_feature_hash": f"hash_{symbol}_{timeframe}",
        },
        "market_state_id": f"market_state_{symbol}_{timeframe}",
        "entry_market_state_id": f"market_state_{symbol}_{timeframe}",
        "strategy_id": "strategy_breakout_major_move",
        "strategy_family": "breakout",
        "strategy_subtype": "correlated_major_squeeze",
        "entry_reason": "paper_only_major_move_candidate",
        "action": "long" if realized_pnl_bps >= 0 else "short",
        "hedge_state": "none",
        "hedge_reason": "no_hedge_context",
        "exit_reason": "take_profit" if realized_pnl_bps >= 0 else "stop_loss",
        "entry_price": 100.0,
        "exit_price": 100.0 + (realized_pnl_bps / 100.0),
        "realized_pnl": realized_pnl_bps / 10_000.0,
        "realized_pnl_bps": realized_pnl_bps,
        "realized_net_pnl_bps": realized_pnl_bps,
        "realized_net_pnl_usd": realized_pnl_bps / 10.0,
        "directional_outcome": "UP" if realized_pnl_bps > 0 else "DOWN" if realized_pnl_bps < 0 else "FLAT",
        "trade_outcome": "WIN" if realized_pnl_bps > 0 else "LOSS" if realized_pnl_bps < 0 else "BREAKEVEN",
        "action_was_profitable": realized_pnl_bps > 0,
        "holding_period": 180,
        "fees": 0.01,
        "slippage": 0.01,
        "funding": 0.0,
        "MFE": 20.0,
        "MAE": 5.0,
        "hold_time_seconds": 180,
        "exit_time": "2026-06-11T12:10:00Z",
        "market_regime": "major_move_breakout",
        "market_regime_at_entry": "major_move_breakout",
        "market_regime_at_exit": "major_move_breakout",
        "liquidity_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "liquidity_score": 0.8,
            "orderbook_depth_usd": 500000.0,
            "depth_imbalance": 0.15,
            "whale_bid_wall_notional_usd": 250000.0,
            "whale_ask_wall_notional_usd": 220000.0,
        },
        "liquidity_zone_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "liquidity_score": 0.8,
            "orderbook_depth_usd": 500000.0,
            "nearest_bid_wall_distance_bps": 8.0,
            "nearest_ask_wall_distance_bps": 9.0,
        },
        "liquidation_distance_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "nearest_liquidation_level_above": 107.0,
            "nearest_liquidation_level_below": 95.0,
            "liquidation_short_strength": 0.4,
            "liquidation_long_strength": 0.3,
            "liquidation_sweep_target_short_distance_bps": 80.0,
            "liquidation_sweep_target_long_distance_bps": 120.0,
        },
        "liquidation_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "nearest_liquidation_level_above": 107.0,
            "nearest_liquidation_level_below": 95.0,
            "liquidation_short_strength": 0.4,
            "liquidation_long_strength": 0.3,
            "liquidation_sweep_target_short_distance_bps": 80.0,
            "liquidation_sweep_target_long_distance_bps": 120.0,
        },
        "microstructure_context": {
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:pytest",
            "bid_ask_spread_bps": 1.4,
        },
        "major_move_context": {
            "signal_id": f"major_move_{symbol}_{timeframe}",
            "direction": "long" if realized_pnl_bps >= 0 else "short",
            "evidence_score": 0.88,
            "paper_only": True,
        },
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "actual_observed_spread_entry_bps": 1.4,
        "actual_observed_spread_exit_bps": 1.6,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:pytest",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:pytest",
        "expected_slippage_bps": 0.9,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "realized_slippage_bps": 1.0,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "mfe_bps": 20.0,
        "mfe_usd": 1.0,
        "mae_bps": 5.0,
        "mae_usd": 0.25,
        "intra_trade_high_price": 101.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
        "oi_funding_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "funding_bps": 0.1,
            "open_interest": 1000000.0,
            "oi_change_pct": 0.18,
            "long_short_ratio": 1.5,
        },
        "public_intel_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "public_intel_score": 0.5,
            "news_attention_score": 0.4,
            "news_sentiment_score": 0.29,
        },
        "premium_ingestor_context_status": "PREMIUM_CONTEXT_READY",
        "premium_ingestor_context_sources": {
            "liquidity_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "liquidity_zone_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "liquidation_distance_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "liquidation_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "microstructure_context": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:pytest",
            "oi_funding_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
            "public_intel_context": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS:pytest",
        },
        "premium_ingestor_missing_contexts": [],
        "liquidation_engine_context_status": "LIQUIDATION_ENGINE_CONTEXT_READY",
        "drawdown_context": {"current_drawdown_bps": 0.0},
        "drawdown_at_entry": 0.0,
        "risk_context": {"paper_only": True},
        "market_structure_context": {"breakout_level": 100.5},
        "future_window_label_source": "closed_trade_outcome",
        "features": dict(_CLEAN_TRUST_FEATURES),
    }


def _bind_feedback_to_snapshot(
    client: _MemoryClient,
    row: dict[str, object],
) -> dict[str, object]:
    snapshot_id = str(row["entry_feature_snapshot_id"])
    snapshot = json.loads(client.store[f"v2:features:snapshot:{snapshot_id}"])
    snapshot_hash = str(snapshot["content_sha256"])
    bound = dict(row)
    source_hashes = dict(bound.get("source_hashes") or {})
    source_hashes["feature_snapshot_content_sha256"] = snapshot_hash
    bound.update(
        {
            "durable_feature_snapshot_archive_content_sha256": snapshot_hash,
            "feature_snapshot_content_sha256": snapshot_hash,
            "entry_feature_snapshot_content_sha256": snapshot_hash,
            "source_hashes": source_hashes,
        }
    )
    return bound


def _seed_trainer_feedback(
    client: _MemoryClient,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    realized_pnl_bps: float = 25.0,
) -> None:
    client.set(
        "v2:trainer:feedback:outcomes",
        json.dumps(
            [
                _bind_feedback_to_snapshot(
                    client,
                    _trainer_feedback_row(
                        symbol=symbol,
                        timeframe=timeframe,
                        realized_pnl_bps=realized_pnl_bps,
                    ),
                )
            ]
        ),
    )


def test_native_trainer_saves_and_loads_npz_weight_blob(tmp_path: Path) -> None:
    model_dir = tmp_path / ".local_models/v2_native_rl_masa_ppo"
    manager = V2HybridCheckpointManager(model_dir)
    model = V2HybridPolicyModel(input_dim=4)
    vector = [0.2, -0.1, 0.4, 0.8]
    before = model.forward(vector)

    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        write_weight_blob=True,
    )

    assert manifest.weight_blob_written is True
    assert manifest.weight_file_format == "npz"
    assert manifest.weight_file_path is not None
    assert Path(manifest.weight_file_path).exists()
    assert Path(manifest.weight_file_path).stat().st_size > 0

    restored = V2HybridPolicyModel(input_dim=4)
    load_status = manager.load_latest_weights(restored)
    after = restored.forward(vector)

    assert load_status["latest_checkpoint_loadable"] is True
    assert load_status["model_state_restored"] is True
    assert load_status["optimizer_state_restored_or_intentionally_not_required"] is True
    assert after.expected_move_bps == pytest.approx(before.expected_move_bps, rel=1e-6, abs=1e-6)
    assert after.confidence_raw == pytest.approx(before.confidence_raw, rel=1e-6, abs=1e-6)


def test_tensor_builder_masks_missing_values_without_silent_zero_fill() -> None:
    client = _MemoryClient()
    _seed(client)
    # Remove one source to force a masked placeholder.
    client.store.pop("v2:market:funding:BTCUSDT")
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    tensor = example.tensor
    funding_idx = tensor.feature_names.index("funding_rate")
    assert tensor.values[funding_idx] == 0.0
    assert tensor.missing_mask[funding_idx] == 1
    assert "funding_rate" in tensor.missing_feature_names
    assert len(tensor.values) == len(tensor.missing_mask) == len(tensor.stale_mask)


def test_tensor_builder_masks_non_current_feature_freshness() -> None:
    client = _MemoryClient()
    _seed(client)
    latest = json.loads(client.store["v2:features:latest:BTCUSDT:1m"])
    latest["feature_freshness_state"] = "MISSING_CLOSED_OHLCV"
    latest["trainer_consumable"] = False
    latest["valid_for_prediction"] = False
    latest["valid_for_paper"] = False
    client.set("v2:features:latest:BTCUSDT:1m", json.dumps(latest))
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")

    assert example.row_classification != "TRAINABLE"
    assert example.trust_row["trainer_consumable"] is False
    assert example.tensor.stale_feature_names
    assert any(example.tensor.stale_mask)


def test_tensor_loader_reads_symbol_scoped_altdata_keys() -> None:
    client = _MemoryClient()
    _seed(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    tensor = example.tensor
    by_name = dict(zip(tensor.feature_names, tensor.values))
    assert by_name["long_short_ratio"] == 1.5
    assert by_name["long_account_ratio"] == 0.6
    assert by_name["short_account_ratio"] == 0.4
    assert by_name["altdata_symbol_score"] == 0.5
    assert by_name["public_intel_score"] == 0.5
    assert by_name["coingecko_discovery_score"] == 0.6
    assert by_name["defillama_liquidity_score"] == 0.4
    assert by_name["whale_wall_score"] == 0.8
    assert by_name["whale_bid_pressure_score"] == 0.85
    assert "v2:altdata:public_intel:symbol:BTCUSDT" in example.payload_keys
    assert "v2:altdata:whale_walls:symbol:BTCUSDT" in example.payload_keys


def test_tensor_loader_reads_symbol_scoped_liquidity_zone_keys() -> None:
    client = _MemoryClient()
    _seed(client)
    client.set(
        "v2:market:liquidity_zones:BTCUSDT",
        json.dumps(
            {
                "available_at": "2026-06-11T12:04:59Z",
                "liquidity_zone_above": 105.0,
                "liquidity_zone_below": 95.0,
                "distance_to_liquidity_zone_bps": 250.0,
            }
        ),
    )
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    tensor = example.tensor
    by_name = dict(zip(tensor.feature_names, tensor.values))
    assert by_name["liquidity_zone_above"] == 105.0
    assert by_name["liquidity_zone_below"] == 95.0
    assert by_name["distance_to_liquidity_zone_bps"] == 250.0
    assert "v2:market:liquidity_zones:BTCUSDT" in example.payload_keys


def test_environment_reset_step_uses_seven_action_contract() -> None:
    client = _MemoryClient()
    _seed(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    examples = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",))
    env = V2PaperShadowHybridEnv(examples=examples)
    obs, info = env.reset()
    assert len(ACTION_LABELS) == 7
    assert info["live_gate"] == LIVE_GATE_BLOCKED
    next_obs, reward, terminated, truncated, step_info = env.step(1)
    assert len(next_obs) == len(obs)
    assert isinstance(reward, float)
    assert terminated is True or truncated is False
    assert step_info["exchange_mutation"] is False


def test_model_forward_emits_masa_ppo_heads_and_cuda_truth() -> None:
    client = _MemoryClient()
    _seed(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    model = V2HybridPolicyModel(input_dim=len(example.tensor.model_vector))
    out = model.forward(example.tensor)
    assert len(out.action_probabilities) == 7
    assert abs(sum(out.action_probabilities) - 1.0) < 1e-5
    assert 0.0 <= out.confidence_calibrated <= 1.0
    assert isinstance(out.policy_value, float)
    assert isinstance(out.masa_signal, float)
    if out.device.startswith("cuda"):
        assert out.cuda_active is True
        assert out.model_tensors_device_verified is True
    if out.cuda_active:
        assert out.model_tensors_device_verified is True
        assert out.device.startswith("cuda")


def test_runtime_blocks_unverified_model_and_writes_honest_artifacts(
    tmp_path: Path,
) -> None:
    client = _MemoryClient()
    _seed(client, symbols=("BTCUSDT", "ETHUSDT"), timeframes=("1m",))
    model_dir = Path(".local_models/test_hybrid_cuda_pytest")
    shutil.rmtree(model_dir, ignore_errors=True)
    config = HybridTrainerConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1m",),
        max_training_rows_per_cycle=4,
        batch_size=4,
        model_dir=model_dir,
    )
    result = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=True,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )
    assert result.go_no_go == "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_BLOCKED"
    assert result.predictions == []
    assert result.lineages == []
    assert (
        result.status["legacy_hybrid_parity_claim"]
        == "V2_FULL_FUNCTION_PARITY_BY_NATIVE_TRAINER_AND_V2_RUNTIME_OWNERSHIP"
    )
    assert (
        "legacy_masa_agent_rebuilt_as_native_masa_adapter_and_cuda_auxiliary_head"
        in result.status["legacy_capabilities_rebuilt_or_reassigned"]
    )
    assert result.metrics["training"]["status"] == "NO_TRUSTED_TRAINING_ROWS"
    assert result.metrics["training"]["metrics"]["trusted_rows_loaded"] == 0
    assert result.metrics["training"]["metrics"]["selected_examples"] == 0
    assert result.metrics["training"]["metrics"]["learning_update_lane"] == "blocked"
    assert result.status["runtime_readiness_status"] == "BLOCKED"
    assert result.status["trainer_learning_ready"] is False
    assert result.status["runtime_readiness_blockers"]
    assert result.status["prediction_publication_status"] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    assert result.status["status_publication_status"] == "FAILED"
    assert result.metrics["parallel_environment_rollout"]["covers_all_loaded_examples"] is True
    assert result.metrics["parallel_environment_rollout"]["envs_instantiated"] == 2
    assert result.status["model_serving_allowed"] is False
    assert "v2:prediction:BTCUSDT:1m" not in client.store
    assert result.metrics["cuda_cpu_resource_utilization"]["actual_batch_size"] == 4
    written = write_runtime_artifacts(paths=default_paths(tmp_path), result=result)
    required = {
        "GO_NO_GO.md",
        "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_IMPLEMENTATION_REPORT.md",
        "v2_native_rl_masa_ppo_port_status.json",
        "v2_native_rl_tensor_builder_status.json",
        "v2_native_rl_environment_status.json",
        "v2_native_rl_reward_stack_status.json",
        "v2_native_rl_masa_ppo_model_status.json",
        "v2_native_rl_cuda_runtime_status.json",
        "v2_native_rl_training_loop_status.json",
        "v2_native_rl_prediction_publisher_status.json",
        "v2_risk_gateway_native_rl_integration_status.json",
        "v2_orchestrator_native_rl_signal_status.json",
        "v2_paper_trader_native_rl_signal_consumption_status.json",
        "v2_website_native_rl_live_control_status.json",
        "operator_dashboard_payload.json",
    }
    public_dir = tmp_path / "v2/frontend/public/v2_native_rl_masa_ppo_cuda_trainer_implementation/latest"
    assert required.issubset({p.name for p in public_dir.iterdir()})
    assert len(written.paths_written) >= len(required)
    shutil.rmtree(model_dir, ignore_errors=True)


def test_runtime_reports_quarantined_feedback_rejection_counts(tmp_path: Path) -> None:
    client = _MemoryClient()
    _seed(client, symbols=("BTCUSDT",), timeframes=("1m",))
    client.set(
        "v2:trainer:feedback:outcomes:quarantine",
        json.dumps(
            [
                {
                    "trainer_feedback_id": "feedback_quarantined_1",
                    "trust_reconstruction_rejection_reasons": [
                        "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND"
                    ],
                    "audit_quality_rejection_reasons": [
                        "MISSING_EXPECTED_SLIPPAGE_BPS"
                    ],
                    "quarantine_reason": "trust:entry_feature_snapshot_not_found",
                }
            ]
        ),
    )
    config = HybridTrainerConfig(
        symbols=("BTCUSDT",),
        timeframes=("1m",),
        max_training_rows_per_cycle=2,
        batch_size=2,
        model_dir=tmp_path / ".local_models/v2_native_rl_masa_ppo",
    )

    result = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=False,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )

    assert result.metrics["training"]["status"] == "NO_TRUSTED_TRAINING_ROWS"
    assert result.metrics["training"]["metrics"]["trusted_rows_loaded"] == 0
    assert result.metrics["training"]["metrics"]["rows_rejected_by_reason"] == {
        "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND": 1,
        "MISSING_EXPECTED_SLIPPAGE_BPS": 1,
    }


def test_runtime_suppresses_unverified_blocked_prediction_and_replay_snapshot() -> None:
    client = _MemoryClient()
    _seed(client, symbols=("BTCUSDT",), timeframes=("1m",))
    for key in list(client.store):
        if key.startswith("v2:market:ohlcv_closed:binance:BTCUSDT:"):
            client.store.pop(key)
    model_dir = Path(".local_models/test_hybrid_cuda_blocked_prediction_pytest")
    shutil.rmtree(model_dir, ignore_errors=True)
    config = HybridTrainerConfig(
        symbols=("BTCUSDT",),
        timeframes=("1m",),
        max_training_rows_per_cycle=4,
        batch_size=4,
        model_dir=model_dir,
    )

    result = run_hybrid_trainer_cycle(config=config, io=V2OnlyJsonIO(client=client), publish=True)

    assert result.predictions == []
    assert result.lineages == []
    assert result.status["prediction_suppressed_count"] == 1
    assert result.status["prediction_publication_status"] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    prediction_key = "v2:prediction:BTCUSDT:1m"
    assert prediction_key not in client.store
    assert not any(key.startswith("v2:replay:snapshots:") for key in client.store)
    shutil.rmtree(model_dir, ignore_errors=True)


def test_runtime_replay_buffer_waits_for_closed_trade_feedback(tmp_path: Path) -> None:
    client = _MemoryClient()
    _seed(client, symbols=("BTCUSDT", "ETHUSDT"), timeframes=("1m",))
    model_dir = Path(".local_models/test_hybrid_cuda_replay_buffer_pytest")
    shutil.rmtree(model_dir, ignore_errors=True)
    replay_buffer = []
    config = HybridTrainerConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1m",),
        max_training_rows_per_cycle=4,
        batch_size=4,
        train_steps=1,
        model_dir=model_dir,
    )

    first = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=False,
        replay_buffer=replay_buffer,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )
    second = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=False,
        replay_buffer=replay_buffer,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )

    assert first.metrics["training"]["metrics"]["selected_examples"] == 0
    assert second.metrics["training"]["metrics"]["selected_examples"] == 0
    assert first.metrics["training"]["metrics"]["trusted_rows_loaded"] == 0
    assert second.metrics["training"]["metrics"]["trusted_rows_loaded"] == 0
    assert first.predictions == []
    assert second.predictions == []
    assert first.status["prediction_suppressed_count"] == 2
    assert second.status["prediction_suppressed_count"] == 2
    assert second.status["replay_buffer_size"] == 0
    assert second.status["prediction_examples_built"] == 2
    assert len(replay_buffer) == 0
    shutil.rmtree(model_dir, ignore_errors=True)


def test_feedback_row_changes_training_batch() -> None:
    client = _MemoryClient()
    _seed(client, symbols=("BTCUSDT",), timeframes=("1m",))
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client))
    baseline = loader.build_example(symbol="BTCUSDT", timeframe="1m")

    _seed_trainer_feedback(client, symbol="BTCUSDT", timeframe="1m", realized_pnl_bps=-42.5)
    [with_feedback] = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",), trusted_only=True, limit=1)

    assert baseline.label_expected_move_after_cost_bps != with_feedback.label_expected_move_after_cost_bps
    assert with_feedback.label_expected_move_after_cost_bps == pytest.approx(-42.5)
    assert ACTION_LABELS[with_feedback.label_action_index] == "short"
    assert with_feedback.trust_row["learning_mode"] == "outcome_supervised"


def test_feedback_optimizer_update_is_not_promoted_without_pit_validation_split(
    tmp_path: Path,
) -> None:
    client = _MemoryClient()
    # Alternate long/short/long/short/long so that dropping ANY 1 row still leaves
    # mixed direction in the 3-row training split.  With validation_fraction=0.2:
    #   5 selected → val_count=1 → train rows 0-3 (mixed) ✓
    #   4 selected → val_count=1 → train rows 0-2 (any 3 of the pattern = mixed) ✓
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    _seed(client, symbols=symbols, timeframes=("1m",))
    client.set(
        "v2:trainer:feedback:outcomes",
        json.dumps(
            [
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="BTCUSDT", timeframe="1m", realized_pnl_bps=55.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="ETHUSDT", timeframe="1m", realized_pnl_bps=-50.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="SOLUSDT", timeframe="1m", realized_pnl_bps=60.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="BNBUSDT", timeframe="1m", realized_pnl_bps=-45.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="XRPUSDT", timeframe="1m", realized_pnl_bps=40.0)),
            ]
        ),
    )
    model_dir = tmp_path / ".local_models/test_feedback_checkpoint_updates"
    config = HybridTrainerConfig(
        symbols=symbols,
        timeframes=("1m",),
        max_training_rows_per_cycle=5,
        batch_size=3,
        train_steps=2,
        model_dir=model_dir,
    )

    first = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=False,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )
    first_training = first.metrics["training"]["metrics"]
    assert first_training["optimizer_steps_this_cycle"] == 2
    assert first_training["parameter_hash_before"] != first_training[
        "parameter_hash_after"
    ]
    assert first_training["weight_delta_norm"] > 0.0
    assert first_training["validation_split_reason"] == (
        "DISTINCT_CHRONOLOGICAL_BOUNDARY_UNAVAILABLE"
    )
    assert first.metrics["checkpoint"]["weight_blob_written"] is False
    assert first.metrics["checkpoint"]["weight_file_path"] is None
    assert first.metrics["checkpoint_promotion"]["checkpoint_promotion_allowed"] is False
    assert "SERVING_VALIDATION_SPLIT_PIT_UNSAFE" in first.metrics[
        "checkpoint_promotion"
    ]["checkpoint_promotion_rejection_reasons"]

    # Cycle 2: invert all signs so the gradient direction flips.
    client.set(
        "v2:trainer:feedback:outcomes",
        json.dumps(
            [
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="BTCUSDT", timeframe="1m", realized_pnl_bps=-55.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="ETHUSDT", timeframe="1m", realized_pnl_bps=50.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="SOLUSDT", timeframe="1m", realized_pnl_bps=-60.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="BNBUSDT", timeframe="1m", realized_pnl_bps=45.0)),
                _bind_feedback_to_snapshot(client, _trainer_feedback_row(symbol="XRPUSDT", timeframe="1m", realized_pnl_bps=-40.0)),
            ]
        ),
    )
    second = run_hybrid_trainer_cycle(
        config=config,
        io=V2OnlyJsonIO(client=client),
        publish=False,
        trusted_replay_archive_root=tmp_path / "empty_archive",
    )
    second_training = second.metrics["training"]["metrics"]

    for training in (first_training, second_training):
        assert training["selected_examples"] == 5
        assert training["policy_action_single_direction_guard_active"] is False
        assert training["policy_action_supervision_strategy"] == "raw_action_labels"
        assert training["expected_move_single_direction_guard_active"] is False
        assert training["optimizer_steps_this_cycle"] == 2
    assert second.metrics["checkpoint_load"]["model_state_restored"] is False
    assert second.metrics["checkpoint"]["weight_blob_written"] is False
    assert second.metrics["checkpoint_promotion"]["checkpoint_promotion_allowed"] is False


def test_single_direction_feedback_does_not_force_prediction_after_guard(tmp_path: Path) -> None:
    positive_client = _MemoryClient()
    negative_client = _MemoryClient()
    _seed(positive_client, symbols=("BTCUSDT",), timeframes=("1m",))
    _seed(negative_client, symbols=("BTCUSDT",), timeframes=("1m",))
    _seed_trainer_feedback(positive_client, symbol="BTCUSDT", timeframe="1m", realized_pnl_bps=90.0)
    _seed_trainer_feedback(negative_client, symbol="BTCUSDT", timeframe="1m", realized_pnl_bps=-90.0)
    base_config = {
        "symbols": ("BTCUSDT",),
        "timeframes": ("1m",),
        "max_training_rows_per_cycle": 1,
        "batch_size": 1,
        "train_steps": 3,
    }

    positive = run_hybrid_trainer_cycle(
        config=HybridTrainerConfig(
            **base_config,
            model_dir=tmp_path / ".local_models/test_feedback_prediction_positive",
        ),
        io=V2OnlyJsonIO(client=positive_client),
        publish=False,
    )
    negative = run_hybrid_trainer_cycle(
        config=HybridTrainerConfig(
            **base_config,
            model_dir=tmp_path / ".local_models/test_feedback_prediction_negative",
        ),
        io=V2OnlyJsonIO(client=negative_client),
        publish=False,
    )

    assert positive.metrics["training"]["metrics"]["selected_examples"] == 1
    assert negative.metrics["training"]["metrics"]["selected_examples"] == 1
    for result in (positive, negative):
        training_metrics = result.metrics["training"]["metrics"]
        assert training_metrics["policy_action_supervision_strategy"] == (
            "neutralize_single_directional_action_labels_to_hold"
        )
        assert training_metrics["policy_action_single_direction_guard_active"] is True
        assert training_metrics["policy_action_labels_neutralized_count"] == 1
        assert training_metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == 1
        assert training_metrics["expected_move_single_direction_guard_active"] is True
        assert training_metrics["expected_move_labels_neutralized_count"] == 1
        assert training_metrics["expected_move_training_target_mean_bps"] == 0.0
        assert result.predictions == []
        assert result.status["prediction_suppressed_count"] == 1
        assert result.status["model_serving_allowed"] is False


def test_v2_only_io_rejects_old_redis_write() -> None:
    io = V2OnlyJsonIO(client=_MemoryClient())
    ok = io.set_json("prediction:BTCUSDT:1m", {"bad": True})
    assert ok is False
    assert io.audit.old_redis_write_attempts == 1


def test_bridge_exit_publisher_preserves_new_hybrid_trainer_source() -> None:
    from v2.backend.app.services.trainer_bridge_exit.native_prediction_publisher import (
        should_preserve_existing,
    )

    assert should_preserve_existing({"trainer_source": TRAINER_SOURCE}) is True


def test_risk_integration_fails_closed_when_caps_unset() -> None:
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    decision = OrchestratorDecisionRecord(
        decision_id="dec_v2h_test",
        prediction_id="v2h_test",
        feature_snapshot_id="fs_test",
        symbol="BTCUSDT",
        decision_ts_ms=1,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.9,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    risk = native_risk_decision_from_orchestrator(
        decision,
        prediction_payload={"data_coverage_percent": 100.0, "confidence_calibrated": 0.9},
        min_data_coverage_percent=70.0,
        risk_caps_configured=False,
    )
    assert risk.risk_action == "deny"
    assert risk.risk_reason_code == "deny_default"


def test_native_risk_decision_forwards_explicit_trust_gate_rejection() -> None:
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    decision = OrchestratorDecisionRecord(
        decision_id="dec_v2h_trust_block",
        prediction_id="v2h_trust_block",
        feature_snapshot_id="fs_trust_block",
        symbol="BTCUSDT",
        decision_ts_ms=1,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.9,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    risk = native_risk_decision_from_orchestrator(
        decision,
        prediction_payload={
            "data_coverage_percent": 100.0,
            "confidence_calibrated": 0.9,
            "trust_gate_result": {
                "accepted": False,
                "severity": "reject",
                "reject_reasons": ["future_feature_cutoff"],
                "warnings": [],
                "data_quality_score": 0.95,
                "future_leak_detected": True,
                "cutoff_mismatch_detected": False,
                "replay_required": True,
                "metrics": {"source": "test"},
            },
        },
        min_data_coverage_percent=70.0,
        risk_caps_configured=True,
    )
    assert risk.risk_action == "deny"
    assert risk.risk_reason_code == "deny_default"


def test_native_risk_decision_blocks_missing_snapshot_linkage() -> None:
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    decision = OrchestratorDecisionRecord(
        decision_id="dec_v2h_snapshot_block",
        prediction_id="v2h_snapshot_block",
        feature_snapshot_id="fs_snapshot_block",
        symbol="BTCUSDT",
        decision_ts_ms=1,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.9,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    risk = native_risk_decision_from_orchestrator(
        decision,
        prediction_payload={
            "data_coverage_percent": 100.0,
            "confidence_calibrated": 0.9,
            "market_state_envelope": {
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "decision_time": "2026-06-11T00:01:05Z",
                "event_time": "2026-06-11T00:01:00Z",
                "available_at": "2026-06-11T00:01:00Z",
                "ingested_at": "2026-06-11T00:01:01Z",
                "timeframe_cutoffs": {"1m": "2026-06-11T00:01:00Z"},
                "feature_cutoff": "2026-06-11T00:01:00Z",
                "feature_version": "v2",
                "feature_hash": "snapshot_hash",
                "data_quality_score": 0.95,
                "data_quality_flags": [],
                "is_backfilled": False,
                "is_final_candle": True,
                "missing_candle_count": 0,
                "duplicate_event_count": 0,
                "out_of_order_event_count": 0,
                "source_disagreement_score": 0.0,
                "latency_ms": 500,
                "decision_id": "dec_v2h_snapshot_block",
            },
        },
        min_data_coverage_percent=70.0,
        risk_caps_configured=True,
    )
    assert risk.risk_action == "deny"
    assert risk.risk_reason_code == "deny_default"


def test_hybrid_trainer_package_does_not_import_raw_legacy_trainer() -> None:
    root = REPO / "v2/backend/app/services/native_trainer/hybrid_cuda_trainer"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from v2.legacy_owned_runtime.rl.hybrid_trainer" not in text
        assert "import v2.legacy_owned_runtime.rl.hybrid_trainer" not in text
