from __future__ import annotations

import hashlib
import json
from typing import Any, NoReturn, cast

import pytest

from v2.backend.app.cli import v2_universe_coverage_sync as coverage
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    closed_candle_key,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    MAX_SOURCE_PAYLOAD_BYTES,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    CANDLE_ID_CHAIN_VERSION,
    CORE_TA_MINIMUM_SOURCE_ROWS,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"
DURATION_MS = TIMEFRAME_DURATION_MS[TIMEFRAME]
OBSERVED_AT_MS = 1_800_000_000_000
SOURCE_KEY = closed_candle_key("binance", SYMBOL, TIMEFRAME)
HOSTILE_DETAIL = "DO_NOT_LEAK_TRANSPORT_SECRET"


class _FakePipeline:
    def __init__(
        self,
        values: dict[str, bytes],
        *,
        fail_execute: bool = False,
    ) -> None:
        self._values = values
        self._fail_execute = fail_execute
        self.commands: list[tuple[object, ...]] = []
        self.reset_calls = 0
        self.close_calls = 0

    def type(self, key: str) -> _FakePipeline:
        self.commands.append(("TYPE", key))
        return self

    def getrange(self, key: str, start: int, end: int) -> _FakePipeline:
        self.commands.append(("GETRANGE", key, start, end))
        return self

    def pttl(self, key: str) -> _FakePipeline:
        self.commands.append(("PTTL", key))
        return self

    def time(self) -> _FakePipeline:
        self.commands.append(("TIME",))
        return self

    def execute(self) -> list[object]:
        if self._fail_execute:
            raise RuntimeError(HOSTILE_DETAIL)
        responses: list[object] = []
        for command in self.commands:
            name = command[0]
            if name == "TYPE":
                key = cast(str, command[1])
                responses.append(b"string" if key in self._values else b"none")
            elif name == "GETRANGE":
                key = cast(str, command[1])
                start = cast(int, command[2])
                end = cast(int, command[3])
                responses.append(self._values.get(key, b"")[start : end + 1])
            elif name == "PTTL":
                key = cast(str, command[1])
                responses.append(-1 if key in self._values else -2)
            elif name == "TIME":
                responses.append((1_800_000_000, 0))
            else:  # pragma: no cover - impossible unless the production API changes
                raise AssertionError(name)
        return responses

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _RawRedis:
    def __init__(
        self,
        values: dict[str, bytes] | None = None,
        *,
        fail_execute: bool = False,
    ) -> None:
        self.values = {} if values is None else values
        self.fail_execute = fail_execute
        self.pipelines: list[_FakePipeline] = []
        self.full_get_calls = 0

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        pipeline = _FakePipeline(self.values, fail_execute=self.fail_execute)
        self.pipelines.append(pipeline)
        return pipeline

    def get(self, _key: str) -> bytes | None:
        self.full_get_calls += 1
        raise AssertionError("OHLCV census must never issue an unbounded GET")


class _DecodedRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = {} if values is None else values
        self.get_calls: list[str] = []

    def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.values.get(key)


def _rest_source_row(open_time: int, timeframe: str = TIMEFRAME) -> list[object]:
    close_time = open_time + TIMEFRAME_DURATION_MS[timeframe] - 1
    return [
        open_time,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "12.0",
        close_time,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_row(open_time: int, timeframe: str = TIMEFRAME) -> dict[str, Any]:
    close_time = open_time + TIMEFRAME_DURATION_MS[timeframe] - 1
    return cast(
        dict[str, Any],
        canonical_from_binance_rest(
            _rest_source_row(open_time, timeframe),
            symbol=SYMBOL,
            timeframe=timeframe,
            ingested_at=close_time + 1,
        ).to_dict(),
    )


def _canonical_rows(
    count: int,
    *,
    timeframe: str = TIMEFRAME,
    observed_at_ms: int = OBSERVED_AT_MS,
    tail_missing_intervals: int = 0,
) -> list[dict[str, Any]]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    expected_close = (observed_at_ms // duration) * duration - 1
    latest_close = expected_close - (tail_missing_intervals * duration)
    latest_open = latest_close - duration + 1
    first_open = latest_open - ((count - 1) * duration)
    return [_canonical_row(first_open + (index * duration), timeframe) for index in range(count)]


def _payload(rows: list[object]) -> bytes:
    return json.dumps(
        rows,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _entry(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    observed_at_ms: int = OBSERVED_AT_MS,
    timeframe: str = TIMEFRAME,
) -> tuple[dict[str, Any], _RawRedis]:
    monkeypatch.setattr(coverage, "_consumer_observed_at_ms", lambda: observed_at_ms)
    source_key = closed_candle_key("binance", SYMBOL, timeframe)
    client = _RawRedis({source_key: payload})
    result = coverage._check_ohlcv_closed(client, SYMBOL)
    return result["tfs"][timeframe], client


def _all_mapping_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        return keys + [key for item in value.values() for key in _all_mapping_keys(item)]
    if isinstance(value, list | tuple):
        return [key for item in value for key in _all_mapping_keys(item)]
    return []


def test_redis_factories_keep_decoded_and_exact_binary_clients_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def _from_url(url: str, *, decode_responses: bool) -> object:
        calls.append((url, decode_responses))
        return object()

    monkeypatch.setenv("REDIS_URL", "redis://coverage-test:6379/9")
    monkeypatch.setattr(coverage.redis.Redis, "from_url", _from_url)

    coverage._redis_client()
    coverage._ohlcv_binary_redis_client()

    assert calls == [
        ("redis://coverage-test:6379/9", True),
        ("redis://coverage-test:6379/9", False),
    ]


def test_consumer_clock_is_captured_immediately_after_each_transport_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    observed_at_ms = OBSERVED_AT_MS + 12_345
    original_read = coverage.read_atomic_redis_sources

    def _read(*args: object, **kwargs: object) -> object:
        result = original_read(*args, **kwargs)
        events.append("transport_returned")
        return result

    def _clock() -> int:
        events.append("consumer_observed")
        return observed_at_ms

    monkeypatch.setattr(coverage, "read_atomic_redis_sources", _read)
    monkeypatch.setattr(coverage, "_consumer_observed_at_ms", _clock)
    client = _RawRedis({SOURCE_KEY: _payload(cast(list[object], _canonical_rows(71)))})

    result = coverage._check_ohlcv_closed(client, SYMBOL)

    assert events == ["transport_returned", "consumer_observed"] * len(
        coverage.REQUIRED_DECISION_TIMEFRAMES
    )
    assert result["tfs"][TIMEFRAME]["consumer_observed_at_ms"] == observed_at_ms
    assert result["tfs"][TIMEFRAME]["expected_latest_finalized_close_time"] == (OBSERVED_AT_MS - 1)


@pytest.mark.parametrize("timeframe", coverage.REQUIRED_DECISION_TIMEFRAMES)
def test_expected_latest_finalized_close_formula_covers_every_timeframe(
    monkeypatch: pytest.MonkeyPatch,
    timeframe: str,
) -> None:
    observed_at_ms = OBSERVED_AT_MS + 12_345
    rows = _canonical_rows(
        CORE_TA_MINIMUM_SOURCE_ROWS,
        timeframe=timeframe,
        observed_at_ms=observed_at_ms,
    )
    entry, _client = _entry(
        monkeypatch,
        _payload(cast(list[object], rows)),
        observed_at_ms=observed_at_ms,
        timeframe=timeframe,
    )
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]

    assert entry["coverage_status"] == "ok"
    assert (
        entry["expected_latest_finalized_close_time"]
        == ((observed_at_ms // duration_ms) * duration_ms) - 1
    )
    assert entry["latest_candle_matches_expected_cutoff"] is True


def test_cap_plus_one_is_oversized_without_materializing_a_full_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, client = _entry(monkeypatch, b"x" * (MAX_SOURCE_PAYLOAD_BYTES + 1))

    assert entry["coverage_status"] == "oversized"
    assert entry["max_exact_payload_bytes"] == MAX_SOURCE_PAYLOAD_BYTES
    assert entry["payload_byte_count_lower_bound"] == MAX_SOURCE_PAYLOAD_BYTES + 1
    assert client.full_get_calls == 0
    assert all(
        ("GETRANGE", pipeline.commands[0][1], 0, MAX_SOURCE_PAYLOAD_BYTES) in pipeline.commands
        for pipeline in client.pipelines
    )


def test_legacy_binance_list_rows_fail_the_exact_canonical_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = [[OBSERVED_AT_MS - DURATION_MS, "1", "2", "0.5", "1.5", "10", OBSERVED_AT_MS - 1]]
    entry, client = _entry(monkeypatch, _payload(legacy))

    assert entry["coverage_status"] == "schema_invalid"
    assert entry["validation_stage"] == "exact_source_schema"
    assert entry["schema_error_code"] == "ohlcv_closed_row_requires_exact_dict"
    assert entry["source_schema_validated"] is False
    assert client.full_get_calls == 0


@pytest.mark.parametrize(
    ("row_count", "expected_status", "ready"),
    [
        (CORE_TA_MINIMUM_SOURCE_ROWS - 1, "contiguous_suffix_short", False),
        (CORE_TA_MINIMUM_SOURCE_ROWS, "ok", True),
        (CORE_TA_MINIMUM_SOURCE_ROWS + 1, "ok", True),
        (100, "ok", True),
    ],
)
def test_71_is_a_core_ta_minimum_floor_not_an_exact_dependency_length(
    monkeypatch: pytest.MonkeyPatch,
    row_count: int,
    expected_status: str,
    ready: bool,
) -> None:
    rows = _canonical_rows(row_count)
    raw = _payload(cast(list[object], rows))
    entry, _client = _entry(monkeypatch, raw)
    chain_material = json.dumps(
        {
            "candle_ids": [row["candle_id"] for row in rows],
            "schema_version": CANDLE_ID_CHAIN_VERSION,
            "selected_count": row_count,
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    expected_chain_sha256 = hashlib.sha256(chain_material.encode("ascii")).hexdigest()

    assert entry["coverage_status"] == expected_status
    assert entry["row_count"] == row_count
    assert entry["contiguous_suffix_count"] == row_count
    assert entry["core_ta_minimum_source_rows"] == 71
    assert entry["core_ta_minimum_coverage_ready"] is ready
    assert entry["market_selection_threshold"] is False
    assert "NOT_EXACT_DEPENDENCY_LENGTH" in entry["coverage_semantics"]
    assert entry["full_contiguous_suffix_candle_id_chain_sha256"] == (expected_chain_sha256)


def test_internal_gap_reports_full_latest_suffix_and_can_still_meet_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _canonical_rows(CORE_TA_MINIMUM_SOURCE_ROWS + 2)
    del rows[1]
    entry, _client = _entry(monkeypatch, _payload(cast(list[object], rows)))

    assert entry["coverage_status"] == "ok"
    assert entry["row_count"] == CORE_TA_MINIMUM_SOURCE_ROWS + 1
    assert entry["gap_count"] == 1
    assert entry["gap_indices"] == [1]
    assert entry["gap_missing_interval_counts"] == [1]
    assert entry["missing_interval_count"] == 1
    assert entry["contiguous_suffix_start_index"] == 1
    assert entry["contiguous_suffix_count"] == CORE_TA_MINIMUM_SOURCE_ROWS
    assert entry["tail_missing_interval_count"] == 0


def test_gap_details_are_bounded_while_hash_and_counts_cover_every_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _canonical_rows((coverage.MAX_REPORTED_OHLCV_GAPS * 2) + 3)[::2]
    entry, _client = _entry(monkeypatch, _payload(cast(list[object], rows)))
    all_gap_pairs = [(index, 1) for index in range(1, entry["gap_count"] + 1)]
    all_gap_material = json.dumps(
        all_gap_pairs,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    expected_digest = hashlib.sha256(all_gap_material.encode("ascii")).hexdigest()
    mutated_pairs = [*all_gap_pairs[:-1], (all_gap_pairs[-1][0], 2)]
    mutated_material = json.dumps(
        mutated_pairs,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )

    assert entry["gap_count"] > coverage.MAX_REPORTED_OHLCV_GAPS
    assert entry["reported_gap_count"] == coverage.MAX_REPORTED_OHLCV_GAPS
    assert len(entry["gap_indices"]) == coverage.MAX_REPORTED_OHLCV_GAPS
    assert entry["gaps_truncated"] is True
    assert entry["all_gaps_sha256"] == expected_digest
    assert entry["all_gaps_sha256"] != hashlib.sha256(mutated_material.encode("ascii")).hexdigest()


def test_tail_gap_is_reported_in_exact_timeframe_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _canonical_rows(
        CORE_TA_MINIMUM_SOURCE_ROWS,
        tail_missing_intervals=3,
    )
    entry, _client = _entry(monkeypatch, _payload(cast(list[object], rows)))

    assert entry["coverage_status"] == "tail_stale"
    assert entry["contiguous_suffix_count"] == CORE_TA_MINIMUM_SOURCE_ROWS
    assert entry["tail_missing_interval_count"] == 3
    assert entry["latest_candle_matches_expected_cutoff"] is False
    assert entry["core_ta_minimum_coverage_ready"] is False


def test_close_equal_to_consumer_observation_is_not_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _canonical_rows(CORE_TA_MINIMUM_SOURCE_ROWS)
    close_equal_observation = OBSERVED_AT_MS - 1
    entry, _client = _entry(
        monkeypatch,
        _payload(cast(list[object], rows)),
        observed_at_ms=close_equal_observation,
    )

    assert entry["coverage_status"] == "schema_invalid"
    assert entry["source_schema_validated"] is True
    assert entry["producer_finality_contract_validated"] is True
    assert entry["end_exclusive_consumer_finality_validated"] is False
    assert entry["validation_stage"] == "consumer_finality_and_continuity"
    assert entry["consumer_contract_error_code"] == (
        "feature_window_candle_not_final_at_consumer_observation"
    )
    assert entry["expected_latest_finalized_close_time"] == (OBSERVED_AT_MS - DURATION_MS - 1)


def test_hostile_transport_failure_is_fixed_and_does_not_leak_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        coverage,
        "_consumer_observed_at_ms",
        lambda: pytest.fail("observation clock must follow successful transport"),
    )
    client = _RawRedis(fail_execute=True)

    result = coverage._check_ohlcv_closed(client, SYMBOL)
    entry = result["tfs"][TIMEFRAME]

    assert entry["coverage_status"] == "transport_invalid"
    assert entry["transport_error_code"] == "atomic_redis_source_read_transport_failed"
    assert HOSTILE_DETAIL not in json.dumps(entry, sort_keys=True)
    assert client.full_get_calls == 0


def test_build_census_preserves_non_ohlcv_reads_and_emits_no_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coverage, "_consumer_observed_at_ms", lambda: OBSERVED_AT_MS)
    decoded = _DecodedRedis()
    raw = _RawRedis({SOURCE_KEY: _payload(cast(list[object], _canonical_rows(71)))})

    census = coverage.build_census(
        cast(Any, decoded),
        [SYMBOL],
        {"source_path": "unit_test", "symbol_profile": "unit_test"},
        ohlcv_r=raw,
    )

    assert census["schema_version"] == "v2_universe_coverage_census_v2"
    assert census["core_ta_minimum_source_rows"] == 71
    assert census["ohlcv_market_selection_threshold"] is False
    assert "min_candles_threshold" not in census
    assert "ohlcv_grace_s" not in census["thresholds"]
    assert f"v2:market:prices:{SYMBOL}" in decoded.get_calls
    assert f"v2:features:latest:{SYMBOL}:1m" in decoded.get_calls
    families = census["symbols"][SYMBOL]["families"]
    assert families["prices"]["status"] == "missing"
    assert families["orderbook"]["status"] == "missing"
    assert families["open_interest"]["status"] == "missing"
    assert families["ta_full"]["status"] == "missing"
    assert families["feature_snapshot"]["status"] == "missing"
    assert census["live_gate"] == "blocked_human_only"
    assert census["places_real_order"] is False
    assert not any("grant" in key.lower() for key in _all_mapping_keys(census))


def _heal_census(*timeframes: str) -> dict[str, Any]:
    return {
        "symbols": {
            SYMBOL: {
                "families": {
                    "ohlcv_closed": {
                        "tfs": {
                            timeframe: {"ok": False, "coverage_status": "missing"}
                            for timeframe in timeframes
                        }
                    }
                }
            }
        }
    }


def test_healing_routes_binary_client_and_reports_write_and_readiness_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RawRedis()
    calls: list[tuple[object, str, str, bool]] = []

    def _backfill(
        passed_client: object,
        symbol: str,
        timeframe: str,
        *,
        replace_invalid_existing: bool,
    ) -> dict[str, Any]:
        calls.append((passed_client, symbol, timeframe, replace_invalid_existing))
        return {
            "write_committed": True,
            "cache_ready_after": False,
            "recovery_status": "write_committed_cache_still_nonready",
            "rows_submitted": 10,
            "total_in_key": 10,
            "transport": "rest_fallback",
            "invalid_existing_replaced": True,
        }

    monkeypatch.setattr(coverage, "_backfill_symbol_tf", _backfill)
    monkeypatch.setattr(coverage.time, "sleep", lambda _seconds: None)

    result = coverage.heal_ohlcv_gaps(
        client,
        _heal_census("1m"),
        max_pairs=1,
        replace_invalid_existing=True,
    )

    assert calls == [(client, SYMBOL, "1m", True)]
    assert result["attempted"] == 1
    assert result["writes_committed"] == 1
    assert result["cache_ready_after"] == 0
    assert result["unresolved_after_attempt"] == 1
    assert result["errors"] == 0
    assert result["details"][0]["status"] == ("write_committed_cache_still_nonready")
    assert "ok" not in result


def test_healing_publishes_only_stable_redacted_error_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RawRedis()

    def _raise(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError(HOSTILE_DETAIL)

    monkeypatch.setattr(coverage, "_backfill_symbol_tf", _raise)
    monkeypatch.setattr(coverage.time, "sleep", lambda _seconds: None)

    result = coverage.heal_ohlcv_gaps(
        client,
        _heal_census("1m"),
        max_pairs=1,
    )

    assert result["errors"] == 1
    assert result["details"] == [
        {
            "symbol": SYMBOL,
            "tf": "1m",
            "status": "error",
            "error_code": "kline_backfill_internal_error",
            "write_committed": False,
            "cache_ready_after": False,
        }
    ]
    assert HOSTILE_DETAIL not in json.dumps(result, sort_keys=True)
