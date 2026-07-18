from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_binance_kline_wss_loop as wss_module
from v2.backend.app.cli.v2_binance_kline_wss_loop import (
    _Canonical5mLabelAdmissionResult,
    _await_wss_canonical_5m_label_durability,
    _build_label_pipeline,
    _Canonical5mLabelArchivePipeline,
    _consume_chunk,
    _runtime_cycle_exit_code,
    _submit_wss_canonical_5m_label,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
)
from v2.backend.app.services.native_trainer.canonical_5m_label_outbox import (
    MAX_CLOSE_WAVE_ROWS,
    Canonical5mLabelOutbox,
    Canonical5mLabelOutboxConflictError,
    Canonical5mLabelOutboxError,
    canonical_json,
    deliver_pending_once,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    MAX_APPEND_ROWS,
    DurableCanonical5mLabelArchive,
)

BASE = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
REPRESENTATIVE_ADAPTIVE_WAVE_ROWS = 149


def _candle(
    index: int,
    *,
    symbol: str | None = None,
    timeframe: str = "5m",
    closed: bool = True,
    source: str = "binance_wss",
    raw_suffix: str = "primary",
) -> CanonicalCandle:
    selected_symbol = symbol or f"S{index:03d}USDT"
    open_at = BASE + timedelta(minutes=5)
    close_at = open_at + timedelta(minutes=5) - timedelta(milliseconds=1)
    event_at = close_at + timedelta(milliseconds=1)
    ingested_at = event_at + timedelta(milliseconds=1)
    close_price = 100.0 + index / 100.0
    raw_hash = hashlib.sha256(
        f"{selected_symbol}:{raw_suffix}".encode()
    ).hexdigest()
    return CanonicalCandle(
        symbol=selected_symbol,
        exchange="binance",
        timeframe=timeframe,
        candle_open_time=int(open_at.timestamp() * 1000),
        candle_close_time=int(close_at.timestamp() * 1000),
        event_time=int(event_at.timestamp() * 1000),
        ingested_at=int(ingested_at.timestamp() * 1000),
        available_at=int(ingested_at.timestamp() * 1000),
        is_closed=closed,
        source=source,
        source_sequence_id=f"wss:{selected_symbol}:{int(event_at.timestamp() * 1000)}",
        raw_payload_hash=raw_hash,
        ohlcv={
            "open": 100.0,
            "high": max(101.0, close_price),
            "low": 99.0,
            "close": close_price,
            "volume": 1_000.0 + index,
            "quote_volume": 100_000.0 + index,
            "num_trades": 100 + index,
            "taker_buy_base_vol": 400.0 + index,
            "taker_buy_quote_vol": 40_000.0 + index,
        },
        is_backfilled=False,
        feature_eligible=closed,
    )


def _payload(index: int, **kwargs: Any) -> dict[str, Any]:
    return _candle(index, **kwargs).to_dict()


def test_149_symbol_close_wave_is_outboxed_once_before_one_archive_append(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=REPRESENTATIVE_ADAPTIVE_WAVE_ROWS * 2,
    )
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    payload_jsons = tuple(
        Canonical5mLabelOutbox.exact_payload_json(_payload(index))
        for index in range(REPRESENTATIVE_ADAPTIVE_WAVE_ROWS)
    )

    enqueued = outbox.enqueue_payloads(payload_jsons)
    observed: dict[str, Any] = {"calls": 0}

    class AssertOutboxedBeforeArchive:
        def append_candles(self, payloads):
            observed["calls"] += 1
            observed["payload_bytes"] = tuple(
                canonical_json(payload) for payload in payloads
            )
            assert outbox.status_snapshot()["pending_rows"] == (
                REPRESENTATIVE_ADAPTIVE_WAVE_ROWS
            )
            return archive.append_candles(payloads)

    delivered = deliver_pending_once(
        outbox=outbox,
        archive=AssertOutboxedBeforeArchive(),  # type: ignore[arg-type]
        limit=REPRESENTATIVE_ADAPTIVE_WAVE_ROWS,
    )

    assert enqueued.inserted_rows == REPRESENTATIVE_ADAPTIVE_WAVE_ROWS
    assert enqueued.durable_readback_verified is True
    assert observed["calls"] == 1
    assert observed["payload_bytes"] == payload_jsons
    assert delivered is not None
    assert delivered.inserted_rows == REPRESENTATIVE_ADAPTIVE_WAVE_ROWS
    status = outbox.status_snapshot()
    assert status["outbox_transactions"] == 1
    assert status["pending_rows"] == 0
    assert status["delivered_rows"] == REPRESENTATIVE_ADAPTIVE_WAVE_ROWS


def test_empty_close_wave_is_rejected_without_zero_row_receipt(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )

    with pytest.raises(Canonical5mLabelOutboxError, match="close_wave_empty"):
        outbox.enqueue_payloads(())

    assert outbox.status_snapshot()["outbox_transactions"] == 0


def test_close_wave_resource_bound_tracks_archive_not_current_universe() -> None:
    assert MAX_CLOSE_WAVE_ROWS == MAX_APPEND_ROWS
    assert MAX_CLOSE_WAVE_ROWS > REPRESENTATIVE_ADAPTIVE_WAVE_ROWS


@pytest.mark.asyncio
async def test_pipeline_coalesces_full_149_symbol_wave_without_row_fsyncs(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=REPRESENTATIVE_ADAPTIVE_WAVE_ROWS,
        batch_rows=REPRESENTATIVE_ADAPTIVE_WAVE_ROWS,
        max_pending_rows=REPRESENTATIVE_ADAPTIVE_WAVE_ROWS * 2,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats=stats,
    )
    assert await pipeline.initialize() is True
    acknowledgements = [
        pipeline.submit(_payload(index))
        for index in range(REPRESENTATIVE_ADAPTIVE_WAVE_ROWS)
    ]
    assert all(not acknowledgement.done() for acknowledgement in acknowledgements)

    assert await pipeline.run_until(time.time()) is True
    results = await asyncio.gather(*acknowledgements)

    assert stats["canonical_5m_label_outbox_transactions"] == 1
    assert stats["canonical_5m_label_archive_transactions"] == 1
    assert all(result.durable_outbox_committed for result in results)
    status = pipeline.status_snapshot()
    assert status["memory_queue_depth"] == 0
    assert status["pending_rows"] == 0
    assert status["delivered_rows"] == REPRESENTATIVE_ADAPTIVE_WAVE_ROWS


@pytest.mark.asyncio
async def test_close_wave_uses_retry_idle_wait_then_10ms_post_first_join(
    tmp_path: Path,
) -> None:
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.5,
        stats={},
    )
    assert await pipeline.initialize() is True

    collector = asyncio.create_task(pipeline._collect_close_wave(None))
    await asyncio.sleep(0.04)
    assert collector.done() is False

    acknowledgement = pipeline.submit(_payload(150, symbol="BTCUSDT"))
    batch = await asyncio.wait_for(collector, timeout=0.1)
    assert len(batch) == 1
    assert batch[0].payload_json == Canonical5mLabelOutbox.exact_payload_json(
        _payload(150, symbol="BTCUSDT")
    )

    pipeline._retry_batch = batch
    assert await pipeline.run_until(time.time()) is True
    assert (await acknowledgement).durable_outbox_committed is True

    idle_collector = asyncio.create_task(pipeline._collect_close_wave(None))
    await asyncio.sleep(0)
    pipeline.request_stop()
    assert await asyncio.wait_for(idle_collector, timeout=0.1) == []


def test_restart_replays_identical_bytes_after_archive_commit_before_ack(
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.sqlite3"
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    payload_json = Canonical5mLabelOutbox.exact_payload_json(_payload(1))
    outbox = Canonical5mLabelOutbox(outbox_path, max_pending_rows=10)
    outbox.enqueue_payloads((payload_json,))
    before_crash = outbox.read_pending(limit=1)

    first = archive.append_candles(
        [json.loads(before_crash[0].payload_json)]
    )
    assert first.inserted_rows == 1
    # Simulated process crash: no outbox acknowledgement is made.
    reopened = Canonical5mLabelOutbox(outbox_path, max_pending_rows=10)
    after_restart = reopened.read_pending(limit=1)

    assert after_restart[0].payload_json == before_crash[0].payload_json
    replayed = deliver_pending_once(
        outbox=reopened,
        archive=archive,
        limit=1,
    )
    assert replayed is not None
    assert replayed.inserted_rows == 0
    assert replayed.duplicate_rows == 1
    assert reopened.status_snapshot()["pending_rows"] == 0


def test_delivery_ack_is_idempotent_for_overlapping_recovery_workers(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    payload_json = Canonical5mLabelOutbox.exact_payload_json(_payload(16))
    outbox.enqueue_payloads((payload_json,))
    rows = outbox.read_pending(limit=1)
    result = archive.append_candles([json.loads(rows[0].payload_json)])

    assert outbox.acknowledge_delivery(rows, result) == 0
    assert outbox.acknowledge_delivery(rows, result) == 0
    assert outbox.status_snapshot()["delivered_rows"] == 1


def test_archive_failure_keeps_exact_payload_pending_for_later_retry(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    payload_json = Canonical5mLabelOutbox.exact_payload_json(_payload(2))
    outbox.enqueue_payloads((payload_json,))

    class FailingArchive:
        def append_candles(self, payloads):
            assert tuple(canonical_json(row) for row in payloads) == (
                payload_json,
            )
            raise OSError("simulated archive disk failure")

    with pytest.raises(OSError, match="simulated archive disk failure"):
        deliver_pending_once(
            outbox=outbox,
            archive=FailingArchive(),  # type: ignore[arg-type]
            limit=1,
        )

    assert outbox.read_pending(limit=1)[0].payload_json == payload_json
    recovered = deliver_pending_once(outbox=outbox, archive=archive, limit=1)
    assert recovered is not None
    assert recovered.inserted_rows == 1


def test_delivery_ack_rejects_archive_result_for_different_exact_rows(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    wanted = Canonical5mLabelOutbox.exact_payload_json(
        _payload(19, symbol="BTCUSDT")
    )
    wrong = _payload(20, symbol="ETHUSDT")
    outbox.enqueue_payloads((wanted,))

    class WrongRowArchive:
        def append_candles(self, ignored_payloads):
            return archive.append_candles([wrong])

    with pytest.raises(
        Canonical5mLabelOutboxError,
        match="archive_append_result_unverified",
    ):
        deliver_pending_once(
            outbox=outbox,
            archive=WrongRowArchive(),  # type: ignore[arg-type]
            limit=1,
        )

    assert outbox.status_snapshot()["pending_rows"] == 1
    assert outbox.status_snapshot()["delivered_rows"] == 0


def test_changed_bytes_for_frozen_wss_slot_persist_fail_closed_blocker(
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.sqlite3"
    outbox = Canonical5mLabelOutbox(outbox_path, max_pending_rows=10)
    first = Canonical5mLabelOutbox.exact_payload_json(
        _payload(3, symbol="BTCUSDT")
    )
    changed = Canonical5mLabelOutbox.exact_payload_json(
        _payload(3, symbol="BTCUSDT", raw_suffix="changed")
    )
    outbox.enqueue_payloads((first,))

    with pytest.raises(
        Canonical5mLabelOutboxConflictError,
        match="WSS_SLOT_IDENTITY_CONFLICT",
    ):
        outbox.enqueue_payloads((changed,))

    reopened = Canonical5mLabelOutbox(outbox_path, max_pending_rows=10)
    status = reopened.status_snapshot()
    assert status["integrity_ok"] is False
    assert "WSS_SLOT_IDENTITY_CONFLICT" in status["integrity_blocker"]
    assert reopened.read_pending(limit=1)[0].payload_json == first


def test_same_primary_wss_fact_reingested_later_reuses_first_frozen_bytes(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    first_payload = _payload(12, symbol="BTCUSDT")
    replay_payload = dict(first_payload)
    replay_payload["ingested_at"] = int(first_payload["ingested_at"]) + 1_000
    replay_payload["available_at"] = replay_payload["ingested_at"]
    first = Canonical5mLabelOutbox.exact_payload_json(first_payload)
    later_reingestion = Canonical5mLabelOutbox.exact_payload_json(replay_payload)
    assert first != later_reingestion

    initial = outbox.enqueue_payloads((first,))
    replay = outbox.enqueue_payloads((later_reingestion,))

    assert initial.inserted_rows == 1
    assert replay.inserted_rows == 0
    assert replay.duplicate_rows == 1
    assert outbox.read_pending(limit=1)[0].payload_json == first


def test_same_primary_reconnect_inside_one_wave_freezes_first_exact_bytes(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    first_payload = _payload(17, symbol="BTCUSDT")
    replay_payload = dict(first_payload)
    replay_payload["ingested_at"] = int(first_payload["ingested_at"]) + 1_000
    replay_payload["available_at"] = replay_payload["ingested_at"]
    first = Canonical5mLabelOutbox.exact_payload_json(first_payload)
    replay = Canonical5mLabelOutbox.exact_payload_json(replay_payload)

    result = outbox.enqueue_payloads((first, replay))

    assert result.attempted_rows == 2
    assert result.inserted_rows == 1
    assert result.duplicate_rows == 1
    assert outbox.read_pending(limit=1)[0].payload_json == first


def test_changed_source_sequence_inside_one_wave_conflicts(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    first_payload = _payload(24, symbol="BTCUSDT")
    changed_payload = dict(first_payload)
    changed_payload["source_sequence_id"] = "different-wss-event"

    with pytest.raises(
        Canonical5mLabelOutboxConflictError,
        match="batch_identity_conflict",
    ):
        outbox.enqueue_payloads(
            (
                Canonical5mLabelOutbox.exact_payload_json(first_payload),
                Canonical5mLabelOutbox.exact_payload_json(changed_payload),
            )
        )


@pytest.mark.asyncio
async def test_pipeline_reconnect_duplicate_does_not_deadlock_or_false_block(
    tmp_path: Path,
) -> None:
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats={},
    )
    assert await pipeline.initialize() is True
    first_payload = _payload(26, symbol="BTCUSDT")
    replay_payload = dict(first_payload)
    replay_payload["ingested_at"] = int(first_payload["ingested_at"]) + 1_000
    replay_payload["available_at"] = replay_payload["ingested_at"]
    acknowledgements = (
        pipeline.submit(first_payload),
        pipeline.submit(replay_payload),
    )

    assert await pipeline.run_until(time.time()) is True
    results = await asyncio.gather(*acknowledgements)

    assert all(result.durable_outbox_committed for result in results)
    status = pipeline.status_snapshot()
    assert status["healthy"] is True
    assert status["memory_retry_batch_rows"] == 0
    assert status["pending_rows"] == 0
    assert status["delivered_rows"] == 1


def test_same_primary_reconnect_after_delivery_is_a_duplicate(
    tmp_path: Path,
) -> None:
    outbox = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    archive = DurableCanonical5mLabelArchive(tmp_path / "archive.sqlite3")
    first_payload = _payload(18, symbol="BTCUSDT")
    replay_payload = dict(first_payload)
    replay_payload["ingested_at"] = int(first_payload["ingested_at"]) + 1_000
    replay_payload["available_at"] = replay_payload["ingested_at"]
    first = Canonical5mLabelOutbox.exact_payload_json(first_payload)
    replay = Canonical5mLabelOutbox.exact_payload_json(replay_payload)
    outbox.enqueue_payloads((first,))
    assert deliver_pending_once(outbox=outbox, archive=archive, limit=1)

    duplicate = outbox.enqueue_payloads((replay,))

    assert duplicate.inserted_rows == 0
    assert duplicate.duplicate_rows == 1
    assert outbox.status_snapshot()["pending_rows"] == 0
    assert outbox.status_snapshot()["delivered_rows"] == 1


@pytest.mark.asyncio
async def test_memory_queue_overflow_is_persisted_and_pipeline_fails_closed(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=1,
        batch_rows=1,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats=stats,
    )
    assert await pipeline.initialize() is True

    first = pipeline.submit(_payload(4, symbol="BTCUSDT"))
    overflow = await pipeline.submit(_payload(5, symbol="ETHUSDT"))
    assert first.done() is False
    assert overflow.durable_outbox_committed is False
    assert overflow.state == "REJECTED_VOLATILE_QUEUE_OVERFLOW"
    assert await pipeline.run_until(time.time()) is False

    status = pipeline.status_snapshot()
    assert status["healthy"] is False
    assert "MEMORY_QUEUE_OVERFLOW" in status["blocked_reason"]
    reopened = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    assert "MEMORY_QUEUE_OVERFLOW" in (
        reopened.status_snapshot()["integrity_blocker"]
    )
    first_result = await first
    assert first_result.durable_outbox_committed is True


@pytest.mark.asyncio
async def test_generic_outbox_commit_failure_is_sticky_across_restart(
    tmp_path: Path,
) -> None:
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats={},
    )
    assert await pipeline.initialize() is True
    assert pipeline.outbox is not None

    def fail_commit(payloads):
        raise OSError("simulated fsync failure")

    pipeline.outbox.enqueue_payloads = fail_commit  # type: ignore[method-assign]
    acknowledgement = pipeline.submit(_payload(21, symbol="BTCUSDT"))

    assert await pipeline.run_until(time.time()) is False
    failed = await acknowledgement
    assert failed.durable_outbox_committed is False
    assert failed.state == "REJECTED_DURABLE_OUTBOX_COMMIT_FAILED"
    status = pipeline.status_snapshot()
    assert status["healthy"] is False
    assert status["volatile_rows_at_risk"] == 0
    assert "OUTBOX_COMMIT_FAILED" in status["blocked_reason"]

    reopened = Canonical5mLabelOutbox(
        tmp_path / "outbox.sqlite3",
        max_pending_rows=10,
    )
    assert "OUTBOX_COMMIT_FAILED" in str(
        reopened.status_snapshot()["integrity_blocker"]
    )
    rejected = await pipeline.submit(_payload(22, symbol="ETHUSDT"))
    assert rejected.state == "REJECTED_PIPELINE_INTEGRITY_BLOCKED"
    assert rejected.durable_outbox_committed is False
    assert pipeline.status_snapshot()["memory_queue_depth"] == 0


@pytest.mark.asyncio
async def test_pipeline_archive_error_is_visible_and_redis_path_can_continue(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats=stats,
    )
    assert await pipeline.initialize() is True

    class FailingArchive:
        def append_candles(self, payloads):
            raise OSError("archive unavailable")

    pipeline.archive = FailingArchive()  # type: ignore[assignment]
    first_ack = pipeline.submit(_payload(6, symbol="SOLUSDT"))
    assert await pipeline.run_until(time.time() + 0.05) is False
    assert (await first_ack).durable_outbox_committed is True

    status = pipeline.status_snapshot()
    assert status["healthy"] is False
    assert "ARCHIVE_APPEND_FAILED" in status["blocked_reason"]
    assert status["pending_rows"] == 1
    # The producer API reports failure without throwing into the independent
    # caller that performs the existing Redis write.
    second_ack = pipeline.submit(_payload(7, symbol="ETHUSDT"))
    pipeline.archive = DurableCanonical5mLabelArchive(
        tmp_path / "archive.sqlite3"
    )
    assert await pipeline.run_until(time.time() + 0.05) is True
    assert (await second_ack).durable_outbox_committed is True
    recovered = pipeline.status_snapshot()
    assert recovered["healthy"] is True
    assert recovered["blocked_reason"] is None
    assert recovered["pending_rows"] == 0
    assert recovered["delivered_rows"] == 2


@pytest.mark.asyncio
async def test_session_shutdown_flushes_all_already_admitted_queue_rows(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=2,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats=stats,
    )
    assert await pipeline.initialize() is True
    acknowledgements = [
        pipeline.submit(_payload(13, symbol="BTCUSDT")),
        pipeline.submit(_payload(14, symbol="ETHUSDT")),
        pipeline.submit(_payload(15, symbol="SOLUSDT")),
    ]

    assert await pipeline.run_until(time.time()) is True
    results = await asyncio.gather(*acknowledgements)
    assert all(result.durable_outbox_committed for result in results)

    status = pipeline.status_snapshot()
    assert status["memory_queue_depth"] == 0
    assert status["memory_retry_batch_rows"] == 0
    assert status["pending_rows"] == 0
    assert status["delivered_rows"] == 3
    assert status["healthy"] is True


def test_missing_enable_flag_never_constructs_or_initializes_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_constructor(*args, **kwargs):
        raise AssertionError("producer construction crossed default-off gate")

    monkeypatch.setattr(
        "v2.backend.app.cli.v2_binance_kline_wss_loop."
        "_Canonical5mLabelArchivePipeline",
        forbidden_constructor,
    )
    stats: dict[str, Any] = {}

    pipeline = _build_label_pipeline(argparse.Namespace(), stats)

    assert pipeline is None
    assert stats["canonical_5m_label_pipeline"]["enabled"] is False
    assert stats["canonical_5m_label_pipeline"]["healthy"] is False
    assert stats["canonical_5m_label_pipeline"]["blocked_reason"] == (
        "CANONICAL_5M_LABEL_PIPELINE_DISABLED"
    )


def test_enabled_unclean_shutdown_maps_to_nonzero_exit() -> None:
    assert _runtime_cycle_exit_code(
        label_pipeline_enabled=True,
        pipeline_clean=False,
        cycle_results=[None],
    ) == 2
    assert _runtime_cycle_exit_code(
        label_pipeline_enabled=False,
        pipeline_clean=False,
        cycle_results=[None],
    ) == 0
    assert _runtime_cycle_exit_code(
        label_pipeline_enabled=False,
        pipeline_clean=True,
        cycle_results=[RuntimeError("worker failed")],
    ) == 2


@pytest.mark.asyncio
async def test_explicit_enable_reports_enabled_and_initializes_off_loop(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    args = argparse.Namespace(
        enable_canonical_5m_label_archive=True,
        canonical_5m_label_archive_path=tmp_path / "archive.sqlite3",
        canonical_5m_label_outbox_path=tmp_path / "outbox.sqlite3",
        canonical_5m_label_queue_capacity=4,
        canonical_5m_label_batch_rows=4,
        canonical_5m_label_max_pending_rows=10,
        canonical_5m_label_close_wave_flush_seconds=0.01,
        canonical_5m_label_archive_retry_seconds=0.01,
    )

    pipeline = _build_label_pipeline(args, stats)

    assert pipeline is not None
    assert not (tmp_path / "outbox.sqlite3").exists()
    assert await pipeline.initialize() is True
    status = pipeline.status_snapshot()
    assert status["enabled"] is True
    assert status["initialized"] is True
    assert status["healthy"] is True
    assert (tmp_path / "outbox.sqlite3").exists()


@pytest.mark.asyncio
async def test_sqlite_init_enqueue_status_and_archive_append_stay_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_loop_thread = threading.get_ident()
    observed_threads: dict[str, list[int]] = {
        "initialize": [],
        "status": [],
        "enqueue": [],
        "archive": [],
    }
    original_outbox_class = wss_module.Canonical5mLabelOutbox

    def tracked_outbox(*args, **kwargs):
        observed_threads["initialize"].append(threading.get_ident())
        outbox = original_outbox_class(*args, **kwargs)
        original_status = outbox.status_snapshot

        def tracked_status():
            observed_threads["status"].append(threading.get_ident())
            return original_status()

        outbox.status_snapshot = tracked_status  # type: ignore[method-assign]
        return outbox

    monkeypatch.setattr(wss_module, "Canonical5mLabelOutbox", tracked_outbox)
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats={},
    )
    assert await pipeline.initialize() is True
    monkeypatch.setattr(
        wss_module,
        "Canonical5mLabelOutbox",
        original_outbox_class,
    )
    assert pipeline.outbox is not None
    assert pipeline.archive is not None
    original_enqueue = pipeline.outbox.enqueue_payloads
    original_append = pipeline.archive.append_candles

    def tracked_enqueue(payloads):
        observed_threads["enqueue"].append(threading.get_ident())
        return original_enqueue(payloads)

    def tracked_append(payloads):
        observed_threads["archive"].append(threading.get_ident())
        return original_append(payloads)

    pipeline.outbox.enqueue_payloads = tracked_enqueue  # type: ignore[method-assign]
    pipeline.archive.append_candles = tracked_append  # type: ignore[method-assign]
    acknowledgement = pipeline.submit(_payload(25, symbol="BTCUSDT"))

    assert await pipeline.run_until(time.time()) is True
    assert (await acknowledgement).durable_outbox_committed is True
    assert all(observed_threads.values())
    assert all(
        thread_id != event_loop_thread
        for thread_ids in observed_threads.values()
        for thread_id in thread_ids
    )


@pytest.mark.asyncio
async def test_handler_awaits_ack_that_resolves_only_after_durable_outbox(
    tmp_path: Path,
) -> None:
    stats: dict[str, Any] = {}
    pipeline = _Canonical5mLabelArchivePipeline(
        archive_path=tmp_path / "archive.sqlite3",
        outbox_path=tmp_path / "outbox.sqlite3",
        queue_capacity=4,
        batch_rows=4,
        max_pending_rows=10,
        flush_seconds=0.01,
        retry_seconds=0.01,
        stats=stats,
    )
    assert await pipeline.initialize() is True
    handler_wait = asyncio.create_task(
        _await_wss_canonical_5m_label_durability(
            _candle(23, symbol="BTCUSDT"),
            pipeline,
            stats,
        )
    )
    await asyncio.sleep(0)
    assert handler_wait.done() is False
    assert pipeline.status_snapshot()["durability_state"] == (
        "VOLATILE_PENDING_DURABLE_OUTBOX"
    )

    assert await pipeline.run_until(time.time()) is True
    result = await handler_wait

    assert result is not None
    assert result.durable_outbox_committed is True
    assert stats["canonical_5m_label_handler_durable_acks"] == 1


@pytest.mark.asyncio
async def test_message_handler_persists_redis_before_label_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    close_ms = int((BASE + timedelta(minutes=10)).timestamp() * 1000) - 1
    data = {
        "E": close_ms + 1,
        "k": {
            "s": "BTCUSDT",
            "i": "5m",
            "t": close_ms - 299_999,
            "T": close_ms,
            "o": "100",
            "h": "101",
            "l": "99",
            "c": "100.5",
            "v": "10",
            "q": "1005",
            "n": 10,
            "V": "4",
            "Q": "402",
            "B": "0",
            "x": True,
        },
    }

    class FakeRedis:
        def get(self, key):
            events.append("redis_get")
            return None

        def set(self, key, value, ex):
            events.append("redis_set")

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent = False

        async def recv(self):
            if not self.sent:
                self.sent = True
                return json.dumps({"data": data})
            await asyncio.Event().wait()

    class Connection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeWebsockets:
        @staticmethod
        def connect(*args, **kwargs):
            return Connection()

    class DurableSink:
        def submit(self, payload):
            assert "redis_set" in events
            events.append("label_submit")
            future = asyncio.get_running_loop().create_future()
            future.set_result(
                _Canonical5mLabelAdmissionResult(
                    state="DURABLE_OUTBOX_COMMITTED",
                    volatile_admitted=True,
                    durable_outbox_committed=True,
                    outbox_transaction_id="test-transaction",
                )
            )
            return future

    monkeypatch.setattr(wss_module, "websockets", FakeWebsockets())
    stats: dict[str, Any] = {}
    task = asyncio.create_task(
        _consume_chunk(
            chunk_id=0,
            streams=("btcusdt@kline_5m",),
            redis_client=FakeRedis(),
            stats=stats,
            ws_base="wss://example.invalid/",
            ttl_seconds=900,
            max_candles=10,
            max_seconds_per_session=60.0,
            stop_at=time.time() + 60.0,
            label_pipeline=DurableSink(),  # type: ignore[arg-type]
        )
    )
    for _ in range(100):
        if "label_submit" in events:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events.index("redis_set") < events.index("label_submit")
    assert stats["canonical_5m_label_handler_durable_acks"] == 1


def test_live_archive_admission_is_finalized_wss_5m_only() -> None:
    accepted: list[dict[str, Any]] = []

    class Sink:
        def submit(self, payload: dict[str, Any]) -> bool:
            accepted.append(payload)
            return True

    sink = Sink()
    assert _submit_wss_canonical_5m_label(
        _candle(8, symbol="BTCUSDT"), sink  # type: ignore[arg-type]
    ) is True
    assert _submit_wss_canonical_5m_label(
        _candle(9, symbol="ETHUSDT", timeframe="1m"),
        sink,  # type: ignore[arg-type]
    ) is None
    assert _submit_wss_canonical_5m_label(
        _candle(10, symbol="SOLUSDT", closed=False),
        sink,  # type: ignore[arg-type]
    ) is None
    assert _submit_wss_canonical_5m_label(
        _candle(11, symbol="XRPUSDT", source="binance_rest"),
        sink,  # type: ignore[arg-type]
    ) is None
    assert len(accepted) == 1
    assert accepted[0]["source"] == "binance_wss"
    assert accepted[0]["timeframe"] == "5m"
    assert accepted[0]["is_closed"] is True
