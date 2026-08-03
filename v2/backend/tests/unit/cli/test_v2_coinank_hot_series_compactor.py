from __future__ import annotations

import json
from dataclasses import fields

import pytest
import redis
from app.cli import v2_coinank_hot_series_compactor as compactor
from app.services.altdata.coinank_hot_series import MAX_HOT_SERIES_SOURCE_BYTES

SERIES_KEY = b"features:coinank:advanced:BTCUSDT:Binance:1h:series"
LATEST_KEY = b"features:coinank:advanced:BTCUSDT:Binance:1h:latest"


def _record(index: int, *, raw_size: int = 10) -> dict[str, object]:
    return {
        "ts_epoch_ms": 1_800_000_000_000 + index,
        "source_ts_ms": 1_800_000_000_000 + index,
        "endpoint": "orderFlow_lists",
        "family": "advanced",
        "baseCoin": "BTCUSDT",
        "exchange": "Binance",
        "interval": "1h",
        "coinank_metric": float(index),
        "raw_data": {"payload": "x" * raw_size},
        "request_parameters": {"symbol": "BTC"},
    }


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _key_pair(base_coin: str) -> tuple[bytes, bytes]:
    prefix = f"features:coinank:advanced:{base_coin}:Binance:1h".encode("ascii")
    return prefix + b":series", prefix + b":latest"


def _record_for(base_coin: str, index: int) -> dict[str, object]:
    return {**_record(index), "baseCoin": base_coin}


def _stored_scan_state(client: FakeRedis) -> dict[str, object]:
    decoded = json.loads(client.store[compactor.SCAN_STATE_KEY])
    assert isinstance(decoded, dict)
    return decoded


class FakeRedis:
    def __init__(
        self,
        store: dict[bytes, bytes],
        *,
        scan_keys: list[bytes] | None = None,
        scan_pages: dict[int, tuple[int, list[bytes]]] | None = None,
        ttl_ms: int = 90_000,
        conflicts_remaining: int = 0,
        conflict_value: bytes | None = None,
        key_types: dict[bytes, bytes] | None = None,
        fail_state_set_calls: set[int] | None = None,
    ) -> None:
        self.store = dict(store)
        self.scan_keys = list(scan_keys if scan_keys is not None else store)
        self.scan_pages = scan_pages or {0: (0, self.scan_keys)}
        self.ttls = {key: ttl_ms for key in store}
        self.versions = {key: 1 for key in store}
        self.conflicts_remaining = conflicts_remaining
        self.conflict_value = conflict_value
        self.key_types = {key: b"string" for key in store}
        self.key_types.update(key_types or {})
        self.fail_state_set_calls = set(fail_state_set_calls or ())
        self.state_set_calls = 0
        self.calls: list[tuple[str, bytes]] = []
        self.scan_arguments: list[tuple[int, bytes, int]] = []

    def scan(self, *, cursor: int, match: bytes, count: int) -> tuple[int, list[bytes]]:
        self.scan_arguments.append((cursor, match, count))
        return self.scan_pages.get(cursor, (0, []))

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is True
        return FakePipeline(self)

    def eval(self, script: str, numkeys: int, key: bytes, cap: int) -> list[object]:
        assert numkeys == 1
        assert "STRLEN" in script and "GETRANGE" in script
        self.calls.append(("state_eval", key))
        if key not in self.store:
            return [b"none", -2, 0, None]
        kind = self.key_types.get(key, b"string")
        if kind != b"string":
            return [kind, self.ttls.get(key, -1), 0, None]
        payload = self.store[key]
        if len(payload) > cap:
            return [kind, self.ttls.get(key, -1), len(payload), None]
        return [kind, self.ttls.get(key, -1), len(payload), payload]

    def set(self, key: bytes, value: bytes, *, px: int) -> bool:
        assert key == compactor.SCAN_STATE_KEY
        assert type(value) is bytes and 0 < len(value) <= compactor.MAX_SCAN_STATE_BYTES
        assert px == compactor.SCAN_STATE_TTL_MS
        self.state_set_calls += 1
        self.calls.append(("state_set", key))
        if self.state_set_calls in self.fail_state_set_calls:
            return False
        self.store[key] = value
        self.ttls[key] = px
        self.key_types[key] = b"string"
        return True


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self.client = client
        self.watched_versions: dict[bytes, int] = {}
        self.pending: tuple[bytes, bytes, bool, int | None] | None = None

    def watch(self, *keys: bytes) -> None:
        for key in keys:
            self.watched_versions[key] = self.client.versions.get(key, 0)

    def eval(self, script: str, numkeys: int, key: bytes, cap: int) -> list[object]:
        assert numkeys == 1
        assert "STRLEN" in script and "GETRANGE" in script
        self.client.calls.append(("pttl", key))
        if key not in self.client.store:
            return [b"none", -2, 0, None]
        kind = self.client.key_types.get(key, b"string")
        if kind != b"string":
            return [kind, self.client.ttls.get(key, -1), 0, None]
        self.client.calls.append(("strlen", key))
        payload = self.client.store[key]
        if len(payload) > cap:
            return [b"string", self.client.ttls.get(key, -1), len(payload), None]
        self.client.calls.append(("get", key))
        return [b"string", self.client.ttls.get(key, -1), len(payload), payload]

    def strlen(self, key: bytes) -> int:
        self.client.calls.append(("strlen", key))
        return len(self.client.store.get(key, b""))

    def pttl(self, key: bytes) -> int:
        self.client.calls.append(("pttl", key))
        return self.client.ttls.get(key, -2)

    def get(self, key: bytes) -> bytes | None:
        self.client.calls.append(("get", key))
        return self.client.store.get(key)

    def multi(self) -> None:
        return None

    def set(
        self,
        key: bytes,
        value: bytes,
        *,
        keepttl: bool = False,
        px: int | None = None,
    ) -> None:
        assert keepttl is not (px is not None)
        self.pending = (key, value, keepttl, px)

    def execute(self) -> list[bool]:
        assert self.pending is not None
        series_key = self.pending[0]
        if self.client.conflicts_remaining:
            self.client.conflicts_remaining -= 1
            assert self.client.conflict_value is not None
            self.client.store[series_key] = self.client.conflict_value
            self.client.versions[series_key] = self.client.versions.get(series_key, 0) + 1
        if any(
            self.client.versions.get(key, 0) != version
            for key, version in self.watched_versions.items()
        ):
            raise redis.WatchError("simulated concurrent writer")
        key, value, keep_ttl, px = self.pending
        previous_ttl = self.client.ttls.get(key, -1)
        self.client.store[key] = value
        self.client.key_types[key] = b"string"
        self.client.ttls[key] = previous_ttl if keep_ttl else int(px or 0)
        self.client.versions[key] = self.client.versions.get(key, 0) + 1
        return [True]

    def reset(self) -> None:
        self.pending = None


def test_exact_key_filter_ttl_and_latest_raw_nonmutation() -> None:
    series_raw = _json_bytes([_record(1), _record(2)])
    latest_raw = _json_bytes(_record(2))
    inexact_keys = [
        b"features:coinank_endpoint:advanced:BTCUSDT:Binance:1h:series",
        b"features:coinank:advanced:BTCUSDT:Binance:1h:extra:series",
        b"features:coinank:advanced:BTCUSDT:Binance:1h:latest",
    ]
    untouched = {
        inexact_keys[0]: b"unchanged-endpoint",
        inexact_keys[1]: b"unchanged-extra-component",
        inexact_keys[2]: latest_raw,
    }
    client = FakeRedis(
        {SERIES_KEY: series_raw, **untouched},
        scan_keys=[*inexact_keys, SERIES_KEY],
        ttl_ms=42_000,
    )

    status = compactor.run_compaction(client)

    assert client.scan_arguments == [(0, compactor.SERIES_SCAN_MATCH, compactor.SCAN_COUNT)]
    assert status.scanned_key_count == 4
    assert status.exact_key_count == 1
    assert status.compacted_key_count == 1
    assert status.rebuilt_key_count == 0
    assert client.ttls[SERIES_KEY] == 42_000
    assert status.expiring_write_count == 1
    assert status.key_results[0].ttl_policy == "PRESERVE_POSITIVE_EXPIRING_TTL"
    assert status.key_results[0].applied_ttl_ms == 42_000
    assert status.key_results[0].output_expiring is True
    assert client.store[LATEST_KEY] == latest_raw
    assert all(client.store[key] == value for key, value in untouched.items())
    assert ("strlen", SERIES_KEY) in client.calls
    assert client.calls.index(("strlen", SERIES_KEY)) < client.calls.index(("get", SERIES_KEY))
    assert ("get", LATEST_KEY) not in client.calls
    stored = json.loads(client.store[SERIES_KEY])
    assert all("raw_data" not in row and "request_parameters" not in row for row in stored)
    assert status.publication_authority is False
    assert status.actual_consumption is False
    assert status.trainer_admission_granted is False
    assert status.admitted_feature_count == 0
    assert status.available_at is None
    assert status.zero_filled_field_count == 0


def test_oversized_series_is_never_get_and_rebuilds_from_bounded_latest() -> None:
    oversized = b"x" * (MAX_HOT_SERIES_SOURCE_BYTES + 1)
    latest_raw = _json_bytes(_record(7, raw_size=1_000))
    client = FakeRedis({SERIES_KEY: oversized, LATEST_KEY: latest_raw}, ttl_ms=71_000)

    status = compactor.run_compaction(client)

    result = status.key_results[0]
    assert result.outcome == "rebuilt_oversized"
    assert result.series_get_performed is False
    assert result.latest_get_performed is True
    assert ("strlen", SERIES_KEY) in client.calls
    assert ("get", SERIES_KEY) not in client.calls
    assert ("strlen", LATEST_KEY) in client.calls
    assert ("get", LATEST_KEY) in client.calls
    assert client.store[LATEST_KEY] == latest_raw
    assert client.ttls[SERIES_KEY] == 71_000
    stored = json.loads(client.store[SERIES_KEY])
    assert len(stored) == 1
    assert stored[0]["coinank_metric"] == 7.0
    assert stored[0]["hot_series_reset_reason"] == (
        "OVERSIZED_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST"
    )


def test_watch_conflict_retries_against_newer_exact_raw_value() -> None:
    original = _json_bytes([_record(1)])
    concurrent = _json_bytes([_record(1), _record(2)])
    latest_raw = _json_bytes(_record(2))
    client = FakeRedis(
        {SERIES_KEY: original, LATEST_KEY: latest_raw},
        ttl_ms=33_000,
        conflicts_remaining=1,
        conflict_value=concurrent,
    )

    status = compactor.run_compaction(client)

    result = status.key_results[0]
    assert result.outcome == "compacted"
    assert result.attempts == 2
    assert result.exact_raw_cas_guarded is True
    assert client.ttls[SERIES_KEY] == 33_000
    stored = json.loads(client.store[SERIES_KEY])
    assert [row["coinank_metric"] for row in stored] == [1.0, 2.0]


def test_persistent_or_zero_ttl_is_replaced_with_positive_resource_ttl() -> None:
    for source_pttl in (-1, 0):
        client = FakeRedis(
            {SERIES_KEY: _json_bytes([_record(1)]), LATEST_KEY: _json_bytes(_record(1))},
            ttl_ms=source_pttl,
        )

        status = compactor.run_compaction(client)

        result = status.key_results[0]
        assert result.previous_pttl_ms == source_pttl
        assert result.ttl_policy == "RESTORE_RESOURCE_CONTROL_EXPIRING_TTL"
        assert result.applied_ttl_ms == compactor.RESTORED_HOT_SERIES_TTL_MS
        assert result.output_expiring is True
        assert client.ttls[SERIES_KEY] == compactor.RESTORED_HOT_SERIES_TTL_MS


def test_persistent_watch_conflict_never_overwrites_concurrent_value() -> None:
    original = _json_bytes([_record(1)])
    concurrent = _json_bytes([_record(9)])
    client = FakeRedis(
        {SERIES_KEY: original, LATEST_KEY: _json_bytes(_record(9))},
        conflicts_remaining=compactor.MAX_CAS_RETRIES,
        conflict_value=concurrent,
    )

    status = compactor.run_compaction(client)

    assert status.cas_conflict_count == 1
    assert status.key_results[0].outcome == "cas_conflict"
    assert client.store[SERIES_KEY] == concurrent


def test_invalid_duplicate_series_rebuilds_without_mutating_latest() -> None:
    invalid = b'[{"ts_epoch_ms":1,"ts_epoch_ms":2}]'
    latest_raw = _json_bytes(_record(4))
    client = FakeRedis({SERIES_KEY: invalid, LATEST_KEY: latest_raw})

    status = compactor.run_compaction(client)

    assert status.key_results[0].outcome == "rebuilt_invalid"
    assert client.store[LATEST_KEY] == latest_raw
    stored = json.loads(client.store[SERIES_KEY])
    assert [row["coinank_metric"] for row in stored] == [4.0]


def test_identity_mismatch_in_any_series_row_rebuilds_only_from_exact_latest() -> None:
    mismatched = {**_record(1), "exchange": "OtherExchange"}
    current = _record(2)
    latest_raw = _json_bytes(_record(3))
    original_series = _json_bytes([mismatched, current])
    client = FakeRedis({SERIES_KEY: original_series, LATEST_KEY: latest_raw})

    status = compactor.run_compaction(client)

    result = status.key_results[0]
    assert result.outcome == "rebuilt_invalid"
    assert result.latest_get_performed is True
    assert client.store[LATEST_KEY] == latest_raw
    stored = json.loads(client.store[SERIES_KEY])
    assert [row["coinank_metric"] for row in stored] == [3.0]
    assert stored[0]["hot_series_reset_reason"] == (
        "IDENTITY_MISMATCH_HOT_CACHE_REBUILT_FROM_LATEST"
    )


@pytest.mark.parametrize(
    "records",
    (
        [_record(2), _record(1)],
        [_record(1), _record(1)],
    ),
)
def test_non_monotonic_series_rebuilds_only_from_exact_latest(
    records: list[dict[str, object]],
) -> None:
    latest_raw = _json_bytes(_record(4))
    client = FakeRedis({SERIES_KEY: _json_bytes(records), LATEST_KEY: latest_raw})

    status = compactor.run_compaction(client)

    assert status.key_results[0].outcome == "rebuilt_invalid"
    assert client.store[LATEST_KEY] == latest_raw
    stored = json.loads(client.store[SERIES_KEY])
    assert [row["coinank_metric"] for row in stored] == [4.0]
    assert stored[0]["hot_series_reset_reason"] == ("NON_MONOTONIC_HOT_CACHE_REBUILT_FROM_LATEST")


def test_per_run_byte_bound_stops_before_get_or_write() -> None:
    series_raw = _json_bytes([_record(1)])
    latest_raw = _json_bytes(_record(1))
    client = FakeRedis({SERIES_KEY: series_raw, LATEST_KEY: latest_raw})

    status = compactor.run_compaction(client, max_bytes_read=1)

    assert status.stop_reason == "coinank_hot_series_byte_budget_exhausted"
    assert status.skipped_key_count == 1
    assert ("strlen", SERIES_KEY) in client.calls
    assert ("get", SERIES_KEY) not in client.calls
    assert client.store[SERIES_KEY] == series_raw
    assert client.store[LATEST_KEY] == latest_raw


def test_per_run_time_bound_stops_before_key_read_or_write() -> None:
    series_raw = _json_bytes([_record(1)])
    client = FakeRedis({SERIES_KEY: series_raw, LATEST_KEY: _json_bytes(_record(1))})
    timestamps = iter((0.0, compactor.MAX_RUNTIME_SECONDS + 1.0, 50.0))

    status = compactor.run_compaction(client, clock=lambda: next(timestamps))

    assert status.stop_reason == "coinank_hot_series_runtime_budget_exhausted"
    assert all(key not in {SERIES_KEY, LATEST_KEY} for _operation, key in client.calls)
    assert client.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS
    assert client.store[SERIES_KEY] == series_raw


def test_empty_scan_page_checks_deadline_before_requesting_another_page() -> None:
    client = FakeRedis({}, scan_pages={0: (17, []), 17: (0, [])})
    timestamps = iter((0.0, 0.0, compactor.MAX_RUNTIME_SECONDS + 1.0, 50.0))

    status = compactor.run_compaction(client, clock=lambda: next(timestamps))

    assert status.stop_reason == "coinank_hot_series_runtime_budget_exhausted"
    assert status.scan_page_count == 1
    assert client.scan_arguments == [(0, compactor.SERIES_SCAN_MATCH, compactor.SCAN_COUNT)]


def test_scan_page_and_cursor_are_explicitly_bounded() -> None:
    too_wide = [b"not-an-exact-key"] * (compactor.MAX_SCAN_PAGE_KEYS + 1)
    client = FakeRedis({}, scan_pages={0: (1, too_wide)})

    status = compactor.run_compaction(client)

    assert status.stop_reason == "coinank_hot_series_scan_page_key_bound_exceeded"
    assert status.scan_page_count == 1
    assert status.exact_key_count == 0


def test_scan_page_count_is_bounded_when_empty_cursor_never_terminates() -> None:
    pages: dict[int, tuple[int, list[bytes]]] = {
        cursor: (cursor + 1, []) for cursor in range(compactor.MAX_SCAN_PAGES_PER_RUN * 2)
    }
    client = FakeRedis({}, scan_pages=pages)

    first = compactor.run_compaction(client)
    second = compactor.run_compaction(client)

    assert first.stop_reason == "coinank_hot_series_scan_page_bound_exhausted"
    assert second.stop_reason == "coinank_hot_series_scan_page_bound_exhausted"
    assert first.scan_page_count == second.scan_page_count == compactor.MAX_SCAN_PAGES_PER_RUN
    assert first.scan_start_cursor == 0
    assert first.scan_end_cursor == compactor.MAX_SCAN_PAGES_PER_RUN
    assert second.scan_start_cursor == compactor.MAX_SCAN_PAGES_PER_RUN
    assert second.scan_end_cursor == compactor.MAX_SCAN_PAGES_PER_RUN * 2
    assert client.scan_arguments[compactor.MAX_SCAN_PAGES_PER_RUN][0] == (
        compactor.MAX_SCAN_PAGES_PER_RUN
    )


def test_runtime_scale_606_page_cycle_eventually_reaches_late_exact_key() -> None:
    page_count = 606
    pages = {cursor: (cursor + 1, []) for cursor in range(page_count - 1)}
    pages[page_count - 1] = (0, [SERIES_KEY])
    client = FakeRedis(
        {SERIES_KEY: _json_bytes([_record(1)]), LATEST_KEY: _json_bytes(_record(1))},
        scan_pages=pages,
    )

    statuses = [compactor.run_compaction(client) for _ in range(10)]

    assert [cursor for cursor, _match, _count in client.scan_arguments] == list(range(page_count))
    assert sum(status.compacted_key_count for status in statuses) == 1
    assert statuses[-1].scan_cycle_completed is True
    assert statuses[-1].scan_end_cursor == 0
    assert client.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS


def test_cursor_and_pending_page_continue_across_timer_runs_without_key_loss() -> None:
    btc_series, btc_latest = _key_pair("BTCUSDT")
    eth_series, eth_latest = _key_pair("ETHUSDT")
    sol_series, sol_latest = _key_pair("SOLUSDT")
    client = FakeRedis(
        {
            btc_series: _json_bytes([_record_for("BTCUSDT", 1)]),
            btc_latest: _json_bytes(_record_for("BTCUSDT", 1)),
            eth_series: _json_bytes([_record_for("ETHUSDT", 1)]),
            eth_latest: _json_bytes(_record_for("ETHUSDT", 1)),
            sol_series: _json_bytes([_record_for("SOLUSDT", 1)]),
            sol_latest: _json_bytes(_record_for("SOLUSDT", 1)),
        },
        scan_pages={
            0: (11, [btc_series]),
            11: (22, [eth_series]),
            22: (0, [sol_series]),
        },
    )

    first = compactor.run_compaction(client, max_keys=1)
    second = compactor.run_compaction(client, max_keys=1)
    third = compactor.run_compaction(client, max_keys=1)

    assert [result.key for result in first.key_results] == [btc_series.decode("ascii")]
    assert [result.key for result in second.key_results] == [eth_series.decode("ascii")]
    assert [result.key for result in third.key_results] == [sol_series.decode("ascii")]
    assert first.pending_end_key_count == 1
    assert second.pending_start_key_count == 1
    assert third.pending_start_key_count == 1
    assert third.scan_cycle_completed is True
    assert [cursor for cursor, _match, _count in client.scan_arguments] == [0, 11, 22]
    assert client.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS


def test_mid_page_key_and_byte_budget_resume_the_unprocessed_offset() -> None:
    eth_series, eth_latest = _key_pair("ETHUSDT")
    btc_raw = _json_bytes([_record(1)])
    eth_raw = _json_bytes([_record_for("ETHUSDT", 1)])
    client = FakeRedis(
        {
            SERIES_KEY: btc_raw,
            LATEST_KEY: _json_bytes(_record(1)),
            eth_series: eth_raw,
            eth_latest: _json_bytes(_record_for("ETHUSDT", 1)),
        },
        scan_pages={0: (0, [SERIES_KEY, eth_series])},
    )

    key_limited = compactor.run_compaction(client, max_keys=1)
    assert key_limited.stop_reason == "coinank_hot_series_key_budget_exhausted"
    assert key_limited.pending_end_key_count == 1
    assert _stored_scan_state(client)["pending_offset"] == 1

    resumed = compactor.run_compaction(client)
    assert resumed.pending_start_key_count == 1
    assert [result.key for result in resumed.key_results] == [eth_series.decode("ascii")]
    assert resumed.scan_cycle_completed is True

    byte_client = FakeRedis(
        {
            SERIES_KEY: btc_raw,
            LATEST_KEY: _json_bytes(_record(1)),
            eth_series: eth_raw,
            eth_latest: _json_bytes(_record_for("ETHUSDT", 1)),
        },
        scan_pages={0: (0, [SERIES_KEY, eth_series])},
    )
    byte_limited = compactor.run_compaction(byte_client, max_bytes_read=len(btc_raw))
    assert byte_limited.stop_reason == "coinank_hot_series_byte_budget_exhausted"
    assert byte_limited.pending_end_key_count == 1
    assert _stored_scan_state(byte_client)["pending_offset"] == 1
    byte_resumed = compactor.run_compaction(byte_client)
    assert byte_resumed.pending_start_key_count == 1
    assert [result.key for result in byte_resumed.key_results] == [eth_series.decode("ascii")]

    time_client = FakeRedis(
        {
            SERIES_KEY: btc_raw,
            LATEST_KEY: _json_bytes(_record(1)),
            eth_series: eth_raw,
            eth_latest: _json_bytes(_record_for("ETHUSDT", 1)),
        },
        scan_pages={0: (0, [SERIES_KEY, eth_series])},
    )
    clock_calls = 0

    def expire_after_first_key() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls <= 8 else compactor.MAX_RUNTIME_SECONDS + 1.0

    time_limited = compactor.run_compaction(time_client, clock=expire_after_first_key)
    assert time_limited.stop_reason == "coinank_hot_series_runtime_budget_exhausted"
    assert time_limited.pending_end_key_count == 1
    assert _stored_scan_state(time_client)["pending_offset"] == 1
    time_resumed = compactor.run_compaction(time_client)
    assert time_resumed.pending_start_key_count == 1
    assert [result.key for result in time_resumed.key_results] == [eth_series.decode("ascii")]


def test_corrupt_wrong_type_oversized_and_nonexpiring_scan_state_reset_truthfully() -> None:
    corrupt_cases = (
        (b"not-json", {}, "INVALID_SCAN_STATE_RESET"),
        (b"wrong-type", {compactor.SCAN_STATE_KEY: b"hash"}, "WRONG_TYPE_SCAN_STATE_RESET"),
        (
            b"x" * (compactor.MAX_SCAN_STATE_BYTES + 1),
            {},
            "OVERSIZED_SCAN_STATE_RESET",
        ),
    )
    for raw_state, key_types, expected_reason in corrupt_cases:
        client = FakeRedis(
            {
                SERIES_KEY: _json_bytes([_record(1)]),
                LATEST_KEY: _json_bytes(_record(1)),
                compactor.SCAN_STATE_KEY: raw_state,
            },
            scan_keys=[SERIES_KEY],
            key_types=key_types,
        )

        status = compactor.run_compaction(client)

        assert status.scan_state_load_outcome == "RESET_INVALID_STATE"
        assert status.scan_state_reset_reason == expected_reason
        assert status.compacted_key_count == 1
        assert client.key_types[compactor.SCAN_STATE_KEY] == b"string"
        assert client.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS
        assert len(client.store[compactor.SCAN_STATE_KEY]) <= compactor.MAX_SCAN_STATE_BYTES

    nonexpiring = FakeRedis({})
    compactor.run_compaction(nonexpiring)
    nonexpiring.ttls[compactor.SCAN_STATE_KEY] = -1
    status = compactor.run_compaction(nonexpiring)
    assert status.scan_state_reset_reason == "NONEXPIRING_SCAN_STATE_RESET"
    assert nonexpiring.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS


def test_repeated_scan_keys_are_deduplicated_within_persistent_cycle() -> None:
    client = FakeRedis(
        {SERIES_KEY: _json_bytes([_record(1)]), LATEST_KEY: _json_bytes(_record(1))},
        scan_pages={0: (9, [SERIES_KEY, SERIES_KEY]), 9: (0, [SERIES_KEY])},
    )

    status = compactor.run_compaction(client)

    assert status.exact_key_count == 1
    assert status.deduplicated_key_count == 2
    assert status.scan_cycle_completed is True
    assert client.versions[SERIES_KEY] == 2


def test_state_write_interruption_retries_pending_key_without_losing_latest_or_cas() -> None:
    latest_raw = _json_bytes(_record(1))
    client = FakeRedis(
        {SERIES_KEY: _json_bytes([_record(1)]), LATEST_KEY: latest_raw},
        scan_pages={0: (0, [SERIES_KEY])},
        fail_state_set_calls={3},
    )

    interrupted = compactor.run_compaction(client)

    assert interrupted.stop_reason == "coinank_hot_series_scan_state_write_not_acknowledged"
    assert interrupted.scan_state_persisted is False
    assert _stored_scan_state(client)["pending_offset"] == 0
    first_series_write_version = client.versions[SERIES_KEY]
    assert client.store[LATEST_KEY] == latest_raw

    retried = compactor.run_compaction(client)

    assert retried.pending_start_key_count == 1
    assert retried.compacted_key_count == 1
    assert retried.scan_cycle_completed is True
    assert client.versions[SERIES_KEY] == first_series_write_version + 1
    assert client.store[LATEST_KEY] == latest_raw


def test_scan_state_schema_is_closed_expiring_and_non_authoritative() -> None:
    client = FakeRedis({})

    status = compactor.run_compaction(client)
    state = _stored_scan_state(client)

    assert status.scan_state_persisted is True
    assert client.ttls[compactor.SCAN_STATE_KEY] == compactor.SCAN_STATE_TTL_MS
    assert set(state) == compactor._SCAN_STATE_FIELDS
    assert state["role"] == compactor.SCAN_STATE_ROLE
    assert state["available_at"] is None
    assert state["admitted_feature_count"] == 0
    assert state["zero_filled_field_count"] == 0
    assert state["no_zero_fill_for_unknown_fields"] is True
    assert all(state[field] is False for field in compactor._SCAN_STATE_FALSE_FIELDS)


def test_status_dataclasses_do_not_accept_authority_constructor_overrides() -> None:
    key_fields = {item.name: item.init for item in fields(compactor.KeyCompactionStatus)}
    run_fields = {item.name: item.init for item in fields(compactor.RunCompactionStatus)}

    assert key_fields["publication_authority"] is False
    assert key_fields["trainer_admission_granted"] is False
    assert run_fields["live_authority"] is False
