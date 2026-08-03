from __future__ import annotations

import fcntl
import hashlib
import io
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import tools.edge_replay_factory_loop as factory
from v2.backend.app.services.durable_paper_evidence_archive import (
    DurablePaperEvidenceArchive,
    canonical_json,
)


def test_streaming_top_level_json_array_parser_handles_split_rows_and_bounds() -> None:
    chunks = [
        "  [{\"id\":1,\"text\":\"hel",
        "lo\"},",
        " {\"id\":2,\"nested\":[1,2]}]  ",
    ]

    assert list(factory._iter_top_level_json_array_chunks(chunks)) == [
        {"id": 1, "text": "hello"},
        {"id": 2, "nested": [1, 2]},
    ]

    try:
        list(
            factory._iter_top_level_json_array_chunks(
                ["[{\"id\":\"" + "x" * 128],
                max_buffer_chars=64,
            )
        )
    except ValueError as exc:
        assert str(exc) == "counterfactual_json_row_exceeds_memory_safety_bound"
    else:  # pragma: no cover - explicit failure message is clearer than pytest.raises here
        raise AssertionError("oversized streaming row was not rejected")

    for invalid, expected in (
        ('[{"id":1},]', "counterfactual_json_trailing_comma"),
        (
            '[{"id":1,"id":2}]',
            "counterfactual_json_duplicate_object_key:id",
        ),
        ('[{"id":NaN}]', "counterfactual_json_nonfinite_constant:NaN"),
    ):
        try:
            list(factory._iter_top_level_json_array_chunks([invalid]))
        except ValueError as exc:
            assert str(exc) == expected
        else:  # pragma: no cover
            raise AssertionError(f"strict streaming parser accepted {invalid}")

    complete_oversized_row = '[{"id":"' + "x" * 128 + '"}]'
    try:
        list(
            factory._iter_top_level_json_array_chunks(
                [complete_oversized_row],
                max_buffer_chars=64,
            )
        )
    except ValueError as exc:
        assert str(exc) == "counterfactual_json_row_exceeds_memory_safety_bound"
    else:  # pragma: no cover
        raise AssertionError("complete oversized row bypassed the parser bound")


def test_counterfactual_archive_exclusive_lock_fails_closed_on_second_worker(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "counterfactuals.sqlite3"
    lock_path = archive_path.with_name(archive_path.name + ".migration.lock")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
        try:
            factory.archive_counterfactual_rows_and_select_hot_set(
                archive_path=archive_path,
                rows=[],
                trainer_hot_max_rows=1,
            )
        except RuntimeError as exc:
            assert str(exc) == (
                "counterfactual_archive_migration_already_in_progress"
            )
        else:  # pragma: no cover
            raise AssertionError("second archive worker bypassed exclusive lock")


class _GuardPipeline:
    def __init__(self, *, conflict: bool = False) -> None:
        self.conflict = conflict
        self.reset_called = False

    def multi(self) -> None:
        return None

    def set(self, _key, _value) -> None:
        return None

    def execute(self):
        if self.conflict:
            watch_error = type("WatchError", (Exception,), {})
            raise watch_error("source changed")
        return [True]

    def reset(self) -> None:
        self.reset_called = True


class _GuardRedisClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_redis_guard_atomic_replace_receipt_distinguishes_success_and_race() -> None:
    for conflict, expected_success in ((False, True), (True, False)):
        pipeline = _GuardPipeline(conflict=conflict)
        redis_client = _GuardRedisClient()
        guard = factory.StableRedisSourceGuard(
            key=factory.COUNTERFACTUAL_KEY,
            pipeline=pipeline,
            redis_client=redis_client,
            source_exists=True,
            observed_source_byte_length=2,
            started_utc="2026-07-18T00:00:00Z",
            observed_source_sha256=hashlib.sha256(b"[]").hexdigest(),
            source_stream_complete=True,
        )
        client = factory.RedisCliJson()
        client._active_source_guards[factory.COUNTERFACTUAL_KEY] = guard

        result = client.replace_json_if_source_unchanged(
            factory.COUNTERFACTUAL_KEY,
            [],
            guard,
        )

        assert result["write_succeeded"] is expected_success
        assert result["source_concurrency_conflict"] is conflict
        assert result["source_compare_atomic_with_write"] is True
        assert result["source_compare_performed_immediately_before_write"] is True
        assert result["source_compare_endpoint_contract"] == (
            "SHARED_EXPLICIT_REDIS_URL_FOR_WATCH_STREAM_AND_WRITE"
        )
        assert result["observed_source_sha256"] == hashlib.sha256(b"[]").hexdigest()
        assert pipeline.reset_called is True
        assert redis_client.closed is True


def test_redis_cli_stream_hashes_only_exact_bulk_value_not_cli_newline(
    monkeypatch,
) -> None:
    source = canonical_json(
        [
            {"trainer_feedback_id": "row-1"},
            {"trainer_feedback_id": "row-2"},
        ]
    ).encode("utf-8")

    class _Process:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(source + b"\n")
            self.stderr = io.BytesIO()

        def wait(self, timeout=None):
            del timeout
            return 0

        def poll(self):
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    popen_argv: list[str] = []

    def fake_popen(argv, **_kwargs):
        popen_argv.extend(argv)
        return _Process()

    monkeypatch.setattr(factory.subprocess, "Popen", fake_popen)
    client = factory.RedisCliJson(redis_url="redis://127.0.0.1:6379/7")
    guard = factory.StableRedisSourceGuard(
        key=factory.COUNTERFACTUAL_KEY,
        pipeline=_GuardPipeline(),
        redis_client=_GuardRedisClient(),
        source_exists=True,
        observed_source_byte_length=len(source),
        started_utc="2026-07-18T00:00:00Z",
    )
    client._active_source_guards[factory.COUNTERFACTUAL_KEY] = guard

    rows = list(client.iter_json_array(factory.COUNTERFACTUAL_KEY))

    assert [row["trainer_feedback_id"] for row in rows] == ["row-1", "row-2"]
    assert guard.source_stream_complete is True
    assert guard.observed_source_sha256 == hashlib.sha256(source).hexdigest()
    assert popen_argv[:3] == [
        "redis-cli",
        "-u",
        "redis://127.0.0.1:6379/7",
    ]


def _source_row(**overrides):
    row = {
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "decision_id": "dec-1",
        "feature_snapshot_id": "feat-1",
        "entry_feature_snapshot_id": "feat-1",
        "mtf_snapshot_id": "mtf-1",
        "market_state_id": "mstate-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "entry_price_utc": "2026-07-09T12:00:00Z",
        "feature_cutoff": "2026-07-09T11:59:00Z",
        "masa_feature_cutoff": "2026-07-09T11:59:00Z",
        "ppo_feature_cutoff": "2026-07-09T11:59:00Z",
        "available_at": "2026-07-09T11:59:30Z",
        "decision_time": "2026-07-09T12:00:00Z",
        "candle_close_time": "2026-07-09T11:59:00Z",
        "candle_closed_confirmed": True,
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "target_notional_usd": 100.0,
        "fee_bps": 2.0,
        "expected_slippage_bps": 1.0,
        "expected_funding_bps": 0.5,
        "depth_derived_price_impact_bps": 0.5,
        "latency_reserve_bps": 0.25,
        "partial_fill_adjustment_bps": 0.25,
        "estimated_production_cost_bps": 4.5,
        "production_grade_cost_evidence": True,
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "runtime_cost_capture_decision_time": "2026-07-09T11:59:59Z",
        "runtime_cost_capture_temporal_reject_reasons": [],
        "runtime_cost_capture_source_reject_reasons": [],
        "fallback_cost_flag": False,
        "cost_source_allowed": True,
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "market_cost_evidence_pit_reject_reasons": [],
        "cost_evidence_source_fields": {
            "depth_impact": "book-depth",
            "fee": "fee-schedule",
            "funding": "mark-funding",
            "latency": "latency-model",
            "partial_fill": "partial-fill-model",
        },
        "expected_slippage_source": "orderbook-impact",
        "strategy_id": "trend",
        "strategy_family": "trend",
        "strategy_subtype": "pullback",
        "source_hashes": {"features": "hash"},
        "paper_only": True,
        "places_real_order": False,
        "future_labels_used_as_features": False,
    }
    row.update(overrides)
    return row


def test_matures_shadow_row_from_closed_candle_without_live_flags() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row()],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "high": 101.5,
                    "low": 99.5,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T12:15:01Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
        min_hold_seconds=900,
    )

    assert len(matured) == 1
    assert pending == []
    assert rejected == []
    row = matured[0]
    assert row["trainer_feedback_source"] == (
        "V2_CONTINUOUS_EDGE_FACTORY_COUNTERFACTUAL_CLOSED_WINDOW"
    )
    assert row["trainer_consumable"] is True
    assert row["counterfactual_label_matured"] is True
    assert row["counterfactual_label_pending"] is False
    assert row["future_labels_used_as_features"] is False
    assert row["counts_as_final_a_plus"] is False
    assert row["counts_as_live_ready"] is False
    assert row["routes_to_live"] is False
    assert row["places_real_order"] is False
    assert row["realized_net_pnl_bps"] > 0
    assert row["label_available_at"] == "2026-07-09T12:15:01.000Z"
    assert row["label_generated_at"] == "2026-07-09T12:16:00.000Z"
    assert row["outcome_targets"]["explicit_total_cost_bps"] == 4.5


def test_rejects_feature_available_after_decision_time() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row(available_at="2026-07-09T12:00:01Z")],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T12:15:01Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )

    assert matured == []
    assert pending == []
    assert rejected[0]["reject_reasons"] == ["AVAILABLE_AT_AFTER_DECISION_TIME"]


def test_pending_until_closed_exit_candle_available() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row()],
        candles_by_symbol_timeframe={("BTCUSDT", "1m"): []},
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )

    assert matured == []
    assert rejected == []
    assert pending[0]["pending_reason"] == "NO_CLOSED_EXIT_CANDLE_AVAILABLE"


def test_counterfactual_label_subtracts_exact_explicit_bps_costs() -> None:
    source = _source_row(
        fee_bps=2.0,
        expected_slippage_bps=3.0,
        expected_funding_bps=3.0,
        depth_derived_price_impact_bps=0.0,
        latency_reserve_bps=0.0,
        partial_fill_adjustment_bps=0.0,
        estimated_production_cost_bps=8.0,
    )
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [source],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 100.05,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T12:15:01Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )

    assert pending == []
    assert rejected == []
    assert len(matured) == 1
    row = matured[0]
    assert abs(row["gross_pnl_bps"] - 5.0) < 1e-9
    assert abs(row["realized_net_pnl_bps"] - (-3.0)) < 1e-9
    assert row["trade_outcome"] == "LOSS"
    assert row["action_was_profitable"] is False
    assert row["fees"] == 2.0
    assert row["slippage"] == 3.0
    assert row["funding"] == 3.0
    assert row["outcome_targets"]["explicit_total_cost_bps"] == 8.0


def test_counterfactual_rejects_zero_notional_instead_of_inventing_one_dollar() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row(target_notional_usd=0.0)],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T12:15:01Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )

    assert matured == []
    assert pending == []
    assert "POSITIVE_PRE_OUTCOME_COUNTERFACTUAL_NOTIONAL_MISSING" in rejected[0][
        "reject_reasons"
    ]


def test_counterfactual_requires_entry_finality_and_exit_availability() -> None:
    missing_finality = _source_row(candle_closed_confirmed=None)
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [missing_finality],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T12:15:01Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )
    assert matured == []
    assert pending == []
    assert "ENTRY_CANDLE_FINALITY_UNPROVEN_OR_CONFLICTING" in rejected[0][
        "reject_reasons"
    ]

    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row()],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "available_at": "2026-07-09T13:00:00Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=UTC),
    )
    assert matured == []
    assert rejected == []
    assert pending[0]["pending_reason"] == "NO_CLOSED_EXIT_CANDLE_AVAILABLE"


def _feedback_row(
    row_id: str,
    decision_time: str,
    *,
    pnl_bps: float,
    generated_utc: str = "2026-07-09T13:00:00Z",
) -> dict:
    return {
        "trainer_feedback_id": row_id,
        "counterfactual_feedback_id": row_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": decision_time,
        "feature_cutoff": decision_time,
        "available_at": decision_time,
        "generated_utc": generated_utc,
        "realized_net_pnl_bps": pnl_bps,
        "future_labels_used_as_features": False,
        "candle_closed_confirmed": True,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "routes_to_live": False,
        "places_real_order": False,
    }


def test_counterfactual_archive_preserves_all_unique_rows_before_bounded_hot_selection(
    tmp_path: Path,
) -> None:
    rows = [
        _feedback_row("feedback-3", "2026-07-09T12:03:00Z", pnl_bps=-3.0),
        _feedback_row("feedback-1", "2026-07-09T12:01:00Z", pnl_bps=100.0),
        _feedback_row("feedback-2", "2026-07-09T12:02:00Z", pnl_bps=-100.0),
    ]

    hot_rows, status = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=tmp_path / "counterfactuals.sqlite3",
        rows=rows,
        trainer_hot_max_rows=2,
    )

    assert [row["trainer_feedback_id"] for row in hot_rows] == ["feedback-2", "feedback-3"]
    assert [row["realized_net_pnl_bps"] for row in hot_rows] == [-100.0, -3.0]
    assert status["status"] == "DURABLE_ARCHIVE_READY_BOUNDED_HOT_CACHE"
    assert status["durable_archive_total_unique_rows"] == 3
    assert status["redis_hot_rows"] == 2
    assert status["redis_hot_rows_omitted_but_preserved_in_archive"] == 1
    assert status["hot_selection_basis"] == "decision_time_then_stable_feedback_id"
    assert status["hot_selection_uses_outcome_fields"] is False
    assert (
        status["hot_limit_is_operational_resource_control_not_market_admission_threshold"]
        is True
    )
    assert status["all_unique_rows_archived_before_hot_cache_replace"] is True
    assert status["counterfactual_rows_count_as_final_a_plus"] is False
    assert status["counterfactual_rows_count_as_live_ready"] is False
    assert status["archive_all_input_rows_accounted_for"] is True
    assert status["source_snapshot_occurrence_count"] == 3
    assert status["source_snapshot_rollback_reconstruction_verified"] is True

    archive = DurablePaperEvidenceArchive(
        tmp_path / "counterfactuals.sqlite3",
        stream_id=factory.COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    reconstructed = b"".join(
        archive.source_snapshot_json_chunks(status["source_snapshot_id"])
    )
    assert reconstructed == canonical_json(rows).encode("utf-8")

    # Re-observing the same immutable rows in a different input order does not
    # perturb deterministic hot ordering or the semantic hot-set hash.
    second_hot, second_status = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=tmp_path / "counterfactuals.sqlite3",
        rows=list(reversed(rows)),
        trainer_hot_max_rows=2,
    )
    assert second_hot == hot_rows
    assert second_status["archive_duplicate_rows"] == 3
    assert second_status["redis_hot_ordered_semantic_rows_sha256"] == status[
        "redis_hot_ordered_semantic_rows_sha256"
    ]


def test_counterfactual_archive_batches_are_row_and_payload_byte_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows = [
        _feedback_row(
            f"feedback-{index}",
            f"2026-07-09T12:0{index}:00Z",
            pnl_bps=float(index),
        )
        for index in range(3)
    ]
    one_row_bound = max(
        len(canonical_json(row).encode("utf-8")) for row in rows
    ) + 1
    monkeypatch.setattr(
        factory,
        "COUNTERFACTUAL_ARCHIVE_BATCH_MAX_BYTES",
        one_row_bound,
    )

    _hot_rows, status = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=tmp_path / "counterfactuals.sqlite3",
        rows=rows,
        trainer_hot_max_rows=3,
    )

    assert status["status"] == "DURABLE_ARCHIVE_READY_BOUNDED_HOT_CACHE"
    assert status["archive_batches_committed"] == 3
    assert status["archive_batch_max_payload_bytes"] == one_row_bound


def test_counterfactual_archive_rejects_immutable_identity_label_rewrite(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "counterfactuals.sqlite3"
    original = _feedback_row("feedback-1", "2026-07-09T12:01:00Z", pnl_bps=4.0)
    replay_only_timestamp_change = _feedback_row(
        "feedback-1",
        "2026-07-09T12:01:00Z",
        pnl_bps=4.0,
        generated_utc="2026-07-09T14:00:00Z",
    )
    changed_label = _feedback_row(
        "feedback-1",
        "2026-07-09T12:01:00Z",
        pnl_bps=-4.0,
        generated_utc="2026-07-09T15:00:00Z",
    )

    _, initial = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=archive_path,
        rows=[original],
        trainer_hot_max_rows=10,
    )
    _, idempotent = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=archive_path,
        rows=[replay_only_timestamp_change],
        trainer_hot_max_rows=10,
    )
    retained, conflict = factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=archive_path,
        rows=[changed_label],
        trainer_hot_max_rows=10,
    )

    assert initial["archive_inserted_unique_rows"] == 1
    assert idempotent["archive_duplicate_rows"] == 1
    assert idempotent["archive_identity_conflicts"] == 0
    assert conflict["status"] == "DURABLE_ARCHIVE_IDENTITY_CONFLICT_FAIL_CLOSED"
    assert conflict["archive_identity_conflicts"] == 1
    assert conflict["all_unique_rows_archived_before_hot_cache_replace"] is False
    assert retained[0]["realized_net_pnl_bps"] == 4.0


def test_counterfactual_archive_refuses_tampered_sqlite_payload(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "counterfactuals.sqlite3"
    original = _feedback_row(
        "feedback-tamper",
        "2026-07-09T12:01:00Z",
        pnl_bps=4.0,
    )
    factory.archive_counterfactual_rows_and_select_hot_set(
        archive_path=archive_path,
        rows=[original],
        trainer_hot_max_rows=10,
    )
    with sqlite3.connect(archive_path) as connection:
        connection.execute(
            """
            UPDATE evidence_records
            SET payload_json = '{"realized_net_pnl_bps":-999}'
            WHERE record_id = 'feedback-tamper'
            """
        )
        connection.commit()

    try:
        factory.archive_counterfactual_rows_and_select_hot_set(
            archive_path=archive_path,
            rows=[original],
            trainer_hot_max_rows=10,
        )
    except ValueError as exc:
        assert "durable_archive_content_hash_mismatch:feedback-tamper" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered archive payload was accepted")


def test_counterfactual_hot_cap_is_read_from_operational_environment(monkeypatch) -> None:
    monkeypatch.setenv(factory.TRAINER_HOT_MAX_ROWS_ENV, "16384")

    args = factory.parse_args(["--once"])

    assert args.trainer_hot_max_rows == 16384


class _MemoryJsonClient:
    def __init__(self, values: dict) -> None:
        self.values = dict(values)
        self.writes: list[tuple[str, object]] = []

    def get(self, key: str):
        return self.values.get(key)

    def set_json(self, key: str, payload) -> bool:
        self.values[key] = payload
        self.writes.append((key, payload))
        return True

    def begin_stable_source_guard(self, key: str):
        encoded = canonical_json(self.values.get(key)).encode("utf-8")
        return {
            "key": key,
            "source_sha256": hashlib.sha256(encoded).hexdigest(),
            "observed_source_sha256": hashlib.sha256(encoded).hexdigest(),
            "observed_source_byte_length": len(encoded),
            "source_stream_complete": True,
            "active": True,
        }

    def replace_json_if_source_unchanged(self, key: str, payload, guard):
        assert guard["active"] is True
        guard["active"] = False
        current = canonical_json(self.values.get(key)).encode("utf-8")
        if hashlib.sha256(current).hexdigest() != guard["source_sha256"]:
            return {
                "source_guard_supported": True,
                "source_guard_acquired": True,
                "source_compare_method": "TEST_REVISION_AND_SHA256_CAS",
                "source_compare_atomic_with_write": True,
                "source_compare_performed_immediately_before_write": True,
                "source_unchanged_at_replace": False,
                "source_concurrency_conflict": True,
                "write_attempted": False,
                "write_succeeded": False,
                "write_outcome": "SOURCE_CHANGED_ATOMIC_REPLACE_ABORTED",
                "redis_state_after_attempt_known": True,
            }
        self.values[key] = payload
        self.writes.append((key, payload))
        return {
            "source_guard_supported": True,
            "source_guard_acquired": True,
            "source_compare_method": "TEST_REVISION_AND_SHA256_CAS",
            "source_compare_atomic_with_write": True,
            "source_compare_performed_immediately_before_write": True,
            "source_compare_endpoint_contract": (
                "SHARED_EXPLICIT_REDIS_URL_FOR_WATCH_STREAM_AND_WRITE"
            ),
            "source_unchanged_at_replace": True,
            "source_concurrency_conflict": False,
            "write_attempted": True,
            "write_succeeded": True,
            "write_outcome": "ATOMIC_REPLACE_SUCCEEDED",
            "redis_state_after_attempt_known": True,
            "observed_source_exists": True,
            "observed_source_byte_length": guard[
                "observed_source_byte_length"
            ],
            "observed_source_sha256": guard["observed_source_sha256"],
        }

    def cancel_stable_source_guard(self, guard) -> None:
        guard["active"] = False


class _StreamingMemoryJsonClient(_MemoryJsonClient):
    def __init__(self, values: dict) -> None:
        super().__init__(values)
        self.counterfactual_written = False

    def iter_json_array(self, key: str):
        assert key == factory.COUNTERFACTUAL_KEY
        yield from list(self.values[key])

    def get(self, key: str):
        if key == factory.COUNTERFACTUAL_KEY and not self.counterfactual_written:
            raise AssertionError("counterfactual source must be streamed, not GET-materialized")
        return super().get(key)

    def replace_json_if_source_unchanged(self, key: str, payload, guard):
        result = super().replace_json_if_source_unchanged(key, payload, guard)
        if key == factory.COUNTERFACTUAL_KEY and result["write_succeeded"]:
            self.counterfactual_written = True
        return result


class _FailFirstCounterfactualSetClient(_MemoryJsonClient):
    def __init__(self, values: dict) -> None:
        super().__init__(values)
        self.counterfactual_set_attempts = 0

    def replace_json_if_source_unchanged(self, key: str, payload, guard):
        if key == factory.COUNTERFACTUAL_KEY:
            self.counterfactual_set_attempts += 1
            if self.counterfactual_set_attempts == 1:
                guard["active"] = False
                return {
                    "source_guard_supported": True,
                    "source_guard_acquired": True,
                    "source_compare_method": "TEST_REVISION_AND_SHA256_CAS",
                    "source_compare_atomic_with_write": True,
                    "source_compare_performed_immediately_before_write": True,
                    "source_unchanged_at_replace": True,
                    "source_concurrency_conflict": False,
                    "write_attempted": True,
                    "write_succeeded": False,
                    "write_outcome": "ATOMIC_REPLACE_COMMAND_REJECTED",
                    "redis_state_after_attempt_known": True,
                }
        return super().replace_json_if_source_unchanged(key, payload, guard)


class _ConcurrentSourceMutationClient(_StreamingMemoryJsonClient):
    def __init__(self, values: dict, concurrent_row: dict) -> None:
        super().__init__(values)
        self.concurrent_row = concurrent_row

    def iter_json_array(self, key: str):
        snapshot = list(self.values[key])
        yield from snapshot
        self.values[key] = [*snapshot, self.concurrent_row]


def test_run_once_replaces_counterfactual_string_only_after_archive_with_bounded_hot_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows = [
        _feedback_row("feedback-3", "2026-07-09T12:03:00Z", pnl_bps=3.0),
        _feedback_row("feedback-1", "2026-07-09T12:01:00Z", pnl_bps=1.0),
        _feedback_row("feedback-2", "2026-07-09T12:02:00Z", pnl_bps=2.0),
    ]
    client = _MemoryJsonClient(
        {
            factory.SHADOW_OBSERVATIONS_KEY: [],
            factory.PREEMPTIVE_COUNTERFACTUAL_KEY: [],
            factory.COUNTERFACTUAL_KEY: rows,
        }
    )
    monkeypatch.setattr(factory, "RedisCliJson", lambda: client)

    status = factory.run_once(
        output_dir=tmp_path / "output",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=tmp_path / "counterfactuals.sqlite3",
        trainer_hot_max_rows=2,
    )

    published = client.values[factory.COUNTERFACTUAL_KEY]
    assert [row["trainer_feedback_id"] for row in published] == ["feedback-2", "feedback-3"]
    contract = status["counterfactual_archive_hot_cache"]
    assert contract["durable_archive_total_unique_rows"] == 3
    assert contract["redis_hot_rows"] == 2
    assert contract["redis_hot_rows_omitted_but_preserved_in_archive"] == 1
    assert status["redis_counterfactual_string_replaced_with_bounded_hot_working_set"] is True
    assert contract["stable_source_guard"]["source_unchanged_at_replace"] is True
    assert contract["replacement_intent_receipt_durable"] is True
    assert contract["replacement_outcome_receipt_durable"] is True
    assert contract["verified_replacement_readiness_verified"] is True
    assert contract["verified_replacement_readiness"]["rejection_reasons"] == []
    assert contract["rollback_status"] == "NOT_REQUIRED_REPLACEMENT_VERIFIED"
    assert contract["no_data_loss_proven"] is True

    archive = DurablePaperEvidenceArchive(
        tmp_path / "counterfactuals.sqlite3",
        stream_id=factory.COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    outcome = archive.latest_operation_receipt(
        operation_kind="COUNTERFACTUAL_HOT_CACHE_REPLACEMENT_OUTCOME"
    )
    assert outcome is not None
    assert outcome["receipt"]["hot_cache_replace_verified"] is True
    assert outcome["receipt"]["no_data_loss_proven"] is True


def test_run_once_streams_existing_counterfactual_source_in_bounded_archive_batches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows = [
        _feedback_row(
            f"feedback-{index}",
            f"2026-07-09T12:{index // 60:02d}:{index % 60:02d}Z",
            pnl_bps=float(index),
        )
        for index in range(600)
    ]
    client = _StreamingMemoryJsonClient(
        {
            factory.SHADOW_OBSERVATIONS_KEY: [],
            factory.PREEMPTIVE_COUNTERFACTUAL_KEY: [],
            factory.COUNTERFACTUAL_KEY: rows,
        }
    )
    monkeypatch.setattr(factory, "RedisCliJson", lambda: client)

    status = factory.run_once(
        output_dir=tmp_path / "output",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=tmp_path / "counterfactuals.sqlite3",
        trainer_hot_max_rows=16,
    )

    contract = status["counterfactual_archive_hot_cache"]
    assert contract["archive_attempted_rows"] == 600
    assert contract["archive_batches_committed"] == 2
    assert contract["archive_batch_max_rows"] == 512
    assert contract["archive_input_materialized_in_memory"] is False
    assert status["redis_counterfactual_string_replaced_with_bounded_hot_working_set"] is True
    assert len(client.values[factory.COUNTERFACTUAL_KEY]) == 16


def test_run_once_leaves_counterfactual_redis_unchanged_when_archive_is_not_strict_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    invalid = _feedback_row("feedback-invalid", "2026-07-09T12:01:00Z", pnl_bps=float("inf"))
    original = [invalid]
    client = _MemoryJsonClient(
        {
            factory.SHADOW_OBSERVATIONS_KEY: [],
            factory.PREEMPTIVE_COUNTERFACTUAL_KEY: [],
            factory.COUNTERFACTUAL_KEY: original,
        }
    )
    monkeypatch.setattr(factory, "RedisCliJson", lambda: client)

    status = factory.run_once(
        output_dir=tmp_path / "output",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=tmp_path / "counterfactuals.sqlite3",
        trainer_hot_max_rows=2,
    )

    assert client.values[factory.COUNTERFACTUAL_KEY] is original
    assert status["counterfactual_archive_hot_cache"]["status"] == (
        "DURABLE_ARCHIVE_WRITE_FAILED_FAIL_CLOSED"
    )
    assert status["redis_counterfactual_string_replaced_with_bounded_hot_working_set"] is False


def test_run_once_claims_replacement_only_after_set_and_readback_then_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows = [
        _feedback_row("feedback-1", "2026-07-09T12:01:00Z", pnl_bps=1.0),
        _feedback_row("feedback-2", "2026-07-09T12:02:00Z", pnl_bps=2.0),
    ]
    original = list(rows)
    client = _FailFirstCounterfactualSetClient(
        {
            factory.SHADOW_OBSERVATIONS_KEY: [],
            factory.PREEMPTIVE_COUNTERFACTUAL_KEY: [],
            factory.COUNTERFACTUAL_KEY: original,
        }
    )
    monkeypatch.setattr(factory, "RedisCliJson", lambda: client)
    archive_path = tmp_path / "counterfactuals.sqlite3"

    first = factory.run_once(
        output_dir=tmp_path / "first",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=archive_path,
        trainer_hot_max_rows=1,
    )

    assert client.values[factory.COUNTERFACTUAL_KEY] is original
    assert first[
        "redis_counterfactual_string_replaced_with_bounded_hot_working_set"
    ] is False
    first_contract = first["counterfactual_archive_hot_cache"]
    assert first_contract["redis_hot_cache_write_succeeded"] is False
    assert first_contract["redis_hot_cache_readback_digest_verified"] is False

    second = factory.run_once(
        output_dir=tmp_path / "second",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=archive_path,
        trainer_hot_max_rows=1,
    )

    assert second[
        "redis_counterfactual_string_replaced_with_bounded_hot_working_set"
    ] is True
    second_contract = second["counterfactual_archive_hot_cache"]
    assert second_contract["archive_duplicate_rows"] == 2
    assert second_contract["redis_hot_cache_write_succeeded"] is True
    assert second_contract["redis_hot_cache_readback_digest_verified"] is True
    assert [
        row["trainer_feedback_id"]
        for row in client.values[factory.COUNTERFACTUAL_KEY]
    ] == ["feedback-2"]


def test_run_once_atomic_guard_preserves_concurrently_changed_source_and_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = [
        _feedback_row("feedback-1", "2026-07-09T12:01:00Z", pnl_bps=1.0),
        _feedback_row("feedback-2", "2026-07-09T12:02:00Z", pnl_bps=2.0),
    ]
    concurrent = _feedback_row(
        "feedback-concurrent",
        "2026-07-09T12:03:00Z",
        pnl_bps=3.0,
    )
    client = _ConcurrentSourceMutationClient(
        {
            factory.SHADOW_OBSERVATIONS_KEY: [],
            factory.PREEMPTIVE_COUNTERFACTUAL_KEY: [],
            factory.COUNTERFACTUAL_KEY: original,
        },
        concurrent,
    )
    monkeypatch.setattr(factory, "RedisCliJson", lambda: client)

    status = factory.run_once(
        output_dir=tmp_path / "output",
        publish_redis=True,
        min_hold_seconds=900,
        max_rows=500,
        counterfactual_archive_path=tmp_path / "counterfactuals.sqlite3",
        trainer_hot_max_rows=1,
    )

    assert client.values[factory.COUNTERFACTUAL_KEY] == [*original, concurrent]
    contract = status["counterfactual_archive_hot_cache"]
    assert contract["stable_source_guard"]["source_concurrency_conflict"] is True
    assert contract["stable_source_guard"]["write_attempted"] is False
    assert contract["redis_hot_cache_replace_verified"] is False
    assert contract["rollback_status"] == (
        "NOT_REQUIRED_SOURCE_CHANGED_ATOMIC_REPLACEMENT_ABORTED"
    )
    assert contract["no_data_loss_proven"] is True
    assert contract["replacement_intent_receipt_durable"] is True
    assert contract["replacement_outcome_receipt_durable"] is True

    archive = DurablePaperEvidenceArchive(
        tmp_path / "counterfactuals.sqlite3",
        stream_id=factory.COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    rollback_rows = json.loads(
        b"".join(
            archive.source_snapshot_json_chunks(contract["source_snapshot_id"])
        )
    )
    assert rollback_rows == original
