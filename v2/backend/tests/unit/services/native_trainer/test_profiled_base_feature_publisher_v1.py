from __future__ import annotations

import json
from collections import Counter, namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli.v2_profiled_base_feature_publisher import (
    bounded_cycle_summary,
)
from v2.backend.app.services.native_trainer import (
    profiled_base_feature_publisher_v1 as publisher_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicCaptureValidationError,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    CanonicalOhlcvMultitimeframeCaptureSetV1Error,
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.profiled_base_feature_publisher_v1 import (
    BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL,
    DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    DISK_RESERVE_POLICY_V1,
    MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    ProfiledBaseFeaturePublisherV1,
    ProfiledBaseFeaturePublisherV1ConfigurationError,
    ProfiledBaseFeaturePublisherV1ResourceError,
    _singleton_writer_lock,
    adaptive_resource_decision_v1,
    least_recently_covered_symbols_v1,
    select_source_shard_index_v1,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    MAX_LEDGER_BYTES,
    TrainerSourceProvenanceLedgerV4DurabilityError,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_multitimeframe_capture_set_v1 as capture_support,
)

DiskUsage = namedtuple("DiskUsage", "total used free")
FIXED_CLOCK = datetime.now(UTC) - timedelta(seconds=2)


class _Pipeline:
    def __init__(self, owner: _Redis) -> None:
        self.owner = owner
        self.key: str | None = None

    def type(self, key: str) -> _Pipeline:
        self.key = key
        return self

    def getrange(self, key: str, _start: int, _end: int) -> _Pipeline:
        assert self.key == key
        return self

    def pttl(self, key: str) -> _Pipeline:
        assert self.key == key
        return self

    def time(self) -> _Pipeline:
        return self

    def execute(self) -> list[object]:
        assert self.key is not None
        self.owner.atomic_reads[self.key] += 1
        payload = self.owner.payloads[self.key]
        return [
            b"string",
            payload,
            600_000,
            (int(FIXED_CLOCK.timestamp()), FIXED_CLOCK.microsecond),
        ]

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Redis:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.atomic_reads: Counter[str] = Counter()
        self.scan_calls = 0

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return _Pipeline(self)

    def scan_iter(self, *, match: bytes, count: int):  # type: ignore[no-untyped-def]
        assert match.startswith(b"v2:market:ohlcv_closed:binance:")
        assert count > 0
        self.scan_calls += 1
        required_timeframe = match.decode("ascii").rsplit(":", 1)[1]
        yield from sorted(
            key.encode("ascii") for key in self.payloads if key.endswith(f":{required_timeframe}")
        )


class _Monotonic:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"


def _payloads(*, stale_5m: bool = False) -> dict[str, bytes]:
    latest_5m = capture_support._latest_open_ms("5m", decision=FIXED_CLOCK)
    if stale_5m:
        latest_5m -= TIMEFRAME_DURATION_MS["5m"]
    latest_1h = capture_support._latest_open_ms("1h", decision=FIXED_CLOCK)
    return {
        _key("BTCUSDT", "5m"): capture_support._payload(
            capture_support._rows("5m", latest_open_ms=latest_5m)
        ),
        _key("BTCUSDT", "1h"): capture_support._payload(
            capture_support._rows("1h", latest_open_ms=latest_1h)
        ),
    }


def _publisher(
    tmp_path: Path,
    redis_client: _Redis,
    *,
    state_name: str = "state.json",
    capture_function=capture_canonical_closed_ohlcv_atomic_receipts,  # type: ignore[no-untyped-def]
    capture_set_builder=build_canonical_ohlcv_multitimeframe_capture_set_v1,  # type: ignore[no-untyped-def]
) -> ProfiledBaseFeaturePublisherV1:
    return ProfiledBaseFeaturePublisherV1(
        redis_client=redis_client,
        data_root=(tmp_path / "publisher").absolute(),
        feature_ledger_path=(tmp_path / "feature-ledger.sqlite3").absolute(),
        state_path=(tmp_path / state_name).absolute(),
        status_path=(tmp_path / f"{state_name}.status").absolute(),
        cycle_period_seconds=300.0,
        boundary_retry_limit=2,
        clock=lambda: FIXED_CLOCK,
        monotonic=_Monotonic(),
        disk_usage=lambda _path: DiskUsage(10**12, 10**9, 10**12 - 10**9),
        capture_function=capture_function,
        capture_set_builder=capture_set_builder,
    )


def _seed_observed_state(path: Path) -> None:
    state = {
        "schema_version": "profiled_base_feature_publisher_state_v1",
        "coverage": {},
        "rotation_last_attempted_at": {},
        "observations": {
            "cycle_count": 1,
            "materialized_publication_count": 1,
            "materialized_publication_elapsed_seconds": 1.0,
            "materialized_publication_bytes": BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL,
        },
    }
    path.write_text(
        json.dumps(state, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )


def test_happy_path_publishes_only_authenticated_quarantined_base(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    publisher = _publisher(tmp_path, redis_client)

    status = publisher.run_cycle()

    assert status["classification"] == "CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED"
    assert status["discovered_symbols"] == ["BTCUSDT"]
    assert status["eligible_symbols"] == ["BTCUSDT"]
    assert status["selected_symbols"] == ["BTCUSDT"]
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["failed_symbols"] == []
    assert status["legacy_feature_redis_write_performed"] is False
    assert status["market_performance_thresholds_applied"] is False
    assert status["disk_resource_safety"]["policy"] == DISK_RESERVE_POLICY_V1
    assert status["disk_resource_safety"]["reserve_bytes"] == 200_000_000_000
    assert status["disk_resource_safety"]["operational_invariant_not_market_selection"] is True
    publication = status["publications"][0]
    assert publication["execution_time"] is None
    assert publication["available_at"] <= publication["decision_time"]
    assert publication["source_appends"][0]["durable_postcommit_readback_verified"] is True
    assert publication["source_appends"][1]["durable_postcommit_readback_verified"] is True
    assert publication["feature_append"]["transaction_committed"] is True
    assert publication["feature_append"]["transaction_readback_verified"] is True
    assert set(publication["authority"].values()) == {False}

    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    fixed = ledger.get_snapshot(publication["durable_snapshot_id"])
    assert fixed is not None
    envelope = fixed.record["frozen_envelope"]
    assert len(envelope["ordered_feature_names"]) == 35
    assert envelope["temporal_rejection_reasons"] == [
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
    ]
    assert envelope["strict_training_eligible"] is False
    lineage = envelope["source_lineage_material"]
    assert lineage["schema_version"] == "profiled_model_feature_snapshot_record_v1"
    assert lineage["physical_model_feature_count"] == 35
    assert set(lineage["authorization"].values()) == {False}


def test_missing_timeframe_is_ineligible_without_source_read(tmp_path: Path) -> None:
    payloads = _payloads()
    payloads.pop(_key("BTCUSDT", "1h"))
    redis_client = _Redis(payloads)

    status = _publisher(tmp_path, redis_client).run_cycle()

    assert status["classification"] == "NO_ELIGIBLE_SYMBOLS"
    assert status["eligible_symbols"] == []
    assert status["selected_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["missing_timeframes"] == ["1h"]
    assert redis_client.atomic_reads == Counter()


def test_stale_final_candle_retries_then_skips_without_feature_record(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads(stale_5m=True))

    status = _publisher(tmp_path, redis_client).run_cycle()

    assert status["classification"] == "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"
    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["boundary_or_finality_related"] is True
    assert redis_client.atomic_reads[_key("BTCUSDT", "5m")] == 2
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_boundary_race_recaptures_whole_pair_before_any_provenance_append(
    tmp_path: Path,
) -> None:
    calls = 0

    def boundary_once(**kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
                "canonical_ohlcv_multitimeframe_stale_or_unfinished_latest_candle"
            )
        return build_canonical_ohlcv_multitimeframe_capture_set_v1(**kwargs)

    redis_client = _Redis(_payloads())
    status = _publisher(
        tmp_path,
        redis_client,
        capture_set_builder=boundary_once,
    ).run_cycle()

    assert calls == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "5m")] == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "1h")] == 2
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["publications"][0]["boundary_attempts"] == 2
    assert len(status["publications"][0]["source_appends"]) == 2


def test_source_ledger_append_failure_prevents_transform_record_and_feature_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_append(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise TrainerSourceProvenanceLedgerV4DurabilityError(
            "source_provenance_v4_injected_append_failure"
        )

    monkeypatch.setattr(
        publisher_module.TrainerSourceProvenanceLedgerV4,
        "append_atomic_capture",
        fail_append,
    )
    status = _publisher(tmp_path, _Redis(_payloads())).run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["reasons"] == ["source_provenance_v4_injected_append_failure"]
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_one_symbol_failure_does_not_block_another_eligible_symbol(tmp_path: Path) -> None:
    payloads = _payloads()
    payloads[_key("AAAUSDT", "5m")] = payloads[_key("BTCUSDT", "5m")]
    payloads[_key("AAAUSDT", "1h")] = payloads[_key("BTCUSDT", "1h")]
    redis_client = _Redis(payloads)

    def selective_capture(*args: Any, expected_symbol: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        if expected_symbol == "AAAUSDT":
            raise CanonicalOhlcvAtomicCaptureValidationError(
                "canonical_ohlcv_injected_symbol_failure"
            )
        return capture_canonical_closed_ohlcv_atomic_receipts(
            *args,
            expected_symbol=expected_symbol,
            **kwargs,
        )

    _seed_observed_state(tmp_path / "state.json")
    status = _publisher(
        tmp_path,
        redis_client,
        capture_function=selective_capture,
    ).run_cycle()

    assert status["selected_symbols"] == ["AAAUSDT", "BTCUSDT"]
    assert status["failed_symbols"] == ["AAAUSDT"]
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["classification"] == "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"


def test_exact_duplicate_replay_is_idempotent_across_rotation_state_loss(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    first = _publisher(tmp_path, redis_client, state_name="state-one.json").run_cycle()
    second = _publisher(tmp_path, redis_client, state_name="state-two.json").run_cycle()

    first_publication = first["publications"][0]
    second_publication = second["publications"][0]
    assert first_publication["durable_snapshot_id"] == second_publication["durable_snapshot_id"]
    assert second_publication["classification"] == ("AUTHENTICATED_QUARANTINED_BASE_EXACT_REPLAY")
    assert second["exact_replay_symbols"] == ["BTCUSDT"]
    assert all(
        item["disposition"] == "EXACT_REPLAY" for item in second_publication["source_appends"]
    )
    assert second_publication["feature_append"]["total_unique_rows"] == 1


def test_unchanged_window_does_not_dilute_materialized_publication_observations(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    first = publisher.run_cycle()
    state_after_insert = json.loads((tmp_path / "state.json").read_text("ascii"))
    second = publisher.run_cycle()
    state_after_unchanged = json.loads((tmp_path / "state.json").read_text("ascii"))

    assert first["published_symbols"] == ["BTCUSDT"]
    assert second["unchanged_symbols"] == ["BTCUSDT"]
    assert state_after_unchanged["observations"] == state_after_insert["observations"] | {
        "cycle_count": state_after_insert["observations"]["cycle_count"] + 1
    }


def test_second_writer_fails_before_state_or_shard_selection(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    data_root = (tmp_path / "publisher").absolute()
    data_root.mkdir(mode=0o700, parents=True)

    with _singleton_writer_lock(data_root):
        with pytest.raises(ProfiledBaseFeaturePublisherV1ResourceError) as exc_info:
            publisher.run_cycle()

    assert exc_info.value.reasons == ("PROFILED_BASE_PUBLISHER_SINGLETON_WRITER_LOCK_CONTENDED",)
    assert not (tmp_path / "state.json").exists()
    assert not (data_root / "source-provenance-shards").exists()


def test_resource_rotation_and_source_sharding_are_evidence_derived() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=200,
        observations={
            "materialized_publication_count": 4,
            "materialized_publication_elapsed_seconds": 40.0,
            "materialized_publication_bytes": 20_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=316_000_000_000,
        disk_free_bytes=684_000_000_000,
    )
    assert decision.estimated_evidence_bytes_per_symbol == 5_000_000
    assert decision.estimated_seconds_per_symbol == 10.0
    assert decision.disk_reserve_policy == DISK_RESERVE_POLICY_V1
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.safe_disk_headroom_bytes == 484_000_000_000
    assert decision.selected_count == 3
    assert decision.bootstrap_observation_required is False
    assert least_recently_covered_symbols_v1(
        ("SOLUSDT", "BTCUSDT", "ETHUSDT"),
        {
            "BTCUSDT": {"last_published_at": "2026-07-21T12:00:00.000000Z"},
            "ETHUSDT": {"last_published_at": "2026-07-21T11:00:00.000000Z"},
        },
    ) == ("SOLUSDT", "ETHUSDT", "BTCUSDT")
    assert select_source_shard_index_v1(
        active_index=7,
        active_ledger_bytes=MAX_LEDGER_BYTES - 10,
        active_ledger_entries=20,
        projected_pair_bytes=11,
    ) == (8, True)


def test_large_universe_is_bounded_by_sustainable_cadence_disk_budget() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=160,
        observations={
            "materialized_publication_count": 10,
            "materialized_publication_elapsed_seconds": 10.0,
            "materialized_publication_bytes": 49_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=316_000_000_000,
        disk_free_bytes=684_000_000_000,
    )
    assert decision.selected_count < 160
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.selected_count == 3
    assert (
        decision.selected_count * decision.estimated_evidence_bytes_per_symbol
        <= decision.sustainable_cycle_write_budget_bytes
    )


def test_shared_filesystem_reserve_holds_when_free_space_is_at_reserve() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=160,
        observations={
            "materialized_publication_count": 10,
            "materialized_publication_elapsed_seconds": 10.0,
            "materialized_publication_bytes": 49_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=800_000_000_000,
        disk_free_bytes=200_000_000_000,
    )

    assert decision.disk_reserve_policy == DISK_RESERVE_POLICY_V1
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.safe_disk_headroom_bytes == 0
    assert decision.sustainable_cycle_write_budget_bytes == 0
    assert decision.disk_capacity_symbols == 0
    assert decision.selected_count == 0
    assert "RESOURCE_HEADROOM_NO_SAFE_PUBLICATION_UNIT" in decision.reasons


def test_two_observed_units_can_bind_shared_filesystem_reserve() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=1,
        observations={
            "materialized_publication_count": 1,
            "materialized_publication_elapsed_seconds": 1.0,
            "materialized_publication_bytes": 150_000_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=600_000_000_000,
        disk_free_bytes=400_000_000_000,
    )

    assert decision.estimated_evidence_bytes_per_symbol == 150_000_000_000
    assert decision.disk_reserve_bytes == 300_000_000_000
    assert decision.safe_disk_headroom_bytes == 100_000_000_000
    assert decision.selected_count == 0


def test_intra_cycle_backpressure_stops_after_observed_write_cost_jump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        _key(symbol, timeframe): b"unused-by-controller-test"
        for symbol in ("AAAUSDT", "BTCUSDT")
        for timeframe in ("5m", "1h")
    }
    _seed_observed_state(tmp_path / "state.json")
    publisher = _publisher(tmp_path, _Redis(payloads))
    disk_usage_calls = 0

    def counted_disk_usage(_path: Path) -> DiskUsage:
        nonlocal disk_usage_calls
        disk_usage_calls += 1
        return DiskUsage(10**12, 10**9, 10**12 - 10**9)

    publisher.disk_usage = counted_disk_usage

    def materialize_first_only(**kwargs: Any):  # type: ignore[no-untyped-def]
        symbol = kwargs["symbol"]
        coverage = {
            "last_published_at": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "feature_cutoff": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "decision_time": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "window_fingerprint_sha256": "a" * 64,
            "durable_snapshot_id": f"durable-{symbol}",
            "record_sha256": "b" * 64,
        }
        return publisher_module._SymbolOutcome(
            symbol=symbol,
            classification="AUTHENTICATED_QUARANTINED_BASE_INSERTED",
            window_fingerprint_sha256="a" * 64,
            materialized_evidence_bytes=50_000_000,
            detail={"symbol": symbol},
            coverage=coverage,
        )

    monkeypatch.setattr(publisher, "_publish_symbol", materialize_first_only)
    status = publisher.run_cycle()

    assert status["selected_symbols"] == ["AAAUSDT"]
    assert status["resource_deferred_symbols"] == ["BTCUSDT"]
    assert status["classification"] == "CYCLE_COMPLETE_RESOURCE_BACKPRESSURE_DEFERRED"
    assert disk_usage_calls == 4
    assert not hasattr(publisher, "_evidence_allocated_bytes")
    assert (
        status["cycle_evidence_accounted_bytes"]
        > status["resource_decision"]["sustainable_cycle_write_budget_bytes"]
    )


def test_short_resource_horizon_cannot_defeat_ninety_day_sustainability(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProfiledBaseFeaturePublisherV1ConfigurationError):
        adaptive_resource_decision_v1(
            eligible_count=160,
            observations={
                "materialized_publication_count": 0,
                "materialized_publication_elapsed_seconds": 0.0,
                "materialized_publication_bytes": 0,
            },
            cycle_period_seconds=300.0,
            resource_sustainability_horizon_seconds=1.0,
            disk_total_bytes=1_000_000_000_000,
            disk_used_bytes=316_000_000_000,
            disk_free_bytes=684_000_000_000,
        )
    with pytest.raises(ProfiledBaseFeaturePublisherV1ConfigurationError):
        ProfiledBaseFeaturePublisherV1(
            redis_client=_Redis(_payloads()),
            data_root=tmp_path / "data",
            feature_ledger_path=tmp_path / "feature-ledger.sqlite3",
            cycle_period_seconds=300.0,
            resource_sustainability_horizon_seconds=1.0,
        )


def test_cli_cycle_summary_stays_bounded_when_full_status_has_large_inventories(
    tmp_path: Path,
) -> None:
    status = {
        "classification": "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED",
        "cycle_started_at": "2026-07-21T12:00:00.000000Z",
        "cycle_completed_at": "2026-07-21T12:00:10.000000Z",
        "cycle_elapsed_seconds": 10.0,
        "discovered_symbol_count": 10_000,
        "eligible_symbol_count": 10_000,
        "selected_symbol_count": 5,
        "published_symbol_count": 4,
        "exact_replay_symbol_count": 0,
        "unchanged_symbol_count": 0,
        "failed_symbol_count": 1,
        "cycle_evidence_accounted_bytes": 20_000_000,
        "status_sha256": "a" * 64,
        "resource_decision": {
            "estimated_evidence_bytes_per_symbol": 5_000_000,
            "estimated_seconds_per_symbol": 2.0,
            "sustainable_cycle_write_budget_bytes": 25_000_000,
            "disk_reserve_policy": DISK_RESERVE_POLICY_V1,
            "disk_reserve_bytes": 200_000_000_000,
            "safe_disk_headroom_bytes": 484_000_000_000,
            "disk_capacity_symbols": 5,
            "publication_latency_capacity_symbols": 150,
            "bootstrap_observation_required": False,
        },
        "discovered_symbols": [f"SYMBOL{index}" for index in range(10_000)],
        "publications": [{"large": "x" * 10_000} for _ in range(100)],
        "failures": [{"large": "y" * 10_000} for _ in range(100)],
    }
    summary = bounded_cycle_summary(
        status,
        status_path=tmp_path / "full-status.json",
    )
    encoded = json.dumps(summary, separators=(",", ":"), sort_keys=True)
    assert len(encoded) < 2_048
    assert "discovered_symbols" not in summary
    assert "publications" not in summary
    assert "failures" not in summary
    assert summary["live_execution_authorized"] is False
