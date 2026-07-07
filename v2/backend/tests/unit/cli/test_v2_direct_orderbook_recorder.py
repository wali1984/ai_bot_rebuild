from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_direct_orderbook_recorder as recorder
from v2.backend.app.services.orderbook_recorder.local_book import LocalOrderBook
from v2.backend.app.services.orderbook_recorder.store import LocalReplayStore


class FakeRedis:
    def __init__(self, store: dict[str, object]):
        self.store = store
        self.read_keys: list[str] = []

    def get(self, key: str):
        self.read_keys.append(key)
        return self.store.get(key)


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
