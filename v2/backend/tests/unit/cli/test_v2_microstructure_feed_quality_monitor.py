from __future__ import annotations

import json

from v2.backend.app.cli import v2_microstructure_feed_quality_monitor as monitor


class FakeRedis:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.store = {key: json.dumps(value) for key, value in (initial or {}).items()}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        assert key.startswith("v2:microstructure:")
        self.store[key] = value


def test_microstructure_monitor_writes_only_microstructure_keys(tmp_path) -> None:
    fake = FakeRedis(
        {
            "v2:orderbook:features:binance:BTCUSDT": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "spread_bps": 10.0,
                "event_time": "2026-07-02T12:00:00.000Z",
                "transaction_time": "2026-07-02T12:00:00.010Z",
                "received_at": "2026-07-02T12:00:00.020Z",
                "available_at": "2026-07-02T12:00:00.020Z",
            },
            "v2:market:agg_trades:BTCUSDT": [
                {"price": 100.0, "quantity": 1.0, "side": "buy"},
                {"price": 100.1, "quantity": 1.0, "side": "buy"},
            ],
        }
    )

    result = monitor.run_once(
        symbols=["BTCUSDT"],
        timeframe="1m",
        exchanges=["binance"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    assert result["old_redis_writes"] is False
    assert result["places_real_order"] is False
    assert result["redis_keys_written"]
    assert all(key.startswith("v2:microstructure:") for key in result["redis_keys_written"])
    trust = json.loads(fake.store["v2:microstructure:trust_score:BTCUSDT:1m"])
    assert trust["public_book_can_approve_trade_alone"] is False
    assert trust["direct_binance_kucoin_active"] is True
    assert trust["direct_orderbook_sources"] == ["binance"]
    assert trust["orderbook_sources"] == ["binance"]
    assert trust["source_availability"]["binance_direct_orderbook"] is True
    assert "microstructure_action" in trust


def test_microstructure_monitor_consumes_generic_v2_market_orderbook_without_overstating_direct_feed(tmp_path) -> None:
    fake = FakeRedis(
        {
            "v2:market:orderbook:BTCUSDT": {
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "event_time": "2026-07-02T12:00:00.000Z",
                "transaction_time": "2026-07-02T12:00:00.010Z",
                "received_at": "2026-07-02T12:00:00.020Z",
                "available_at": "2026-07-02T12:00:00.020Z",
            },
        }
    )

    result = monitor.run_once(
        symbols=["BTCUSDT"],
        timeframe="1m",
        exchanges=["binance", "kucoin"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    assert "v2:microstructure:trust_score:BTCUSDT:1m" in result["redis_keys_written"]
    trust = json.loads(fake.store["v2:microstructure:trust_score:BTCUSDT:1m"])
    assert trust["direct_binance_kucoin_active"] is False
    assert trust["direct_orderbook_sources"] == []
    assert trust["orderbook_sources"] == ["binance"]
    assert trust["source_availability"]["binance"] is True
    assert trust["source_availability"]["kucoin"] is False
    assert trust["source_availability"]["binance_direct_orderbook"] is False
    assert "LOCAL_LATENCY_MISSING" not in (trust.get("feed_quality_fail_reasons") or [])
    row = result["trust_rows"][0]
    assert row["source_availability"]["kucoin"] is False
    assert row["source_availability"]["direct_binance_or_kucoin"] is False
    assert result["old_redis_writes"] is False
    assert result["places_real_order"] is False


def test_microstructure_monitor_explains_provider_unsupported_venue(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        monitor,
        "_load_provider_symbol_support",
        lambda: {
            "kucoin": {
                "BICOUSDT": {
                    "provider_symbol": "BICOUSDTM",
                    "listed": False,
                    "orderbook_supported": False,
                    "status": "MISSING",
                }
            }
        },
    )
    fake = FakeRedis(
        {
            "v2:orderbook:features:binance:BICOUSDT": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "event_time": "2026-07-02T12:00:00.000Z",
                "transaction_time": "2026-07-02T12:00:00.010Z",
                "received_at": "2026-07-02T12:00:00.020Z",
                "available_at": "2026-07-02T12:00:00.020Z",
            },
        }
    )

    result = monitor.run_once(
        symbols=["BICOUSDT"],
        timeframe="1m",
        exchanges=["binance", "kucoin"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    trust = json.loads(fake.store["v2:microstructure:trust_score:BICOUSDT:1m"])
    assert result["places_real_order"] is False
    assert trust["direct_orderbook_sources"] == ["binance"]
    assert trust["source_availability"]["kucoin_direct_orderbook"] is False
    assert trust["venue_unavailable_reasons"]["kucoin"] == (
        "KUCOIN_DIRECT_ORDERBOOK_UNSUPPORTED:MISSING:BICOUSDTM"
    )
    assert trust["provider_symbol_support_details"]["kucoin"]["listed"] is False


def test_microstructure_monitor_uses_direct_orderbook_source_latency(tmp_path) -> None:
    observed_at = monitor.iso_now()
    fake = FakeRedis(
        {
            "v2:orderbook:features:binance:ETHUSDT": {
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "received_at": observed_at,
                "available_at": observed_at,
                "source_latency_ms": 42,
            },
        }
    )

    result = monitor.run_once(
        symbols=["ETHUSDT"],
        timeframe="1m",
        exchanges=["binance"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    feed = json.loads(fake.store["v2:microstructure:feed_quality:binance:ETHUSDT"])
    assert feed["local_latency_ms"] == 42
    assert feed["local_latency_source"] == "observed_local_latency_ms"
    assert "LOCAL_LATENCY_MISSING" not in (feed.get("fail_reasons") or [])
    trust = json.loads(fake.store["v2:microstructure:trust_score:ETHUSDT:1m"])
    assert "LOCAL_LATENCY_MISSING" not in (trust.get("feed_quality_fail_reasons") or [])


def test_microstructure_monitor_uses_binance_event_and_transaction_timestamp_aliases(tmp_path) -> None:
    fake = FakeRedis(
        {
            "v2:market:orderbook:binance:ETHUSDT": {
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "E": 1783298709000,
                "T": 1783298709010,
                "available_at": 1783298709052,
            },
        }
    )

    result = monitor.run_once(
        symbols=["ETHUSDT"],
        timeframe="1m",
        exchanges=["binance"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    feed = json.loads(fake.store["v2:microstructure:feed_quality:binance:ETHUSDT"])
    assert feed["event_time"] == 1783298709000
    assert feed["transaction_time"] == 1783298709010
    assert feed["local_latency_ms"] == 42
    assert feed["local_latency_source"] == "timestamp_delta"
    assert "LOCAL_LATENCY_MISSING" not in (feed.get("fail_reasons") or [])
    trust = result["trust_rows"][0]
    assert "LOCAL_LATENCY_MISSING" not in (trust.get("feed_quality_fail_reasons") or [])


def test_microstructure_context_reads_binance_and_coinglass_derivatives_aliases() -> None:
    fake = FakeRedis(
        {
            "v2:market:long_short:BTCUSDT": {
                "longShortRatio": "1.5740",
            },
            "v2:market:funding:BTCUSDT": {
                "lastFundingRate": "0.00006622",
            },
            "v2:features:coinglass:BTCUSDT:1m": {
                "features": {
                    "coinglass_open_interest_delta_usd_5m": -100.0,
                    "coinglass_open_interest_usd": 10000.0,
                }
            },
        }
    )

    ctx = monitor._read_context(fake, "BTCUSDT", "1m")

    assert ctx["long_short_ratio"] == 1.574
    assert ctx["funding_rate"] == 0.00006622
    assert ctx["open_interest_change_pct"] == -0.01


def test_microstructure_context_derives_open_interest_change_from_hist() -> None:
    fake = FakeRedis(
        {
            "v2:market:long_short:ALICEUSDT": {
                "long_short_ratio": 1.2,
            },
            "v2:market:funding:ALICEUSDT": {
                "lastFundingRate": "0.00005",
            },
            "v2:market:open_interest_hist:ALICEUSDT:5m": [
                {"sumOpenInterest": "1000", "timestamp": 1_780_000_000_000},
                {"sumOpenInterest": "1050", "timestamp": 1_780_000_300_000},
            ],
        }
    )

    ctx = monitor._read_context(fake, "ALICEUSDT", "1m")

    assert ctx["long_short_ratio"] == 1.2
    assert ctx["funding_rate"] == 0.00005
    assert ctx["open_interest_change_pct"] == 0.05


def test_combined_feed_quality_does_not_fail_close_on_secondary_latency_warning() -> None:
    out = monitor._combine_feed_quality(
        [
            {
                "exchange": "binance",
                "feed_quality_score": 0.92,
                "latency_ms": 96,
                "local_latency_ms": 96,
                "sequence_gap_count": 0,
                "fail_closed": False,
                "fail_reasons": [],
            },
            {
                "exchange": "kucoin",
                "feed_quality_score": 0.64,
                "latency_ms": 2200,
                "local_latency_ms": 2200,
                "sequence_gap_count": 0,
                "fail_closed": True,
                "fail_reasons": ["LATENCY_ABOVE_ADAPTIVE_BOUND"],
            },
        ]
    )

    assert out["fail_closed"] is False
    assert out["feed_quality_score"] == 0.92
    assert out["latency_ms"] == 96
    assert out["usable_source_exchanges"] == ["binance"]
    assert out["fail_reasons"] == []
    assert out["secondary_feed_warning_reasons"] == ["kucoin:LATENCY_ABOVE_ADAPTIVE_BOUND"]
    assert out["all_feed_fail_reasons"] == ["LATENCY_ABOVE_ADAPTIVE_BOUND"]


def test_combined_feed_quality_preserves_hard_temporal_failures() -> None:
    out = monitor._combine_feed_quality(
        [
            {
                "exchange": "binance",
                "feed_quality_score": 0.92,
                "latency_ms": 96,
                "sequence_gap_count": 0,
                "fail_closed": False,
                "fail_reasons": [],
            },
            {
                "exchange": "kucoin",
                "feed_quality_score": 0.80,
                "latency_ms": 100,
                "sequence_gap_count": 0,
                "fail_closed": True,
                "fail_reasons": ["AVAILABLE_AT_AFTER_DECISION_TIME"],
            },
        ]
    )

    assert out["fail_closed"] is True
    assert out["fail_reasons"] == ["AVAILABLE_AT_AFTER_DECISION_TIME"]
    assert out["combined_fail_policy"] == "hard_temporal_or_all_venues_failed"


def test_microstructure_monitor_decision_time_is_after_book_read(monkeypatch, tmp_path) -> None:
    fake = FakeRedis(
        {
            "v2:orderbook:features:binance:SOLUSDT": {
                "bids": [[100.0, 2.0]],
                "asks": [[100.1, 2.0]],
                "received_at": "2026-07-02T12:00:00.002Z",
                "available_at": "2026-07-02T12:00:00.002Z",
                "source_latency_ms": 42,
            },
        }
    )
    stamps = iter(
        [
            "2026-07-02T12:00:00.000Z",
            "2026-07-02T12:00:00.003Z",
        ]
    )
    monkeypatch.setattr(
        monitor,
        "iso_now",
        lambda: next(stamps, "2026-07-02T12:00:00.004Z"),
    )

    result = monitor.run_once(
        symbols=["SOLUSDT"],
        timeframe="1m",
        exchanges=["binance"],
        replay_root=tmp_path,
        write_redis=True,
        redis_client_override=fake,
    )

    trust = result["trust_rows"][0]
    assert trust["decision_time"] == "2026-07-02T12:00:00.003Z"
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" not in (trust.get("feed_quality_fail_reasons") or [])


def test_microstructure_status_does_not_overstate_missing_direct_feed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(monitor, "REPO_ROOT", tmp_path)

    result = monitor.run_once(
        symbols=["BTCUSDT"],
        timeframe="1m",
        exchanges=["binance", "kucoin"],
        replay_root=tmp_path,
        write_status=True,
        redis_client_override=FakeRedis(),
    )

    assert result["trust_rows"][0]["direct_binance_kucoin_active"] is False
    goal_dir = tmp_path / "goal_state" / monitor.GOAL_ID
    website = json.loads((goal_dir / "website_microstructure_truth_status.json").read_text())
    paper = json.loads((goal_dir / "paper_microstructure_cost_evidence_status.json").read_text())
    assert website["direct_binance_kucoin_active"] is False
    assert website["symbols_covered"] == 0
    assert website["symbols_evaluated"] == 1
    assert "BTCUSDT" in website["stale_symbols"]
    assert paper["paper_fills_have_real_spread_source"] is False
    assert paper["paper_fills_have_real_depth_source"] is False


def test_microstructure_monitor_loop_mode_runs_bounded_cycles(monkeypatch, tmp_path, capsys) -> None:
    calls: list[list[str]] = []

    def fake_run_once(**kwargs):
        calls.append(list(kwargs["symbols"]))
        return {
            "schema_version": "v2_microstructure_feed_quality_monitor_run_v1",
            "symbols": kwargs["symbols"],
            "trust_rows": [],
            "feed_summary": {"rows": 0},
            "places_real_order": False,
            "test_orders": False,
            "old_redis_writes": False,
            "redis_trim": False,
        }

    monkeypatch.setattr(monitor, "run_once", fake_run_once)

    assert monitor.main(
        [
            "--symbols",
            "BTCUSDT",
            "--loop",
            "--loop-max-runs",
            "2",
            "--interval-seconds",
            "0",
            "--replay-root",
            str(tmp_path),
        ]
    ) == 0

    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert calls == [["BTCUSDT"], ["BTCUSDT"]]
    assert [row["loop_run_index"] for row in outputs] == [1, 2]
    assert all(row["loop"] is True for row in outputs)
    assert all(row["places_real_order"] is False for row in outputs)
    assert all(
        row["schema_version"] == "v2_microstructure_feed_quality_monitor_loop_log_v1"
        for row in outputs
    )
    assert all(row["symbols_count"] == 1 for row in outputs)
    assert all("symbols" not in row for row in outputs)
    assert all("trust_rows" not in row for row in outputs)


def test_microstructure_monitor_full_loop_log_mode_is_explicit(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(
        monitor,
        "run_once",
        lambda **kwargs: {
            "schema_version": "v2_microstructure_feed_quality_monitor_run_v1",
            "symbols": kwargs["symbols"],
            "trust_rows": [{"symbol": "BTCUSDT"}],
            "feed_summary": {"rows": 0},
            "places_real_order": False,
        },
    )

    assert monitor.main(
        [
            "--symbols",
            "BTCUSDT",
            "--loop",
            "--loop-max-runs",
            "1",
            "--loop-log-mode",
            "full",
            "--interval-seconds",
            "0",
            "--replay-root",
            str(tmp_path),
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "v2_microstructure_feed_quality_monitor_run_v1"
    assert output["symbols"] == ["BTCUSDT"]
    assert output["trust_rows"] == [{"symbol": "BTCUSDT"}]
