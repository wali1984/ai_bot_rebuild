from __future__ import annotations

import datetime as dt
import json

from v2.backend.app.services import adaptive_symbol_selection_runtime as runtime
from v2.backend.app.services.adaptive_symbol_selection import (
    select_adaptive_symbol_universe,
)


class _Redis:
    def __init__(self, values: dict[str, object]):
        self.values = {
            key: json.dumps(value, separators=(",", ":")).encode() for key, value in values.items()
        }

    def getrange(self, key: str, start: int, end: int) -> bytes:
        return self.values.get(key, b"")[start : end + 1]


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _candles(symbol: str, *, dirty_last: bool = False) -> list[dict[str, object]]:
    first_open = _ms("2026-07-19T23:00:00Z")
    rows: list[dict[str, object]] = []
    for index in range(72):
        open_ms = first_open + index * runtime.OHLCV_INTERVAL_MS
        close_ms = open_ms + runtime.OHLCV_INTERVAL_MS - 1
        price = 100.0 + (index * 0.1) + (0.2 if index % 2 else -0.1)
        open_price = price - 0.05
        rows.append(
            {
                "symbol": symbol,
                "timeframe": runtime.OHLCV_TIMEFRAME,
                "candle_open_time": open_ms,
                "candle_close_time": close_ms,
                "closed_candle": True,
                "candle_closed_confirmed": not (dirty_last and index == 71),
                "is_closed": True,
                "event_time": close_ms + 10,
                "ingested_at": close_ms + 20,
                "available_at": close_ms + 20,
                "open": open_price,
                "high": max(open_price, price) + 0.1,
                "low": min(open_price, price) - 0.1,
                "close": price,
                "volume": 500.0 + index,
                "quote_volume": 50_000.0 + index,
            }
        )
    return rows


def _orderbook(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sequence_gap": False,
        "best_bid": 106.9,
        "best_ask": 107.0,
        "best_bid_size": 20.0,
        "best_ask_size": 25.0,
        "event_time": "2026-07-20T04:59:30.000Z",
        "received_at": "2026-07-20T04:59:30.050Z",
        "available_at": "2026-07-20T04:59:30.050Z",
        "generated_at": "2026-07-20T04:59:30.060Z",
    }


def _coverage(symbol: str, *, training_ready: bool) -> dict[str, object]:
    return {
        "generated_utc": "2026-07-20T04:59:00Z",
        "symbols": {
            symbol: {
                "families": {
                    "ohlcv_closed": {"source_windows_ready": True},
                    "prices": {"status": "ok"},
                    "orderbook": {"status": "ok"},
                    "open_interest": {"status": "ok"},
                    "ta_full": {"trainer_consumption_ready": training_ready},
                    "feature_snapshot": {"trainer_consumption_ready": training_ready},
                }
            }
        },
    }


def _reader(symbol: str, *, training_ready: bool, dirty_last: bool = False) -> _Redis:
    return _Redis(
        {
            runtime.COVERAGE_REDIS_KEY: _coverage(symbol, training_ready=training_ready),
            f"v2:market:ohlcv_closed:binance:{symbol}:5m": _candles(symbol, dirty_last=dirty_last),
            f"v2:market:orderbook:{symbol}": _orderbook(symbol),
        }
    )


def test_runtime_adapter_uses_final_candles_and_explicit_book_clocks(monkeypatch) -> None:
    observed = dt.datetime.fromisoformat("2026-07-20T05:00:01+00:00").timestamp()
    monkeypatch.setattr(runtime.time, "time", lambda: observed)

    evidence = runtime.build_runtime_selection_evidence(
        _reader("BTCUSDT", training_ready=True),
        ["BTCUSDT"],
        edge_payload={
            "per_symbol": [
                {
                    "symbol": "BTCUSDT",
                    "outcome_sample_count": 0,
                    "current_prediction_confidence": 0.999,
                }
            ]
        },
    )
    row = evidence["evidence_rows"][0]

    assert row["candle_final"] is True
    assert row["closed_candle_count"] == 72
    assert row["closed_quote_volume_usd"] > 3_500_000.0
    assert row["realized_volatility_bps"] > 0.0
    assert row["market_data_coverage_ratio"] == 1.0
    assert row["training_data_ready"] is True
    assert row["source_blockers"] == []
    assert "current_prediction_confidence" not in row

    selection = select_adaptive_symbol_universe(
        evidence["evidence_rows"], decision_time=evidence["decision_time"]
    )
    assert selection["training_eligible_symbols"] == ["BTCUSDT"]
    assert selection["trading_eligible_symbols"] == []
    assert selection["metrics"]["predictability_proven_symbol_count"] == 0


def test_consumer_held_training_pipeline_fails_closed(monkeypatch) -> None:
    observed = dt.datetime.fromisoformat("2026-07-20T05:00:01+00:00").timestamp()
    monkeypatch.setattr(runtime.time, "time", lambda: observed)

    evidence = runtime.build_runtime_selection_evidence(
        _reader("BTCUSDT", training_ready=False), ["BTCUSDT"]
    )
    selection = select_adaptive_symbol_universe(
        evidence["evidence_rows"], decision_time=evidence["decision_time"]
    )

    assert selection["training_eligible_symbols"] == []
    assert (
        "source:coverage_trainer_consumption_not_explicitly_ready"
        in selection["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    )


def test_partially_formed_or_dirty_candle_window_fails_closed(monkeypatch) -> None:
    observed = dt.datetime.fromisoformat("2026-07-20T05:00:01+00:00").timestamp()
    monkeypatch.setattr(runtime.time, "time", lambda: observed)

    evidence = runtime.build_runtime_selection_evidence(
        _reader("BTCUSDT", training_ready=True, dirty_last=True), ["BTCUSDT"]
    )
    selection = select_adaptive_symbol_universe(
        evidence["evidence_rows"], decision_time=evidence["decision_time"]
    )

    assert selection["training_eligible_symbols"] == []
    blockers = selection["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    assert any("finality_invalid" in blocker for blocker in blockers)


def test_unrepresentable_coverage_clock_is_a_row_blocker(monkeypatch) -> None:
    observed = dt.datetime.fromisoformat("2026-07-20T05:00:01+00:00").timestamp()
    monkeypatch.setattr(runtime.time, "time", lambda: observed)
    reader = _reader("BTCUSDT", training_ready=True)
    coverage = _coverage("BTCUSDT", training_ready=True)
    coverage["generated_utc"] = 1.0e300
    reader.values[runtime.COVERAGE_REDIS_KEY] = json.dumps(coverage).encode()

    evidence = runtime.build_runtime_selection_evidence(reader, ["BTCUSDT"])
    selection = select_adaptive_symbol_universe(
        evidence["evidence_rows"], decision_time=evidence["decision_time"]
    )

    assert selection["training_eligible_symbols"] == []
    assert (
        "source:coverage_census_clock_invalid"
        in selection["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    )


def test_duplicate_edge_rows_fail_closed_independent_of_order(monkeypatch) -> None:
    observed = dt.datetime.fromisoformat("2026-07-20T05:00:01+00:00").timestamp()
    monkeypatch.setattr(runtime.time, "time", lambda: observed)
    proven = {
        "symbol": "BTCUSDT",
        "outcome_sample_count": 90,
        "after_cost_expectancy_bps": 12.0,
        "after_cost_ci_lower_bps": 5.0,
        "validation_out_of_sample": True,
        "validation_after_cost": True,
        "validation_leakage_free": True,
        "validation_cutoff": "2026-07-20T04:00:00Z",
        "validation_event_time": "2026-07-20T04:00:01Z",
        "validation_ingested_at": "2026-07-20T04:00:02Z",
        "validation_available_at": "2026-07-20T04:00:03Z",
        "validation_generated_at": "2026-07-20T04:00:04Z",
    }
    incomplete = {"symbol": "BTCUSDT", "outcome_sample_count": 0}
    observed_blockers: list[list[str]] = []

    for edge_rows in ([proven, incomplete], [incomplete, proven]):
        evidence = runtime.build_runtime_selection_evidence(
            _reader("BTCUSDT", training_ready=True),
            ["BTCUSDT"],
            edge_payload={"per_symbol": edge_rows},
        )
        row = evidence["evidence_rows"][0]
        selection = select_adaptive_symbol_universe(
            [row], decision_time=evidence["decision_time"]
        )
        explanation = selection["symbol_explanations"]["BTCUSDT"]

        assert "validation_sample_count" not in row
        assert row["validation_source_blockers"] == [
            "duplicate_edge_symbol_evidence"
        ]
        assert selection["training_eligible_symbols"] == ["BTCUSDT"]
        assert selection["trading_eligible_symbols"] == []
        assert evidence["metrics"]["duplicate_edge_symbol_count"] == 1
        assert evidence["metrics"]["duplicate_edge_symbols"] == ["BTCUSDT"]
        observed_blockers.append(explanation["trading_blockers"])

    assert observed_blockers[0] == observed_blockers[1]
    assert "source:duplicate_edge_symbol_evidence" in observed_blockers[0]
