from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_coinapi_orderbook_ingestor import (
    OrderbookIngestor,
    OrderbookMicrostructureCalculator,
)
from v2.backend.app.cli.v2_crossexchange_analyzer import (
    CrossExchangeAnalyzer,
    CrossExchangeIngestor,
)
from v2.backend.app.cli.v2_liquidation_enhanced import (
    EnhancedLiquidationCalculator,
    EnhancedLiquidationIngestor,
)
from v2.backend.app.cli.v2_tokenmetrics_onchain_ingestor import (
    OnChainMetricsCalculator,
    TokenMetricsIngestor,
)


class FakeRedis:
    def __init__(self) -> None:
        self.writes: dict[str, str] = {}

    def setex(self, key: str, ttl_seconds: int, payload: str) -> bool:
        self.writes[key] = payload
        return True


def test_phase_c_calculators_reject_incomplete_provider_payloads() -> None:
    assert OrderbookMicrostructureCalculator().calculate_metrics([[1, 1]], [[2, 1]]) == {}
    assert OnChainMetricsCalculator().calculate_metrics({"whale_transactions_24h": 1}) == {}
    assert CrossExchangeAnalyzer().calculate_metrics(
        {"price": 100, "volume_24h": 10, "funding_rate": 0.01},
        {"price": 101, "volume_24h": 10, "funding_rate": 0.01},
    ) == {}
    assert EnhancedLiquidationCalculator().calculate_metrics(
        "BTCUSDT",
        {
            "price": 100,
            "long_oi": 10,
            "short_oi": 10,
            "liq_level_long": 95,
            "liq_level_short": 105,
        },
    ) == {}


@pytest.mark.parametrize(
    ("ingestor_cls", "calc", "process_args", "actual_key", "status_key"),
    (
        (
            OrderbookIngestor,
            OrderbookMicrostructureCalculator(),
            ("BTCUSDT",),
            "v2:microstructure:orderbook:BTCUSDT",
            "v2:microstructure:orderbook_status:BTCUSDT",
        ),
        (
            TokenMetricsIngestor,
            OnChainMetricsCalculator(),
            ("BTC", "Bitcoin"),
            "v2:onchain:tokenmetrics:BTC",
            "v2:onchain:tokenmetrics_status:BTC",
        ),
        (
            CrossExchangeIngestor,
            CrossExchangeAnalyzer(),
            ("BTCUSDT",),
            "v2:crossexchange:analysis:BTCUSDT",
            "v2:crossexchange:analysis_status:BTCUSDT",
        ),
        (
            EnhancedLiquidationIngestor,
            EnhancedLiquidationCalculator(),
            ("BTCUSDT",),
            "v2:liquidation:enhanced:BTCUSDT",
            "v2:liquidation:enhanced_status:BTCUSDT",
        ),
    ),
)
def test_phase_c_ingestors_default_to_status_only_without_provider(
    ingestor_cls,
    calc,
    process_args: tuple[str, ...],
    actual_key: str,
    status_key: str,
) -> None:
    redis = FakeRedis()
    ingestor = ingestor_cls.__new__(ingestor_cls)
    ingestor.allow_synthetic = False
    ingestor.redis = redis
    ingestor.calc = calc
    if isinstance(calc, CrossExchangeAnalyzer):
        ingestor.analyzer = calc

    assert ingestor.process_symbol(*process_args) is False
    assert actual_key not in redis.writes
    assert status_key in redis.writes
