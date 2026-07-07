from __future__ import annotations

from v2.backend.app.cli import v2_agg_trades_ingestor_loop as ingestor


def _trade(ts_ms: int, price: float, qty: float, buyer_is_maker: bool) -> dict:
    return {"T": ts_ms, "p": str(price), "q": str(qty), "m": buyer_is_maker}


BASE = 1_760_000_000_000  # aligned-ish epoch ms


def test_compute_tape_features_empty() -> None:
    features = ingestor.compute_tape_features([])
    assert features["trade_count"] == 0
    assert features["taker_buy_pct_1m"] is None
    assert features["large_trade_flag"] is False


def test_compute_tape_features_buy_pressure() -> None:
    # buyer_is_maker=False means aggressive BUY
    trades = [
        _trade(BASE + offset * 1_000, 100.0, 2.0, False) for offset in range(30)
    ] + [
        _trade(BASE + 30_000 + offset * 1_000, 100.0, 1.0, True) for offset in range(10)
    ]
    features = ingestor.compute_tape_features(trades, now_ms=BASE + 40_000)
    assert features["trade_count"] == 40
    assert features["aggressive_buy_volume"] == 6000.0
    assert features["aggressive_sell_volume"] == 1000.0
    assert features["taker_buy_pct_1m"] is not None and features["taker_buy_pct_1m"] > 0.8
    assert features["delta_1m"] == 5000.0
    assert features["cumulative_delta_trend_5m"] == "RISING"


def test_compute_tape_features_sell_pressure_and_large_trade() -> None:
    trades = [_trade(BASE + offset * 500, 50.0, 1.0, True) for offset in range(40)]
    trades.append(_trade(BASE + 21_000, 50.0, 50.0, True))  # 2500 notional vs mean ~50
    features = ingestor.compute_tape_features(trades, now_ms=BASE + 22_000)
    assert features["delta_1m"] is not None and features["delta_1m"] < 0
    assert features["cumulative_delta_trend_5m"] == "FALLING"
    assert features["large_trade_flag"] is True
    assert features["large_trade_count"] == 1


def test_compute_tape_features_ignores_malformed_rows() -> None:
    trades = [
        {"T": "not-a-number", "p": "x", "q": "1", "m": False},
        {"p": "100", "q": "1"},
        _trade(BASE, 100.0, 1.0, False),
    ]
    features = ingestor.compute_tape_features(trades, now_ms=BASE)
    assert features["trade_count"] == 1


def test_run_cycle_writes_agg_and_feature_keys(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def get(self, key: str):
            return self.store.get(key)

        def set(self, key: str, value: str, ex: int | None = None):
            self.store[key] = value

    fake = FakeRedis()
    monkeypatch.setattr(ingestor, "_universe", lambda client: ["AAAUSDT", "BBBUSDT"])
    monkeypatch.setattr(ingestor, "_priority_symbols", lambda client: ["BTCUSDT"])
    monkeypatch.setattr(
        ingestor,
        "_fetch_agg_trades",
        lambda symbol, limit: [_trade(BASE, 100.0, 1.0, False)],
    )
    status = ingestor.run_cycle(client=fake, symbols_per_cycle=2, limit=100, ttl_seconds=60)
    assert status["symbols_written"] == 2
    assert "v2:market:agg_trades:BTCUSDT" in fake.store
    assert "v2:market:trade_tape_features:BTCUSDT" in fake.store
    assert status["places_real_order"] is False
    assert status["writes_legacy_redis"] is False


def test_run_cycle_records_fetch_failures(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def get(self, key: str):
            return self.store.get(key)

        def set(self, key: str, value: str, ex: int | None = None):
            self.store[key] = value

    def boom(symbol, limit):
        raise TimeoutError("timed out")

    fake = FakeRedis()
    monkeypatch.setattr(ingestor, "_universe", lambda client: [])
    monkeypatch.setattr(ingestor, "_priority_symbols", lambda client: ["BTCUSDT"])
    monkeypatch.setattr(ingestor, "_fetch_agg_trades", boom)
    status = ingestor.run_cycle(client=fake, symbols_per_cycle=1, limit=100, ttl_seconds=60)
    assert status["symbols_written"] == 0
    assert "BTCUSDT" in status["symbols_failed"]
