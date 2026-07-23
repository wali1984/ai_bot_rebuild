from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import redis

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE,
    CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    CLOSED_WINDOW_MAX_RECEIPT_BYTES,
    EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
    ClosedWindowRedisStoreError,
    ClosedWindowRedisWriteResult,
    adopt_existing_closed_window_publication,
    cadence_bounded_publication_ttls,
    merge_closed_window_rows,
    require_verified_closed_window_publication,
    serialize_bounded_closed_window,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    atomic_merge_closed_window as _atomic_merge_closed_window,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    validate_ohlcv_closed_window,
)

KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
BASE_MS = 1_800_000_000_000
CODE_SHA256 = "a" * 64
CONFIG_SHA256 = "b" * 64
RECEIPT_TTL_SECONDS = 86_400
ARCHIVE_TTL_SECONDS = 172_800


def atomic_merge_closed_window(client: object, **kwargs: Any) -> ClosedWindowRedisWriteResult:
    kwargs.setdefault("producer_role", BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE)
    kwargs.setdefault("producer_code_sha256", CODE_SHA256)
    kwargs.setdefault("producer_config_sha256", CONFIG_SHA256)
    kwargs.setdefault("receipt_ttl_seconds", RECEIPT_TTL_SECONDS)
    kwargs.setdefault("archive_ttl_seconds", ARCHIVE_TTL_SECONDS)
    return _atomic_merge_closed_window(client, **kwargs)


@pytest.fixture()  # type: ignore[misc]
def redis_socket(tmp_path: Path) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the atomic Lua contract test")
    socket_path = str(tmp_path / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local executable and arguments
        [
            executable,
            "--port",
            "0",
            "--save",
            "",
            "--appendonly",
            "no",
            "--unixsocket",
            socket_path,
            "--unixsocketperm",
            "700",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    client: redis.Redis | None = None
    while time.monotonic() < deadline:
        try:
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=False)
            if client.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    assert client is not None
    client.flushdb()
    try:
        yield socket_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


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


def _canonical_wss_row(*, ingested_at: int) -> dict[str, Any]:
    open_time = BASE_MS
    close_time = open_time + 59_999
    packet = {
        "E": close_time + 1,
        "k": {
            "s": "BTCUSDT",
            "i": "1m",
            "t": open_time,
            "T": close_time,
            "o": "100.0",
            "h": "102.0",
            "l": "99.0",
            "c": "101.0",
            "v": "12.0",
            "q": "1206.0",
            "n": 10,
            "V": "6.0",
            "Q": "603.0",
            "B": "0",
            "x": True,
        },
    }
    return canonical_from_binance_wss(
        packet,
        symbol="BTCUSDT",
        timeframe="1m",
        ingested_at=ingested_at,
    ).to_dict()


def _payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _adoption_client(
    payload: str | bytes,
    *,
    pttl_ms: int = 86_400_000,
) -> _FakeRedis:
    client = _FakeRedis({KEY: payload}, initial_pttl_ms=pttl_ms)
    decoded = json.loads(payload)
    client.clock_us = max(
        int(row["available_at"])
        for row in decoded
    ) * 1000
    return client


def _adopt(client: object, **kwargs: Any) -> Any:
    return adopt_existing_closed_window_publication(
        client,
        redis_key=kwargs.pop("redis_key", KEY),
        adopter_code_sha256=kwargs.pop("adopter_code_sha256", CODE_SHA256),
        adopter_config_sha256=kwargs.pop(
            "adopter_config_sha256",
            CONFIG_SHA256,
        ),
        **kwargs,
    )


def _stored_text(client: _FakeRedis, key: str = KEY) -> str:
    raw = client.store[key]
    assert type(raw) in (str, bytes)
    return raw if type(raw) is str else raw.decode("ascii")


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
        self.clock_us = 2_000_000_000_000_000
        self.before_commit: Any = None
        self.before_adoption_commit: Any = None
        self.before_reopen: Any = None
        self.inject_competing_valid_receipt = False

    @staticmethod
    def _raw(value: object) -> bytes:
        if type(value) is bytes:
            return value
        if type(value) is str:
            return value.encode("utf-8")
        raise AssertionError(f"unexpected fake Redis value: {type(value)!r}")

    def _time(self) -> tuple[bytes, bytes]:
        self.clock_us += 1_000
        return (
            str(self.clock_us // 1_000_000).encode("ascii"),
            str(self.clock_us % 1_000_000).encode("ascii"),
        )

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        self.pipeline_calls += 1
        return _FakePipeline(self)

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[object]:
        keys = [str(value) for value in keys_and_args[:numkeys]]
        args = list(keys_and_args[numkeys:])
        if "canonical_closed_ohlcv_adoption_commit_v1" in script:
            canonical_key, archive_key, receipt_key, pointer_key = keys
            payload = self._raw(args[0])
            receipt_payload = self._raw(args[1])
            revision_id = self._raw(args[2])
            receipt_ttl = int(args[3])
            if self.before_adoption_commit is not None:
                self.before_adoption_commit(
                    self,
                    canonical_key,
                    archive_key,
                    receipt_key,
                    pointer_key,
                )
            if pointer_key in self.store:
                return [b"RETRY", b"LATEST_POINTER_APPEARED_BEFORE_ADOPTION_COMMIT"]
            if self.store.get(canonical_key) != payload:
                return [b"RETRY", b"CANONICAL_KEY_CHANGED_BEFORE_ADOPTION_COMMIT"]
            if self.store.get(archive_key) != payload:
                return [b"ERROR", b"ADOPTION_ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"]
            existing = self.store.get(receipt_key)
            if existing is not None and self._raw(existing) != receipt_payload:
                return [b"ERROR", b"ADOPTION_RECEIPT_IDENTITY_CONFLICT"]
            committed_receipt = (
                self._raw(existing) if existing is not None else receipt_payload
            )
            self.store[receipt_key] = committed_receipt
            self.pttls[receipt_key] = receipt_ttl * 1000
            self.store[pointer_key] = revision_id
            self.pttls[pointer_key] = receipt_ttl * 1000
            self.versions[receipt_key] = self.versions.get(receipt_key, 0) + 1
            self.versions[pointer_key] = self.versions.get(pointer_key, 0) + 1
            seconds, microseconds = self._time()
            return [
                b"IDEMPOTENT" if existing is not None else b"COMMITTED",
                seconds,
                microseconds,
                committed_receipt,
            ]
        if "canonical_closed_ohlcv_publication_commit_v1" in script:
            canonical_key, archive_key, receipt_key, pointer_key = keys
            payload = self._raw(args[0])
            receipt_payload = self._raw(args[1])
            revision_id = self._raw(args[2])
            receipt_ttl = int(args[3])
            if self.before_commit is not None:
                self.before_commit(self, canonical_key, archive_key, receipt_key)
            if self.store.get(canonical_key) != payload:
                return [b"RETRY", b"CANONICAL_KEY_CHANGED_BEFORE_RECEIPT_COMMIT"]
            if self.store.get(archive_key) != payload:
                return [b"ERROR", b"ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"]
            if self.inject_competing_valid_receipt:
                self.inject_competing_valid_receipt = False
                competing = json.loads(receipt_payload)
                available = datetime.strptime(
                    competing["publication_available_at"],
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                ).replace(tzinfo=UTC)
                competing["publication_available_at"] = (
                    (available + timedelta(microseconds=500))
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z")
                )
                unsigned = {
                    key: value
                    for key, value in competing.items()
                    if key != "receipt_sha256"
                }
                competing["receipt_sha256"] = hashlib.sha256(
                    json.dumps(
                        unsigned,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
                self.store[receipt_key] = json.dumps(
                    competing,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
            existing = self.store.get(receipt_key)
            committed_receipt = (
                self._raw(existing) if existing is not None else receipt_payload
            )
            self.store[receipt_key] = committed_receipt
            self.pttls[receipt_key] = receipt_ttl * 1000
            self.store[pointer_key] = revision_id
            self.pttls[pointer_key] = receipt_ttl * 1000
            self.versions[receipt_key] = self.versions.get(receipt_key, 0) + 1
            self.versions[pointer_key] = self.versions.get(pointer_key, 0) + 1
            seconds, microseconds = self._time()
            status = (
                b"COMMITTED"
                if existing is None
                else b"IDEMPOTENT"
                if committed_receipt == receipt_payload
                else b"ADOPTED"
            )
            return [status, seconds, microseconds, committed_receipt]
        if "canonical_closed_ohlcv_publication_reopen_v1" in script:
            canonical_key, archive_key, receipt_key, pointer_key = keys
            payload = self._raw(args[0])
            revision_id = self._raw(args[1])
            if self.before_reopen is not None:
                self.before_reopen(self, canonical_key, archive_key, receipt_key, pointer_key)
            if self.store.get(canonical_key) != payload:
                return [b"RETRY", b"CANONICAL_KEY_CHANGED_BEFORE_REOPEN"]
            if archive_key not in self.store:
                return [b"ERROR", b"ARCHIVE_MISSING"]
            if self.store.get(archive_key) != payload:
                return [b"ERROR", b"ARCHIVE_REOPEN_MISMATCH"]
            if receipt_key not in self.store:
                return [b"ERROR", b"RECEIPT_MISSING"]
            if self.store.get(pointer_key) != revision_id:
                return [b"RETRY", b"LATEST_POINTER_CHANGED_BEFORE_REOPEN"]
            archive_pttl = self.pttls[archive_key]
            receipt_pttl = self.pttls[receipt_key]
            pointer_pttl = self.pttls[pointer_key]
            if (
                archive_pttl <= receipt_pttl
                or archive_pttl <= pointer_pttl
                or receipt_pttl <= 0
                or pointer_pttl <= 0
            ):
                return [b"ERROR", b"PUBLICATION_TTL_ORDER_INVALID"]
            seconds, microseconds = self._time()
            return [
                b"REOPENED",
                self.store[archive_key],
                self.store[receipt_key],
                self.store[pointer_key],
                archive_pttl,
                receipt_pttl,
                pointer_pttl,
                seconds,
                microseconds,
            ]
        raise AssertionError("unexpected direct Lua script")


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client
        self.key: str | None = None
        self.versions: dict[str, int] = {}
        self.pending: tuple[str, str, int | None, bool] | None = None
        self.pending_eval: tuple[list[str], list[object]] | None = None
        self.in_multi = False

    def watch(self, *keys: str) -> None:
        assert keys
        self.key = keys[0]
        self.versions = {
            key: self.client.versions.get(key, 0)
            for key in keys
        }

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        if "canonical_closed_ohlcv_publication_prepare_v1" in script:
            assert self.in_multi is True
            self.pending_eval = (
                [str(value) for value in keys_and_args[:numkeys]],
                list(keys_and_args[numkeys:]),
            )
            return self
        assert len(keys_and_args) == 2
        key = str(keys_and_args[0])
        cap = int(keys_and_args[1])
        assert key in self.versions
        assert numkeys == 1
        assert "STRLEN" in script and "GETRANGE" in script
        self.client.bounded_read_calls += 1
        if key not in self.client.store:
            kind = "none" if self.client.decode_responses else b"none"
            response: list[object] = [kind, -2, 0, None]
            if "canonical_closed_ohlcv_adoption_bounded_read_v1" in script:
                response.extend(self.client._time())
            return response
        raw = self.client.store[key]
        kind_text = "string" if type(raw) in {str, bytes} else "list"
        kind = kind_text if self.client.decode_responses else kind_text.encode("ascii")
        pttl = self.client.pttls.get(key, -1)
        if kind_text != "string":
            response = [kind, pttl, 0, None]
            if "canonical_closed_ohlcv_adoption_bounded_read_v1" in script:
                response.extend(self.client._time())
            return response
        payload = raw if type(raw) is bytes else str(raw).encode("utf-8")
        if len(payload) > cap:
            response = [kind, pttl, len(payload), None]
            if "canonical_closed_ohlcv_adoption_bounded_read_v1" in script:
                response.extend(self.client._time())
            return response
        self.client.max_payload_bytes_returned = max(
            self.client.max_payload_bytes_returned,
            len(payload),
        )
        response = [
            kind,
            pttl,
            len(payload),
            payload.decode("utf-8") if self.client.decode_responses else payload,
        ]
        if "canonical_closed_ohlcv_adoption_bounded_read_v1" in script:
            response.extend(self.client._time())
        return response

    def multi(self) -> None:
        self.in_multi = True

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        keepttl: bool = False,
    ) -> None:
        self.pending = (key, value, ex, keepttl)

    def execute(self) -> list[object]:
        assert self.key is not None
        if self.client.conflicts_remaining:
            self.client.conflicts_remaining -= 1
            current = self.client.store.get(self.key, "[]")
            assert type(current) in (str, bytes)
            rows = json.loads(current)
            if self.client.conflict_row is not None:
                rows.append(self.client.conflict_row)
            self.client.store[self.key] = _payload(rows)
            self.client.versions[self.key] = self.client.versions.get(self.key, 0) + 1
        if any(
            self.client.versions.get(key, 0) != version
            for key, version in self.versions.items()
        ):
            raise redis.WatchError("simulated concurrent writer")

        if self.pending_eval is not None:
            if not self.client.execute_ack:
                return []
            keys, args = self.pending_eval
            canonical_key, archive_key, receipt_key = keys
            payload = self.client._raw(args[0])
            archive_ttl = int(args[1])
            receipt_ttl = int(args[2])
            mutable_ttl = int(args[3])
            ttl_policy = str(args[4])
            existing_archive = self.client.store.get(archive_key)
            if existing_archive is not None and type(existing_archive) not in (str, bytes):
                return [[b"ERROR", b"ARCHIVE_TYPE_INVALID"]]  # type: ignore[list-item]
            if (
                existing_archive is not None
                and len(self.client._raw(existing_archive)) > int(args[5])
            ):
                return [[b"ERROR", b"ARCHIVE_SIZE_INVALID"]]  # type: ignore[list-item]
            if existing_archive is not None and self.client._raw(existing_archive) != payload:
                return [[b"ERROR", b"ARCHIVE_IDENTITY_CONFLICT"]]  # type: ignore[list-item]
            self.client.store[archive_key] = payload
            self.client.pttls[archive_key] = archive_ttl * 1000
            existing_receipt = self.client.store.get(receipt_key)
            if existing_receipt is not None and type(existing_receipt) not in (str, bytes):
                return [[b"ERROR", b"RECEIPT_TYPE_INVALID"]]  # type: ignore[list-item]
            if (
                existing_receipt is not None
                and len(self.client._raw(existing_receipt)) > int(args[6])
            ):
                return [[b"ERROR", b"RECEIPT_SIZE_INVALID"]]  # type: ignore[list-item]
            previous_ttl = self.client.pttls.get(canonical_key, -1)
            self.client.store[canonical_key] = payload
            if ttl_policy == "set":
                self.client.pttls[canonical_key] = mutable_ttl * 1000
            elif ttl_policy == "preserve":
                self.client.pttls[canonical_key] = previous_ttl
            else:
                self.client.pttls[canonical_key] = -1
            self.client.versions[canonical_key] = self.client.versions.get(canonical_key, 0) + 1
            seconds, microseconds = self.client._time()
            return [[
                b"IDEMPOTENT_PREPARED" if existing_receipt is not None else b"PREPARED",
                seconds,
                microseconds,
                (
                    self.client._raw(existing_receipt)
                    if existing_receipt is not None
                    else None
                ),
            ]]  # type: ignore[list-item]

        assert self.pending is not None

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
        self.pending_eval = None


def test_store_payload_cap_matches_exact_trainer_consumer_cap() -> None:
    assert CLOSED_WINDOW_MAX_PAYLOAD_BYTES == MAX_OHLCV_CLOSED_PAYLOAD_BYTES


def test_authority_flags_are_not_public_constructor_arguments() -> None:
    init_by_name = {item.name: item.init for item in fields(ClosedWindowRedisWriteResult)}

    assert init_by_name["exact_source_schema_validated"] is False
    assert init_by_name["immutable_cas_captured"] is False
    assert init_by_name["publication_receipt_verified"] is False
    assert init_by_name["trainer_admission_granted"] is False
    assert init_by_name["prediction_authorized"] is False
    assert init_by_name["paper_trading_authorized"] is False
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


def test_identical_wss_packet_reobservation_retains_first_pit_observation() -> None:
    first = _canonical_wss_row(ingested_at=BASE_MS + 60_100)
    replay = _canonical_wss_row(ingested_at=BASE_MS + 65_000)
    first_payload = _payload([first]).encode("ascii")
    replay_payload = _payload([replay]).encode("ascii")
    assert first["candle_id"] == replay["candle_id"]
    assert first["raw_payload_hash"] == replay["raw_payload_hash"]
    assert first["ingested_at"] != replay["ingested_at"]
    assert first_payload != replay_payload
    validate_ohlcv_closed_window(
        first_payload,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    validate_ohlcv_closed_window(
        replay_payload,
        symbol="BTCUSDT",
        timeframe="1m",
    )

    merged, discarded = merge_closed_window_rows([first], [replay])

    assert merged == [first]
    assert discarded == 1


def test_same_open_wss_source_revision_still_fails_closed() -> None:
    first = _canonical_wss_row(ingested_at=BASE_MS + 60_100)
    revision = {
        **first,
        "event_time": first["event_time"] + 1,
        "source_sequence_id": str(first["event_time"] + 1),
    }

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="conflicting_candle_identity",
    ):
        merge_closed_window_rows([first], [revision])


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
    assert result.immutable_cas_captured is True
    assert result.publication_receipt_verified is True
    assert result.receipt is not None
    assert result.receipt["trainer_admission_authorized"] is False
    assert result.receipt["paper_trading_authorized"] is False
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


def test_receipt_happy_path_binds_exact_bytes_bounds_identity_and_holds_authority() -> None:
    client = _FakeRedis()

    result = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0), _canonical_row(1)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )

    assert result.publication_receipt_verified is True
    assert result.immutable_cas_captured is True
    assert result.revision_id is not None and len(result.revision_id.rsplit("_", 1)[1]) == 64
    assert client.store[result.archive_key] == _stored_text(client).encode("ascii")
    assert client.store[result.receipt_key]
    assert client.store[result.latest_receipt_pointer_key] == result.revision_id.encode("ascii")
    assert result.receipt is not None
    assert result.receipt["exact_payload_sha256"] == result.payload_sha256
    assert result.receipt["exact_payload_byte_count"] == result.payload_byte_count
    assert result.receipt["row_count"] == 2
    assert result.receipt["first_candle_id"] == _canonical_row(0)["candle_id"]
    assert result.receipt["latest_candle_id"] == _canonical_row(1)["candle_id"]
    assert all(
        result.receipt[field] is False
        for field in (
            "trainer_admission_authorized",
            "prediction_authorized",
            "paper_trading_authorized",
            "live_execution_authorized",
        )
    )


def test_publication_evidence_ttls_follow_cadence_not_mutable_cache_residency() -> None:
    assert cadence_bounded_publication_ttls("1m") == (180, 240)
    assert cadence_bounded_publication_ttls("4h") == (43_200, 57_600)

    result = atomic_merge_closed_window(
        _FakeRedis(),
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=86_400,
        receipt_ttl_seconds=180,
        archive_ttl_seconds=240,
    )

    assert result.ttl_seconds == 86_400
    assert result.receipt_ttl_seconds == 180
    assert result.archive_ttl_seconds == 240


def test_mutation_between_prepare_and_commit_retries_against_new_canonical_value() -> None:
    client = _FakeRedis()

    def mutate_once(
        target: _FakeRedis,
        canonical_key: str,
        _archive_key: str,
        _receipt_key: str,
    ) -> None:
        target.before_commit = None
        target.store[canonical_key] = _payload(
            [_canonical_row(0), _canonical_row(1)]
        ).encode("ascii")
        target.pttls[canonical_key] = RECEIPT_TTL_SECONDS * 1000
        target.versions[canonical_key] = target.versions.get(canonical_key, 0) + 1

    client.before_commit = mutate_once
    result = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )

    assert result.attempts == 2
    assert result.stored_row_count == 2
    assert result.publication_receipt_verified is True


def test_concurrent_identical_publisher_adopts_first_valid_receipt() -> None:
    client = _FakeRedis()
    client.inject_competing_valid_receipt = True

    result = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )

    assert result.publication_receipt_verified is True
    assert result.prepare_observed_at == result.publication_available_at
    assert result.publication_available_at is not None
    assert result.receipt_postcommit_observed_at is not None
    assert result.publication_available_at < result.receipt_postcommit_observed_at


@pytest.mark.parametrize("tamper", ["archive", "missing_receipt", "receipt_bytes"])
def test_postcommit_tamper_or_missing_receipt_fails_closed(tamper: str) -> None:
    client = _FakeRedis()

    if tamper == "archive":
        def before_commit(
            target: _FakeRedis,
            _canonical_key: str,
            archive_key: str,
            _receipt_key: str,
        ) -> None:
            target.store[archive_key] = b"[]"

        client.before_commit = before_commit
    else:
        def before_reopen(
            target: _FakeRedis,
            _canonical_key: str,
            _archive_key: str,
            receipt_key: str,
            _pointer_key: str,
        ) -> None:
            if tamper == "missing_receipt":
                target.store.pop(receipt_key, None)
            else:
                target.store[receipt_key] = b"{}"

        client.before_reopen = before_reopen

    with pytest.raises(ClosedWindowRedisStoreError):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0)],
            ttl_policy="set",
            ttl_seconds=RECEIPT_TTL_SECONDS,
        )


@pytest.mark.parametrize(
    ("substituted_field", "substituted_value"),
    [("symbol", "ETHUSDT"), ("timeframe", "5m")],
)
def test_cross_symbol_or_timeframe_receipt_substitution_fails_rederivation(
    substituted_field: str,
    substituted_value: str,
) -> None:
    client = _FakeRedis()

    def substitute_receipt(
        target: _FakeRedis,
        _canonical_key: str,
        _archive_key: str,
        receipt_key: str,
        _pointer_key: str,
    ) -> None:
        receipt = json.loads(target._raw(target.store[receipt_key]))
        receipt[substituted_field] = substituted_value
        unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        target.store[receipt_key] = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    client.before_reopen = substitute_receipt
    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="receipt_rederivation_mismatch",
    ):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0)],
            ttl_policy="set",
            ttl_seconds=RECEIPT_TTL_SECONDS,
        )


@pytest.mark.parametrize("invalid_artifact", ["archive_type", "receipt_oversized"])
def test_invalid_archive_or_receipt_type_and_size_fail_closed(
    invalid_artifact: str,
) -> None:
    client = _FakeRedis()
    first = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )
    assert first.archive_key is not None and first.receipt_key is not None
    if invalid_artifact == "archive_type":
        client.store[first.archive_key] = ["wrong-type"]
    else:
        client.store[first.receipt_key] = b"x" * (CLOSED_WINDOW_MAX_RECEIPT_BYTES + 1)

    with pytest.raises(ClosedWindowRedisStoreError):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0)],
            ttl_policy="set",
            ttl_seconds=RECEIPT_TTL_SECONDS,
        )


def test_redis_clock_regression_fails_closed() -> None:
    client = _FakeRedis()

    def regress_clock(
        target: _FakeRedis,
        _canonical_key: str,
        _archive_key: str,
        _receipt_key: str,
    ) -> None:
        target.clock_us -= 10_000

    client.before_commit = regress_clock
    with pytest.raises(ClosedWindowRedisStoreError, match="clock_order_invalid"):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0)],
            ttl_policy="set",
            ttl_seconds=RECEIPT_TTL_SECONDS,
        )


def test_ttl_inversion_is_rejected_before_redis_access() -> None:
    client = _FakeRedis()

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="archive_ttl_must_exceed_receipt_ttl",
    ):
        atomic_merge_closed_window(
            client,
            redis_key=KEY,
            new_rows=[_canonical_row(0)],
            receipt_ttl_seconds=100,
            archive_ttl_seconds=100,
        )
    assert client.pipeline_calls == 0


def test_exact_idempotent_replay_preserves_original_publication_availability() -> None:
    client = _FakeRedis()
    first = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )
    second = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[_canonical_row(0)],
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
    )

    assert second.revision_id == first.revision_id
    assert second.receipt_sha256 == first.receipt_sha256
    assert second.publication_available_at == first.publication_available_at
    assert second.prepare_observed_at == first.prepare_observed_at
    assert second.consumer_reopened_at > first.consumer_reopened_at


@pytest.mark.parametrize(
    ("missing_field", "reason"),
    [
        ("producer_role", "producer_role_invalid"),
        ("producer_code_sha256", "producer_code_sha256_invalid"),
        ("producer_config_sha256", "producer_config_sha256_invalid"),
        ("receipt_ttl_seconds", "receipt_ttl_seconds_invalid"),
        ("archive_ttl_seconds", "archive_ttl_seconds_invalid"),
    ],
)
def test_publication_caller_identity_and_ttl_arguments_are_required(
    missing_field: str,
    reason: str,
) -> None:
    kwargs: dict[str, object] = {
        "redis_key": KEY,
        "new_rows": [_canonical_row(0)],
        "producer_role": BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE,
        "producer_code_sha256": CODE_SHA256,
        "producer_config_sha256": CONFIG_SHA256,
        "receipt_ttl_seconds": RECEIPT_TTL_SECONDS,
        "archive_ttl_seconds": ARCHIVE_TTL_SECONDS,
    }
    kwargs[missing_field] = None

    with pytest.raises(ClosedWindowRedisStoreError, match=reason):
        _atomic_merge_closed_window(_FakeRedis(), **kwargs)


def test_caller_rejects_legacy_unreceipted_write_result() -> None:
    legacy = ClosedWindowRedisWriteResult(
        redis_key=KEY,
        attempts=1,
        existing_row_count=0,
        submitted_row_count=1,
        stored_row_count=1,
        rows_deduplicated_or_trimmed_for_row_limit=0,
        rows_trimmed_for_bytes=0,
        payload_sha256="c" * 64,
        payload_byte_count=100,
        ttl_policy="set",
        ttl_seconds=RECEIPT_TTL_SECONDS,
        previous_pttl_ms=-2,
        invalid_existing_replaced=False,
    )

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="publication_receipt_required",
    ):
        require_verified_closed_window_publication(
            legacy,
            expected_redis_key=KEY,
            expected_producer_role=BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE,
        )


def test_adoption_preserves_exact_bytes_pttl_and_never_claims_authority() -> None:
    payload = json.dumps([_canonical_row(0)], indent=2).encode("utf-8")
    client = _adoption_client(payload, pttl_ms=12_345_678)

    result = _adopt(client)

    assert result.status == "ADOPTED_EXISTING_PAYLOAD"
    assert client.store[KEY] == payload
    assert client.pttls[KEY] == 12_345_678
    assert result.payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.payload_byte_count == len(payload)
    assert result.producer_role == EXISTING_CLOSED_WINDOW_ADOPTER_ROLE
    assert result.publication_receipt_verified is True
    assert result.producer_authenticity_verified is False
    assert result.legacy_source_authenticity_verified is False
    assert result.trainer_admission_granted is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.receipt["trainer_admission_authorized"] is False
    assert result.receipt["live_execution_authorized"] is False
    assert result.receipt["receipt_ttl_seconds"] == 180
    assert result.receipt["archive_ttl_seconds"] == 240


def test_adoption_keeps_more_than_wss_row_limit_without_reserialization() -> None:
    rows = [_canonical_row(index) for index in range(101)]
    payload = (json.dumps(rows, separators=(", ", ": ")) + "\n").encode("ascii")
    client = _adoption_client(payload)

    result = _adopt(client)

    assert result.row_count == 101
    assert result.payload_byte_count == len(payload)
    assert client.store[KEY] == payload
    assert client.store[result.archive_key] == payload


@pytest.mark.parametrize(
    ("initial", "reason"),
    [
        (None, "adoption_source_missing"),
        (["wrong-type"], "adoption_source_type_invalid"),
        (b"x" * (CLOSED_WINDOW_MAX_PAYLOAD_BYTES + 1), "adoption_payload_size_invalid"),
        (b"\xff", "adoption_source_schema_invalid"),
        (b"{", "adoption_source_schema_invalid"),
    ],
)
def test_adoption_rejects_missing_wrong_type_oversized_or_malformed_source(
    initial: object,
    reason: str,
) -> None:
    client = _FakeRedis(
        {} if initial is None else {KEY: initial},
        initial_pttl_ms=60_000,
    )

    with pytest.raises(ClosedWindowRedisStoreError, match=reason):
        _adopt(client)

    assert all("publication_receipt" not in key for key in client.store)


def test_adoption_rejects_schema_valid_row_not_available_at_redis_observation() -> None:
    row = _canonical_row(0)
    client = _adoption_client(_payload([row]))
    client.clock_us = int(row["candle_close_time"]) * 1000

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="adoption_source_not_yet_available",
    ):
        _adopt(client)


def test_adoption_requires_the_latest_expected_finalized_close() -> None:
    row = _canonical_row(0)
    client = _adoption_client(_payload([row]))
    client.clock_us = (int(row["candle_close_time"]) + 60_001) * 1000

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="adoption_source_latest_finalized_close_missing",
    ):
        _adopt(client)


def test_adoption_retries_watch_mutation_and_preserves_exact_current_bytes() -> None:
    payload = _payload([_canonical_row(0)])
    client = _adoption_client(payload)
    client.conflicts_remaining = 1

    result = _adopt(client)

    assert result.status == "ADOPTED_EXISTING_PAYLOAD"
    assert result.attempts == 2
    assert client._raw(client.store[KEY]) == payload.encode("ascii")


def test_adoption_idempotently_reopens_existing_adopter_receipt() -> None:
    payload = _payload([_canonical_row(0)])
    client = _adoption_client(payload)
    first = _adopt(client)

    second = _adopt(client)

    assert second.status == "ALREADY_RECEIPTED"
    assert second.revision_id == first.revision_id
    assert second.producer_role == EXISTING_CLOSED_WINDOW_ADOPTER_ROLE
    assert second.producer_authenticity_verified is False
    assert client.store[KEY] == payload.encode("ascii")


def test_adoption_reopens_valid_writer_receipt_without_provenance_downgrade() -> None:
    row = _canonical_row(0)
    client = _adoption_client(_payload([row]))
    writer = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[row],
        ttl_policy="preserve",
    )

    result = _adopt(client)

    assert result.status == "ALREADY_RECEIPTED"
    assert result.revision_id == writer.revision_id
    assert result.producer_role == BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE
    assert result.producer_authenticity_verified is False
    assert client.store[result.latest_receipt_pointer_key] == writer.revision_id.encode(
        "ascii"
    )


def test_writer_pointer_appearing_after_prepare_wins_adoption_race() -> None:
    row = _canonical_row(0)
    payload = _payload([row])
    genuine = _adoption_client(payload)
    writer = atomic_merge_closed_window(
        genuine,
        redis_key=KEY,
        new_rows=[row],
        ttl_policy="preserve",
    )
    target = _adoption_client(payload)

    def publish_writer_receipt(
        client: _FakeRedis,
        _canonical_key: str,
        _archive_key: str,
        _receipt_key: str,
        _pointer_key: str,
    ) -> None:
        client.before_adoption_commit = None
        for redis_key in (
            writer.archive_key,
            writer.receipt_key,
            writer.latest_receipt_pointer_key,
        ):
            assert redis_key is not None
            client.store[redis_key] = genuine.store[redis_key]
            client.pttls[redis_key] = genuine.pttls[redis_key]
            client.versions[redis_key] = client.versions.get(redis_key, 0) + 1

    target.before_adoption_commit = publish_writer_receipt

    result = _adopt(target)

    assert result.status == "ALREADY_RECEIPTED"
    assert result.attempts == 2
    assert result.revision_id == writer.revision_id
    assert result.producer_role == BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE
    assert target.store[result.latest_receipt_pointer_key] == writer.revision_id.encode(
        "ascii"
    )


@pytest.mark.parametrize("tamper", ["pointer", "archive", "receipt"])
def test_adoption_fails_closed_on_existing_publication_tamper(tamper: str) -> None:
    client = _adoption_client(_payload([_canonical_row(0)]))
    first = _adopt(client)
    if tamper == "pointer":
        client.store[first.latest_receipt_pointer_key] = b"not-a-revision"
    elif tamper == "archive":
        client.store[first.archive_key] = b"[]"
    else:
        receipt = json.loads(client.store[first.receipt_key])
        receipt["trainer_admission_authorized"] = True
        client.store[first.receipt_key] = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    with pytest.raises(ClosedWindowRedisStoreError):
        _adopt(client)


def test_adoption_never_points_to_a_conflicting_orphan_receipt() -> None:
    client = _adoption_client(_payload([_canonical_row(0)]))
    first = _adopt(client)
    del client.store[first.latest_receipt_pointer_key]
    del client.pttls[first.latest_receipt_pointer_key]
    receipt = json.loads(client.store[first.receipt_key])
    receipt["publication_available_at"] = "2034-01-01T00:00:00.000000Z"
    client.store[first.receipt_key] = json.dumps(
        receipt,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")

    with pytest.raises(
        ClosedWindowRedisStoreError,
        match="receipt_rederivation_mismatch",
    ):
        _adopt(client)

    assert first.latest_receipt_pointer_key not in client.store


def test_real_redis_lua_exact_reopen_ttl_order_and_idempotence(
    redis_socket: str,
) -> None:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    now_ms = int(time.time() * 1000)
    open_time = ((now_ms // 60_000) - 2) * 60_000
    close_time = open_time + 59_999
    source = [
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
    row = canonical_from_binance_rest(
        source,
        symbol="BTCUSDT",
        timeframe="1m",
        ingested_at=close_time + 200,
    ).to_dict()

    first = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[row],
        ttl_policy="set",
        ttl_seconds=60,
        receipt_ttl_seconds=60,
        archive_ttl_seconds=120,
    )
    second = atomic_merge_closed_window(
        client,
        redis_key=KEY,
        new_rows=[row],
        ttl_policy="set",
        ttl_seconds=60,
        receipt_ttl_seconds=60,
        archive_ttl_seconds=120,
    )

    assert first.publication_receipt_verified is True
    assert client.get(KEY) == client.get(first.archive_key)
    assert client.get(first.latest_receipt_pointer_key) == first.revision_id.encode("ascii")
    assert client.pttl(first.archive_key) > client.pttl(first.receipt_key) > 0
    assert client.pttl(first.archive_key) > client.pttl(first.latest_receipt_pointer_key) > 0
    assert second.revision_id == first.revision_id
    assert second.receipt_sha256 == first.receipt_sha256
    assert second.publication_available_at == first.publication_available_at


def test_real_redis_adoption_preserves_exact_bytes_and_recognizes_receipt(
    redis_socket: str,
) -> None:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    now_ms = int(time.time() * 1000)
    open_time = ((now_ms // 60_000) - 1) * 60_000
    close_time = open_time + 59_999
    row = canonical_from_binance_rest(
        [
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
        ],
        symbol="BTCUSDT",
        timeframe="1m",
        ingested_at=close_time + 1,
    ).to_dict()
    payload = (json.dumps([row], indent=2) + "\n").encode("ascii")
    assert client.set(KEY, payload, px=120_000)
    before_pttl = client.pttl(KEY)

    first = _adopt(client)
    after_pttl = client.pttl(KEY)
    second = _adopt(client)

    assert first.status == "ADOPTED_EXISTING_PAYLOAD"
    assert second.status == "ALREADY_RECEIPTED"
    assert first.revision_id == second.revision_id
    assert first.producer_role == EXISTING_CLOSED_WINDOW_ADOPTER_ROLE
    assert client.get(KEY) == payload
    assert 0 < after_pttl <= before_pttl
    assert client.get(first.archive_key) == payload
    assert client.get(first.latest_receipt_pointer_key) == first.revision_id.encode(
        "ascii"
    )
    assert client.pttl(first.archive_key) > client.pttl(first.receipt_key) > 0
