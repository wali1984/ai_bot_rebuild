from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

import pytest
import redis

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    ClosedWindowRedisStoreError,
    ClosedWindowRedisWriteResult,
    atomic_merge_closed_window,
    merge_closed_window_rows,
    serialize_bounded_closed_window,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    validate_ohlcv_closed_window,
)

KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
BASE_MS = 1_800_000_000_000


def _canonical_row(
    index: int,
    *,
    symbol: str = "BTCUSDT",
    close_delta: float = 0.0,
) -> dict[str, Any]:
    open_time = BASE_MS + index * 60_000
    close_time = open_time + 59_999
    close = 101.0 + close_delta
    source = [
        open_time,
        "100.0",
        str(max(102.0, close)),
        "99.0",
        str(close),
        "12.0",
        close_time,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]
    return canonical_from_binance_rest(
        source,
        symbol=symbol,
        timeframe="1m",
        ingested_at=close_time + 200,
    ).to_dict()


def _small_row(index: int, *, padding: int = 0) -> dict[str, Any]:
    open_time = BASE_MS + index * 60_000
    return {
        "candle_id": f"{index:024x}",
        "candle_open_time": open_time,
        "candle_close_time": open_time + 59_999,
        "payload": "x" * padding,
    }


def _payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _stored_text(client: _FakeRedis, key: str = KEY) -> str:
    raw = client.store[key]
    assert type(raw) is str
    return raw


class _FakeRedis:
    def __init__(
        self,
        initial: dict[str, object] | None = None,
        *,
        initial_pttl_ms: int = -1,
        conflicts_remaining: int = 0,
        conflict_row: dict[str, Any] | None = None,
        execute_ack: bool = True,
        decode_responses: bool = False,
    ) -> None:
        self.store = dict(initial or {})
        self.versions = {key: 1 for key in self.store}
        self.pttls = {key: initial_pttl_ms for key in self.store}
        self.conflicts_remaining = conflicts_remaining
        self.conflict_row = conflict_row
        self.execute_ack = execute_ack
        self.decode_responses = decode_responses
        self.pipeline_calls = 0
        self.bounded_read_calls = 0
        self.max_payload_bytes_returned = 0

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        self.pipeline_calls += 1
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client
        self.key: str | None = None
        self.version: int | None = None
        self.pending: tuple[str, str, int | None, bool] | None = None

    def watch(self, key: str) -> None:
        self.key = key
        self.version = self.client.versions.get(key, 0)

    def eval(self, script: str, numkeys: int, key: str, cap: int) -> list[object]:
        assert key == self.key
        assert numkeys == 1
        assert "STRLEN" in script and "GETRANGE" in script
        self.client.bounded_read_calls += 1
        if key not in self.client.store:
            kind = "none" if self.client.decode_responses else b"none"
            return [kind, -2, 0, None]
        raw = self.client.store[key]
        kind_text = "string" if type(raw) in {str, bytes} else "list"
        kind = kind_text if self.client.decode_responses else kind_text.encode("ascii")
        pttl = self.client.pttls.get(key, -1)
        if kind_text != "string":
            return [kind, pttl, 0, None]
        payload = raw if type(raw) is bytes else str(raw).encode("utf-8")
        if len(payload) > cap:
            return [kind, pttl, len(payload), None]
        self.client.max_payload_bytes_returned = max(
            self.client.max_payload_bytes_returned,
            len(payload),
        )
        if self.client.decode_responses:
            return [kind, pttl, len(payload), payload.decode("utf-8")]
        return [kind, pttl, len(payload), payload]

    def multi(self) -> None:
        return None

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        keepttl: bool = False,
    ) -> None:
        self.pending = (key, value, ex, keepttl)

    def execute(self) -> list[bool]:
        assert self.key is not None
        assert self.pending is not None
        if self.client.conflicts_remaining:
            self.client.conflicts_remaining -= 1
            current = self.client.store.get(self.key, "[]")
            assert type(current) is str
            rows = json.loads(current)
            if self.client.conflict_row is not None:
                rows.append(self.client.conflict_row)
            self.client.store[self.key] = _payload(rows)
            self.client.versions[self.key] = self.client.versions.get(self.key, 0) + 1
        if self.client.versions.get(self.key, 0) != self.version:
            raise redis.WatchError("simulated concurrent writer")

        key, value, ttl_seconds, keep_ttl = self.pending
        previous_ttl = self.client.pttls.get(key, -1)
        self.client.store[key] = value
        if ttl_seconds is not None:
            self.client.pttls[key] = ttl_seconds * 1000
        elif keep_ttl:
            self.client.pttls[key] = previous_ttl
        else:
            self.client.pttls[key] = -1
        self.client.versions[key] = self.client.versions.get(key, 0) + 1
        return [self.client.execute_ack]

    def reset(self) -> None:
        self.pending = None


def test_store_payload_cap_matches_exact_trainer_consumer_cap() -> None:
    assert CLOSED_WINDOW_MAX_PAYLOAD_BYTES == MAX_OHLCV_CLOSED_PAYLOAD_BYTES


def test_authority_flags_are_not_public_constructor_arguments() -> None:
    init_by_name = {item.name: item.init for item in fields(ClosedWindowRedisWriteResult)}

    assert init_by_name["exact_source_schema_validated"] is False
    assert init_by_name["immutable_cas_captured"] is False
    assert init_by_name["trainer_admission_granted"] is False
    assert init_by_name["live_execution_authorized"] is False


def test_merge_deduplicates_exact_row_and_keeps_chronological_suffix() -> None:
    existing = [_small_row(index) for index in range(4)]

    merged, discarded = merge_closed_window_rows(
        existing,
        [_small_row(2), _small_row(4)],
        row_limit=4,
    )

    assert [row["candle_open_time"] for row in merged] == [
        _small_row(index)["candle_open_time"] for index in range(1, 5)
    ]
    assert discarded == 2


def test_merge_rejects_same_open_time_with_different_candle_identity() -> None:
    first = _small_row(0)
    conflicting = {**first, "candle_id": "f" * 24}

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="conflicting_candle_identity",
    ):
        merge_closed_window_rows([first], [conflicting])


def test_merge_does_not_treat_byte_distinct_int_and_float_rows_as_duplicates() -> None:
    float_row = _canonical_row(0)
    int_row = {**float_row, "open": 100, "ohlcv": {**float_row["ohlcv"], "open": 100}}
    float_payload = _payload([float_row]).encode("ascii")
    int_payload = _payload([int_row]).encode("ascii")
    assert float_payload != int_payload
    validate_ohlcv_closed_window(float_payload, symbol="BTCUSDT", timeframe="1m")
    validate_ohlcv_closed_window(int_payload, symbol="BTCUSDT", timeframe="1m")

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="conflicting_candle_identity",
    ):
        merge_closed_window_rows([float_row], [int_row])


def test_serializer_trims_only_oldest_rows_and_is_exact_at_cap_boundary() -> None:
    rows = [_small_row(index, padding=400) for index in range(8)]
    exact_three = len(_payload(rows[-3:]).encode("ascii"))

    at_cap = serialize_bounded_closed_window(rows, max_payload_bytes=exact_three)
    below_cap = serialize_bounded_closed_window(
        rows,
        max_payload_bytes=exact_three - 1,
    )

    assert at_cap.payload_byte_count == exact_three
    assert at_cap.row_count == 3
    assert at_cap.rows_trimmed_for_bytes == 5
    assert below_cap.payload_byte_count <= exact_three - 1
    assert below_cap.row_count == 2
    assert [row["candle_id"] for row in json.loads(at_cap.payload_json)] == [
        row["candle_id"] for row in rows[-3:]
    ]


def test_serializer_rejects_when_minimum_suffix_cannot_fit() -> None:
    rows = [_small_row(index, padding=500) for index in range(3)]

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="minimum_rows_exceed_payload_cap",
    ):
        serialize_bounded_closed_window(
            rows,
            max_payload_bytes=100,
            minimum_rows_to_preserve=2,
        )


def test_atomic_merge_retries_and_preserves_concurrent_writer_row() -> None:
    client = _FakeRedis(
        {KEY: _payload([_canonical_row(0)])},
        initial_pttl_ms=90_000,
        conflicts_remaining=1,
        conflict_row=_canonical_row(1),
    )

    result = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(2)],
    )
    stored = json.loads(_stored_text(client))

    assert result.attempts == 2
    assert [row["candle_open_time"] for row in stored] == [
        _canonical_row(index)["candle_open_time"] for index in range(3)
    ]
    assert result.ttl_policy == "preserve"
    assert result.previous_pttl_ms == 90_000
    assert client.pttls[KEY] == 90_000
    assert result.exact_source_schema_validated is True
    assert result.immutable_cas_captured is False
    validate_ohlcv_closed_window(
        _stored_text(client).encode("ascii"),
        symbol="BTCUSDT",
        timeframe="1m",
    )


def test_atomic_merge_exhausts_bounded_conflict_retries_without_own_write() -> None:
    client = _FakeRedis(
        {KEY: _payload([_canonical_row(0)])},
        conflicts_remaining=3,
        conflict_row=_canonical_row(1),
    )

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="concurrent_write_retry_exhausted",
    ):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(2)],
            max_retries=2,
        )

    assert client.pipeline_calls == 2


def test_oversized_existing_is_not_returned_and_is_explicitly_repairable() -> None:
    client = _FakeRedis({KEY: "x" * (CLOSED_WINDOW_MAX_PAYLOAD_BYTES + 1)})

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="existing_payload_size_invalid",
    ):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])
    assert client.max_payload_bytes_returned == 0

    repaired = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        replace_invalid_existing=True,
    )
    assert repaired.invalid_existing_replaced is True
    assert client.max_payload_bytes_returned == 0
    assert json.loads(_stored_text(client)) == [_canonical_row(0)]


def test_empty_existing_string_is_explicitly_repairable() -> None:
    client = _FakeRedis({KEY: b""})

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="existing_payload_size_invalid",
    ):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])

    repaired = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        replace_invalid_existing=True,
    )
    assert repaired.invalid_existing_replaced is True
    assert json.loads(_stored_text(client)) == [_canonical_row(0)]


def test_hostile_huge_submitted_string_is_rejected_before_redis_pipeline() -> None:
    hostile = {**_canonical_row(0), "source_sequence_id": "x" * 513}
    client = _FakeRedis()

    with pytest.raises(ClosedWindowRedisStoreError, match="row_string_invalid"):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[hostile])
    assert client.pipeline_calls == 0


def test_wrong_redis_type_requires_explicit_repair_authority() -> None:
    client = _FakeRedis({KEY: ["not", "a", "string"]}, initial_pttl_ms=15_000)

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="existing_redis_type_not_string",
    ):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])

    repaired = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        replace_invalid_existing=True,
    )
    assert repaired.invalid_existing_replaced is True
    assert client.pttls[KEY] == 15_000


def test_invalid_utf8_existing_is_repairable_with_required_binary_client() -> None:
    client = _FakeRedis({KEY: b"\xff"})

    with pytest.raises(ClosedWindowRedisStoreError, match="existing_schema_invalid"):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])

    repaired = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        replace_invalid_existing=True,
    )
    assert repaired.invalid_existing_replaced is True
    assert json.loads(_stored_text(client)) == [_canonical_row(0)]


def test_decoded_redis_client_is_rejected_before_any_write() -> None:
    client = _FakeRedis(decode_responses=True)

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="redis_client_requires_binary_responses",
    ):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])
    assert KEY not in client.store


@pytest.mark.parametrize("invalid_kind", ["duplicate_key", "nan", "wrong_symbol"])
def test_semantically_invalid_existing_requires_explicit_repair(
    invalid_kind: str,
) -> None:
    valid = _payload([_canonical_row(0)])
    if invalid_kind == "duplicate_key":
        needle = '"symbol":"BTCUSDT"'
        invalid = valid.replace(needle, f"{needle},{needle}", 1)
    elif invalid_kind == "nan":
        needle = '"open":100.0'
        invalid = valid.replace(needle, '"open":NaN', 1)
    else:
        invalid = _payload([_canonical_row(0, symbol="ETHUSDT")])
    assert invalid != valid
    client = _FakeRedis({KEY: invalid})

    with pytest.raises(ClosedWindowRedisStoreError, match="existing_schema_invalid"):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(1)])

    repaired = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(1)],
        replace_invalid_existing=True,
    )
    assert repaired.invalid_existing_replaced is True
    assert json.loads(_stored_text(client)) == [_canonical_row(1)]


def test_valid_rows_with_same_open_but_different_raw_identity_fail_closed() -> None:
    client = _FakeRedis({KEY: _payload([_canonical_row(0)])})

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="conflicting_candle_identity",
    ):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0, close_delta=0.5)],
        )


@pytest.mark.parametrize(
    ("ttl_policy", "ttl_seconds", "initial_pttl", "expected_pttl"),
    [
        ("preserve", None, 42_000, 42_000),
        ("set", 60, 42_000, 60_000),
        ("persist", None, 42_000, -1),
    ],
)
def test_ttl_policy_is_explicit_and_observable(
    ttl_policy: str,
    ttl_seconds: int | None,
    initial_pttl: int,
    expected_pttl: int,
) -> None:
    client = _FakeRedis(
        {KEY: _payload([_canonical_row(0)])},
        initial_pttl_ms=initial_pttl,
    )

    result = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(1)],
        ttl_policy=ttl_policy,
        ttl_seconds=ttl_seconds,
    )

    assert result.ttl_policy == ttl_policy
    assert result.ttl_seconds == ttl_seconds
    assert result.previous_pttl_ms == initial_pttl
    assert client.pttls[KEY] == expected_pttl


def test_non_acknowledged_commit_fails_closed() -> None:
    client = _FakeRedis(execute_ack=False)

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="commit_not_acknowledged",
    ):
        atomic_merge_closed_window(client, redis_key=KEY, new_rows=[_canonical_row(0)])


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"redis_key": "v1:bad", "new_rows": [_canonical_row(0)]}, "redis_key_invalid"),
        (
            {"redis_key": KEY, "new_rows": []},
            "new_rows_count_invalid",
        ),
        (
            {"redis_key": KEY, "new_rows": [_canonical_row(0)], "max_retries": True},
            "max_retries_invalid",
        ),
        (
            {
                "redis_key": KEY,
                "new_rows": [_canonical_row(0)],
                "ttl_policy": "set",
                "ttl_seconds": float("inf"),
            },
            "ttl_seconds_invalid",
        ),
        (
            {
                "redis_key": KEY,
                "new_rows": [_canonical_row(0)],
                "ttl_policy": "preserve",
                "ttl_seconds": 60,
            },
            "ttl_seconds_for_policy_invalid",
        ),
        (
            {
                "redis_key": "v2:market:ohlcv_closed:binance:ETHUSDT:1m",
                "new_rows": [_canonical_row(0)],
            },
            "submitted_schema_invalid",
        ),
        (
            {
                "redis_key": "v2:market:ohlcv_closed:binance:BTCUSDT:2m",
                "new_rows": [_canonical_row(0)],
            },
            "redis_key_invalid",
        ),
    ],
)
def test_hostile_public_arguments_fail_closed(
    kwargs: dict[str, Any],
    reason: str,
) -> None:
    with pytest.raises(ClosedWindowRedisStoreError, match=reason):
        atomic_merge_closed_window(_FakeRedis(), **kwargs)
