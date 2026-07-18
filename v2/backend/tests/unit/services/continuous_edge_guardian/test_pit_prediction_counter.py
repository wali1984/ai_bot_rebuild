from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools import guardian_pit_prediction_counter as pit_counter_cli
from v2.backend.app.services import (
    all_timeframe_prediction_signal_price_target_publisher as publisher,
)
from v2.backend.app.services.continuous_edge_guardian import (
    pit_prediction_counter as pit_counter_module,
)
from v2.backend.app.services.continuous_edge_guardian.pit_prediction_counter import (
    GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY,
    REDIS_HOT_CACHE_OBSERVATION_KEY,
    blocker_projection,
    collect_hot_cache_prediction_rows,
    collect_prediction_rows,
    consume_durable_guardian_pit_archive,
    coverage_status,
    dedupe_new_records,
    dedupe_records,
    guardian_pit_archive_consumption_status,
    guardian_pit_archive_record_id,
    read_jsonl,
    update_holdout_manifest,
)
from v2.backend.app.services.durable_paper_evidence_archive import (
    ArchiveCandidate,
    DurablePaperEvidenceArchive,
)


class FakeRedis:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str) -> str | None:
        payload = self.payloads.get(key)
        if payload is None:
            return None
        return json.dumps(payload)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        rows = self.lists.get(key, [])
        if start < 0:
            start = max(0, len(rows) + start)
        if end < 0:
            end = len(rows) + end
        return rows[start : end + 1]


def _prediction(**overrides):
    row = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "hold",
        "feature_cutoff": "2026-07-09T18:44:59.999Z",
        "available_at": "2026-07-09T18:45:20.000Z",
        "decision_time": "2026-07-09T18:48:10.000Z",
        "generated_at": "2026-07-09T18:48:10.000Z",
        "future_labels_used_as_features": False,
    }
    row.update(overrides)
    return row


def _archive_payload(index: int, **overrides) -> dict:
    decision = datetime(2026, 7, 9, 20, 40, tzinfo=UTC) + timedelta(minutes=index)
    feature_cutoff = decision - timedelta(milliseconds=1)
    row = {
        "schema_version": "v2_guardian_pit_prediction_observation_append_v1",
        "producer": "v2_all_timeframe_prediction_signal_price_target_publisher",
        "source": "all_timeframe_prediction_signal_price_target_publisher",
        "source_redis_key": f"v2:prediction:COIN{index}USDT:1m",
        "prediction_id": f"archive-pred-{index}",
        "symbol": f"COIN{index}USDT",
        "timeframe": "1m",
        "selected_action": ("long", "short", "hold")[index % 3],
        "decision_time": decision.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "feature_cutoff": feature_cutoff.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "available_at": feature_cutoff.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "candle_close_time": feature_cutoff.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "candle_closed_confirmed": True,
        "generated_at": decision.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "feature_vector_hash": f"feature-hash-{index}",
        "future_labels_used_as_features": False,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "places_real_order": False,
        "routes_to_live": False,
        "test_order_submitted": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    }
    row.update(overrides)
    return row


def _write_source_archive(
    path: Path,
    payloads: list[dict],
    *,
    migration_complete: bool = True,
) -> DurablePaperEvidenceArchive:
    archive = DurablePaperEvidenceArchive(
        path,
        stream_id="v2_guardian_pit_prediction_observations_unique_v1",
    )
    candidates = []
    for payload in payloads:
        record_id = guardian_pit_archive_record_id(payload)
        candidate = publisher._guardian_pit_archive_candidate(payload)
        assert candidate.record_id == record_id
        candidates.append(candidate)
    result = archive.append_unique(candidates)
    assert result.identity_conflicts == 0
    archive.set_metadata("redis_legacy_migration_cursor", "0")
    archive.set_metadata("redis_legacy_migration_observed_length", "0")
    archive.set_metadata(
        "redis_legacy_migration_complete",
        "true" if migration_complete else "false",
    )
    return archive


def test_collect_prediction_rows_counts_only_pit_valid_predictions() -> None:
    client = FakeRedis({"v2:prediction:BTCUSDT:1m": _prediction()})

    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))

    assert rejected == []
    assert len(valid) == 1
    assert valid[0]["selected_policy_action"] == "NO_TRADE"
    assert valid[0]["feature_cutoff_before_or_at_decision_time"] is True
    assert valid[0]["counts_as_a_grade_evidence"] is False
    assert valid[0]["counts_as_a_plus"] is False


def test_collect_prediction_rows_rejects_future_leaking_predictions() -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": _prediction(
                feature_cutoff="2026-07-09T18:50:00.000Z",
                future_labels_used_as_features=True,
            )
        }
    )

    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))

    assert valid == []
    reasons = set(rejected[0]["reasons"])
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME" in reasons
    assert "FUTURE_LABELS_USED_AS_FEATURES" in reasons


def test_coverage_status_dedupes_and_projects_remaining_predictions(tmp_path) -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": _prediction(),
            "v2:prediction:ETHUSDT:1m": _prediction(prediction_id="pred_2", symbol="ETHUSDT", selected_action="long"),
        }
    )
    valid, rejected = collect_prediction_rows(client, symbols=["BTCUSDT", "ETHUSDT"], timeframes=("1m",))
    new_rows = dedupe_new_records([], valid)
    status = coverage_status(
        archive_rows=new_rows,
        current_valid_rows=valid,
        rejected_rows=rejected,
        new_rows_appended=len(new_rows),
        generated_utc="2026-07-09T18:50:00.000Z",
    )
    projection = blocker_projection(status, generated_utc="2026-07-09T18:50:00.000Z")

    assert status["point_in_time_valid_prediction_count"] == 2
    assert status["selected_policy_action_counts"]["NO_TRADE"] == 1
    assert status["selected_policy_action_counts"]["LONG"] == 1
    assert status["counts_as_a_grade_evidence"] is False
    assert projection["exact_blocker"] == "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"

    manifest_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl.manifest.json"
    manifest = update_holdout_manifest(manifest_path, status, generated_utc="2026-07-09T18:50:00.000Z")
    assert manifest["holdout_prediction_coverage_status"]["point_in_time_valid_prediction_count"] == 2
    assert manifest["counts_as_a_grade_evidence"] is False


def test_cli_default_symbols_unions_positive_summary_with_runtime_universe(monkeypatch) -> None:
    class SummaryRedis:
        def get(self, key: str) -> str | None:
            if key == "v2:strategy_supply:latest_positive_summary":
                return json.dumps({"positive_symbols": ["BTCUSDT", "ETHUSDT"]})
            return None

    from v2.backend.app.services import v2_symbol_runtime_universe

    monkeypatch.setattr(
        v2_symbol_runtime_universe,
        "resolve_symbols",
        lambda: ["ETHUSDT", "NEARUSDT", "PAXGUSDT"],
    )

    assert pit_counter_cli._default_symbols(SummaryRedis()) == [
        "BTCUSDT",
        "ETHUSDT",
        "NEARUSDT",
        "PAXGUSDT",
    ]


def test_hot_cache_prediction_rows_are_collected_and_deduped_with_latest_keys() -> None:
    client = FakeRedis({"v2:prediction:BTCUSDT:1m": _prediction()})
    client.lists[REDIS_HOT_CACHE_OBSERVATION_KEY] = [
        json.dumps(
            {
                "prediction_id": "pred_1",
                "source_redis_key": "v2:prediction:BTCUSDT:1m",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "selected_action": "hold",
                "feature_cutoff": "2026-07-09T18:44:59.999Z",
                "available_at": "2026-07-09T18:45:20.000Z",
                "decision_time": "2026-07-09T18:48:10.000Z",
                "generated_at": "2026-07-09T18:48:10.000Z",
                "future_labels_used_as_features": False,
                "counts_as_a_grade_evidence": False,
                "counts_as_a_plus": False,
            }
        ),
        json.dumps(
            {
                "prediction_id": "pred_3",
                "source_redis_key": "v2:prediction:ETHUSDT:1m",
                "symbol": "ETHUSDT",
                "timeframe": "1m",
                "selected_action": "short",
                "feature_cutoff": "2026-07-09T18:44:59.999Z",
                "available_at": "2026-07-09T18:45:20.000Z",
                "decision_time": "2026-07-09T18:48:10.000Z",
                "generated_at": "2026-07-09T18:48:10.000Z",
                "future_labels_used_as_features": False,
                "counts_as_a_grade_evidence": False,
                "counts_as_a_plus": False,
            }
        ),
    ]

    latest, latest_rejected = collect_prediction_rows(client, symbols=["BTCUSDT"], timeframes=("1m",))
    cached, cache_rejected = collect_hot_cache_prediction_rows(client, timeframes=("1m",))
    combined = dedupe_records([*latest, *cached])

    assert latest_rejected == []
    assert cache_rejected == []
    assert len(latest) == 1
    assert len(cached) == 2
    assert len(combined) == 2
    assert {row["prediction_id"] for row in combined} == {"pred_1", "pred_3"}
    assert all(row["counts_as_a_grade_evidence"] is False for row in combined)
    assert all(row["counts_as_a_plus"] is False for row in combined)


def test_durable_archive_consumer_recovers_every_row_beyond_redis_hot_cap(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "guardian.sqlite3"
    destination_path = tmp_path / "guardian_coverage.jsonl"
    payloads = [_archive_payload(index) for index in range(7)]
    archive = _write_source_archive(source_path, payloads)
    assert guardian_pit_archive_consumption_status(source_path)[
        "redis_hot_cache_trim_safe"
    ] is False

    # Model a held Guardian resuming after the producer retained only the last
    # two rows in Redis. The SQLite consumer must still recover all seven.
    client = FakeRedis({})
    client.lists[REDIS_HOT_CACHE_OBSERVATION_KEY] = [
        json.dumps(payload) for payload in payloads[-2:]
    ]
    cached, rejected = collect_hot_cache_prediction_rows(
        client,
        timeframes=("1m",),
        max_rows=2,
    )
    assert rejected == []
    assert len(cached) == 2

    batches: list[int] = []
    statuses: list[dict] = []
    for cycle in range(3):
        rows, status = consume_durable_guardian_pit_archive(
            source_archive_path=source_path,
            guardian_coverage_archive_path=destination_path,
            allowed_timeframes=("1m",),
            batch_rows=3,
            generated_utc=f"2026-07-10T00:00:0{cycle}.000Z",
        )
        batches.append(len(rows))
        statuses.append(status)

    assert batches == [3, 3, 1]
    assert statuses[0]["status"] == "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_IN_PROGRESS"
    assert statuses[0]["redis_hot_cache_trim_safe"] is False
    assert statuses[-1]["status"] == (
        "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED"
    )
    assert statuses[-1]["archive_consumption_complete_verified"] is True
    assert statuses[-1]["redis_hot_cache_trim_safe"] is True
    assert statuses[-1]["consumer_consumed_unique_rows"] == 7
    assert len(read_jsonl(destination_path)) == 7

    cursor = json.loads(archive.metadata(GUARDIAN_PIT_ARCHIVE_CURSOR_METADATA_KEY))
    assert cursor["consumed_unique_rows"] == 7
    assert cursor["last_consumed_sequence"] > 0
    assert cursor["selected_policy_action_counts"] == {
        "LONG": 3,
        "SHORT": 2,
        "NO_TRADE": 2,
    }
    live_status = guardian_pit_archive_consumption_status(
        source_path,
        generated_utc="2026-07-10T00:01:00.000Z",
    )
    assert live_status["redis_hot_cache_trim_safe"] is True
    assert live_status["archive_unconsumed_unique_rows"] == 0
    assert live_status["counts_as_a_plus"] is False
    assert live_status["routes_to_live"] is False

    _write_source_archive(source_path, [_archive_payload(7)])
    after_new_archive_row = guardian_pit_archive_consumption_status(source_path)
    assert after_new_archive_row["redis_hot_cache_trim_safe"] is False
    assert after_new_archive_row["archive_unconsumed_unique_rows"] == 1


def test_durable_archive_consumer_fails_closed_on_content_hash_tampering(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "tampered.sqlite3"
    destination_path = tmp_path / "guardian_coverage.jsonl"
    _write_source_archive(source_path, [_archive_payload(0)])
    with sqlite3.connect(source_path) as connection:
        payload = _archive_payload(0, symbol="TAMPEREDUSDT")
        connection.execute(
            "UPDATE evidence_records SET payload_json = ? WHERE stream_id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "v2_guardian_pit_prediction_observations_unique_v1",
            ),
        )

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=10,
    )

    assert rows == []
    assert status["status"] == "BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION"
    assert status["consumer_cursor_sequence"] == 0
    assert status["redis_hot_cache_trim_safe"] is False
    assert any(
        "ARCHIVE_CONTENT_SHA256_MISMATCH" in reason
        for reason in status["block_reasons"]
    )
    assert not destination_path.exists()
    assert guardian_pit_archive_consumption_status(source_path)[
        "redis_hot_cache_trim_safe"
    ] is False


def test_durable_archive_consumer_quarantines_schema_pit_and_finality_violations(
    tmp_path: Path,
) -> None:
    invalid_payloads = {
        "schema": _archive_payload(0, schema_version="unsupported_guardian_schema_v0"),
        "pit": _archive_payload(
            1,
            feature_cutoff="2026-07-09T20:41:00Z",
            available_at="2026-07-09T20:41:00Z",
            decision_time="2026-07-09T20:41:00Z",
            generated_at="2026-07-09T20:41:00Z",
        ),
        "finality": _archive_payload(
            2,
            feature_cutoff="2026-07-09T20:41:30Z",
            available_at="2026-07-09T20:41:30Z",
            candle_close_time="2026-07-09T20:41:30Z",
        ),
        "naive": _archive_payload(
            3,
            feature_cutoff="2026-07-09T20:42:59.999",
            available_at="2026-07-09T20:42:59.999",
            candle_close_time="2026-07-09T20:42:59.999",
            decision_time="2026-07-09T20:43:00",
            generated_at="2026-07-09T20:43:00",
        ),
    }
    expected_reasons = {
        "schema": "ARCHIVE_RECORD_SCHEMA_VERSION_INVALID",
        "pit": "ARCHIVE_FEATURE_CUTOFF_NOT_STRICTLY_BEFORE_DECISION_TIME",
        "finality": "ARCHIVE_CANDLE_CLOSE_NOT_FINAL_TIMEFRAME_BOUNDARY",
        "naive": "ARCHIVE_DECISION_TIME_NAIVE",
    }

    for name, payload in invalid_payloads.items():
        source_path = tmp_path / f"{name}.sqlite3"
        destination_path = tmp_path / f"{name}.jsonl"
        _write_source_archive(source_path, [payload])

        rows, status = consume_durable_guardian_pit_archive(
            source_archive_path=source_path,
            guardian_coverage_archive_path=destination_path,
            allowed_timeframes=("1m",),
            batch_rows=1,
        )

        assert rows == []
        assert status["consumer_cursor_sequence"] > 0
        assert status["archive_consumption_complete_verified"] is True
        assert status["quarantined_unique_rows"] == 1
        assert status["coverage_eligible_unique_rows"] == 0
        assert any(
            expected_reasons[name] in reason
            for reason in status["quarantine_reason_counts"]
        )
        assert not destination_path.exists()


def test_cli_coverage_uses_sqlite_archive_and_reports_machine_trim_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "guardian.sqlite3"
    output_dir = tmp_path / "output"
    destination_path = tmp_path / "guardian_coverage.jsonl"
    manifest_path = tmp_path / "holdout_manifest.json"
    payloads = [_archive_payload(index) for index in range(4)]
    _write_source_archive(source_path, payloads)
    redis = FakeRedis({})
    redis.lists[REDIS_HOT_CACHE_OBSERVATION_KEY] = [json.dumps(payloads[-1])]
    monkeypatch.setattr(pit_counter_cli, "_redis_client", lambda _url: redis)
    args = pit_counter_cli.parse_args(
        [
            "--output-dir",
            str(output_dir),
            "--archive-path",
            str(destination_path),
            "--source-sqlite-archive-path",
            str(source_path),
            "--manifest-path",
            str(manifest_path),
            "--symbols",
            "COIN0USDT",
            "--timeframes",
            "1m",
        ]
    )

    result = pit_counter_cli.run(args)

    consumption = result["durable_archive_consumption"]
    assert consumption["consumer_consumed_unique_rows"] == 4
    assert consumption["archive_consumption_complete_verified"] is True
    assert consumption["redis_hot_cache_trim_safe"] is True
    assert result["point_in_time_valid_prediction_count"] == 4
    assert result["counts_as_a_plus"] is False
    status = json.loads(
        (output_dir / "guardian_pit_prediction_growth_status.json").read_text()
    )
    assert status["redis_hot_cache_cycle_valid_prediction_count"] == 1
    assert status["durable_archive_role"].startswith("SQLITE_HASH_VERIFIED_SOURCE")


def test_consumer_identity_matches_publisher_and_rewrite_conflicts(
    tmp_path: Path,
) -> None:
    original = _archive_payload(0)
    rewritten = dict(original)
    rewritten.update(
        {
            "selected_action": "short",
            "decision_time": "2026-07-09T20:41:00Z",
            "generated_at": "2026-07-09T20:41:00Z",
        }
    )
    consumer_id = guardian_pit_archive_record_id(original)
    assert consumer_id == publisher._guardian_pit_record_id(original)
    assert guardian_pit_archive_record_id(rewritten) == consumer_id

    archive = DurablePaperEvidenceArchive(
        tmp_path / "identity.sqlite3",
        stream_id="v2_guardian_pit_prediction_observations_unique_v1",
    )
    first = archive.append_unique([publisher._guardian_pit_archive_candidate(original)])
    conflict = archive.append_unique(
        [publisher._guardian_pit_archive_candidate(rewritten)]
    )

    assert first.inserted_rows == 1
    assert conflict.inserted_rows == 0
    assert conflict.identity_conflicts == 1
    assert conflict.identity_conflict_ids == (consumer_id,)


def test_consumer_accepts_exact_publisher_payload_end_to_end(tmp_path: Path) -> None:
    source_path = tmp_path / "publisher.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    source_row = {
        **_archive_payload(0),
        "status": "PRESENT_CURRENT",
        "prediction_redis_key": "v2:prediction:COIN0USDT:1m",
        "prediction_temporal_block_reasons": [],
        "generated_est": "2026-07-09T20:40:00Z",
    }
    payload = publisher.guardian_pit_observation_payload(source_row)
    assert payload is not None
    _write_source_archive(source_path, [payload])

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert len(rows) == 1
    assert rows[0]["prediction_id"] == "archive-pred-0"
    assert status["coverage_eligible_unique_rows"] == 1
    assert status["quarantined_unique_rows"] == 0
    assert status["redis_hot_cache_trim_safe"] is True


def test_consumer_chain_mismatch_blocks_cursor_and_trim(tmp_path: Path) -> None:
    source_path = tmp_path / "chain.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    archive = _write_source_archive(source_path, [_archive_payload(0)])
    archive.set_metadata("archive_chain_sha256", "0" * 64)

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert rows == []
    assert "DURABLE_ARCHIVE_CHAIN_SHA256_MISMATCH" in status["block_reasons"]
    assert status["consumer_cursor_sequence"] == 0
    assert status["redis_hot_cache_trim_safe"] is False
    assert not destination_path.exists()


def test_trim_gate_requires_migration_complete_and_empty_outbox(tmp_path: Path) -> None:
    source_path = tmp_path / "migration.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    payload = _archive_payload(0)
    candidate = publisher._guardian_pit_archive_candidate(payload)
    archive = DurablePaperEvidenceArchive(
        source_path,
        stream_id="v2_guardian_pit_prediction_observations_unique_v1",
    )
    archive.append_unique([candidate], queue_hot_cache_delivery=True)
    archive.set_metadata("redis_legacy_migration_cursor", "0")
    archive.set_metadata("redis_legacy_migration_observed_length", "1")
    archive.set_metadata("redis_legacy_migration_complete", "false")

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert len(rows) == 1
    assert status["archive_consumer_caught_up_verified"] is True
    assert status["redis_hot_cache_trim_safe"] is False
    assert status["publisher_legacy_migration_complete"] is False
    assert status["publisher_pending_hot_cache_deliveries"] == 1

    archive.set_metadata("redis_legacy_migration_cursor", "1")
    archive.set_metadata("redis_legacy_migration_complete", "true")
    still_pending = guardian_pit_archive_consumption_status(source_path)
    assert still_pending["redis_hot_cache_trim_safe"] is False
    assert archive.acknowledge_hot_cache_deliveries([candidate.record_id]) == 1
    assert guardian_pit_archive_consumption_status(source_path)[
        "redis_hot_cache_trim_safe"
    ] is True


def test_valid_legacy_quarantine_advances_chain_without_counting_coverage(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "quarantine.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    candidate = publisher._guardian_legacy_archive_candidate(b"\xff", list_index=0)
    archive = DurablePaperEvidenceArchive(
        source_path,
        stream_id="v2_guardian_pit_prediction_observations_unique_v1",
    )
    archive.append_unique([candidate])
    archive.set_metadata("redis_legacy_migration_cursor", "1")
    archive.set_metadata("redis_legacy_migration_observed_length", "1")
    archive.set_metadata("redis_legacy_migration_complete", "true")

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert rows == []
    assert status["consumer_consumed_unique_rows"] == 1
    assert status["coverage_eligible_unique_rows"] == 0
    assert status["quarantined_unique_rows"] == 1
    assert status["quarantine_reason_counts"] == {
        "LEGACY_INVALID_REDIS_RECORD_QUARANTINED": 1
    }
    assert status["redis_hot_cache_trim_safe"] is True
    assert not destination_path.exists()


def test_dirty_legacy_row_then_clean_row_progresses_without_dirty_coverage(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "dirty_then_clean.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    dirty = _archive_payload(0)
    for field in (
        "producer",
        "source",
        "candle_close_time",
        "candle_closed_confirmed",
        "test_order_submitted",
        "leverage_mutation",
        "margin_mode_mutation",
    ):
        dirty.pop(field)
    clean = _archive_payload(1)
    _write_source_archive(source_path, [dirty, clean])

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=10,
    )

    assert [row["prediction_id"] for row in rows] == ["archive-pred-1"]
    assert status["consumer_consumed_unique_rows"] == 2
    assert status["coverage_eligible_unique_rows"] == 1
    assert status["quarantined_unique_rows"] == 1
    assert len(read_jsonl(destination_path)) == 1
    assert read_jsonl(destination_path)[0]["prediction_id"] == "archive-pred-1"


def test_malformed_non_wrapper_archive_row_blocks_cursor(tmp_path: Path) -> None:
    source_path = tmp_path / "malformed.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    archive = DurablePaperEvidenceArchive(
        source_path,
        stream_id="v2_guardian_pit_prediction_observations_unique_v1",
    )
    archive.append_unique(
        [
            ArchiveCandidate(
                record_id="not-a-valid-stable-id",
                sort_key="not-a-valid-sort-key",
                payload={"schema_version": "not-a-quarantine-wrapper"},
            )
        ]
    )
    archive.set_metadata("redis_legacy_migration_cursor", "1")
    archive.set_metadata("redis_legacy_migration_observed_length", "1")
    archive.set_metadata("redis_legacy_migration_complete", "true")

    rows, status = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert rows == []
    assert status["consumer_cursor_sequence"] == 0
    assert status["redis_hot_cache_trim_safe"] is False
    assert any(
        "ARCHIVE_STABLE_IDENTITY_MISSING" in reason
        for reason in status["block_reasons"]
    )


def test_sink_readback_failure_keeps_cursor_replayable_after_durable_append(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "readback.sqlite3"
    destination_path = tmp_path / "coverage.jsonl"
    _write_source_archive(source_path, [_archive_payload(0)])
    original_inspect = pit_counter_module._inspect_coverage_archive
    calls = 0

    def fail_second_inspection(*args, **kwargs):
        nonlocal calls
        calls += 1
        result, reasons = original_inspect(*args, **kwargs)
        if calls == 2:
            return result, [*reasons, "INJECTED_DURABLE_READBACK_FAILURE"]
        return result, reasons

    monkeypatch.setattr(
        pit_counter_module,
        "_inspect_coverage_archive",
        fail_second_inspection,
    )
    rows, blocked = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert rows == []
    assert blocked["consumer_cursor_sequence"] == 0
    assert blocked["redis_hot_cache_trim_safe"] is False
    assert len(read_jsonl(destination_path)) == 1

    monkeypatch.setattr(
        pit_counter_module,
        "_inspect_coverage_archive",
        original_inspect,
    )
    replayed, recovered = consume_durable_guardian_pit_archive(
        source_archive_path=source_path,
        guardian_coverage_archive_path=destination_path,
        allowed_timeframes=("1m",),
        batch_rows=1,
    )

    assert len(replayed) == 1
    assert recovered["consumer_consumed_unique_rows"] == 1
    assert recovered["guardian_coverage_archive_rows_appended_this_cycle"] == 0
    assert recovered["redis_hot_cache_trim_safe"] is True
    assert len(read_jsonl(destination_path)) == 1


def test_trim_status_rejects_deleted_or_tampered_coverage_sink(tmp_path: Path) -> None:
    for mutation in ("delete", "tamper"):
        source_path = tmp_path / f"{mutation}.sqlite3"
        destination_path = tmp_path / f"{mutation}.jsonl"
        _write_source_archive(source_path, [_archive_payload(0)])
        rows, complete = consume_durable_guardian_pit_archive(
            source_archive_path=source_path,
            guardian_coverage_archive_path=destination_path,
            allowed_timeframes=("1m",),
            batch_rows=1,
        )
        assert len(rows) == 1
        assert complete["redis_hot_cache_trim_safe"] is True

        if mutation == "delete":
            destination_path.unlink()
        else:
            tampered = read_jsonl(destination_path)[0]
            tampered["symbol"] = "TAMPEREDUSDT"
            destination_path.write_text(json.dumps(tampered) + "\n")

        status = guardian_pit_archive_consumption_status(source_path)
        assert status["archive_consumption_complete_verified"] is False
        assert status["redis_hot_cache_trim_safe"] is False
        assert any(
            "GUARDIAN_COVERAGE_ARCHIVE" in reason
            for reason in status["block_reasons"]
        )
