from __future__ import annotations

from collections.abc import Iterable

import pytest

from v2.backend.app.cli import v2_production_equivalence_comparator as subject


class CursorRedis:
    def __init__(self, pages: dict[int, tuple[int, Iterable[str | bytes]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[int, int]] = []

    def scan(self, *, cursor: int, count: int) -> tuple[int, Iterable[str | bytes]]:
        self.calls.append((cursor, count))
        return self.pages[cursor]


class EndlessCursorRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def scan(self, *, cursor: int, count: int) -> tuple[int, list[str]]:
        self.calls.append((cursor, count))
        return cursor + 1, [f"v2:orchestrator:decision:{cursor}"]


def _all_namespace_keys() -> list[str | bytes]:
    return [
        b"v2:market:prices:BTCUSDT",
        "v2:features:latest:BTCUSDT:1m",
        "v2:prediction:BTCUSDT:1m",
        "v2:trainer:status",
        "v2:orchestrator:decisions",
        "v2:signals:paper",
        "v2:paper:ledger",
        "v2:risk:decisions",
        "prediction:BTCUSDT:1m",
        "features:BTCUSDT:1m",
        "trainer:status",
        "signals:paper",
        "orchestrator:decisions",
        "market:prices:BTCUSDT",
        "unrelated:key",
    ]


def test_bounded_inventory_uses_one_shared_cursor_cycle() -> None:
    redis = CursorRedis(
        {
            0: (37, _all_namespace_keys()[:8]),
            37: (0, _all_namespace_keys()[8:]),
        }
    )

    result = subject._bounded_keyspace_inventory(
        redis,
        max_calls=10,
        max_seconds=10.0,
        count_hint=250,
        monotonic=lambda: 0.0,
    )

    assert redis.calls == [(0, 250), (37, 250)]
    assert result["scan"]["complete"] is True
    assert result["scan"]["stopped_reason"] == "CURSOR_CYCLE_COMPLETE"
    assert result["scan"]["count_classification"] == "COMPLETE_CURSOR_PASS"
    assert result["scan"]["keys_examined"] == 15
    assert result["v2_total_key_count"] == 8
    assert result["v2_namespace_counts"] == {
        namespace: 1 for namespace in subject.V2_NAMESPACES
    }
    assert result["legacy_namespace_counts"] == {
        namespace: 1 for namespace in subject.LEGACY_NAMESPACES
    }
    assert result["examples"]["v2_latest_orchestrator_keys"] == [
        "v2:orchestrator:decisions"
    ]


def test_bounded_inventory_stops_at_call_budget_and_labels_partial_pass() -> None:
    redis = EndlessCursorRedis()

    result = subject._bounded_keyspace_inventory(
        redis,
        max_calls=4,
        max_seconds=10.0,
        count_hint=1_000,
        monotonic=lambda: 0.0,
    )

    assert len(redis.calls) == 4
    assert result["scan"]["complete"] is False
    assert result["scan"]["stopped_reason"] == "CALL_BUDGET_EXHAUSTED"
    assert result["scan"]["count_classification"] == "PARTIAL_CURSOR_PASS"
    assert result["v2_namespace_counts"]["v2:orchestrator:"] == 4


def test_sparse_no_match_cursor_cycle_is_still_call_bounded() -> None:
    class SparseRedis(EndlessCursorRedis):
        def scan(self, *, cursor: int, count: int) -> tuple[int, list[str]]:
            self.calls.append((cursor, count))
            return cursor + 1, [f"unrelated:key:{cursor}"]

    redis = SparseRedis()

    result = subject._bounded_keyspace_inventory(
        redis,
        max_calls=3,
        max_seconds=10.0,
        monotonic=lambda: 0.0,
    )

    assert len(redis.calls) == 3
    assert result["scan"]["stopped_reason"] == "CALL_BUDGET_EXHAUSTED"
    assert result["v2_total_key_count"] == 0
    assert all(count == 0 for count in result["v2_namespace_counts"].values())


def test_bounded_inventory_stops_at_time_budget() -> None:
    redis = EndlessCursorRedis()
    clock_values = iter((0.0, 0.0, 2.0, 2.0))

    result = subject._bounded_keyspace_inventory(
        redis,
        max_calls=100,
        max_seconds=1.0,
        monotonic=lambda: next(clock_values),
    )

    assert len(redis.calls) == 1
    assert result["scan"]["complete"] is False
    assert result["scan"]["stopped_reason"] == "TIME_BUDGET_EXHAUSTED"


def test_repeated_cursor_fails_closed() -> None:
    redis = CursorRedis(
        {
            0: (19, ["v2:orchestrator:first"]),
            19: (19, ["v2:orchestrator:duplicate-cursor"]),
        }
    )

    result = subject._bounded_keyspace_inventory(
        redis,
        max_calls=10,
        max_seconds=10.0,
        monotonic=lambda: 0.0,
    )

    assert redis.calls == [
        (0, subject.REDIS_SCAN_COUNT_HINT),
        (19, subject.REDIS_SCAN_COUNT_HINT),
    ]
    assert result["scan"]["complete"] is False
    assert result["scan"]["stopped_reason"] == "CURSOR_REPEATED"
    assert result["scan"]["last_cursor"] == 19


@pytest.mark.parametrize(
    "invalid_cursor",
    (-1, True, 1.5, "not-a-cursor", subject.REDIS_SCAN_MAX_CURSOR + 1),
)
def test_invalid_cursor_fails_closed(invalid_cursor: object) -> None:
    class InvalidCursorRedis:
        def scan(self, *, cursor: int, count: int):
            return invalid_cursor, ["v2:orchestrator:first"]

    result = subject._bounded_keyspace_inventory(
        InvalidCursorRedis(),
        monotonic=lambda: 0.0,
    )

    assert result["scan"]["complete"] is False
    assert result["scan"]["stopped_reason"] == "INVALID_CURSOR"
    assert result["scan"]["count_classification"] == "PARTIAL_CURSOR_PASS"


def test_bounded_inventory_scan_error_is_truthful_and_incomplete() -> None:
    class BrokenRedis:
        def scan(self, *, cursor: int, count: int):
            raise ConnectionError("redis unavailable")

    result = subject._bounded_keyspace_inventory(
        BrokenRedis(),
        monotonic=lambda: 0.0,
    )

    assert result["scan"]["complete"] is False
    assert result["scan"]["stopped_reason"] == "SCAN_ERROR"
    assert result["scan"]["error_type"] == "ConnectionError"
    assert result["scan"]["calls"] == 1


def test_collect_observation_uses_one_inventory_pass(monkeypatch) -> None:
    redis = CursorRedis({0: (0, _all_namespace_keys())})
    monkeypatch.setattr(subject, "_process_running", lambda _pattern: True)

    observation = subject.collect_soak_observation(redis)

    assert redis.calls == [(0, subject.REDIS_SCAN_COUNT_HINT)]
    assert observation["schema_version"] == "v2_runtime_soak_observation_v2"
    assert observation["namespace_scan_cursor_cycle_complete"] is True
    assert observation["namespace_count_classification"] == "COMPLETE_CURSOR_PASS"
    assert observation["redis_keyspace_scan"]["calls"] == 1


def test_complete_inventory_limits_examples_but_counts_every_match() -> None:
    keys = [f"v2:orchestrator:decision:{index}" for index in range(5)]
    redis = CursorRedis({0: (0, keys)})

    result = subject._bounded_keyspace_inventory(
        redis,
        monotonic=lambda: 0.0,
    )

    assert result["v2_namespace_counts"]["v2:orchestrator:"] == 5
    assert result["examples"]["v2_latest_orchestrator_keys"] == keys[:3]
    assert result["scan"]["count_semantics"] == (
        "observed_matches_in_single_scan_cursor_cycle"
    )
    assert result["scan"]["counts_are_exact"] is False
    assert result["scan"]["counts_are_lower_bounds"] is False
    assert result["scan"]["point_in_time_snapshot"] is False


def test_incomplete_inventory_cannot_qualify_soak_readiness() -> None:
    namespace_counts = {namespace: 1 for namespace in subject.V2_NAMESPACES}
    observations = [
        {
            "schema_version": "v2_runtime_soak_observation_v2",
            "observed_utc": "2026-07-18T20:00:00Z",
            "v2_all_required_running": True,
            "v2_namespace_counts": namespace_counts,
            "redis_keyspace_scan": {"complete": True},
        },
        {
            "schema_version": "v2_runtime_soak_observation_v2",
            "observed_utc": "2026-07-18T21:00:00Z",
            "v2_all_required_running": True,
            "v2_namespace_counts": namespace_counts,
            "redis_keyspace_scan": {"complete": False},
        },
    ]

    status = subject.emit_soak_status(observations)

    assert status["redis_keyspace_scans_all_complete"] is False
    assert status["redis_keyspace_scan_incomplete_observation_count"] == 1
    assert status["v2_namespaces_never_empty"] is False
    assert status["soak_15m_ready"] is False
    assert status["soak_1h_ready"] is False


def test_historical_v1_completed_observations_remain_compatible() -> None:
    namespace_counts = {namespace: 1 for namespace in subject.V2_NAMESPACES}
    observations = [
        {
            "schema_version": "v2_runtime_soak_observation_v1",
            "observed_utc": "2026-07-18T20:00:00Z",
            "v2_all_required_running": True,
            "v2_namespace_counts": namespace_counts,
        },
        {
            "schema_version": "v2_runtime_soak_observation_v1",
            "observed_utc": "2026-07-18T21:00:00Z",
            "v2_all_required_running": True,
            "v2_namespace_counts": namespace_counts,
        },
    ]

    status = subject.emit_soak_status(observations)

    assert status["redis_keyspace_scans_all_complete"] is True
    assert status["redis_keyspace_scan_incomplete_observation_count"] == 0
    assert status["v2_namespaces_never_empty"] is True
    assert status["soak_1h_ready"] is True
