from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.cli.v2_strategy_supply_publish_hypotheses import (
    _generator_failure_row,
    _positive_net_usd,
    _redis_client,
    publish_strategy_supply,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.strategy_supply import causal_native_ta
from v2.backend.app.services.strategy_supply import (
    edge_hypothesis_generator as edge_generator,
)

_FROZEN_NATIVE_TA_NOW: datetime | None = None


@pytest.fixture(autouse=True)
def _freeze_native_ta_test_clock(monkeypatch: pytest.MonkeyPatch):
    """Keep runtime fixtures deterministic across a candle-close boundary."""

    frozen = datetime.now(UTC)
    frozen_text = frozen.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    global _FROZEN_NATIVE_TA_NOW
    _FROZEN_NATIVE_TA_NOW = frozen
    monkeypatch.setattr(causal_native_ta, "_now", lambda: frozen)
    monkeypatch.setattr(edge_generator, "_utc_now", lambda: frozen_text)
    yield
    _FROZEN_NATIVE_TA_NOW = None


class FakeRedis:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = {
            key: value
            if type(value) in (bytes, str)
            else json.dumps(value)
            for key, value in data.items()
        }
        self.set_calls: list[tuple[str, int | None]] = []

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        assert key.startswith("v2:strategy_supply:")
        self.data[key] = value
        self.set_calls.append((key, ex))


def _canonical_closed_ohlcv_bytes(
    *, symbol: str = "BTCUSDT", timeframe: str = "1m", count: int = 100
) -> bytes:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    assert _FROZEN_NATIVE_TA_NOW is not None
    now_ms = int(_FROZEN_NATIVE_TA_NOW.timestamp() * 1000)
    latest_close_ms = (now_ms // duration_ms) * duration_ms - 1
    rows: list[dict] = []
    for index in range(count):
        close_time = latest_close_ms - (count - 1 - index) * duration_ms
        open_time = close_time - duration_ms + 1
        close_price = 60_000.0 - (count - 1 - index) * 10.0
        open_price = close_price - 5.0
        volume = 1_000.0 + index
        source_row = [
            open_time,
            str(open_price),
            str(close_price + 120.0),
            str(open_price - 120.0),
            str(close_price),
            str(volume),
            close_time,
            str(volume * close_price),
            100 + index,
            str(volume / 2.0),
            str((volume / 2.0) * close_price),
            "0",
        ]
        rows.append(
            canonical_from_binance_rest(
                source_row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=close_time + 1,
            ).to_dict()
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


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
        f"v2:market:ohlcv_closed:binance:{symbol}:1m": (
            _canonical_closed_ohlcv_bytes(symbol=symbol)
        ),
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
    assert status["positive_hypothesis_count"] == 0
    assert status["gate_clean_positive_hypothesis_count"] == 0
    assert status["ttl_seconds"] == 123
    assert status["status"] == "GRAY_MICROSTRUCTURE_MISSING_OR_WEAK"
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
    assert all(row.get("consumer_eligible") is False for row in directional)
    assert all(row.get("trainer_consumable") is False for row in directional)
    assert all(row.get("available_at") is None for row in directional)
    assert all(
        row.get("output_postcommit_readback_receipt_emitted") is False
        for row in directional
    )
    positive_payload = json.loads(client.data["v2:strategy_supply:positive_hypotheses:BTCUSDT:1m"])
    assert positive_payload["rows"] == []
    assert (tmp_path / "strategy_supply_publish_status.json").exists()
    positive_rows = (tmp_path / "strategy_supply_positive_hypotheses.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert positive_rows == []


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


def test_generator_failure_row_does_not_fabricate_market_or_output_clocks() -> None:
    observed_at = "2026-07-21T12:34:56.123456Z"

    row = _generator_failure_row(
        "BTCUSDT",
        "1m",
        observed_at,
        RuntimeError("forced generator failure"),
    )

    assert row["failure_observed_at"] == observed_at
    assert row["generated_at"] == observed_at
    assert row["feature_cutoff"] is None
    assert row["input_available_at"] is None
    assert row["decision_time"] is None
    assert row["available_at"] is None
    assert row["output_postcommit_readback_receipt_emitted"] is False
    assert row["consumer_eligible"] is False
    assert row["trainer_consumable"] is False
    assert row["trainer_admission_granted"] is False
    assert row["counts_as_final_a_plus"] is False
    assert row["live_execution_authorized"] is False


def test_strategy_supply_runtime_redis_client_preserves_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    captured: dict[str, object] = {}

    class Client:
        def ping(self) -> bool:
            return True

    def from_url(url: str, **kwargs: object) -> Client:
        captured["url"] = url
        captured.update(kwargs)
        return Client()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    monkeypatch.setenv("V2_REDIS_URL", "redis://example.invalid:6379/9")

    client = _redis_client()

    assert isinstance(client, Client)
    assert captured["url"] == "redis://example.invalid:6379/9"
    assert captured["decode_responses"] is False
