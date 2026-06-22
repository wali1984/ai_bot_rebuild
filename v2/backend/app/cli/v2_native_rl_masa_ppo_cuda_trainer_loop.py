"""V2 native RL/MASA/PPO CUDA trainer loop CLI.

Runs one or more paper/shadow trainer cycles. It never enables live trading,
never calls the exchange, and writes only V2-owned Redis keys through the
hybrid trainer publisher.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (  # noqa: E402
    DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    DEFAULT_TIMEFRAMES,
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (  # noqa: E402
    default_paths,
    run_hybrid_trainer_cycle,
    write_runtime_artifacts,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO  # noqa: E402
from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    REQUIRED_DECISION_TIMEFRAMES,
    stable_hash,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: E402


class _MemoryClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str):
        self.store[key] = value
        return True


def _seed_smoke_fixture(client: _MemoryClient, *, symbols: list[str], timeframes: list[str]) -> None:
    decision_time = datetime(2026, 6, 19, 4, 0, tzinfo=timezone.utc)
    decision_time_iso = decision_time.isoformat().replace("+00:00", "Z")
    decision_ms = int(decision_time.timestamp() * 1000)
    timeframe_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
    }

    def _closed_candle(symbol: str, timeframe: str) -> dict[str, object]:
        seconds = timeframe_seconds[timeframe]
        close_ms = decision_ms - 1_000
        open_ms = close_ms - (seconds * 1_000) + 1
        body = {
            "symbol": symbol,
            "exchange": "binance",
            "timeframe": timeframe,
            "candle_open_time": open_ms,
            "candle_close_time": close_ms,
            "event_time": close_ms,
            "ingested_at": close_ms,
            "available_at": close_ms,
            "is_closed": True,
            "closed_candle": True,
            "candle_closed_confirmed": True,
            "source": "smoke_fixture_closed_candle",
            "source_sequence_id": f"{symbol}:{timeframe}:{close_ms}",
            "raw_payload_hash": stable_hash({"symbol": symbol, "timeframe": timeframe, "close_ms": close_ms}),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
            "quote_volume": 101000.0,
            "num_trades": 250,
            "taker_buy_base_vol": 520.0,
            "taker_buy_quote_vol": 52520.0,
        }
        body["candle_id"] = stable_hash(body)[:24]
        return body

    for symbol in symbols:
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            client.set(
                f"v2:market:ohlcv_closed:binance:{symbol}:{snapshot_timeframe}",
                json.dumps([_closed_candle(symbol, snapshot_timeframe)]),
            )
        for tf in timeframes:
            feature_cutoff = decision_time_iso
            client.set(
                f"v2:features:latest:{symbol}:{tf}",
                json.dumps(
                    {
                        "feature_snapshot_id": f"v2_fsnap_{symbol}_{tf}_hybrid_smoke",
                        "feature_freshness_state": "CURRENT",
                        "freshness_state": "FRESH",
                        "generated_at": decision_time_iso,
                        "decision_time": decision_time_iso,
                        "feature_cutoff": feature_cutoff,
                        "available_at": feature_cutoff,
                        "source_available_time": feature_cutoff,
                        "masa_feature_cutoff": feature_cutoff,
                        "ppo_feature_cutoff": feature_cutoff,
                        "candle_closed_confirmed": True,
                        "closed_candle": True,
                        "replay_snapshot_id": f"replay_{symbol}_{tf}_hybrid_smoke",
                        "replay_snapshot_key": f"v2:replay:snapshots:replay_{symbol}_{tf}_hybrid_smoke",
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
                            "ATR": 0.8,
                            "bollinger_upper": 103.0,
                            "bollinger_middle": 101.0,
                            "bollinger_lower": 99.0,
                            "bollinger_width_pct": 0.04,
                            "bb_width_pct": 0.012,
                            "htf_ret_pct": 0.002,
                            "htf_rsi_14": 58.0,
                            "bid_ask_spread_bps": 3.0,
                            "depth_imbalance": 0.15,
                            "micro_price": 101.0,
                            "toxicity_proxy": 0.1,
                            "paper_position_present": 0,
                        },
                        "missing_feature_flags": [],
                        "stale_feature_flags": [],
                    }
                ),
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
                        "mark_price": 101.05,
                        "index_price": 101.0,
                        "basis_pct": 0.0005,
                        "ticker_24hr": {"lastPrice": "101.0", "quoteVolume": "101000.0"},
                        "funding": {"markPrice": "101.05", "indexPrice": "101.0", "basis_pct": 0.0005},
                    }
                ),
            )
            client.set(f"v2:market:ohlcv:binance:{symbol}:{tf}", json.dumps(_closed_candle(symbol, tf)))
            client.set(
                f"v2:market:orderbook:{symbol}",
                json.dumps(
                    {
                        "best_bid": 100.98,
                        "best_ask": 101.01,
                        "spread_bps": 3.0,
                        "depth_imbalance": 0.15,
                        "orderbook_depth_usd": 250000.0,
                        "depth_total_usd": 250000.0,
                        "depth_usd": 250000.0,
                        "orderbook_wall_strength": 0.35,
                        "bids": [{"price": 100.98, "qty": 100.0}],
                        "asks": [{"price": 101.01, "qty": 85.0}],
                    }
                ),
            )
            client.set(f"v2:market:funding:{symbol}", json.dumps({"funding_rate": 0.0001}))
            client.set(f"v2:market:open_interest:{symbol}", json.dumps({"open_interest": 1000000.0}))
            client.set(f"v2:market:open_interest_hist:{symbol}:5m", json.dumps({"change_pct": 0.01}))
            client.set(
                f"v2:market:long_short:{symbol}",
                json.dumps({"long_short_ratio": 1.05, "long_account_ratio": 0.512, "short_account_ratio": 0.488}),
            )
            client.set(
                f"v2:market:microstructure:{symbol}",
                json.dumps(
                    {
                        "micro_price": 101.0,
                        "microprice": 101.0,
                        "toxicity_proxy": 0.1,
                        "depth_vs_tape_divergence": 0.02,
                        "microstructure_liquidity_depth": 250000.0,
                        "coinapi_wsds_tape_imbalance": 0.04,
                        "tape_imbalance": 0.04,
                        "order_flow_imbalance": 0.03,
                        "micro_volatility": 0.005,
                    }
                ),
            )
            client.set(
                f"v2:market:liquidation_levels:{symbol}",
                json.dumps(
                    {
                        "long_level": 94.0,
                        "short_level": 108.0,
                        "nearest_liquidation_level_above": 108.0,
                        "nearest_liquidation_level_below": 94.0,
                        "distance_to_long_liq_bps": 700.0,
                        "distance_to_short_liq_bps": 700.0,
                        "liquidation_cluster_strength_long": 0.20,
                        "liquidation_cluster_strength_short": 0.18,
                        "distance_pct": 0.07,
                        "strength": 0.20,
                        "liquidation_cascade_risk": 0.10,
                        "liquidation_pressure_direction": 0.0,
                        "nearest_distance_bps": 150.0,
                        "liquidation_is_stale": 0.0,
                    }
                ),
            )
            client.set(
                f"v2:market:liquidity_zones:{symbol}",
                json.dumps(
                    {
                        "liquidity_zone_above": 106.0,
                        "liquidity_zone_below": 96.0,
                        "distance_to_liquidity_zone_bps": 350.0,
                    }
                ),
            )
            client.set(
                f"v2:altdata:public_intel:symbol:{symbol}",
                json.dumps(
                    {
                        "public_intel_score": 0.5,
                        "defillama_liquidity_score": 0.5,
                        "defillama_tvl_momentum_score": 0.5,
                        "news_attention_score": 0.5,
                        "news_sentiment_score": 0.5,
                        "fear_greed_score": 50.0,
                        "btc_mempool_pressure_score": 0.2,
                    }
                ),
            )
            client.set(f"v2:altdata:lunarcrush:symbol:{symbol}", json.dumps({"score": 0.5}))
            client.set(f"v2:altdata:nansen:symbol:{symbol}", json.dumps({"presence": 1.0, "score": 0.5}))
            client.set(
                f"v2:altdata:aicoin:symbol:{symbol}",
                json.dumps(
                    {
                        "aicoin_market_activity_score": 0.5,
                        "aicoin_coin_profile_score": 0.5,
                        "aicoin_order_flow_score": 0.5,
                        "aicoin_whale_order_score": 0.5,
                        "aicoin_signal_score": 0.5,
                        "aicoin_drop_radar_score": 0.5,
                        "aicoin_airdrop_score": 0.5,
                        "aicoin_liquidation_score": 0.5,
                        "aicoin_open_interest_score": 0.5,
                        "aicoin_news_attention_score": 0.5,
                    }
                ),
            )
            client.set(
                f"v2:altdata:whale_walls:symbol:{symbol}",
                json.dumps(
                    {
                        "whale_wall_score": 0.4,
                        "whale_bid_pressure_score": 0.45,
                        "whale_ask_pressure_score": 0.35,
                        "whale_wall_imbalance_score": 0.1,
                        "whale_wall_count_score": 0.3,
                        "whale_wall_event_count": 2,
                        "whale_bid_wall_notional_usd": 50000.0,
                        "whale_ask_wall_notional_usd": 45000.0,
                        "whale_total_wall_notional_usd": 95000.0,
                        "nearest_bid_wall_distance_bps": 80.0,
                        "nearest_ask_wall_distance_bps": 90.0,
                    }
                ),
            )
            client.set(
                f"v2:altdata:symbol_score:{symbol}",
                json.dumps(
                    {
                        "altdata_symbol_score": 0.5,
                        "provider_availability_score": 1.0,
                        "altdata_freshness_score": 1.0,
                        "public_intel_score": 0.5,
                        "coingecko_discovery_score": 0.5,
                        "coingecko_liquidity_score": 0.5,
                        "coingecko_momentum_score": 0.5,
                        "surf_market_price_signal_score": 0.5,
                        "coinglass_derivatives_score": 0.5,
                        "defillama_liquidity_score": 0.5,
                        "defillama_tvl_momentum_score": 0.5,
                        "news_attention_score": 0.5,
                        "news_sentiment_score": 0.5,
                        "fear_greed_score": 50.0,
                        "btc_mempool_pressure_score": 0.2,
                        "aicoin_score": 0.5,
                        "aicoin_market_activity_score": 0.5,
                        "aicoin_coin_profile_score": 0.5,
                        "aicoin_order_flow_score": 0.5,
                        "aicoin_whale_order_score": 0.5,
                        "aicoin_signal_score": 0.5,
                        "aicoin_drop_radar_score": 0.5,
                        "aicoin_airdrop_score": 0.5,
                        "aicoin_liquidation_score": 0.5,
                        "aicoin_open_interest_score": 0.5,
                        "aicoin_news_attention_score": 0.5,
                        "whale_wall_score": 0.4,
                        "whale_bid_pressure_score": 0.45,
                        "whale_ask_pressure_score": 0.35,
                        "whale_wall_imbalance_score": 0.1,
                        "whale_wall_count_score": 0.3,
                        "whale_wall_event_count": 2,
                        "whale_bid_wall_notional_usd": 50000.0,
                        "whale_ask_wall_notional_usd": 45000.0,
                        "whale_total_wall_notional_usd": 95000.0,
                        "nearest_bid_wall_distance_bps": 80.0,
                        "nearest_ask_wall_distance_bps": 90.0,
                    }
                ),
            )
    client.set("v2:liquidations:events", json.dumps({"count_5m": 1, "last_liq_bps_24h": 12.0}))
    client.set("v2:risk:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:orchestrator:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:paper:positions", json.dumps({"position_present": 0, "unrealized_bps": 0.0}))
    client.set("v2:paper:ledger", json.dumps({"entries": []}))
    client.set("v2:paper:position_history", json.dumps({"entries": []}))


def _try_redis_io() -> V2OnlyJsonIO:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        return V2OnlyJsonIO(client=client)
    except Exception:  # noqa: BLE001
        return V2OnlyJsonIO(client=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run V2 native RL/MASA/PPO CUDA trainer in paper/shadow mode.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--symbols", default="")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument("--smoke-fixture", action="store_true", help="Use an in-memory V2 fixture for hermetic validation.")
    parser.add_argument("--write-artifacts", action="store_true")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE)
    parser.add_argument("--risk-caps-configured", action="store_true")
    args = parser.parse_args(argv)

    explicit_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    symbols = explicit_symbols or resolve_symbols()
    timeframes = tuple(tf.strip() for tf in args.timeframes.split(",") if tf.strip())

    if args.smoke_fixture:
        memory = _MemoryClient()
        _seed_smoke_fixture(memory, symbols=list(symbols[:3]), timeframes=list(timeframes))
        io = V2OnlyJsonIO(client=memory)
        symbols = list(symbols[:3])
    elif args.no_redis:
        io = V2OnlyJsonIO(client=None)
    else:
        io = _try_redis_io()

    result = None
    for _ in range(max(1, int(args.cycles))):
        config = HybridTrainerConfig(
            symbols=tuple(symbols),
            timeframes=tuple(timeframes),
            max_training_rows_per_cycle=int(args.max_rows),
            risk_caps_configured=bool(args.risk_caps_configured),
        )
        result = run_hybrid_trainer_cycle(config=config, io=io, publish=not args.no_redis or args.smoke_fixture)
    assert result is not None
    if args.write_artifacts:
        result = write_runtime_artifacts(
            paths=default_paths(Path(args.repo_root).resolve()),
            result=result,
        )
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "predictions": len(result.predictions),
                "lineages": len(result.lineages),
                "paths_written": list(result.paths_written),
                "cuda_active": result.status["cuda_active"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
