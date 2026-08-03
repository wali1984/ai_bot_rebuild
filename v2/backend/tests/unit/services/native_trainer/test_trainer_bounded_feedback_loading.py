from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from v2.backend.app.services.durable_paper_evidence_archive import (
    ArchiveCandidate,
    DurablePaperEvidenceArchive,
    counterfactual_archive_sort_key,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    data_loader as data_loader_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
    TRAINER_FEEDBACK_OUTCOMES_KEY,
    TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES,
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


class _MemoryIO:
    def __init__(self, payloads: dict[str, object] | None = None) -> None:
        self.payloads = payloads or {}

    def get_json(self, key: str):  # noqa: ANN201
        return self.payloads.get(key)


class _ForbiddenRedisFallbackIO:
    def __init__(self) -> None:
        self.get_calls = 0

    def get_json(self, _key: str):  # pragma: no cover - must remain unreachable
        self.get_calls += 1
        raise AssertionError(
            "an existing unready durable archive must suppress Redis fallback"
        )


class _OversizedRedis:
    def __init__(self) -> None:
        self.get_calls = 0

    def strlen(self, key: str) -> int:
        assert key == TRAINER_FEEDBACK_COUNTERFACTUALS_KEY
        return TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES + 1

    def get(self, _key: str):  # pragma: no cover - must remain unreachable
        self.get_calls += 1
        raise AssertionError("oversized Redis JSON must never be fetched")


class _OversizedRedisIO:
    def __init__(self, client: _OversizedRedis) -> None:
        self.client = client

    def get_json(self, key: str):  # pragma: no cover - must remain unreachable
        return self.client.get(key)


def _archive(path: Path, *, rows: int):
    archive = DurablePaperEvidenceArchive(
        path,
        stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    candidates = []
    for index in range(rows):
        payload = {
            "trainer_feedback_id": f"row-{index:04d}",
            "counterfactual_feedback_id": f"row-{index:04d}",
            "decision_time": f"2026-07-18T00:{index:02d}:00Z",
            "ordinal": index,
        }
        candidates.append(
            ArchiveCandidate(
                record_id=f"row-{index:04d}",
                sort_key=counterfactual_archive_sort_key(payload),
                payload=payload,
            )
        )
    archive.append_unique(candidates)
    return archive


def test_oversized_counterfactual_redis_json_is_never_fetched(
    tmp_path: Path,
) -> None:
    client = _OversizedRedis()
    loader = V2HybridTrainerDataLoader(
        io=_OversizedRedisIO(client),
        counterfactual_archive_path=tmp_path / "missing.sqlite3",
    )

    rows, status = loader._bounded_feedback_rows(  # noqa: SLF001
        source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
        limit=512,
    )

    assert rows == []
    assert client.get_calls == 0
    assert "REDIS_JSON_OVERSIZED_SKIPPED_FAIL_CLOSED" in status["status"]
    assert status["redis_payload_bytes"] == TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES + 1


def test_verified_counterfactual_archive_returns_only_bounded_newest_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "counterfactual.sqlite3"
    _archive(archive_path, rows=10)
    calls: list[tuple[str, int]] = []

    def verified_latest_rows(self, *, source_key: str, limit: int):
        calls.append((source_key, limit))
        rows = self.latest_rows(limit)
        return rows, {
            "schema_version": (
                "durable_paper_evidence_verified_replacement_readiness_v1"
            ),
            "readiness_verified": True,
            "rejection_reasons": [],
            "archive_integrity_verified": True,
            "archive_total_unique_rows": 10,
            "archive_total_occurrences": 10,
            "archive_chain_sha256": "a" * 64,
            "bounded_rows_snapshot_compare_verified": True,
            "verification_cost": (
                "O_TOTAL_ARCHIVE_BYTES_PLUS_SOURCE_SNAPSHOT_BYTES"
            ),
            "verification_memory_bound": "STREAMING_ROWS_PLUS_ONE_ROW",
        }

    monkeypatch.setattr(
        DurablePaperEvidenceArchive,
        "verified_latest_rows",
        verified_latest_rows,
    )
    loader = V2HybridTrainerDataLoader(
        io=_MemoryIO(),
        counterfactual_archive_path=archive_path,
    )

    rows, status = loader._bounded_feedback_rows(  # noqa: SLF001
        source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
        limit=3,
    )

    assert [row["ordinal"] for row in rows] == [7, 8, 9]
    assert len(rows) == 3
    assert calls == [(TRAINER_FEEDBACK_COUNTERFACTUALS_KEY, 3)]
    assert status["status"] == "DURABLE_ARCHIVE_READY_BOUNDED_ROWS"
    assert status["archive_integrity_verified"] is True
    assert status["archive_migration_complete"] is True
    assert status["archive_bounded_rows_snapshot_compare_verified"] is True


def test_counterfactual_archive_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "tampered.sqlite3"
    _archive(archive_path, rows=2)
    with sqlite3.connect(str(archive_path)) as connection:
        connection.execute(
            "UPDATE evidence_records SET payload_json = ? WHERE record_id = ?",
            ('{"ordinal":999}', "row-0001"),
        )
        connection.commit()
    loader = V2HybridTrainerDataLoader(
        io=_MemoryIO(),
        counterfactual_archive_path=archive_path,
    )

    rows, status = loader._bounded_feedback_rows(  # noqa: SLF001
        source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
        limit=2,
    )

    assert rows == []
    assert "DURABLE_ARCHIVE_REPLACEMENT_READINESS_UNPROVEN" in status["status"]
    assert any(
        "durable_archive_content_hash_mismatch" in reason
        for reason in status["archive_status"][
            "archive_readiness_rejection_reasons"
        ]
    )


def test_counterfactual_archive_replacement_readiness_missing_fails_closed(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "incomplete.sqlite3"
    _archive(archive_path, rows=2)
    loader = V2HybridTrainerDataLoader(
        io=_MemoryIO(),
        counterfactual_archive_path=archive_path,
    )

    rows, status = loader._bounded_feedback_rows(  # noqa: SLF001
        source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
        limit=2,
    )

    assert rows == []
    assert "DURABLE_ARCHIVE_REPLACEMENT_READINESS_UNPROVEN" in status["status"]
    assert status["archive_status"][
        "archive_readiness_rejection_reasons"
    ] == ["OUTCOME_RECEIPT_MISSING"]


def test_existing_unready_counterfactual_archive_never_falls_back_to_redis(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unready.sqlite3"
    _archive(archive_path, rows=2)
    io = _ForbiddenRedisFallbackIO()
    loader = V2HybridTrainerDataLoader(
        io=io,
        counterfactual_archive_path=archive_path,
    )

    rows, status = loader._bounded_feedback_rows(  # noqa: SLF001
        source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
        limit=2,
    )

    assert rows == []
    assert io.get_calls == 0
    assert status["redis_fallback_suppressed"] is True
    assert status["redis_read_attempted"] is False
    assert status["archive_fallback_used"] is False
    assert "DURABLE_ARCHIVE_REPLACEMENT_READINESS_UNPROVEN" in status[
        "status"
    ]


def _example(index: int, *, label_available_at: str) -> TrainingExample:
    tensor = FeatureTensorRecord(
        tensor_id=f"tensor-{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"snapshot-{index}",
        values=(float(index),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("close",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=1,
        label_expected_move_after_cost_bps=1.0,
        payload_keys=(f"row-{index}",),
        row_classification="TRAINABLE",
        decision_time="2026-07-18T00:00:00Z",
        label_available_at=label_available_at,
        trust_row={
            "decision_time": "2026-07-18T00:00:00Z",
            "label_available_at": label_available_at,
            "producer_trainer_consumable_claim_present": True,
            "producer_trainer_consumable_claim": True,
            "producer_trainer_consumable_literal_true": True,
            "accepted_for_training": True,
            "valid_for_training": True,
            "trainer_consumable": True,
            "reject_reasons": [],
        },
    )


def test_closed_trade_materialization_respects_hard_row_and_observation_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = V2HybridTrainerDataLoader(io=_MemoryIO())
    calls: list[tuple[str, int]] = []

    def bounded_rows(*, source_key: str, limit: int):
        calls.append((source_key, limit))
        if source_key != TRAINER_FEEDBACK_OUTCOMES_KEY:
            return [], {"source_key": source_key, "status": "EMPTY"}
        return [
            {"feature_snapshot_id": f"snapshot-{index}", "ordinal": index}
            for index in range(limit)
        ], {"source_key": source_key, "status": "BOUNDED"}

    monkeypatch.setenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "0")
    monkeypatch.setattr(data_loader_module, "_trainer_feedback_row_usable", lambda _row: True)
    monkeypatch.setattr(loader, "_bounded_feedback_rows", bounded_rows)
    monkeypatch.setattr(
        loader,
        "_closed_trade_feature_snapshot",
        lambda **_kwargs: ({"content_sha256": "a" * 64}, "unit"),
    )
    monkeypatch.setattr(
        loader,
        "_closed_trade_snapshot_training_example",
        lambda row, **_kwargs: _example(
            int(row["ordinal"]),
            label_available_at="2026-07-18T00:01:00Z",
        ),
    )

    examples = loader._closed_trade_snapshot_training_examples(  # noqa: SLF001
        limit=5,
        training_observed_at="2026-07-18T00:02:00Z",
    )

    assert len(examples) == 5
    assert calls == [(TRAINER_FEEDBACK_OUTCOMES_KEY, 5)]
    assert loader.last_closed_trade_load["hard_row_bound_respected"] is True
    assert loader.last_closed_trade_load["requested_max_rows"] == 5


def test_closed_trade_observation_cutoff_filters_bounded_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = V2HybridTrainerDataLoader(io=_MemoryIO())

    def bounded_rows(*, source_key: str, limit: int):
        if source_key != TRAINER_FEEDBACK_OUTCOMES_KEY:
            return [], {"source_key": source_key, "status": "EMPTY"}
        return [
            {"feature_snapshot_id": f"snapshot-{index}", "ordinal": index}
            for index in range(limit)
        ], {"source_key": source_key, "status": "BOUNDED"}

    monkeypatch.setenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "0")
    monkeypatch.setattr(data_loader_module, "_trainer_feedback_row_usable", lambda _row: True)
    monkeypatch.setattr(loader, "_bounded_feedback_rows", bounded_rows)
    monkeypatch.setattr(
        loader,
        "_closed_trade_feature_snapshot",
        lambda **_kwargs: ({"content_sha256": "a" * 64}, "unit"),
    )
    monkeypatch.setattr(
        loader,
        "_closed_trade_snapshot_training_example",
        lambda row, **_kwargs: _example(
            int(row["ordinal"]),
            label_available_at="2026-07-18T00:03:00Z",
        ),
    )

    examples = loader._closed_trade_snapshot_training_examples(  # noqa: SLF001
        limit=4,
        training_observed_at="2026-07-18T00:02:00Z",
    )

    assert examples == []
    assert loader.last_closed_trade_load[
        "rows_rejected_after_training_observation_cutoff"
    ] == 4
