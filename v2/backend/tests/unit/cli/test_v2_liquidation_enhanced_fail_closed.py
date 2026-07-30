from __future__ import annotations

import json

from v2.backend.app.cli import v2_liquidation_enhanced as mod


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.writes: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, _ttl: int, payload: str) -> bool:
        self.writes[key] = payload
        return True


def _ingestor(redis_client: FakeRedis) -> mod.EnhancedLiquidationIngestor:
    ingestor = mod.EnhancedLiquidationIngestor.__new__(
        mod.EnhancedLiquidationIngestor
    )
    ingestor.allow_synthetic = False
    ingestor.redis = redis_client
    ingestor.calc = mod.EnhancedLiquidationCalculator()
    return ingestor


def _valid_calculator_input() -> dict:
    return {
        "price": 100.0,
        "long_oi": 120.0,
        "short_oi": 80.0,
        "liq_level_long": 90.0,
        "liq_level_short": 110.0,
        "liquidation_count_1m": 2.0,
        "liquidation_volume_1m": 5000.0,
    }


def test_calculator_rejects_missing_or_zero_side_split_oi() -> None:
    calculator = mod.EnhancedLiquidationCalculator()
    missing = _valid_calculator_input()
    missing["long_oi"] = None
    assert calculator.calculate_metrics("BTCUSDT", missing) == {}

    zero = _valid_calculator_input()
    zero["long_oi"] = 0.0
    zero["short_oi"] = 0.0
    assert calculator.calculate_metrics("BTCUSDT", zero) == {}


def test_calculator_does_not_fabricate_predicted_zones() -> None:
    metrics = mod.EnhancedLiquidationCalculator().calculate_metrics(
        "BTCUSDT", _valid_calculator_input()
    )
    assert metrics
    assert not any(key.startswith("predicted_") for key in metrics)


def test_observed_cluster_surface_is_rejected() -> None:
    levels_key = "v2:liquidations:levels:BTCUSDT:1m"
    redis_client = FakeRedis({
        levels_key: json.dumps({
            "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
            "liquidation_observation_coverage_complete": 1,
            "liquidation_current_price_execution_grade": 1,
            "liquidation_surface_validated": True,
        })
    })
    ingestor = _ingestor(redis_client)
    assert ingestor._read_liquidation_levels("BTCUSDT") == {}
    assert ingestor.process_symbol("BTCUSDT") is False
    assert "v2:liquidation:enhanced:BTCUSDT" not in redis_client.writes
    assert "v2:liquidation:enhanced_status:BTCUSDT" in redis_client.writes


def test_total_oi_and_five_minute_aliases_cannot_be_relabelled_as_one_minute(
    monkeypatch,
) -> None:
    ingestor = _ingestor(FakeRedis())
    monkeypatch.setattr(ingestor, "_read_liquidation_levels", lambda _symbol: {
        "liquidation_current_price": 100.0,
        "liquidation_long_level": 90.0,
        "liquidation_short_level": 110.0,
        "liquidation_count_5m": 5,
        "liquidation_volume": 10_000.0,
        "event_time": 1,
        "feature_cutoff": 1,
        "ingested_at": 2,
        "available_at": 3,
    })
    monkeypatch.setattr(ingestor, "_read_coinank_features", lambda _symbol: {
        "coinank_open_interest": 1_000_000.0,
        "coinank_liquidation_long_turnover": 100.0,
        "coinank_liquidation_short_turnover": 200.0,
    })
    assert ingestor.fetch_market_data("BTCUSDT") == {}


def test_hypothetical_valid_candidate_is_shadow_only_and_excluded(
    monkeypatch,
) -> None:
    redis_client = FakeRedis()
    ingestor = _ingestor(redis_client)
    candidate = {
        **_valid_calculator_input(),
        "event_time": "2026-07-19T12:00:00.000Z",
        "feature_cutoff": "2026-07-19T12:00:00.000Z",
        "ingested_at": "2026-07-19T12:00:01.000Z",
        "available_at": "2026-07-19T12:00:02.000Z",
        "_real": True,
    }
    monkeypatch.setattr(ingestor, "fetch_market_data", lambda _symbol: candidate)
    assert ingestor.process_symbol("BTCUSDT") is False
    assert "v2:liquidation:enhanced:BTCUSDT" not in redis_client.writes
    shadow_key = "v2:liquidation:enhanced:shadow:BTCUSDT"
    payload = json.loads(redis_client.writes[shadow_key])
    assert payload["actual_payload_present"] is False
    assert payload["excluded_from_training"] is True
    assert payload["semantic_kind"] == "enhanced_liquidation_candidate_shadow_only"
    assert payload["feature_cutoff"] == candidate["feature_cutoff"]

