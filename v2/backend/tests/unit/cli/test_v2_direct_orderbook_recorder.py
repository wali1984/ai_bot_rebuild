from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from v2.backend.app.cli import v2_direct_orderbook_recorder as recorder
from v2.backend.app.services.orderbook_recorder.local_book import LocalOrderBook
from v2.backend.app.services.orderbook_recorder.store import LocalReplayStore


class FakeRedis:
    def __init__(self, store: dict[str, object]):
        self.store = store
        self.read_keys: list[str] = []
        self.write_calls: list[tuple[str, int | None]] = []

    def get(self, key: str):
        self.read_keys.append(key)
        return self.store.get(key)

    def set(self, key: str, value: object, ex: int | None = None):
        self.write_calls.append((key, ex))
        self.store[key] = value
        return True


def _binance_usdm_symbol_filter_row(symbol: str) -> dict[str, object]:
    normalized = symbol.upper()
    return {
        "symbol": normalized,
        "status": "TRADING",
        "contractType": "PERPETUAL",
        "baseAsset": normalized.removesuffix("USDT"),
        "quoteAsset": "USDT",
        "filters": [
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
            {
                "filterType": "LOT_SIZE",
                "minQty": "1",
                "maxQty": "1000000",
                "stepSize": "1",
            },
            {
                "filterType": "MARKET_LOT_SIZE",
                "minQty": "1",
                "maxQty": "1000000",
                "stepSize": "1",
            },
            {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
        ],
    }


def test_snapshot_seed_limit_reserves_budget_for_live_updates() -> None:
    assert recorder._snapshot_seed_limit(symbol_count=0, max_messages=10) == 0
    assert recorder._snapshot_seed_limit(symbol_count=10, max_messages=0) == 0
    assert recorder._snapshot_seed_limit(symbol_count=10, max_messages=1) == 1
    assert recorder._snapshot_seed_limit(symbol_count=10, max_messages=5) == 2
    assert recorder._snapshot_seed_limit(symbol_count=3, max_messages=10) == 3


def test_binance_seed_limit_skips_rest_seed_without_diff_depth() -> None:
    assert recorder._binance_snapshot_seed_limit(
        symbol_count=24,
        max_messages=120,
        include_diff_depth=False,
    ) == 0
    assert recorder._binance_snapshot_seed_limit(
        symbol_count=24,
        max_messages=120,
        include_diff_depth=True,
    ) == 24


def test_binance_websocket_startup_seed_uses_cache_not_rest(monkeypatch, tmp_path) -> None:
    def fail_rest_seed(*_args, **_kwargs):
        raise AssertionError("REST depth must not be used as WebSocket startup seed")

    def cached_seed(symbol: str, *, redis_client=None):
        return {
            "exchange": "binance",
            "symbol": symbol.upper(),
            "type": "websocket_cache_snapshot",
            "bids": [["100", "1"]],
            "asks": [["101", "1"]],
            "sequence_id": 100,
            "is_snapshot": True,
            "raw": {"transport": "websocket_cache_primary"},
        }

    monkeypatch.setattr(recorder, "fetch_binance_snapshot", fail_rest_seed)
    monkeypatch.setattr(recorder, "_binance_snapshot_from_cache", cached_seed)
    store = LocalReplayStore(tmp_path / "orderbook_replay")

    rows = asyncio.run(
        recorder._run_binance_ws(
            symbols=["BTCUSDT"],
            books={},
            replay_store=store,
            redis_client=None,
            max_messages=1,
            speed="100ms",
            include_diff_depth=True,
        )
    )

    assert rows[0]["update_type"] == "websocket_cache_snapshot_seed"
    assert rows[0]["rest_fallback_used"] is False


def test_redis_feature_freshness_status_reports_fresh_key() -> None:
    feature_key = recorder._features_key("binance", "BTCUSDT")
    redis = FakeRedis(
        {
            feature_key: json.dumps(
                {
                    "available_at": recorder.utc_now_iso(),
                    "received_at": recorder.utc_now_iso(),
                    "generated_at": recorder.utc_now_iso(),
                    "update_type": "partial_depth",
                    "sequence_gap": False,
                    "source_latency_ms": 12.0,
                }
            )
        }
    )

    status = recorder._redis_feature_freshness_status(
        redis,
        exchange_symbols={"binance": ["BTCUSDT"]},
        stale_bound_ms=1500.0,
    )

    assert redis.read_keys == [feature_key]
    assert status["old_redis_reads"] is False
    assert status["old_redis_writes"] is False
    assert status["redis_trim"] is False
    assert status["fresh_symbol_count"] == 1
    assert status["stale_symbol_count"] == 0
    assert status["missing_symbol_count"] == 0
    assert status["by_symbol"]["binance:BTCUSDT"]["fresh"] is True


def test_redis_feature_freshness_status_reports_stale_and_missing_keys() -> None:
    feature_key = recorder._features_key("binance", "BTCUSDT")
    redis = FakeRedis(
        {
            feature_key: json.dumps(
                {
                    "available_at": "2026-01-01T00:00:00.000Z",
                    "update_type": "partial_depth",
                    "sequence_gap": True,
                    "source_latency_ms": 20.0,
                }
            )
        }
    )

    status = recorder._redis_feature_freshness_status(
        redis,
        exchange_symbols={"binance": ["BTCUSDT", "ETHUSDT"]},
        stale_bound_ms=1500.0,
    )

    assert status["fresh_symbol_count"] == 0
    assert status["stale_symbol_count"] == 1
    assert status["missing_symbol_count"] == 1
    assert status["by_symbol"]["binance:BTCUSDT"]["stale_reason"] == "BOOK_UPDATE_AGE_TOO_HIGH"
    assert status["by_symbol"]["binance:BTCUSDT"]["sequence_gap"] is True
    assert status["by_symbol"]["binance:ETHUSDT"]["stale_reason"] == "KEY_MISSING"


def test_process_raw_message_writes_replay_and_new_key_names(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    books: dict[tuple[str, str], LocalOrderBook] = {}
    raw = {
        "stream": "btcusdt@depth20@100ms",
        "data": {
            "e": "depthUpdate",
            "E": 1780000000000,
            "T": 1780000000001,
            "s": "BTCUSDT",
            "U": 10,
            "u": 11,
            "pu": 9,
            "b": [["100", "2"]],
            "a": [["101", "3"]],
        },
    }

    result = recorder.process_raw_message(
        json.dumps(raw),
        parser_name="binance",
        books=books,
        replay_store=store,
    )

    assert result is not None
    assert result["features"]["spread_bps"] is not None
    assert f"{recorder.NEW_REDIS_PREFIX}top:binance:BTCUSDT" in result["redis_keys"]
    assert store.status()["symbols_recorded"] == 1


def test_binance_partial_depth_does_not_reset_diff_sequence_anchor(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    books: dict[tuple[str, str], LocalOrderBook] = {}

    recorder.process_event(
        {
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "type": "rest_snapshot",
            "bids": [["100", "1"]],
            "asks": [["101", "1"]],
            "sequence_id": 100,
            "is_snapshot": True,
        },
        books=books,
        replay_store=store,
    )
    recorder.process_event(
        {
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "type": "partial_depth",
            "bids": [["100", "2"]],
            "asks": [["101", "2"]],
            "sequence_id": 120,
            "previous_sequence_id": 119,
            "is_snapshot": True,
        },
        books=books,
        replay_store=store,
    )
    result = recorder.process_event(
        {
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "type": "diff_depth",
            "bids": [["100", "3"]],
            "asks": [],
            "first_sequence_id": 101,
            "final_sequence_id": 101,
            "previous_sequence_id": 100,
            "sequence_id": 101,
            "is_snapshot": False,
        },
        books=books,
        replay_store=store,
    )

    assert result["sequence_gap"] is False
    assert result["features"]["sequence_gap_flag"] == 0


def test_rest_snapshot_seed_records_observed_latency_without_exchange_timestamp(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    books: dict[tuple[str, str], LocalOrderBook] = {}

    result = recorder.process_event(
        {
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "type": "rest_snapshot",
            "bids": [["100", "1"]],
            "asks": [["101", "1"]],
            "sequence_id": 100,
            "is_snapshot": True,
        },
        books=books,
        replay_store=store,
    )

    assert result["features"]["event_time"] is None
    assert result["features"]["transaction_time"] is None
    assert result["features"]["source_latency_ms"] == 0.0


def test_write_goal_statuses_records_zero_budget_decision(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "replay")
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="features",
        event_time="2026-06-01T00:00:00.000Z",
        payload={
            "event_time": "2026-06-01T00:00:00.000Z",
            "bid": 100.0,
            "ask": 101.0,
            "sequence_gap": False,
        },
    )
    recorder.write_goal_statuses(repo_root=tmp_path, replay_store=store, recorder_active=False)

    status_path = (
        tmp_path
        / "goal_state"
        / recorder.GOAL_ID
        / "zero_budget_provider_decision_status.json"
    )
    payload = json.loads(status_path.read_text())

    assert payload["coinapi_renewal_required"] is False
    assert payload["tardis_purchase_required"] is False
    assert payload["primary_live_orderbook_source"] == "direct_binance_kucoin"
    assert payload["live_gate"] == "blocked_human_only"

    website_path = (
        tmp_path
        / "goal_state"
        / recorder.GOAL_ID
        / "website_orderbook_runtime_truth_status.json"
    )
    website = json.loads(website_path.read_text())
    assert website["direct_binance_active"] is True
    assert website["direct_kucoin_active"] is False
    assert website["direct_binance_kucoin_active"] is False


def test_exchange_both_reserves_message_budget_for_kucoin(monkeypatch, tmp_path, capsys) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_binance_ws(**kwargs):
        calls.append(("binance", kwargs["max_messages"]))
        return [{"exchange": "binance", "symbol": "BTCUSDT"} for _ in range(kwargs["max_messages"])]

    async def fake_kucoin_ws(**kwargs):
        calls.append(("kucoin", kwargs["max_messages"]))
        return [{"exchange": "kucoin", "symbol": "BTCUSDT"} for _ in range(kwargs["max_messages"])]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)
    monkeypatch.setattr(recorder, "_run_kucoin_ws", fake_kucoin_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "both",
            "--max-messages",
            "5",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert calls == [("binance", 2), ("kucoin", 3)]
    assert output["processed_exchanges"] == ["binance", "kucoin"]
    assert output["direct_binance_kucoin_active"] is True


def test_binance_diff_depth_stream_requires_explicit_flag(monkeypatch, tmp_path, capsys) -> None:
    calls: list[bool] = []

    async def fake_binance_ws(**kwargs):
        calls.append(kwargs["include_diff_depth"])
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "partial_depth"}]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--replay-root",
            str(tmp_path / "replay-default"),
        ]
    ) == 0
    default_output = json.loads(capsys.readouterr().out)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--binance-include-diff-depth",
            "--replay-root",
            str(tmp_path / "replay-diff"),
        ]
    ) == 0
    diff_output = json.loads(capsys.readouterr().out)

    assert calls == [False, True]
    assert default_output["binance_include_diff_depth"] is False
    assert "btcusdt@depth@100ms" not in default_output["binance_streams"]
    assert diff_output["binance_include_diff_depth"] is True
    assert "btcusdt@depth@100ms" in diff_output["binance_streams"]


def test_binance_book_ticker_stream_requires_explicit_flag(monkeypatch, tmp_path, capsys) -> None:
    calls: list[bool] = []

    async def fake_binance_ws(**kwargs):
        calls.append(kwargs["include_book_ticker"])
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "partial_depth"}]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--replay-root",
            str(tmp_path / "replay-no-book-ticker"),
        ]
    ) == 0
    default_output = json.loads(capsys.readouterr().out)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--binance-include-book-ticker",
            "--replay-root",
            str(tmp_path / "replay-book-ticker"),
        ]
    ) == 0
    opt_in_output = json.loads(capsys.readouterr().out)

    assert calls == [False, True]
    assert default_output["binance_include_book_ticker"] is False
    assert "btcusdt@bookTicker" not in default_output["binance_streams"]
    assert opt_in_output["binance_include_book_ticker"] is True
    assert "btcusdt@bookTicker" in opt_in_output["binance_streams"]


def test_binance_book_ticker_only_removes_partial_depth_streams(monkeypatch, tmp_path, capsys) -> None:
    calls: list[dict[str, object]] = []

    async def fake_binance_ws(**kwargs):
        calls.append(
            {
                "include_book_ticker": kwargs["include_book_ticker"],
                "include_diff_depth": kwargs["include_diff_depth"],
                "partial_levels": kwargs["partial_levels"],
            }
        )
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "book_ticker"}]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT,ETHUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--binance-book-ticker-only",
            "--replay-root",
            str(tmp_path / "replay-book-ticker-only"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert calls == [
        {
            "include_book_ticker": True,
            "include_diff_depth": False,
            "partial_levels": (),
        }
    ]
    assert output["binance_book_ticker_only"] is True
    assert output["binance_partial_depth_levels"] == []
    assert output["binance_streams"] == ["btcusdt@bookTicker", "ethusdt@bookTicker"]


def test_websocket_close_timeout_is_passed_to_exchange_runner(monkeypatch, tmp_path, capsys) -> None:
    calls: list[float] = []

    async def fake_binance_ws(**kwargs):
        calls.append(kwargs["websocket_close_timeout_seconds"])
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "partial_depth"}]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--ws-close-timeout-seconds",
            "0.25",
            "--replay-root",
            str(tmp_path / "replay-close-timeout"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert calls == [0.25]
    assert output["ws_close_timeout_seconds"] == 0.25


def test_loop_mode_runs_bounded_recorder_cycles(monkeypatch, tmp_path, capsys) -> None:
    calls: list[int] = []

    async def fake_binance_ws(**kwargs):
        calls.append(kwargs["max_messages"])
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "book_ticker"}]

    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--loop",
            "--loop-max-runs",
            "2",
            "--interval-seconds",
            "0",
            "--replay-root",
            str(tmp_path / "replay-loop"),
        ]
    ) == 0

    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert calls == [3, 3]
    assert [row["loop_run_index"] for row in outputs] == [1, 2]
    assert all(row["loop"] is True for row in outputs)
    assert all(row["places_real_order"] is False for row in outputs)


def test_verify_redis_freshness_cli_reads_new_feature_key(monkeypatch, tmp_path, capsys) -> None:
    feature_key = recorder._features_key("binance", "BTCUSDT")
    fake_redis = FakeRedis(
        {
            feature_key: json.dumps(
                {
                    "available_at": recorder.utc_now_iso(),
                    "received_at": recorder.utc_now_iso(),
                    "generated_at": recorder.utc_now_iso(),
                    "update_type": "book_ticker",
                    "sequence_gap": False,
                    "source_latency_ms": 5.0,
                }
            )
        }
    )

    async def fake_binance_ws(**kwargs):
        return [{"exchange": "binance", "symbol": "BTCUSDT", "update_type": "book_ticker"}]

    monkeypatch.setattr(recorder, "_redis_client", lambda enabled: fake_redis if enabled else None)
    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)

    assert recorder.main(
        [
            "--symbols",
            "BTCUSDT",
            "--exchange",
            "binance",
            "--max-messages",
            "3",
            "--write-redis",
            "--verify-redis-freshness",
            "--replay-root",
            str(tmp_path / "replay-freshness"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert fake_redis.read_keys == [feature_key]
    assert output["redis_freshness_check"]["enabled"] is True
    assert output["redis_freshness_check"]["feature_keys_read"] == [feature_key]
    assert output["redis_freshness_check"]["fresh_symbol_count"] == 1
    assert output["redis_freshness_check"]["old_redis_reads"] is False
    assert output["redis_freshness_check"]["old_redis_writes"] is False


def test_provider_support_filters_symbols_per_exchange() -> None:
    support = {
        "binance": {
            "BICOUSDT": {"orderbook_supported": True},
            "IPUSDT": {"orderbook_supported": False},
            "SUNUSDT": {"orderbook_supported": True},
        },
        "kucoin": {
            "BICOUSDT": {"orderbook_supported": False},
            "IPUSDT": {"orderbook_supported": False},
            "SUNUSDT": {"orderbook_supported": True},
        },
    }
    symbols = ["BICOUSDT", "IPUSDT", "SUNUSDT"]

    assert recorder.supported_symbols_for_exchange(symbols, support, "binance") == [
        "BICOUSDT",
        "SUNUSDT",
    ]
    assert recorder.supported_symbols_for_exchange(symbols, support, "kucoin") == ["SUNUSDT"]
    assert recorder.active_direct_orderbook_symbols(symbols, support) == [
        "BICOUSDT",
        "SUNUSDT",
    ]


def test_exchange_both_filters_unsupported_symbols_when_status_enabled(monkeypatch, tmp_path, capsys) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_support(symbols):
        assert symbols == ["BICOUSDT", "IPUSDT", "SUNUSDT"]
        return {
            "binance": {
                "BICOUSDT": {"orderbook_supported": True},
                "IPUSDT": {"orderbook_supported": False},
                "SUNUSDT": {"orderbook_supported": True},
            },
            "kucoin": {
                "BICOUSDT": {"orderbook_supported": False},
                "IPUSDT": {"orderbook_supported": False},
                "SUNUSDT": {"orderbook_supported": True},
            },
        }

    async def fake_binance_ws(**kwargs):
        calls.append(("binance", list(kwargs["symbols"])))
        return [{"exchange": "binance", "symbol": symbol} for symbol in kwargs["symbols"]]

    async def fake_kucoin_ws(**kwargs):
        calls.append(("kucoin", list(kwargs["symbols"])))
        return [{"exchange": "kucoin", "symbol": symbol} for symbol in kwargs["symbols"]]

    monkeypatch.setattr(recorder, "fetch_provider_symbol_support", fake_support)
    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)
    monkeypatch.setattr(recorder, "_run_kucoin_ws", fake_kucoin_ws)
    monkeypatch.setattr(recorder, "write_goal_statuses", lambda **kwargs: {})

    assert recorder.main(
        [
            "--symbols",
            "BICOUSDT,IPUSDT,SUNUSDT",
            "--exchange",
            "both",
            "--max-messages",
            "10",
            "--write-status",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert calls == [("binance", ["BICOUSDT", "SUNUSDT"]), ("kucoin", ["SUNUSDT"])]
    assert output["requested_symbols"] == ["BICOUSDT", "IPUSDT", "SUNUSDT"]
    assert output["symbols"] == ["BICOUSDT", "SUNUSDT"]
    assert output["provider_filtered_symbols"] == ["IPUSDT"]
    assert output["exchange_symbols"] == {
        "binance": ["BICOUSDT", "SUNUSDT"],
        "kucoin": ["SUNUSDT"],
    }


def test_fetch_binance_snapshot_rejects_empty_book(monkeypatch) -> None:
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"lastUpdateId":1,"bids":[],"asks":[]}'

    monkeypatch.setattr(recorder.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="binance_snapshot_empty_book"):
        recorder.fetch_binance_snapshot("IPUSDT")


def test_fetch_binance_snapshot_blocks_rest_when_fallback_disabled(monkeypatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(
        recorder.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("REST fallback should be blocked before urlopen"),
    )

    with pytest.raises(RuntimeError, match="BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"):
        recorder.fetch_binance_snapshot("IPUSDT")


def test_fetch_binance_snapshot_uses_websocket_cache_before_rest(monkeypatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(
        recorder.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("REST fallback should not run when cache has book data"),
    )
    redis = FakeRedis(
        {
            recorder._depth_key("binance", "IPUSDT"): json.dumps(
                {
                    "bids": [["1.00", "10"]],
                    "asks": [["1.01", "11"]],
                    "sequence_id": 123,
                    "source": "binance_public_websocket_orderbook_cache_primary",
                }
            )
        }
    )

    snapshot = recorder.fetch_binance_snapshot("IPUSDT", redis_client=redis)

    assert snapshot["type"] == "websocket_cache_snapshot"
    assert snapshot["sequence_id"] == 123
    assert snapshot["bids"] == [["1.00", "10"]]
    assert redis.read_keys == [recorder._depth_key("binance", "IPUSDT")]


def test_fetch_provider_symbol_support_uses_binance_cache_before_exchangeinfo(monkeypatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(
        recorder.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "cached Binance-only metadata must not issue any external HTTP request"
        ),
    )
    redis = FakeRedis(
        {
            "v2:exchange:symbol_filters:IPUSDT": json.dumps(
                {
                    "symbol": "IPUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "baseAsset": "IP",
                    "quoteAsset": "USDT",
                }
            )
        }
    )

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        include_kucoin=False,
    )

    assert support["binance_cache_primary_count"] == 1
    assert support["binance"]["IPUSDT"]["orderbook_supported"] is True
    assert support["binance"]["IPUSDT"]["transport"] == "websocket_cache_primary"


def test_fetch_provider_symbol_support_can_seed_filter_cache_from_rest_fallback(monkeypatch) -> None:
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body

    requested_urls: list[str] = []

    def fake_urlopen(request, *args, **kwargs):
        url = getattr(request, "full_url", str(request))
        requested_urls.append(url)
        if "fapi.binance.com" in url:
            return FakeResponse(
                json.dumps(
                    {
                        "symbols": [
                            _binance_usdm_symbol_filter_row("IPUSDT")
                        ]
                    }
                ).encode()
            )
        pytest.fail(f"Binance-only symbol-filter seed issued unrelated HTTP: {url}")

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)
    redis = FakeRedis({})

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    seed = support["symbol_filter_cache_seed"]
    assert seed["attempted"] is True
    assert set(seed["written_keys"]) == {
        "v2:exchange:binance:exchangeInfo",
        "v2:exchange:symbol_filters",
        "v2:exchange:symbol_filters:IPUSDT",
    }
    assert seed["write_errors"] == []
    assert "v2:exchange:symbol_filters:IPUSDT" in redis.store
    assert support["binance"]["IPUSDT"]["transport"] == "rest_fallback"
    assert requested_urls == [f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"]
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is not None


def test_symbol_filter_seed_materializes_later_shard_exact_key(monkeypatch) -> None:
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )
    rows = [
        _binance_usdm_symbol_filter_row("AAAUSDT"),
        _binance_usdm_symbol_filter_row("BBBUSDT"),
    ]
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"symbols": rows}).encode()

    def fake_urlopen(request, *_args, **_kwargs):
        requested_urls.append(getattr(request, "full_url", str(request)))
        return FakeResponse()

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)
    redis = FakeRedis({})

    first = recorder.fetch_provider_symbol_support(
        ["AAAUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )
    second = recorder.fetch_provider_symbol_support(
        ["BBBUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )
    cached = recorder.fetch_provider_symbol_support(
        ["BBBUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    assert first["symbol_filter_cache_seed"]["missing_symbols"] == ["AAAUSDT"]
    assert second["binance_cache_primary_count"] == 1
    assert second["symbol_filter_cache_seed"]["missing_symbols"] == ["BBBUSDT"]
    assert f"v2:exchange:symbol_filters:BBBUSDT" in redis.store
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "BBBUSDT",
    ) is not None
    assert cached["symbol_filter_cache_seed"]["missing_symbols"] == []
    assert cached["symbol_filter_cache_seed"]["attempted"] is False
    assert requested_urls == [
        f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
        f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
    ]


def test_symbol_filter_seed_refreshes_valid_still_present_key_when_due(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )
    cached_row = _binance_usdm_symbol_filter_row("IPUSDT")
    refreshed_row = json.loads(json.dumps(cached_row))
    next(
        row
        for row in refreshed_row["filters"]
        if row.get("filterType") == "MIN_NOTIONAL"
    )["notional"] = "7"
    redis = FakeRedis({})
    fetched_at = (
        datetime.now(timezone.utc)
        - timedelta(
            seconds=recorder.SYMBOL_FILTER_CACHE_REFRESH_SECONDS + 1
        )
    ).isoformat()
    assert recorder._safe_symbol_filter_cache_set(
        redis,
        "v2:exchange:symbol_filters:IPUSDT",
        cached_row,
        fetched_at=fetched_at,
    ) is True
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"symbols": [refreshed_row]}).encode()

    def fake_urlopen(request, *_args, **_kwargs):
        requested_urls.append(getattr(request, "full_url", str(request)))
        return FakeResponse()

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    seed = support["symbol_filter_cache_seed"]
    assert seed["missing_symbols"] == []
    assert seed["refresh_due_symbols"] == ["IPUSDT"]
    assert seed["refresh_target_symbols"] == ["IPUSDT"]
    assert seed["attempted"] is True
    assert "v2:exchange:symbol_filters:IPUSDT" in seed["written_keys"]
    assert requested_urls == [f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"]
    refreshed = recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    )
    assert refreshed is not None
    assert next(
        row
        for row in refreshed["filters"]
        if row.get("filterType") == "MIN_NOTIONAL"
    )["notional"] == "7"


def test_symbol_filter_seed_does_not_fetch_when_exact_key_is_fresh(
    monkeypatch,
) -> None:
    redis = FakeRedis({})
    assert recorder._safe_symbol_filter_cache_set(
        redis,
        "v2:exchange:symbol_filters:IPUSDT",
        _binance_usdm_symbol_filter_row("IPUSDT"),
    ) is True
    monkeypatch.setattr(
        recorder.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "fresh exact filter evidence must not issue an HTTP request"
        ),
    )

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    seed = support["symbol_filter_cache_seed"]
    assert seed["canonical_exact_fresh_symbols"] == ["IPUSDT"]
    assert seed["refresh_due_symbols"] == []
    assert seed["refresh_target_symbols"] == []
    assert seed["attempted"] is False


@pytest.mark.parametrize(
    "cache_key",
    (
        "v2:exchange:symbol_filters",
        "v2:symbol_filters:IPUSDT",
        "v2:exchange:symbol_filters:IPUSDT",
    ),
)
def test_symbol_filter_seed_does_not_accept_shared_legacy_or_unstamped_coverage(
    monkeypatch,
    cache_key,
) -> None:
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )
    row = _binance_usdm_symbol_filter_row("IPUSDT")
    cached_payload = {"symbols": [row]} if cache_key.endswith("symbol_filters") else row
    redis = FakeRedis({cache_key: json.dumps(cached_payload)})
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"symbols": [row]}).encode()

    def fake_urlopen(request, *_args, **_kwargs):
        requested_urls.append(getattr(request, "full_url", str(request)))
        return FakeResponse()

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    assert support["binance_cache_primary_count"] == 1
    assert support["binance_canonical_exact_cache_count"] == 0
    assert support["symbol_filter_cache_seed"]["missing_symbols"] == ["IPUSDT"]
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is not None
    assert requested_urls == [f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"]


@pytest.mark.parametrize("invalid_notional_contract", ("dual", "notional_only"))
def test_symbol_filter_seed_replaces_non_usdm_notional_filter_contract(
    monkeypatch,
    invalid_notional_contract,
) -> None:
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )
    valid_row = _binance_usdm_symbol_filter_row("IPUSDT")
    invalid_row = json.loads(json.dumps(valid_row))
    if invalid_notional_contract == "dual":
        invalid_row["filters"].append(
            {
                "filterType": "NOTIONAL",
                "minNotional": "5",
                "applyMinToMarket": True,
            }
        )
    else:
        invalid_row["filters"] = [
            {
                **row,
                "filterType": (
                    "NOTIONAL"
                    if row.get("filterType") == "MIN_NOTIONAL"
                    else row.get("filterType")
                ),
            }
            for row in invalid_row["filters"]
        ]
    redis = FakeRedis({})
    assert recorder._safe_symbol_filter_cache_set(
        redis,
        "v2:exchange:symbol_filters:IPUSDT",
        invalid_row,
    ) is True
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is None
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"symbols": [valid_row]}).encode()

    def fake_urlopen(request, *_args, **_kwargs):
        requested_urls.append(getattr(request, "full_url", str(request)))
        return FakeResponse()

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    assert support["symbol_filter_cache_seed"]["missing_symbols"] == ["IPUSDT"]
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is not None
    assert requested_urls == [f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"]


@pytest.mark.parametrize(
    "malformation",
    (
        "zero",
        "nan",
        "garbage",
        "alias_conflict",
    ),
)
def test_symbol_filter_seed_repairs_malformed_numeric_exact_cache(
    monkeypatch,
    malformation,
) -> None:
    monkeypatch.setattr(
        recorder,
        "require_binance_rest_fallback",
        lambda **_kwargs: {"request_allowed": True},
    )
    valid_row = _binance_usdm_symbol_filter_row("IPUSDT")
    invalid_row = json.loads(json.dumps(valid_row))
    market_filter = next(
        row
        for row in invalid_row["filters"]
        if row.get("filterType") == "MARKET_LOT_SIZE"
    )
    min_notional_filter = next(
        row
        for row in invalid_row["filters"]
        if row.get("filterType") == "MIN_NOTIONAL"
    )
    if malformation == "zero":
        market_filter["maxQty"] = "0"
    elif malformation == "nan":
        market_filter["stepSize"] = "NaN"
    elif malformation == "garbage":
        min_notional_filter["notional"] = "not-a-number"
    else:
        invalid_row["min_qty"] = "2"

    redis = FakeRedis({})
    assert recorder._safe_symbol_filter_cache_set(
        redis,
        "v2:exchange:symbol_filters:IPUSDT",
        invalid_row,
    ) is True
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is None
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"symbols": [valid_row]}).encode()

    def fake_urlopen(request, *_args, **_kwargs):
        requested_urls.append(getattr(request, "full_url", str(request)))
        return FakeResponse()

    monkeypatch.setattr(recorder.urllib.request, "urlopen", fake_urlopen)

    support = recorder.fetch_provider_symbol_support(
        ["IPUSDT"],
        redis_client=redis,
        seed_cache_from_rest_fallback=True,
        include_kucoin=False,
    )

    assert support["symbol_filter_cache_seed"]["missing_symbols"] == ["IPUSDT"]
    assert recorder._validated_canonical_symbol_filter_cache_payload(
        redis,
        "IPUSDT",
    ) is not None
    assert requested_urls == [f"{recorder.BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"]


def test_fetch_kucoin_snapshot_rejects_error_payload(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"code":"200003","msg":"contract not exist"}'

    monkeypatch.setattr(recorder.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="kucoin_snapshot_error"):
        recorder.fetch_kucoin_snapshot("BICOUSDT")


def test_shard_symbols_partitions_full_universe_deterministically() -> None:
    universe = [f"SYM{i:03d}USDT" for i in range(148)] + ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    shards = [
        recorder.shard_symbols(universe, shard_index=index, shard_count=4)
        for index in range(4)
    ]

    combined = sorted(symbol for shard in shards for symbol in shard)
    assert combined == sorted(set(universe))
    for shard in shards:
        assert len(shard) in {37, 38}
    # Majors always land in exactly one covered shard.
    for major in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sum(major in shard for shard in shards) == 1
    # Deterministic across calls (stable assignment between processes).
    assert shards[1] == recorder.shard_symbols(list(reversed(universe)), shard_index=1, shard_count=4)


def test_shard_symbols_disabled_returns_input() -> None:
    symbols = ["ETHUSDT", "BTCUSDT"]
    assert recorder.shard_symbols(symbols, shard_index=0, shard_count=0) == symbols
    assert recorder.shard_symbols(symbols, shard_index=0, shard_count=1) == symbols


def test_parse_args_rejects_out_of_range_shard_index() -> None:
    with pytest.raises(SystemExit):
        recorder.parse_args(["--shard-index", "4", "--shard-count", "4"])
    args = recorder.parse_args(["--shard-index", "3", "--shard-count", "4"])
    assert args.shard_index == 3
    assert args.shard_count == 4
    assert args.replay_capture is True


def test_parse_args_requires_redis_write_for_symbol_filter_seed() -> None:
    with pytest.raises(SystemExit):
        recorder.parse_args(["--seed-symbol-filter-cache-from-rest-fallback"])

    args = recorder.parse_args(
        [
            "--write-redis",
            "--seed-symbol-filter-cache-from-rest-fallback",
        ]
    )

    assert args.write_redis is True
    assert args.seed_symbol_filter_cache_from_rest_fallback is True


def test_run_once_seeds_metadata_without_status_mode_using_write_client(
    monkeypatch,
    tmp_path,
) -> None:
    redis = FakeRedis({})
    captured: dict[str, object] = {}

    def fake_support(
        symbols,
        *,
        redis_client=None,
        seed_cache_from_rest_fallback=False,
        include_kucoin=True,
    ):
        captured["symbols"] = list(symbols)
        captured["redis_client"] = redis_client
        captured["seed"] = seed_cache_from_rest_fallback
        captured["include_kucoin"] = include_kucoin
        return {
            "binance": {"IPUSDT": {"orderbook_supported": True}},
            "kucoin": {},
        }

    async def fake_binance_ws(**_kwargs):
        return []

    monkeypatch.setattr(recorder, "_resolved_symbols", lambda _args: ["IPUSDT"])
    monkeypatch.setattr(recorder, "_redis_client", lambda _enabled: redis)
    monkeypatch.setattr(recorder, "fetch_provider_symbol_support", fake_support)
    monkeypatch.setattr(recorder, "_run_binance_ws", fake_binance_ws)
    args = recorder.parse_args(
        [
            "--write-redis",
            "--seed-symbol-filter-cache-from-rest-fallback",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    )

    result = recorder._run_once(args)

    assert captured == {
        "symbols": ["IPUSDT"],
        "redis_client": redis,
        "seed": True,
        "include_kucoin": False,
    }
    assert result["provider_symbol_support"]["binance"]["IPUSDT"][
        "orderbook_supported"
    ] is True


def test_resolved_symbols_shards_resolver_universe(monkeypatch) -> None:
    universe = [f"AA{i:02d}USDT" for i in range(10)]
    monkeypatch.setattr(recorder, "resolve_symbols", lambda **_kwargs: list(universe))
    args = recorder.parse_args(["--shard-index", "1", "--shard-count", "3"])

    resolved = recorder._resolved_symbols(args)

    assert resolved == sorted(universe)[1::3]


def test_no_replay_capture_writes_redis_only(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    books: dict[tuple[str, str], LocalOrderBook] = {}
    fake_redis = FakeRedis({})
    raw = {
        "stream": "btcusdt@depth20@250ms",
        "data": {
            "e": "depthUpdate",
            "E": 1780000000000,
            "T": 1780000000001,
            "s": "BTCUSDT",
            "U": 10,
            "u": 11,
            "pu": 9,
            "b": [["100", "2"]],
            "a": [["101", "3"]],
        },
    }

    result = recorder.process_raw_message(
        json.dumps(raw),
        parser_name="binance",
        books=books,
        replay_store=store,
        redis_client=fake_redis,
        persist_replay=False,
    )

    assert result is not None
    assert result["replay_writes"] == []
    assert not list((tmp_path / "orderbook_replay").rglob("*.jsonl"))
    written_keys = {key for key, _ttl in fake_redis.write_calls}
    assert f"{recorder.NEW_REDIS_PREFIX}features:binance:BTCUSDT" in written_keys
    assert f"{recorder.NEW_REDIS_PREFIX}depth:binance:BTCUSDT" in written_keys


def test_parse_args_partial_depth_levels_validation() -> None:
    args = recorder.parse_args(["--binance-partial-depth-levels", "20"])
    assert args.binance_partial_depth_levels == (20,)
    args = recorder.parse_args([])
    assert args.binance_partial_depth_levels == (5, 10, 20)
    with pytest.raises(SystemExit):
        recorder.parse_args(["--binance-partial-depth-levels", "7"])
    with pytest.raises(SystemExit):
        recorder.parse_args(["--binance-partial-depth-levels", ""])
