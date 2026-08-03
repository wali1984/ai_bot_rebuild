import json

from v2.backend.app.services.preemptive_edge_control.bucket_health import (
    build_bucket_health,
    candidate_bucket_assessment,
)


def _closed_row(net_usd: float) -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "side": "long",
        "timeframe": "5m",
        "strategy_selected_mode": "trend",
        "market_regime_at_entry": "TRENDING",
        "realized_net_pnl_usd": net_usd,
        "realized_pnl_bps": net_usd,
        "gross_notional_usd": 1_000.0,
    }


def test_win_only_bucket_health_is_strict_json_with_explicit_unbounded_semantics() -> None:
    health = build_bucket_health([_closed_row(8.0), _closed_row(5.0), _closed_row(3.0)])

    symbol_bucket = health["symbol:BTCUSDT"]
    assert symbol_bucket["profit_factor"] is None
    assert symbol_bucket["profit_factor_unbounded_no_losses"] is True
    assert symbol_bucket["profit_factor_semantics"] == ("UNBOUNDED_POSITIVE_WINS_WITH_NO_LOSSES")
    json.dumps(health, sort_keys=True, allow_nan=False)

    assessment = candidate_bucket_assessment(
        health,
        symbol="BTCUSDT",
        side="long",
        timeframe="5m",
        strategy_mode="trend",
        regime="TRENDING",
        min_evidence_count=3,
    )
    assert assessment["bucket_profit_factor"] is None
    assert assessment["bucket_profit_factor_unbounded_no_losses"] is True
    assert "symbol:BTCUSDT" in assessment["unbounded_profit_factor_buckets"]
    assert assessment["bucket_negative"] is False


def test_bucket_health_keeps_finite_profit_factor_when_losses_exist() -> None:
    health = build_bucket_health([_closed_row(8.0), _closed_row(4.0), _closed_row(-2.0)])

    symbol_bucket = health["symbol:BTCUSDT"]
    assert symbol_bucket["profit_factor"] == 6.0
    assert symbol_bucket["profit_factor_unbounded_no_losses"] is False
    assert symbol_bucket["profit_factor_semantics"] == ("FINITE_GROSS_WINS_DIVIDED_BY_GROSS_LOSSES")
