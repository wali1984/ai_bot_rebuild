from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from v2.backend.app.cli.v2_strategy_supply_publish_hypotheses import (
    _positive_net_usd,
    publish_strategy_supply,
)


class FakeRedis:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = {key: json.dumps(value) for key, value in data.items()}
        self.set_calls: list[tuple[str, int | None]] = []

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        assert key.startswith("v2:strategy_supply:")
        self.data[key] = value
        self.set_calls.append((key, ex))


def _runtime_keys(symbol: str = "BTCUSDT") -> dict[str, object]:
    now = datetime.now(UTC)

    def _utc(seconds_ago: int) -> str:
        return (now - timedelta(seconds=seconds_ago)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")

    return {
        f"v2:orderbook:top:binance:{symbol}": {
            "best_bid": 60000.0,
            "best_ask": 60006.0,
            "best_bid_size": 1.2,
            "best_ask_size": 1.1,
            "event_time": "2026-07-09T05:00:00Z",
            "available_at": "2026-07-09T05:00:00Z",
        },
        f"v2:market:prices:{symbol}": {
            "ticker_24hr": {
                "lastPrice": "60000",
                "bidPrice": "59997",
                "askPrice": "60003",
                "closeTime": 4102444800000,
            },
        },
        f"v2:features:latest:{symbol}:1m": {
            "features": {"atr_bps": 40.0},
            "atr_bps": 40.0,
        },
        f"v2:features:coinglass:{symbol}:1m": {
            "schema_version": "coinglass_aggregated_feature_payload_v2",
            "provider": "coinglass",
            "symbol": symbol,
            "timeframe": "1m",
            "feature_cutoff": _utc(30),
            "available_at": _utc(2),
            "generated_at": _utc(1),
            "actual_payload_present": True,
            "provider_ready": True,
            "decision_time_safe": True,
            "temporal_contract_valid": True,
            "features": {
                "coinglass_funding_rate_zscore": 2.4,
                "coinglass_long_ratio": 0.72,
                "coinglass_long_short_extreme_score": 0.8,
            },
            "missing_feature_flags": [],
            "stale_feature_flags": [],
        },
        f"v2:microstructure:trust_score:{symbol}:1m": {
            "microstructure_trust_score": 0.74,
            "composite_microstructure_trust_score": 0.74,
            "trade_tape_confirmation_score": 0.71,
            "available_at": "2026-07-09T05:00:00Z",
        },
    }


def test_strategy_supply_publish_writes_redis_contract_and_artifacts(tmp_path: Path) -> None:
    client = FakeRedis(_runtime_keys())

    status = publish_strategy_supply(
        client=client,
        symbols=["BTCUSDT"],
        timeframes=["1m"],
        ttl_seconds=123,
        output_dir=tmp_path,
    )

    assert status["places_real_order"] is False
    assert status["test_order_submitted"] is False
    assert status["positive_hypothesis_count"] > 0
    assert status["ttl_seconds"] == 123
    assert status["status"] in {
        "GREEN_PUBLISHING_GATE_CLEAN_POSITIVES",
        "YELLOW_POSITIVE_HYPOTHESES_STAGE_REJECTED",
    }
    assert ("v2:strategy_supply:hypotheses:BTCUSDT:1m", 123) in client.set_calls
    assert ("v2:strategy_supply:positive_hypotheses:BTCUSDT:1m", 123) in client.set_calls
    assert ("v2:strategy_supply:gate_clean_positive_hypotheses:BTCUSDT:1m", 123) in client.set_calls
    assert ("v2:strategy_supply:latest_positive_summary", 123) in client.set_calls
    assert ("v2:strategy_supply:latest_error_summary", 123) in client.set_calls
    assert ("v2:strategy_supply:status", 123) in client.set_calls
    payload = json.loads(client.data["v2:strategy_supply:hypotheses:BTCUSDT:1m"])
    directional = [row for row in payload["rows"] if row.get("side")]
    assert directional
    assert all(row.get("hypothesis_id") for row in directional)
    assert all(row.get("feature_vector_hash") for row in directional)
    assert all(isinstance(row.get("provider_feature_hashes"), dict) for row in directional)
    positive_payload = json.loads(client.data["v2:strategy_supply:positive_hypotheses:BTCUSDT:1m"])
    assert all(row["expected_net_pnl_usd"] > 0 for row in positive_payload["rows"])
    for row in positive_payload["rows"]:
        if row.get("side") == "short":
            assert row["expected_move_after_cost_bps"] < 0
            assert row["expected_short_net_edge_bps"] > 0
    assert (tmp_path / "strategy_supply_publish_status.json").exists()
    positive_rows = (tmp_path / "strategy_supply_positive_hypotheses.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert positive_rows


def test_strategy_supply_publish_rejects_inconsistent_selected_side_positive() -> None:
    assert _positive_net_usd(
        {
            "side": "short",
            "expected_net_pnl_usd": 0.82,
            "short_expected_net_pnl_usd": 0.82,
            "expected_short_net_edge_bps": -18.0,
            "expected_move_after_cost_bps": 256.9,
        }
    ) is False
    assert _positive_net_usd(
        {
            "side": "short",
            "expected_net_pnl_usd": 0.82,
            "short_expected_net_pnl_usd": 0.82,
            "expected_short_net_edge_bps": 18.0,
            "expected_move_after_cost_bps": -18.0,
        }
    ) is True
