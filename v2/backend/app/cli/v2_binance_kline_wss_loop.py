"""V2 Binance USD-M kline websocket loop.

Read-only V2 service. It opens Binance Futures market websocket kline streams
and splits current/open klines from confirmed closed-candle storage.

Safety:
* writes only V2 Redis keys
* writes public status JSON only
* never calls REST
* never places/cancels/modifies orders
* never changes leverage or margin
* never enables live/canary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_wss,
    closed_candle_key,
    current_candle_key,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    CLOSED_WINDOW_MAX_ROWS,
    ClosedWindowRedisStoreError,
    ClosedWindowRedisWriteResult,
    atomic_merge_closed_window,
)
from v2.backend.app.services.native_trainer.canonical_5m_label_outbox import (
    DEFAULT_MAX_PENDING_ROWS,
    MAX_CLOSE_WAVE_ROWS,
    Canonical5mLabelOutbox,
    Canonical5mLabelOutboxConflictError,
    Canonical5mLabelOutboxOverflowError,
    OutboxEnqueueResult,
    default_outbox_path,
    deliver_pending_once,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveWriterLease,
    Canonical5mArchiveWriterLeaseError,
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.runtime_clock import est_now_iso
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


WORKER_ID = "v2_binance_kline_wss_loop"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
ROLLOVER_TIMING_POLICY = "SHORTEST_TIMEFRAME_MIDPOINT_WITH_BOUNDED_FALLBACK_V2"
ROLLOVER_GAP_CLASSIFICATION = "MITIGATION_NOT_CONTINUITY_PROOF"
ROLLOVER_EXACT_MIDPOINT_MODE = "EXACT_SHORTEST_TIMEFRAME_MIDPOINT"
ROLLOVER_MAXIMUM_FALLBACK_MODE = "BOUNDED_CONFIGURED_MAXIMUM_FALLBACK"
ROLLOVER_BOUNDARY_FALLBACK_MODE = "BOUNDED_HALF_WINDOW_BOUNDARY_FALLBACK"
WEBSOCKET_OPEN_TIMEOUT_MAX_SECONDS = 15.0
WEBSOCKET_CLOSE_TIMEOUT_MAX_SECONDS = 5.0
WEBSOCKET_CLOSE_TIMEOUT_MULTIPLIER_BOUND = 5.0
WEBSOCKET_CLOSE_RESERVE_DIVISOR = 10.0
WEBSOCKET_RETRY_SECONDS = 2.0
# Operator directive: preferred majors must ride the FIRST websocket
# connection so they stay covered even if later chunks degrade. This only
# reorders the resolved universe; it never adds or removes symbols.
PREFERRED_MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
# Volatile keys (current candle, source marker, heartbeat) keep a short TTL
# regardless of --ttl-seconds so stale-freshness detection still works when
# closed-candle history TTL is raised (closed candles are immutable facts).
VOLATILE_TTL_CAP_SECONDS = 900
REDIS_RECONNECT_INTERVAL_SECONDS = 15.0
DEFAULT_WS_BASE = "wss://fstream.binance.com/market/stream?streams="
DEFAULT_STATUS_PATH = Path("v2/frontend/public/operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json")
DEFAULT_PUBLIC_PATH = Path("v2/frontend/public/v2_binance_kline_wss/latest/operator_dashboard_payload.json")
DEFAULT_WORKLOG_PATH = Path("claude_worklog/final_readiness/v2_binance_kline_wss_runtime/latest/v2_binance_kline_wss_status.json")
# Multiple websocket chunks close the adaptive universe concurrently. Hold a
# short bounded wave window, capped only by the archive resource contract, so
# those facts share a durable transaction without freezing today's symbol count.
# Awaiting durability in each websocket chunk must not stall a five-second
# close wave. One short event-loop microbatch turn coalesces concurrent chunks
# while keeping the upstream websocket queues moving.
DEFAULT_LABEL_CLOSE_WAVE_FLUSH_SECONDS = 0.01
DEFAULT_LABEL_ARCHIVE_RETRY_SECONDS = 5.0
DEFAULT_LABEL_QUEUE_CAPACITY = MAX_CLOSE_WAVE_ROWS * 4
MAX_LABEL_QUEUE_CAPACITY = MAX_CLOSE_WAVE_ROWS * 8
CLOSED_WINDOW_MAX_STATUS_BLOCKED_KEYS = 4096


@dataclass(frozen=True)
class _Canonical5mLabelAdmissionResult:
    """An honest acknowledgement resolved only after durable outbox readback."""

    state: str
    volatile_admitted: bool
    durable_outbox_committed: bool
    reason: str | None = None
    outbox_transaction_id: str | None = None


@dataclass(frozen=True)
class _QueuedCanonical5mAdmission:
    payload_json: str
    acknowledgement: asyncio.Future[_Canonical5mLabelAdmissionResult]


@dataclass(frozen=True)
class _RolloverDeadlinePlan:
    """A deterministic close-boundary-avoiding transport deadline."""

    planned_at_epoch_seconds: float
    deadline_epoch_seconds: float
    planned_duration_seconds: float
    maximum_seconds: float
    shortest_timeframe_seconds: int
    close_boundary_distance_seconds: float
    plan_mode: str


def _est_iso() -> str:
    return est_now_iso()


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
        # Closed-window publication requires exact raw bytes so corrupt UTF-8
        # can fail closed or be repaired only by an explicitly authorized
        # recovery worker. JSON writers accept this binary-response client.
        client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_timeout=1.0,
        )
        client.ping()
        return client
    except Exception:
        return None


class _RedisHolder:
    """Redis handle that lazily reconnects.

    The loop previously connected exactly once at process start. When Redis
    (or name resolution at boot) was briefly unavailable, the process ran for
    the full --total-seconds window receiving millions of klines while
    persisting none of them (redis_ok=false, ohlcv_keys_written=0). This
    holder retries the connection at a bounded interval and drops broken
    clients so writes recover without a service restart.
    """

    def __init__(self) -> None:
        self._last_attempt = time.time()
        self.client: Any | None = _connect_redis()
        self.reconnects = 0

    @property
    def connected(self) -> bool:
        return self.client is not None

    def ensure(self) -> Any | None:
        if self.client is not None:
            return self.client
        now = time.time()
        if now - self._last_attempt < REDIS_RECONNECT_INTERVAL_SECONDS:
            return None
        self._last_attempt = now
        self.client = _connect_redis()
        if self.client is not None:
            self.reconnects += 1
        return self.client

    def mark_broken(self) -> None:
        client, self.client = self.client, None
        self._last_attempt = time.time()
        try:
            if client is not None:
                client.close()
        except Exception:
            pass


class _Canonical5mLabelArchivePipeline:
    """Bounded WSS-only close-wave queue feeding the durable label archive."""

    def __init__(
        self,
        *,
        archive_path: Path,
        outbox_path: Path,
        queue_capacity: int,
        batch_rows: int,
        max_pending_rows: int,
        flush_seconds: float,
        retry_seconds: float,
        stats: dict[str, Any],
    ) -> None:
        self.stats = stats
        self.archive_path = Path(archive_path)
        self.outbox_path = Path(outbox_path)
        configuration_error: str | None = None
        try:
            self.queue_capacity = self._bounded_int(
                queue_capacity,
                name="canonical_5m_label_queue_capacity",
                maximum=MAX_LABEL_QUEUE_CAPACITY,
            )
            self.batch_rows = self._bounded_int(
                batch_rows,
                name="canonical_5m_label_batch_rows",
                maximum=MAX_CLOSE_WAVE_ROWS,
            )
            self.flush_seconds = self._bounded_float(
                flush_seconds,
                name="canonical_5m_label_flush_seconds",
            )
            self.retry_seconds = self._bounded_float(
                retry_seconds,
                name="canonical_5m_label_retry_seconds",
            )
        except Exception as exc:
            self.queue_capacity = 1
            self.batch_rows = 1
            self.flush_seconds = DEFAULT_LABEL_CLOSE_WAVE_FLUSH_SECONDS
            self.retry_seconds = DEFAULT_LABEL_ARCHIVE_RETRY_SECONDS
            configuration_error = self._error_text(
                "CANONICAL_5M_LABEL_PIPELINE_CONFIGURATION_INVALID", exc
            )
        self.queue: asyncio.Queue[_QueuedCanonical5mAdmission] = asyncio.Queue(
            maxsize=self.queue_capacity
        )
        self.max_pending_rows = int(max_pending_rows)
        if (
            configuration_error is None
            and self.max_pending_rows < self.batch_rows
        ):
            configuration_error = (
                "canonical_5m_label_max_pending_rows_below_batch_rows"
            )
        self._configuration_error = configuration_error
        self._retry_batch: list[_QueuedCanonical5mAdmission] = []
        self._admission_futures: set[
            asyncio.Future[_Canonical5mLabelAdmissionResult]
        ] = set()
        self._last_outbox_status: dict[str, Any] = {}
        self._initialization_error: str | None = None
        self._outbox_error: str | None = None
        self._archive_error: str | None = None
        self._worker_error: str | None = None
        self._blocker_persistence_error: str | None = None
        self._sticky_blocker: str | None = None
        self._sticky_blocker_pending_persistence: str | None = None
        self._next_archive_retry_at = 0.0
        self._initialization_attempted = False
        self._initialized = False
        self._stop_requested = False
        self._wake_event = asyncio.Event()
        self.outbox: Canonical5mLabelOutbox | None = None
        self.archive: DurableCanonical5mLabelArchive | None = None
        self._writer_lease: Canonical5mArchiveWriterLease | None = None
        self._storage_tasks: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._closing = False
        self._publish_runtime_stats()

    async def initialize(self) -> bool:
        """Open SQLite state in a worker thread before accepting facts."""

        if self._initialization_attempted:
            return self._initialized
        self._initialization_attempted = True
        if self._configuration_error is not None:
            self._initialization_error = (
                "CANONICAL_5M_LABEL_PIPELINE_CONFIGURATION_INVALID:"
                f"{self._configuration_error}"
            )
            self._publish_runtime_stats()
            return False

        def _open_storage() -> tuple[
            Canonical5mLabelOutbox,
            DurableCanonical5mLabelArchive,
            Canonical5mArchiveWriterLease,
            dict[str, Any],
        ]:
            writer_lease = Canonical5mArchiveWriterLease.acquire(
                self.archive_path
            )
            try:
                outbox = Canonical5mLabelOutbox(
                    self.outbox_path,
                    max_pending_rows=self.max_pending_rows,
                )
                archive = DurableCanonical5mLabelArchive(
                    self.archive_path,
                    writer_lease=writer_lease,
                )
                return (
                    outbox,
                    archive,
                    writer_lease,
                    outbox.status_snapshot(),
                )
            except Exception:
                writer_lease.release()
                raise

        open_storage_task = asyncio.create_task(asyncio.to_thread(_open_storage))
        try:
            (
                self.outbox,
                self.archive,
                self._writer_lease,
                self._last_outbox_status,
            ) = await asyncio.shield(open_storage_task)
            self._initialized = True
            persistent = self._last_outbox_status.get("integrity_blocker")
            if persistent:
                self._sticky_blocker = str(persistent)
            if int(self._last_outbox_status.get("pending_rows") or 0) > 0:
                self._archive_error = (
                    "CANONICAL_5M_LABEL_OUTBOX_RECOVERY_PENDING"
                )
        except asyncio.CancelledError:
            # ``to_thread`` cannot be force-cancelled after it starts.  Wait
            # for its bounded SQLite open in an independent task callback.  A
            # second cancellation of this caller therefore cannot interrupt
            # lease release and orphan the raw file descriptor/flock.
            self._initialization_error = (
                "CANONICAL_5M_LABEL_PIPELINE_INITIALIZATION_CANCELLED"
            )

            def _release_cancelled_open(
                completed: asyncio.Task[
                    tuple[
                        Canonical5mLabelOutbox,
                        DurableCanonical5mLabelArchive,
                        Canonical5mArchiveWriterLease,
                        dict[str, Any],
                    ]
                ],
            ) -> None:
                try:
                    opened = completed.result()
                    opened[2].release()
                except BaseException as cleanup_exc:
                    self._initialization_error = self._error_text(
                        "CANONICAL_5M_LABEL_CANCELLED_INITIALIZATION_CLEANUP_FAILED",
                        cleanup_exc,
                    )
                self._publish_runtime_stats()

            open_storage_task.add_done_callback(_release_cancelled_open)
            self._publish_runtime_stats()
            raise
        except Exception as exc:
            self._initialization_error = self._error_text(
                "CANONICAL_5M_LABEL_PIPELINE_INITIALIZATION_FAILED", exc
            )
        self._publish_runtime_stats()
        return self._initialized

    async def close(self) -> None:
        """Drain every worker-thread storage call before releasing the lease."""

        if self._close_task is None:
            self._closing = True
            self._initialized = False
            self._stop_requested = True
            self._wake_event.set()
            self._close_task = asyncio.create_task(
                self._drain_storage_and_release()
            )
        await asyncio.shield(self._close_task)

    async def _drain_storage_and_release(self) -> None:
        storage_errors: list[BaseException] = []
        while self._storage_tasks:
            results = await asyncio.gather(
                *tuple(self._storage_tasks),
                return_exceptions=True,
            )
            storage_errors.extend(
                result
                for result in results
                if isinstance(result, BaseException)
            )
        if storage_errors:
            self._worker_error = self._error_text(
                "CANONICAL_5M_LABEL_STORAGE_DRAIN_FAILED",
                storage_errors[0],
            )

        writer_lease, self._writer_lease = self._writer_lease, None
        self.archive = None
        if writer_lease is not None:
            writer_lease.release()
        self._publish_runtime_stats()

    async def _run_storage_call(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self._closing:
            raise RuntimeError("CANONICAL_5M_LABEL_PIPELINE_CLOSING")
        task = asyncio.create_task(
            asyncio.to_thread(function, *args, **kwargs)
        )
        self._storage_tasks.add(task)
        task.add_done_callback(self._storage_tasks.discard)
        return await asyncio.shield(task)

    @staticmethod
    def _bounded_int(value: int, *, name: str, maximum: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > maximum
        ):
            raise ValueError(f"{name}_outside_1_to_{maximum}")
        return value

    @staticmethod
    def _bounded_float(value: float, *, name: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0.0 or parsed > 60.0:
            raise ValueError(f"{name}_outside_0_to_60_seconds")
        return parsed

    @staticmethod
    def _error_text(prefix: str, exc: BaseException) -> str:
        detail = str(exc).replace("\n", " ")[:300]
        return f"{prefix}:{type(exc).__name__}:{detail}"

    async def _refresh_outbox_status(self) -> None:
        if self.outbox is None:
            return
        self._last_outbox_status = await self._run_storage_call(
            self.outbox.status_snapshot
        )
        persistent = self._last_outbox_status.get("integrity_blocker")
        if persistent:
            self._sticky_blocker = str(persistent)

    def _publish_runtime_stats(self) -> None:
        self.stats["canonical_5m_label_pipeline"] = self.status_snapshot()

    def _mark_sticky_blocker(self, reason: str) -> None:
        normalized = str(reason)[:500]
        self._sticky_blocker = self._sticky_blocker or normalized
        self._sticky_blocker_pending_persistence = (
            self._sticky_blocker_pending_persistence or normalized
        )

    async def _flush_sticky_blocker(self) -> None:
        reason = self._sticky_blocker_pending_persistence
        if reason is None or self.outbox is None:
            return
        try:
            await self._run_storage_call(
                self.outbox.record_integrity_blocker,
                reason,
            )
            self._sticky_blocker_pending_persistence = None
            self._blocker_persistence_error = None
            await self._refresh_outbox_status()
        except Exception as exc:
            self._blocker_persistence_error = self._error_text(
                "CANONICAL_5M_LABEL_BLOCKER_PERSIST_FAILED", exc
            )

    @staticmethod
    def _resolve_immediately(
        result: _Canonical5mLabelAdmissionResult,
    ) -> asyncio.Future[_Canonical5mLabelAdmissionResult]:
        future = asyncio.get_running_loop().create_future()
        future.set_result(result)
        return future

    def submit(
        self,
        payload: dict[str, Any],
    ) -> asyncio.Future[_Canonical5mLabelAdmissionResult]:
        """Queue a fact and return an acknowledgement future, never a false ack."""

        self.stats["canonical_5m_label_candidates"] = int(
            self.stats.get("canonical_5m_label_candidates") or 0
        ) + 1
        if self._sticky_blocker is not None:
            self.stats["canonical_5m_label_candidates_rejected"] = int(
                self.stats.get("canonical_5m_label_candidates_rejected") or 0
            ) + 1
            return self._resolve_immediately(
                _Canonical5mLabelAdmissionResult(
                    state="REJECTED_PIPELINE_INTEGRITY_BLOCKED",
                    volatile_admitted=False,
                    durable_outbox_committed=False,
                    reason=self._sticky_blocker,
                )
            )
        if not self._initialized:
            self.stats["canonical_5m_label_candidates_rejected"] = int(
                self.stats.get("canonical_5m_label_candidates_rejected") or 0
            ) + 1
            self._publish_runtime_stats()
            return self._resolve_immediately(
                _Canonical5mLabelAdmissionResult(
                    state="REJECTED_PIPELINE_NOT_INITIALIZED",
                    volatile_admitted=False,
                    durable_outbox_committed=False,
                    reason=(
                        self._initialization_error
                        or "CANONICAL_5M_LABEL_PIPELINE_NOT_INITIALIZED"
                    ),
                )
            )
        try:
            payload_json = Canonical5mLabelOutbox.exact_payload_json(payload)
        except Exception as exc:
            reason = self._error_text(
                "CANONICAL_5M_WSS_PAYLOAD_VALIDATION_FAILED", exc
            )
            self._mark_sticky_blocker(reason)
            self.stats["canonical_5m_label_candidates_rejected"] = int(
                self.stats.get("canonical_5m_label_candidates_rejected") or 0
            ) + 1
            self._publish_runtime_stats()
            return self._resolve_immediately(
                _Canonical5mLabelAdmissionResult(
                    state="REJECTED_INVALID_CANONICAL_FACT",
                    volatile_admitted=False,
                    durable_outbox_committed=False,
                    reason=reason,
                )
            )
        acknowledgement = asyncio.get_running_loop().create_future()
        admission = _QueuedCanonical5mAdmission(
            payload_json=payload_json,
            acknowledgement=acknowledgement,
        )
        try:
            self.queue.put_nowait(admission)
        except asyncio.QueueFull:
            reason = (
                "CANONICAL_5M_LABEL_MEMORY_QUEUE_OVERFLOW:"
                f"capacity={self.queue_capacity}"
            )
            self._mark_sticky_blocker(reason)
            self.stats["canonical_5m_label_candidates_dropped"] = int(
                self.stats.get("canonical_5m_label_candidates_dropped") or 0
            ) + 1
            self._publish_runtime_stats()
            acknowledgement.set_result(
                _Canonical5mLabelAdmissionResult(
                    state="REJECTED_VOLATILE_QUEUE_OVERFLOW",
                    volatile_admitted=False,
                    durable_outbox_committed=False,
                    reason=reason,
                )
            )
            return acknowledgement
        self._wake_event.set()
        self._admission_futures.add(acknowledgement)
        self.stats["canonical_5m_label_candidates_queued"] = int(
            self.stats.get("canonical_5m_label_candidates_queued") or 0
        ) + 1
        self._publish_runtime_stats()
        return acknowledgement

    async def _persist_batch(
        self,
        batch: list[_QueuedCanonical5mAdmission],
    ) -> OutboxEnqueueResult | None:
        assert self.outbox is not None
        try:
            result = await self._run_storage_call(
                self.outbox.enqueue_payloads,
                tuple(item.payload_json for item in batch),
            )
            if result.durable_readback_verified is not True:
                raise RuntimeError("outbox_durable_readback_unverified")
            self.stats["canonical_5m_label_outbox_transactions"] = int(
                self.stats.get("canonical_5m_label_outbox_transactions") or 0
            ) + 1
            self.stats["canonical_5m_label_outboxed_rows"] = int(
                self.stats.get("canonical_5m_label_outboxed_rows") or 0
            ) + result.inserted_rows
            self.stats["canonical_5m_label_outbox_duplicate_rows"] = int(
                self.stats.get("canonical_5m_label_outbox_duplicate_rows") or 0
            ) + result.duplicate_rows
            self.stats["canonical_5m_label_outbox_last_transaction_id"] = (
                result.transaction_id
            )
            self.stats["canonical_5m_label_outbox_last_batch_sha256"] = (
                result.batch_sha256
            )
            self.stats["canonical_5m_label_outbox_last_attempted_rows"] = (
                result.attempted_rows
            )
            self.stats["canonical_5m_label_outbox_last_inserted_rows"] = (
                result.inserted_rows
            )
            self._last_outbox_status = {
                **self._last_outbox_status,
                "pending_rows": result.pending_rows,
                "outbox_transactions": int(
                    self._last_outbox_status.get("outbox_transactions") or 0
                )
                + 1,
            }
            self._outbox_error = None
            return result
        except (
            Canonical5mLabelOutboxConflictError,
            Canonical5mLabelOutboxOverflowError,
        ) as exc:
            reason = self._error_text(
                "CANONICAL_5M_LABEL_OUTBOX_COMMIT_FAILED", exc
            )
            self._outbox_error = reason
            self._mark_sticky_blocker(reason)
            self.stats["canonical_5m_label_outbox_failures"] = int(
                self.stats.get("canonical_5m_label_outbox_failures") or 0
            ) + 1
            await self._flush_sticky_blocker()
            return None
        except Exception as exc:
            self._outbox_error = self._error_text(
                "CANONICAL_5M_LABEL_OUTBOX_COMMIT_FAILED", exc
            )
            self._mark_sticky_blocker(self._outbox_error)
            self.stats["canonical_5m_label_outbox_failures"] = int(
                self.stats.get("canonical_5m_label_outbox_failures") or 0
            ) + 1
            await self._flush_sticky_blocker()
            return None
        finally:
            self._publish_runtime_stats()

    async def _deliver_pending(self, *, force: bool = False) -> None:
        if self.outbox is None or self.archive is None:
            return
        now = time.monotonic()
        if not force and now < self._next_archive_retry_at:
            return
        self._next_archive_retry_at = now + self.retry_seconds
        delivered_any = False
        try:
            # Drain in bounded transactions. Yield between waves so websocket
            # consumers and Redis persistence cannot be starved by recovery.
            for _ in range(4):
                delivered = await self._run_storage_call(
                    deliver_pending_once,
                    outbox=self.outbox,
                    archive=self.archive,
                    limit=self.batch_rows,
                )
                if delivered is None:
                    break
                delivered_any = True
                self.stats["canonical_5m_label_archive_transactions"] = int(
                    self.stats.get(
                        "canonical_5m_label_archive_transactions"
                    )
                    or 0
                ) + 1
                self.stats["canonical_5m_label_archive_inserted_rows"] = int(
                    self.stats.get(
                        "canonical_5m_label_archive_inserted_rows"
                    )
                    or 0
                ) + delivered.inserted_rows
                self.stats["canonical_5m_label_archive_duplicate_rows"] = int(
                    self.stats.get(
                        "canonical_5m_label_archive_duplicate_rows"
                    )
                    or 0
                ) + delivered.duplicate_rows
                self.stats["canonical_5m_label_archive_last_transaction_id"] = (
                    delivered.archive_transaction_id
                )
                self.stats[
                    "canonical_5m_label_archive_last_append_receipt_sha256"
                ] = delivered.archive_append_receipt_sha256
                await asyncio.sleep(0)
            await self._refresh_outbox_status()
            pending_rows = int(
                self._last_outbox_status.get("pending_rows") or 0
            )
            if pending_rows == 0:
                self._archive_error = None
                self._next_archive_retry_at = 0.0
            else:
                self._archive_error = (
                    "CANONICAL_5M_LABEL_OUTBOX_RECOVERY_PENDING"
                )
                if delivered_any:
                    self._next_archive_retry_at = 0.0
        except Exception as exc:
            self._archive_error = self._error_text(
                "CANONICAL_5M_LABEL_ARCHIVE_APPEND_FAILED", exc
            )
            self.stats["canonical_5m_label_archive_failures"] = int(
                self.stats.get("canonical_5m_label_archive_failures") or 0
            ) + 1
            self._next_archive_retry_at = time.monotonic() + self.retry_seconds
        finally:
            self._publish_runtime_stats()

    async def _collect_close_wave(
        self,
        stop_at: float | None,
    ) -> list[_QueuedCanonical5mAdmission]:
        if self._retry_batch:
            return list(self._retry_batch)
        remaining = (
            self.retry_seconds if stop_at is None else stop_at - time.time()
        )
        if remaining <= 0.0 or self._stop_requested:
            return []
        if self.queue.empty():
            # Idle waits follow the archive retry cadence, not the 10ms
            # post-first-item coalescing window. The explicit wake event makes
            # both a new admission and graceful shutdown prompt without a
            # high-frequency empty-queue poll loop.
            self._wake_event.clear()
            if self.queue.empty() and not self._stop_requested:
                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=min(self.retry_seconds, remaining),
                    )
                except TimeoutError:
                    return []
        if self._stop_requested:
            return []
        try:
            first = self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return []
        batch = [first]
        wave_deadline = time.monotonic() + self.flush_seconds
        while len(batch) < self.batch_rows:
            timeout = wave_deadline - time.monotonic()
            if timeout <= 0.0:
                break
            try:
                batch.append(
                    await asyncio.wait_for(self.queue.get(), timeout=timeout)
                )
            except TimeoutError:
                break
        return batch

    def _take_available_close_wave(
        self,
    ) -> list[_QueuedCanonical5mAdmission]:
        if self._retry_batch:
            return list(self._retry_batch)
        batch: list[_QueuedCanonical5mAdmission] = []
        while len(batch) < self.batch_rows:
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def _complete_durable_admissions(
        self,
        batch: list[_QueuedCanonical5mAdmission],
        result: OutboxEnqueueResult,
    ) -> None:
        acknowledgement = _Canonical5mLabelAdmissionResult(
            state="DURABLE_OUTBOX_COMMITTED",
            volatile_admitted=True,
            durable_outbox_committed=True,
            outbox_transaction_id=result.transaction_id,
        )
        for item in batch:
            if not item.acknowledgement.done():
                item.acknowledgement.set_result(acknowledgement)
            self._admission_futures.discard(item.acknowledgement)
            self.queue.task_done()
        self.stats["canonical_5m_label_durable_acknowledgements"] = int(
            self.stats.get(
                "canonical_5m_label_durable_acknowledgements"
            )
            or 0
        ) + len(batch)

    def _fail_blocked_admissions(
        self,
        batch: list[_QueuedCanonical5mAdmission],
    ) -> None:
        reason = self._sticky_blocker or self._outbox_error or (
            "CANONICAL_5M_LABEL_OUTBOX_COMMIT_FAILED"
        )
        acknowledgement = _Canonical5mLabelAdmissionResult(
            state="REJECTED_DURABLE_OUTBOX_COMMIT_FAILED",
            volatile_admitted=True,
            durable_outbox_committed=False,
            reason=reason,
        )
        for item in batch:
            if not item.acknowledgement.done():
                item.acknowledgement.set_result(acknowledgement)
            self._admission_futures.discard(item.acknowledgement)
            self.queue.task_done()

    def request_stop(self) -> None:
        self._stop_requested = True
        self._wake_event.set()

    async def run_until(self, stop_at: float | None) -> bool:
        """Recover first, then coalesce/persist/deliver close waves."""

        if not self._initialized:
            self._publish_runtime_stats()
            return False
        self._stop_requested = False
        self._wake_event.clear()
        try:
            await self._flush_sticky_blocker()
            await self._deliver_pending(force=True)
            while not self._stop_requested and (
                stop_at is None or time.time() < stop_at
            ):
                batch = await self._collect_close_wave(stop_at)
                if not batch:
                    await self._flush_sticky_blocker()
                    await self._deliver_pending()
                    continue
                if not self._retry_batch:
                    self._retry_batch = list(batch)
                result = await self._persist_batch(self._retry_batch)
                if result is not None:
                    completed = list(self._retry_batch)
                    self._complete_durable_admissions(completed, result)
                    self._retry_batch.clear()
                    await self._deliver_pending(force=True)
                else:
                    if self._sticky_blocker is not None:
                        blocked = list(self._retry_batch)
                        self._fail_blocked_admissions(blocked)
                        self._retry_batch.clear()
                        await self._deliver_pending(force=True)
                        continue
                    await self._deliver_pending(force=True)
                    await asyncio.sleep(
                        self.retry_seconds
                        if stop_at is None
                        else min(
                            self.retry_seconds,
                            max(0.0, stop_at - time.time()),
                        )
                    )
            # Drain every already-admitted row in bounded close-wave commits.
            # If a commit fails, its exact bytes stay in retry_batch and the
            # status remains blocked rather than silently claiming shutdown.
            while self._retry_batch or not self.queue.empty():
                batch = self._take_available_close_wave()
                if not batch:
                    break
                if not self._retry_batch:
                    self._retry_batch = list(batch)
                result = await self._persist_batch(self._retry_batch)
                if result is not None:
                    completed = list(self._retry_batch)
                    self._complete_durable_admissions(completed, result)
                    self._retry_batch.clear()
                    await self._deliver_pending(force=True)
                    continue
                if self._sticky_blocker is not None:
                    blocked = list(self._retry_batch)
                    self._fail_blocked_admissions(blocked)
                    self._retry_batch.clear()
                await self._deliver_pending(force=True)
                break
            for _ in range(
                max(1, math.ceil(self.max_pending_rows / self.batch_rows))
            ):
                await self._deliver_pending(force=True)
                if int(
                    self._last_outbox_status.get("pending_rows") or 0
                ) == 0:
                    break
                if self._archive_error and not self._archive_error.endswith(
                    "RECOVERY_PENDING"
                ):
                    break
            await self._flush_sticky_blocker()
        except asyncio.CancelledError:
            volatile_rows = self.queue.qsize() + len(self._retry_batch)
            if volatile_rows:
                self._worker_error = (
                    "CANONICAL_5M_LABEL_WORKER_CANCELLED_WITH_VOLATILE_ROWS:"
                    f"{volatile_rows}"
                )
            self._publish_runtime_stats()
            raise
        except Exception as exc:
            self._worker_error = self._error_text(
                "CANONICAL_5M_LABEL_WORKER_CRASHED", exc
            )
            self.stats["canonical_5m_label_worker_crashes"] = int(
                self.stats.get("canonical_5m_label_worker_crashes") or 0
            ) + 1
        finally:
            self._publish_runtime_stats()
        return self.status_snapshot()["healthy"] is True

    def status_snapshot(self) -> dict[str, Any]:
        persistent = self._last_outbox_status.get("integrity_blocker")
        outbox_status = dict(self._last_outbox_status)
        volatile_rows = self.queue.qsize() + len(self._retry_batch)
        pending_rows = int(outbox_status.get("pending_rows") or 0)
        runtime_error = next(
            (
                value
                for value in (
                    self._initialization_error,
                    self._blocker_persistence_error,
                    self._worker_error,
                    self._outbox_error,
                    self._archive_error,
                )
                if value
            ),
            None,
        )
        blocker = self._sticky_blocker or persistent or runtime_error
        writer_lease = self._writer_lease
        writer_lease_contract: dict[str, Any] | None = None
        if writer_lease is not None:
            try:
                writer_lease_contract = writer_lease.contract()
            except Canonical5mArchiveWriterLeaseError:
                writer_lease_contract = None
        writer_lease_held = writer_lease_contract is not None
        if blocker is None and self._initialized and not writer_lease_held:
            blocker = "CANONICAL_5M_LABEL_ARCHIVE_WRITER_LEASE_NOT_HELD"
        if blocker is None and volatile_rows:
            blocker = (
                "CANONICAL_5M_LABEL_VOLATILE_ADMISSION_PENDING_DURABLE_OUTBOX:"
                f"{volatile_rows}"
            )
        if blocker is None and pending_rows:
            blocker = "CANONICAL_5M_LABEL_OUTBOX_RECOVERY_PENDING"
        return {
            "schema_version": "canonical_5m_wss_label_pipeline_v1",
            "enabled": True,
            "initialization_attempted": self._initialization_attempted,
            "initialized": self._initialized,
            "healthy": (
                self._initialized and writer_lease_held and blocker is None
            ),
            "blocked_reason": blocker,
            "runtime_error": runtime_error,
            "sticky_integrity_blocker": self._sticky_blocker or persistent,
            "sticky_blocker_persistence_pending": (
                self._sticky_blocker_pending_persistence is not None
            ),
            "source_authority": "BINANCE_WSS_FINALIZED_5M_ONLY",
            "rest_recovery_used": False,
            "redis_used_as_archive_source": False,
            "exact_payload_outbox_before_archive": True,
            "admission_ack_contract": (
                "SUCCESS_RESOLVES_ONLY_AFTER_SQLITE_FULL_SYNC_COMMIT_READBACK"
            ),
            "durability_state": (
                "VOLATILE_PENDING_DURABLE_OUTBOX"
                if volatile_rows
                else "NO_VOLATILE_ADMISSIONS"
            ),
            "volatile_rows_at_risk": volatile_rows,
            "unresolved_admission_acknowledgements": len(
                self._admission_futures
            ),
            "archive_path": str(self.archive_path),
            "archive_writer_lease_held": writer_lease_held,
            "archive_writer_lease_contract": writer_lease_contract,
            "outbox_path": str(self.outbox_path),
            "memory_queue_depth": self.queue.qsize(),
            "memory_retry_batch_rows": len(self._retry_batch),
            "memory_queue_capacity": self.queue_capacity,
            "archive_batch_rows": self.batch_rows,
            "close_wave_flush_seconds": self.flush_seconds,
            "archive_retry_seconds": self.retry_seconds,
            "pending_rows": pending_rows,
            "delivered_rows": int(outbox_status.get("delivered_rows") or 0),
            "max_pending_rows": outbox_status.get("max_pending_rows"),
            "outbox": outbox_status,
        }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_status(payload: dict[str, Any], paths: tuple[Path, ...]) -> None:
    for path in paths:
        _write_json(path, payload)


def _parse_csv(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return default
    out = tuple(part.strip() for part in raw.split(",") if part.strip())
    return out or default


def _resolve_symbols(raw: str | None, *, max_symbols: int) -> tuple[str, ...]:
    explicit = None
    if raw and raw.strip().lower() not in {"auto", "all", "universe"}:
        explicit = raw
    symbols = tuple(resolve_symbols(explicit=explicit))
    majors = tuple(symbol for symbol in PREFERRED_MAJOR_SYMBOLS if symbol in symbols)
    symbols = majors + tuple(symbol for symbol in symbols if symbol not in majors)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    return symbols


def _ohlcv_key(symbol: str, timeframe: str) -> str:
    return closed_candle_key("binance", symbol, timeframe)


def _current_key(symbol: str, timeframe: str) -> str:
    return current_candle_key("binance", symbol, timeframe)


def _heartbeat_key() -> str:
    return "v2:market:ohlcv:binance:kline_wss:heartbeat"


def _source_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv:binance:{symbol}:{timeframe}:source"


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    client = redis_client.ensure() if isinstance(redis_client, _RedisHolder) else redis_client
    if client is None:
        return False
    if not key.startswith("v2:"):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    try:
        client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
    except Exception:
        if isinstance(redis_client, _RedisHolder):
            redis_client.mark_broken()
        return False
    return True


def _to_kline_row(message: dict[str, Any]) -> tuple[str, str, list[Any]] | None:
    kline = message.get("k")
    if not isinstance(kline, dict):
        return None
    symbol = str(kline.get("s") or message.get("s") or "").upper()
    timeframe = str(kline.get("i") or "")
    if not symbol or not timeframe:
        return None
    try:
        open_time = int(kline["t"])
        close_time = int(kline["T"])
    except Exception:
        return None
    row = [
        open_time,
        str(kline.get("o") or "0"),
        str(kline.get("h") or "0"),
        str(kline.get("l") or "0"),
        str(kline.get("c") or "0"),
        str(kline.get("v") or "0"),
        close_time,
        str(kline.get("q") or "0"),
        int(kline.get("n") or 0),
        str(kline.get("V") or "0"),
        str(kline.get("Q") or "0"),
        str(kline.get("B") or "0"),
    ]
    return symbol, timeframe, row


def _merge_row(existing: Any, row: list[Any], *, max_candles: int) -> list[Any]:
    rows = existing if isinstance(existing, list) else []
    by_open: dict[int, Any] = {}
    for item in rows:
        if not isinstance(item, list) or not item:
            continue
        try:
            by_open[int(item[0])] = item
        except Exception:
            continue
    by_open[int(row[0])] = row
    return [by_open[key] for key in sorted(by_open)][-max(1, int(max_candles)) :]


def _stream_chunks(symbols: tuple[str, ...], timeframes: tuple[str, ...], max_streams: int) -> list[tuple[str, ...]]:
    streams = tuple(f"{symbol.lower()}@kline_{timeframe}" for symbol in symbols for timeframe in timeframes)
    chunk_size = max(1, int(max_streams))
    return [streams[index : index + chunk_size] for index in range(0, len(streams), chunk_size)]


def _runtime_stream_plan(
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], tuple[str, ...], list[tuple[str, ...]]]:
    """Resolve the current adaptive universe into one exact stream plan."""

    symbols = _resolve_symbols(args.symbols, max_symbols=int(args.max_symbols))
    timeframes = _parse_csv(args.timeframes, DEFAULT_TIMEFRAMES)
    max_candles = getattr(args, "max_candles", 100)
    if type(max_candles) is not int or not 1 <= max_candles <= CLOSED_WINDOW_MAX_ROWS:
        raise ValueError("closed_window_max_candles_invalid")
    if any(timeframe not in SUPPORTED_TRAINER_TIMEFRAMES for timeframe in timeframes):
        raise ValueError("closed_window_timeframe_unsupported")
    if len(symbols) * len(timeframes) > CLOSED_WINDOW_MAX_STATUS_BLOCKED_KEYS:
        raise ValueError("closed_window_stream_count_exceeds_status_resource_bound")
    chunks = _stream_chunks(
        symbols,
        timeframes,
        max_streams=int(args.max_streams_per_connection),
    )
    return symbols, timeframes, chunks


def _closed_window_status_blocker(stats: dict[str, Any]) -> str | None:
    blocked = stats.get("ohlcv_closed_blocked_keys")
    if not isinstance(blocked, dict) or not blocked:
        return None
    first_key = sorted(str(key) for key in blocked)[0]
    reason = str(blocked.get(first_key) or "closed_window_publication_failed")[:160]
    return (
        "CLOSED_WINDOW_ATOMIC_PUBLICATION_BLOCKED:"
        f"{len(blocked)}:{first_key}:{reason}"
    )


def _record_closed_window_failure(
    stats: dict[str, Any],
    *,
    key: str,
    symbol: str,
    timeframe: str,
    error: ClosedWindowRedisStoreError,
) -> None:
    reason = str(error)[:160]
    blocked = stats.setdefault("ohlcv_closed_blocked_keys", {})
    if not isinstance(blocked, dict):
        blocked = {}
        stats["ohlcv_closed_blocked_keys"] = blocked
    if key in blocked or len(blocked) < CLOSED_WINDOW_MAX_STATUS_BLOCKED_KEYS:
        blocked[key] = reason
    else:
        # A validated stream plan cannot reach this branch because each stream
        # has one exact closed-window key and the plan is capped at this same
        # resource bound. Keep the map bounded even under a hostile direct call.
        stats["ohlcv_closed_blocker_tracking_overflow_events"] = int(
            stats.get("ohlcv_closed_blocker_tracking_overflow_events") or 0
        ) + 1
    stats["ohlcv_closed_write_failures"] = int(
        stats.get("ohlcv_closed_write_failures") or 0
    ) + 1
    stats["ohlcv_closed_last_blocked_key"] = key
    stats["ohlcv_closed_last_blocked_symbol"] = symbol
    stats["ohlcv_closed_last_blocked_timeframe"] = timeframe
    stats["ohlcv_closed_last_error"] = reason


def _record_closed_window_success(
    stats: dict[str, Any],
    *,
    key: str,
    result: ClosedWindowRedisWriteResult,
) -> None:
    blocked = stats.get("ohlcv_closed_blocked_keys")
    if isinstance(blocked, dict):
        blocked.pop(key, None)
    stats["ohlcv_closed_keys_written"] = int(
        stats.get("ohlcv_closed_keys_written") or 0
    ) + 1
    stats["ohlcv_keys_written"] = int(stats.get("ohlcv_keys_written") or 0) + 1
    stats["ohlcv_closed_atomic_writes"] = int(
        stats.get("ohlcv_closed_atomic_writes") or 0
    ) + 1
    stats["ohlcv_closed_atomic_retries"] = int(
        stats.get("ohlcv_closed_atomic_retries") or 0
    ) + max(0, result.attempts - 1)
    stats["ohlcv_closed_rows_trimmed_for_bytes"] = int(
        stats.get("ohlcv_closed_rows_trimmed_for_bytes") or 0
    ) + result.rows_trimmed_for_bytes
    stats["ohlcv_closed_rows_deduplicated_or_trimmed_for_row_limit"] = int(
        stats.get("ohlcv_closed_rows_deduplicated_or_trimmed_for_row_limit") or 0
    ) + result.rows_deduplicated_or_trimmed_for_row_limit


def _publish_closed_window(
    redis_client: Any,
    *,
    key: str,
    row: dict[str, Any],
    row_limit: int,
    ttl_seconds: int,
) -> ClosedWindowRedisWriteResult:
    client = (
        redis_client.ensure()
        if isinstance(redis_client, _RedisHolder)
        else redis_client
    )
    if client is None:
        raise ClosedWindowRedisStoreError("closed_window_redis_unavailable")
    try:
        return atomic_merge_closed_window(
            client,
            redis_key=key,
            new_rows=(row,),
            row_limit=row_limit,
            ttl_policy="set",
            ttl_seconds=ttl_seconds,
            replace_invalid_existing=False,
        )
    except ClosedWindowRedisStoreError as exc:
        if (
            isinstance(redis_client, _RedisHolder)
            and str(exc).startswith("closed_window_redis_operation_failed:")
        ):
            redis_client.mark_broken()
        raise


def _closed_window_ttl_seconds(timeframe: str, configured_floor_seconds: int) -> int:
    interval_ms = TIMEFRAME_DURATION_MS.get(timeframe)
    if interval_ms is None:
        raise ClosedWindowRedisStoreError("closed_window_timeframe_unsupported")
    if type(configured_floor_seconds) is not int or configured_floor_seconds < 1:
        raise ClosedWindowRedisStoreError("closed_window_ttl_floor_invalid")
    return max(configured_floor_seconds, (interval_ms // 1000) * 3)


def _plan_rollover_deadline(
    *,
    now_epoch_seconds: float,
    maximum_seconds: float,
    timeframes: tuple[str, ...],
) -> _RolloverDeadlinePlan:
    """Plan a bounded reconnect away from a close boundary when possible."""

    if type(now_epoch_seconds) not in (int, float):
        raise ValueError("rollover_now_epoch_seconds_invalid")
    if type(maximum_seconds) not in (int, float):
        raise ValueError("rollover_maximum_seconds_invalid")
    try:
        now = float(now_epoch_seconds)
    except (OverflowError, ValueError):
        raise ValueError("rollover_now_epoch_seconds_invalid") from None
    try:
        maximum = float(maximum_seconds)
    except (OverflowError, ValueError):
        raise ValueError("rollover_maximum_seconds_invalid") from None
    if not math.isfinite(now) or now < 0.0:
        raise ValueError("rollover_now_epoch_seconds_invalid")
    if not math.isfinite(maximum) or maximum <= 0.0:
        raise ValueError("rollover_maximum_seconds_invalid")
    if type(timeframes) is not tuple or not timeframes:
        raise ValueError("rollover_timeframes_invalid")
    if any(type(timeframe) is not str for timeframe in timeframes):
        raise ValueError("rollover_timeframes_invalid")
    try:
        timeframe_seconds = tuple(
            TIMEFRAME_DURATION_MS[timeframe] // 1000 for timeframe in timeframes
        )
    except (KeyError, TypeError):
        raise ValueError("rollover_timeframes_invalid") from None
    shortest = min(timeframe_seconds)

    target = now + maximum
    if not math.isfinite(target):
        raise ValueError("rollover_deadline_range_invalid")
    midpoint = shortest / 2.0
    deadline = math.floor((target - midpoint) / shortest) * shortest + midpoint
    if deadline <= now:
        deadline = target
        plan_mode = ROLLOVER_MAXIMUM_FALLBACK_MODE
        if _nearest_close_boundary_distance_seconds(
            epoch_seconds=deadline,
            timeframes=timeframes,
        ) == 0.0:
            deadline = now + maximum / 2.0
            plan_mode = ROLLOVER_BOUNDARY_FALLBACK_MODE
        if (
            deadline > now
            and _nearest_close_boundary_distance_seconds(
                epoch_seconds=deadline,
                timeframes=timeframes,
            ) == 0.0
        ):
            deadline = math.nextafter(deadline, now)
    else:
        plan_mode = ROLLOVER_EXACT_MIDPOINT_MODE
    if (
        not math.isfinite(deadline)
        or deadline <= now
        or deadline > target
    ):
        raise ValueError("rollover_deadline_range_invalid")
    close_boundary_distance = _nearest_close_boundary_distance_seconds(
        epoch_seconds=deadline,
        timeframes=timeframes,
    )
    if close_boundary_distance <= 0.0:
        raise ValueError("rollover_boundary_avoiding_deadline_unrepresentable")
    planned_duration = min(maximum, deadline - now)
    if planned_duration <= 0.0:
        raise ValueError("rollover_deadline_range_invalid")

    return _RolloverDeadlinePlan(
        planned_at_epoch_seconds=now,
        deadline_epoch_seconds=deadline,
        planned_duration_seconds=planned_duration,
        maximum_seconds=maximum,
        shortest_timeframe_seconds=shortest,
        close_boundary_distance_seconds=close_boundary_distance,
        plan_mode=plan_mode,
    )


def _nearest_close_boundary_distance_seconds(
    *,
    epoch_seconds: float,
    timeframes: tuple[str, ...],
) -> float:
    """Return actual distance to the nearest subscribed close boundary."""

    if type(epoch_seconds) not in (int, float):
        raise ValueError("rollover_epoch_seconds_invalid")
    try:
        epoch = float(epoch_seconds)
    except (OverflowError, ValueError):
        raise ValueError("rollover_epoch_seconds_invalid") from None
    if not math.isfinite(epoch) or epoch < 0.0:
        raise ValueError("rollover_epoch_seconds_invalid")
    if type(timeframes) is not tuple or not timeframes:
        raise ValueError("rollover_timeframes_invalid")
    if any(type(timeframe) is not str for timeframe in timeframes):
        raise ValueError("rollover_timeframes_invalid")
    try:
        durations = tuple(
            TIMEFRAME_DURATION_MS[timeframe] / 1000.0 for timeframe in timeframes
        )
    except (KeyError, TypeError):
        raise ValueError("rollover_timeframes_invalid") from None
    distances = []
    for duration in durations:
        offset = epoch % duration
        distances.append(min(offset, duration - offset))
    return min(distances)


def _monotonic_deadline_from_plan(
    *,
    plan: _RolloverDeadlinePlan,
    now_monotonic_seconds: float,
) -> float:
    """Bind one epoch phase plan to an adjustment-resistant runtime clock."""

    if type(now_monotonic_seconds) not in (int, float):
        raise ValueError("rollover_monotonic_seconds_invalid")
    try:
        monotonic_now = float(now_monotonic_seconds)
    except (OverflowError, ValueError):
        raise ValueError("rollover_monotonic_seconds_invalid") from None
    if not math.isfinite(monotonic_now) or monotonic_now < 0.0:
        raise ValueError("rollover_monotonic_seconds_invalid")
    planned_duration = plan.planned_duration_seconds
    if planned_duration <= 0.0 or planned_duration > plan.maximum_seconds:
        raise ValueError("rollover_planned_duration_invalid")
    deadline = monotonic_now + planned_duration
    if not math.isfinite(deadline) or deadline <= monotonic_now:
        raise ValueError("rollover_monotonic_deadline_invalid")
    return deadline


def _record_rollover_deadline(
    stats: dict[str, Any],
    *,
    plan: _RolloverDeadlinePlan,
    scope: str,
    chunk_id: int | None = None,
) -> None:
    """Publish bounded timing evidence without claiming stream continuity."""

    deadline = plan.deadline_epoch_seconds
    planned_duration = plan.planned_duration_seconds
    if planned_duration <= 0.0 or planned_duration > plan.maximum_seconds:
        raise ValueError("rollover_recorded_deadline_exceeds_maximum")
    stats["rollover_timing_policy"] = ROLLOVER_TIMING_POLICY
    stats["rollover_gap_classification"] = ROLLOVER_GAP_CLASSIFICATION
    stats["rollover_continuity_guaranteed"] = False
    stats["rollover_shortest_timeframe_seconds"] = (
        plan.shortest_timeframe_seconds
    )
    stats["rollover_planned_close_boundary_distance_seconds"] = (
        plan.close_boundary_distance_seconds
    )
    stats["rollover_deadline_enforcement_clock"] = "MONOTONIC"
    stats[f"rollover_{scope}_deadlines_planned"] = int(
        stats.get(f"rollover_{scope}_deadlines_planned") or 0
    ) + 1
    if chunk_id is None:
        stats[f"rollover_last_{scope}_deadline_epoch_seconds"] = deadline
        stats[f"rollover_last_{scope}_planned_duration_seconds"] = planned_duration
        stats[f"rollover_last_{scope}_configured_maximum_seconds"] = (
            plan.maximum_seconds
        )
        stats[f"rollover_last_{scope}_plan_mode"] = plan.plan_mode
        stats[f"rollover_last_{scope}_planned_close_boundary_distance_seconds"] = (
            plan.close_boundary_distance_seconds
        )
    else:
        deadlines = stats.setdefault(
            f"rollover_last_{scope}_deadline_epoch_seconds_by_chunk", {}
        )
        if isinstance(deadlines, dict):
            deadlines[str(chunk_id)] = deadline
        durations = stats.setdefault(
            f"rollover_last_{scope}_planned_duration_seconds_by_chunk", {}
        )
        maxima = stats.setdefault(
            f"rollover_last_{scope}_configured_maximum_seconds_by_chunk", {}
        )
        modes = stats.setdefault(f"rollover_last_{scope}_plan_mode_by_chunk", {})
        distances = stats.setdefault(
            f"rollover_last_{scope}_planned_close_boundary_distance_seconds_by_chunk",
            {},
        )
        if isinstance(durations, dict):
            durations[str(chunk_id)] = planned_duration
        if isinstance(maxima, dict):
            maxima[str(chunk_id)] = plan.maximum_seconds
        if isinstance(modes, dict):
            modes[str(chunk_id)] = plan.plan_mode
        if isinstance(distances, dict):
            distances[str(chunk_id)] = plan.close_boundary_distance_seconds


def _record_rollover_disconnect(
    stats: dict[str, Any],
    *,
    chunk_id: int,
    monotonic_deadline_seconds: float,
    timeframes: tuple[str, ...],
) -> None:
    disconnected_at = time.time()
    disconnected_at_monotonic = time.monotonic()
    signed_timing_offset = disconnected_at_monotonic - monotonic_deadline_seconds
    lateness = max(0.0, signed_timing_offset)
    actual_boundary_distance = _nearest_close_boundary_distance_seconds(
        epoch_seconds=disconnected_at,
        timeframes=timeframes,
    )
    chunk_key = str(chunk_id)
    stats["rollover_deadline_disconnects"] = int(
        stats.get("rollover_deadline_disconnects") or 0
    ) + 1
    last_disconnects = stats.setdefault(
        "rollover_last_disconnect_epoch_seconds_by_chunk", {}
    )
    pending_disconnects = stats.setdefault(
        "rollover_pending_disconnect_epoch_seconds_by_chunk", {}
    )
    pending_disconnects_monotonic = stats.setdefault(
        "rollover_pending_disconnect_monotonic_seconds_by_chunk", {}
    )
    if isinstance(last_disconnects, dict):
        last_disconnects[chunk_key] = disconnected_at
    if isinstance(pending_disconnects, dict):
        pending_disconnects[chunk_key] = disconnected_at
    if isinstance(pending_disconnects_monotonic, dict):
        pending_disconnects_monotonic[chunk_key] = disconnected_at_monotonic
    actual_epochs = stats.setdefault(
        "rollover_last_actual_disconnect_epoch_seconds_by_chunk", {}
    )
    lateness_by_chunk = stats.setdefault(
        "rollover_last_actual_disconnect_lateness_seconds_by_chunk", {}
    )
    offsets_by_chunk = stats.setdefault(
        "rollover_last_actual_disconnect_timing_offset_seconds_by_chunk", {}
    )
    distances_by_chunk = stats.setdefault(
        "rollover_last_actual_disconnect_close_boundary_distance_seconds_by_chunk",
        {},
    )
    if isinstance(actual_epochs, dict):
        actual_epochs[chunk_key] = disconnected_at
    if isinstance(lateness_by_chunk, dict):
        lateness_by_chunk[chunk_key] = lateness
    if isinstance(offsets_by_chunk, dict):
        offsets_by_chunk[chunk_key] = signed_timing_offset
    if isinstance(distances_by_chunk, dict):
        distances_by_chunk[chunk_key] = actual_boundary_distance
    prior_lateness = stats.get("rollover_max_actual_disconnect_lateness_seconds")
    if type(prior_lateness) is int:
        prior_lateness_float = float(prior_lateness)
    elif type(prior_lateness) is float:
        prior_lateness_float = prior_lateness
    else:
        prior_lateness_float = 0.0
    stats["rollover_max_actual_disconnect_lateness_seconds"] = max(
        prior_lateness_float,
        lateness,
    )
    prior_distance = stats.get(
        "rollover_min_actual_disconnect_close_boundary_distance_seconds"
    )
    if type(prior_distance) is int:
        prior_distance_float = float(prior_distance)
    elif type(prior_distance) is float:
        prior_distance_float = prior_distance
    else:
        prior_distance_float = actual_boundary_distance
    stats["rollover_min_actual_disconnect_close_boundary_distance_seconds"] = min(
        prior_distance_float,
        actual_boundary_distance,
    )


def _record_rollover_reconnect(stats: dict[str, Any], *, chunk_id: int) -> None:
    connected_at_monotonic = time.monotonic()
    chunk_key = str(chunk_id)
    pending_disconnects = stats.get(
        "rollover_pending_disconnect_epoch_seconds_by_chunk"
    )
    if not isinstance(pending_disconnects, dict):
        return
    pending_disconnects.pop(chunk_key, None)
    pending_disconnects_monotonic = stats.get(
        "rollover_pending_disconnect_monotonic_seconds_by_chunk"
    )
    if not isinstance(pending_disconnects_monotonic, dict):
        return
    disconnected_at_monotonic = pending_disconnects_monotonic.pop(
        chunk_key,
        None,
    )
    if type(disconnected_at_monotonic) not in (int, float):
        return
    gap_seconds = max(
        0.0,
        connected_at_monotonic - float(disconnected_at_monotonic),
    )
    stats["rollover_reconnect_gap_clock"] = "MONOTONIC"
    stats["rollover_reconnect_gap_observations"] = int(
        stats.get("rollover_reconnect_gap_observations") or 0
    ) + 1
    gaps = stats.setdefault("rollover_last_reconnect_gap_seconds_by_chunk", {})
    if isinstance(gaps, dict):
        gaps[chunk_key] = gap_seconds
    prior_maximum = stats.get("rollover_max_reconnect_gap_seconds")
    if type(prior_maximum) is int:
        prior_maximum_float = float(prior_maximum)
    elif type(prior_maximum) is float:
        prior_maximum_float = prior_maximum
    else:
        prior_maximum_float = 0.0
    stats["rollover_max_reconnect_gap_seconds"] = max(
        prior_maximum_float,
        gap_seconds,
    )


def _runtime_cycle_seconds(args: argparse.Namespace) -> float:
    """Bound one loop cycle to the universe-refresh cadence.

    The production refresh default equals the existing websocket session
    rollover, so adaptive re-resolution does not add reconnects.  The cadence
    is a transport-control interval, never a market-selection threshold.
    """

    def finite_seconds(value: Any, *, name: str) -> float:
        if type(value) is bool:
            raise ValueError(f"{name}_must_be_finite_number")
        try:
            parsed = float(value)
        except Exception:
            raise ValueError(f"{name}_must_be_finite_number") from None
        if not math.isfinite(parsed):
            raise ValueError(f"{name}_must_be_finite_number")
        return parsed

    total_seconds = max(
        15.0,
        finite_seconds(args.total_seconds, name="total_seconds"),
    )
    if not bool(args.loop):
        return total_seconds
    configured_refresh = getattr(args, "universe_refresh_seconds", None)
    refresh_source = (
        configured_refresh
        if configured_refresh is not None
        else getattr(args, "max_seconds_per_session", 600.0)
    )
    refresh_name = (
        "universe_refresh_seconds"
        if configured_refresh is not None
        else "max_seconds_per_session"
    )
    refresh_seconds = max(
        15.0,
        finite_seconds(refresh_source, name=refresh_name),
    )
    return min(total_seconds, refresh_seconds)


def _submit_wss_canonical_5m_label(
    canonical: Any,
    label_pipeline: _Canonical5mLabelArchivePipeline | None,
) -> asyncio.Future[_Canonical5mLabelAdmissionResult] | None:
    """Return a future that can only resolve success after durable readback."""

    if (
        label_pipeline is None
        or
        getattr(canonical, "is_closed", None) is not True
        or getattr(canonical, "timeframe", None) != "5m"
        or getattr(canonical, "source", None) != "binance_wss"
    ):
        return None
    return label_pipeline.submit(canonical.to_dict())


async def _await_wss_canonical_5m_label_durability(
    canonical: Any,
    label_pipeline: _Canonical5mLabelArchivePipeline | None,
    stats: dict[str, Any],
) -> _Canonical5mLabelAdmissionResult | None:
    acknowledgement = _submit_wss_canonical_5m_label(
        canonical,
        label_pipeline,
    )
    if acknowledgement is None:
        return None
    result = await asyncio.shield(acknowledgement)
    _record_canonical_5m_label_admission(stats, result)
    return result


def _record_canonical_5m_label_admission(
    stats: dict[str, Any],
    result: _Canonical5mLabelAdmissionResult,
) -> None:
    if result.durable_outbox_committed:
        stats["canonical_5m_label_handler_durable_acks"] = int(
            stats.get("canonical_5m_label_handler_durable_acks") or 0
        ) + 1
    else:
        stats["canonical_5m_label_handler_rejections"] = int(
            stats.get("canonical_5m_label_handler_rejections") or 0
        ) + 1


def _submit_wss_canonical_5m_label_without_receive_stall(
    canonical: Any,
    label_pipeline: _Canonical5mLabelArchivePipeline | None,
    stats: dict[str, Any],
) -> None:
    """Admit a 5m close to the durable label pipeline without blocking recv.

    The admission future still resolves only after the pipeline producer's
    FULL-sync commit-readback (that contract lives in the pipeline, not
    here); stats acks are recorded via done-callback when durability
    resolves. Awaiting durability inline capped the pipeline queue depth at
    one, degrading the designed whole-wave coalescing into ~159 sequential
    fsync commits per 5m boundary and stalling the shared receive loop past
    the websocket queue runway — shedding entire close-waves (WQ-R35;
    2026-07-24 17:30Z universal 5m gap, recurring 1m gaps at 5m boundaries).
    """

    acknowledgement = _submit_wss_canonical_5m_label(
        canonical,
        label_pipeline,
    )
    if acknowledgement is None:
        return

    def _on_durability_resolved(
        future: "asyncio.Future[_Canonical5mLabelAdmissionResult]",
    ) -> None:
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            stats["canonical_5m_label_handler_rejections"] = int(
                stats.get("canonical_5m_label_handler_rejections") or 0
            ) + 1
            stats["canonical_5m_label_async_admission_last_error"] = (
                f"{type(error).__name__}:{str(error)[:160]}"
            )
            return
        _record_canonical_5m_label_admission(stats, future.result())

    acknowledgement.add_done_callback(_on_durability_resolved)


def _base_status(
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    chunks: list[tuple[str, ...]],
    stream_connected_count: int,
    redis_ok: bool,
    stats: dict[str, Any],
    blocker: str | None,
    ws_base: str,
) -> dict[str, Any]:
    status = "V2_BINANCE_KLINE_WSS_CONNECTED" if stream_connected_count > 0 and not blocker else "V2_BINANCE_KLINE_WSS_BLOCKED"
    label_pipeline = stats.get("canonical_5m_label_pipeline")
    if not isinstance(label_pipeline, dict):
        label_pipeline = {
            "enabled": False,
            "initialized": False,
            "healthy": False,
            "blocked_reason": "CANONICAL_5M_LABEL_PIPELINE_DISABLED",
            "source_authority": "BINANCE_WSS_FINALIZED_5M_ONLY",
        }
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_binance_kline_wss_status_v1",
        "status": status,
        "classification": status,
        "generated_at": _est_iso(),
        "generated_est": _est_iso(),
        "heartbeat_at": _est_iso(),
        "operator_time_zone": "America/New_York",
        "timestamp_contract": "EST_PRIMARY_WITH_PROTOCOL_EPOCH_MS_INTERNAL",
        "service_active": True,
        "stream_connected": stream_connected_count > 0,
        "stream_connected_count": stream_connected_count,
        "connection_count": len(chunks),
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "timeframes": list(timeframes),
        "stream_count": sum(len(chunk) for chunk in chunks),
        "redis_ok": redis_ok,
        "blocked_reason": blocker,
        "canonical_5m_label_archive_ok": (
            label_pipeline.get("enabled") is True
            and label_pipeline.get("healthy") is True
        ),
        "canonical_5m_label_archive_blocked_reason": label_pipeline.get(
            "blocked_reason"
        ),
        "canonical_5m_label_source_authority": label_pipeline.get(
            "source_authority"
        ),
        "canonical_5m_label_pipeline": label_pipeline,
        "ws_base": ws_base,
        "stats": stats,
        "heartbeat_key": _heartbeat_key(),
        "target_redis_key_pattern": "v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
        "current_kline_key_pattern": "v2:market:kline_current:binance:{symbol}:{timeframe}",
        "source_type": "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED",
        "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "calls_test_order_endpoint": False,
        "calls_rest_api": False,
        "calls_binance_rest": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "approves_live": False,
        "approves_canary": False,
        "redis_trim_performed": False,
    }


async def _consume_chunk(
    *,
    chunk_id: int,
    streams: tuple[str, ...],
    redis_client: Any | None,
    stats: dict[str, Any],
    ws_base: str,
    ttl_seconds: int,
    max_candles: int,
    max_seconds_per_session: float,
    timeframes: tuple[str, ...],
    stop_at_monotonic: float,
    label_pipeline: _Canonical5mLabelArchivePipeline | None,
) -> None:
    url = ws_base + "/".join(streams)
    volatile_ttl = min(int(ttl_seconds), VOLATILE_TTL_CAP_SECONDS)
    if type(max_seconds_per_session) not in (int, float):
        raise ValueError("rollover_maximum_seconds_invalid")
    try:
        configured_session_limit = float(max_seconds_per_session)
    except (OverflowError, ValueError):
        raise ValueError("rollover_maximum_seconds_invalid") from None
    if not math.isfinite(configured_session_limit) or configured_session_limit <= 0.0:
        raise ValueError("rollover_maximum_seconds_invalid")
    while time.monotonic() < stop_at_monotonic:
        session_started_monotonic = time.monotonic()
        outer_remaining = stop_at_monotonic - session_started_monotonic
        if outer_remaining <= 0.0:
            return
        session_limit = min(configured_session_limit, outer_remaining)
        session_plan = _plan_rollover_deadline(
            now_epoch_seconds=time.time(),
            maximum_seconds=session_limit,
            timeframes=timeframes,
        )
        session_deadline_monotonic = _monotonic_deadline_from_plan(
            plan=session_plan,
            now_monotonic_seconds=session_started_monotonic,
        )
        _record_rollover_deadline(
            stats,
            plan=session_plan,
            scope="session",
            chunk_id=chunk_id,
        )
        planned_duration = (
            session_deadline_monotonic - session_started_monotonic
        )
        close_timeout = min(
            WEBSOCKET_CLOSE_TIMEOUT_MAX_SECONDS,
            planned_duration
            / (
                WEBSOCKET_CLOSE_RESERVE_DIVISOR
                * WEBSOCKET_CLOSE_TIMEOUT_MULTIPLIER_BOUND
            ),
            session_plan.close_boundary_distance_seconds
            / (
                WEBSOCKET_CLOSE_RESERVE_DIVISOR
                * WEBSOCKET_CLOSE_TIMEOUT_MULTIPLIER_BOUND
            ),
        )
        close_reserve = close_timeout * WEBSOCKET_CLOSE_TIMEOUT_MULTIPLIER_BOUND
        receive_deadline_monotonic = session_deadline_monotonic - close_reserve
        open_budget = receive_deadline_monotonic - time.monotonic()
        if open_budget <= 0.0:
            stats["rollover_session_connect_budget_exhausted"] = int(
                stats.get("rollover_session_connect_budget_exhausted") or 0
            ) + 1
            remaining = session_deadline_monotonic - time.monotonic()
            if remaining > 0.0:
                await asyncio.sleep(remaining)
            continue
        planned_disconnect = False
        connected = False
        retry_after_error = False
        try:
            assert websockets is not None
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=min(
                    WEBSOCKET_OPEN_TIMEOUT_MAX_SECONDS,
                    open_budget,
                ),
                close_timeout=close_timeout,
                max_queue=2048,
            ) as ws:
                connected = True
                _record_rollover_reconnect(stats, chunk_id=chunk_id)
                stats["connected_chunks"] = int(stats.get("connected_chunks") or 0) + 1
                while True:
                    receive_remaining = (
                        receive_deadline_monotonic - time.monotonic()
                    )
                    if receive_remaining <= 0.0:
                        planned_disconnect = True
                        break
                    try:
                        raw = await asyncio.wait_for(
                            ws.recv(),
                            timeout=receive_remaining,
                        )
                    except TimeoutError:
                        planned_disconnect = True
                        stats["session_timeouts"] = int(
                            stats.get("session_timeouts") or 0
                        ) + 1
                        break
                    stats["messages_received"] = int(stats.get("messages_received") or 0) + 1
                    try:
                        packet = json.loads(raw)
                    except Exception:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    data = packet.get("data") if isinstance(packet, dict) else None
                    if not isinstance(data, dict):
                        continue
                    parsed = _to_kline_row(data)
                    if parsed is None:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    symbol, timeframe, row = parsed
                    try:
                        canonical = canonical_from_binance_wss(data, symbol=symbol, timeframe=timeframe)
                    except Exception:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    source_payload = {
                        "source_type": "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED",
                        "source_stream": f"{symbol.lower()}@kline_{timeframe}",
                        "updated_at": _est_iso(),
                        "updated_est": _est_iso(),
                        "event_time_ms": data.get("E"),
                        "open_time_ms": row[0],
                        "close_time_ms": row[6],
                        "closed_candle": bool((data.get("k") or {}).get("x")) if isinstance(data.get("k"), dict) else False,
                    }
                    if canonical.is_closed:
                        received_key = f"close_events_received_{timeframe}"
                        stats[received_key] = int(stats.get(received_key) or 0) + 1
                        key = _ohlcv_key(symbol, timeframe)
                        # Closed-candle HISTORY must outlive the candle interval:
                        # a flat 900s TTL expired 1h/4h keys between closes and
                        # perpetually reset history to a single row (destroying
                        # REST backfills). Keep the CLI TTL as a floor only.
                        # Explicit SET TTL preserves the deployed refresh policy
                        # while WATCH/MULTI/EXEC removes lost concurrent writes.
                        closed_ttl = _closed_window_ttl_seconds(
                            timeframe,
                            ttl_seconds,
                        )
                        try:
                            write_result = _publish_closed_window(
                                redis_client,
                                key=key,
                                row=canonical.to_dict(),
                                row_limit=max_candles,
                                ttl_seconds=closed_ttl,
                            )
                        except ClosedWindowRedisStoreError as exc:
                            _record_closed_window_failure(
                                stats,
                                key=key,
                                symbol=symbol,
                                timeframe=timeframe,
                                error=exc,
                            )
                            # A source sidecar or trainer label without its
                            # canonical window publication would create false
                            # durability/provenance. Hold this message locally.
                            continue
                        _record_closed_window_success(
                            stats,
                            key=key,
                            result=write_result,
                        )
                    else:
                        key = _current_key(symbol, timeframe)
                        if _safe_set_json(redis_client, key, canonical.to_dict(), ex=volatile_ttl):
                            stats["kline_current_keys_written"] = int(stats.get("kline_current_keys_written") or 0) + 1
                    if _safe_set_json(redis_client, _source_key(symbol, timeframe), source_payload, ex=volatile_ttl):
                        stats["source_keys_written"] = int(stats.get("source_keys_written") or 0) + 1
                    # Preserve the independent existing market-data feed first.
                    # The returned admission future is resolved by the producer
                    # worker only after the exact payload is FULL-sync committed
                    # to the outbox and read back; stats acks land via callback
                    # so the receive loop never stalls behind durability
                    # (WQ-R35: inline awaiting shed whole close-waves).
                    _submit_wss_canonical_5m_label_without_receive_stall(
                        canonical,
                        label_pipeline,
                        stats,
                    )
                    stats["last_symbol"] = symbol
                    stats["last_timeframe"] = timeframe
                    stats["last_event_est"] = _est_iso()
        except TimeoutError:
            stats["session_timeouts"] = int(stats.get("session_timeouts") or 0) + 1
            retry_after_error = True
        except Exception as exc:
            stats["connection_errors"] = int(stats.get("connection_errors") or 0) + 1
            stats[f"chunk_{chunk_id}_last_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
            retry_after_error = True
        if planned_disconnect and connected:
            _record_rollover_disconnect(
                stats,
                chunk_id=chunk_id,
                monotonic_deadline_seconds=session_deadline_monotonic,
                timeframes=timeframes,
            )
            remaining = session_deadline_monotonic - time.monotonic()
            if remaining > 0.0:
                await asyncio.sleep(remaining)
        elif retry_after_error:
            retry_budget = min(
                stop_at_monotonic,
                session_deadline_monotonic,
            ) - time.monotonic()
            if retry_budget > 0.0:
                await asyncio.sleep(
                    min(WEBSOCKET_RETRY_SECONDS, retry_budget)
                )


def _build_label_pipeline(
    args: argparse.Namespace,
    stats: dict[str, Any],
) -> _Canonical5mLabelArchivePipeline | None:
    """Honor the explicit operator interlock before producer construction."""

    if not bool(getattr(args, "enable_canonical_5m_label_archive", False)):
        stats["canonical_5m_label_pipeline"] = {
            "schema_version": "canonical_5m_wss_label_pipeline_v1",
            "enabled": False,
            "initialized": False,
            "healthy": False,
            "blocked_reason": "CANONICAL_5M_LABEL_PIPELINE_DISABLED",
            "source_authority": "BINANCE_WSS_FINALIZED_5M_ONLY",
            "exact_payload_outbox_before_archive": False,
        }
        return None
    return _Canonical5mLabelArchivePipeline(
        archive_path=Path(
            getattr(
                args,
                "canonical_5m_label_archive_path",
                default_canonical_5m_label_archive_path(),
            )
        ),
        outbox_path=Path(
            getattr(
                args,
                "canonical_5m_label_outbox_path",
                default_outbox_path(),
            )
        ),
        queue_capacity=int(
            getattr(
                args,
                "canonical_5m_label_queue_capacity",
                DEFAULT_LABEL_QUEUE_CAPACITY,
            )
        ),
        batch_rows=int(
            getattr(
                args,
                "canonical_5m_label_batch_rows",
                MAX_CLOSE_WAVE_ROWS,
            )
        ),
        max_pending_rows=int(
            getattr(
                args,
                "canonical_5m_label_max_pending_rows",
                DEFAULT_MAX_PENDING_ROWS,
            )
        ),
        flush_seconds=float(
            getattr(
                args,
                "canonical_5m_label_close_wave_flush_seconds",
                DEFAULT_LABEL_CLOSE_WAVE_FLUSH_SECONDS,
            )
        ),
        retry_seconds=float(
            getattr(
                args,
                "canonical_5m_label_archive_retry_seconds",
                DEFAULT_LABEL_ARCHIVE_RETRY_SECONDS,
            )
        ),
        stats=stats,
    )


def _runtime_cycle_exit_code(
    *,
    label_pipeline_enabled: bool,
    pipeline_clean: bool,
    cycle_results: list[Any],
) -> int:
    task_failed = any(
        isinstance(result, BaseException) for result in cycle_results
    )
    if task_failed or (label_pipeline_enabled and not pipeline_clean):
        return 2
    return 0


async def run_loop(args: argparse.Namespace) -> int:
    if websockets is None:
        symbols, timeframes, _chunks = _runtime_stream_plan(args)
        payload = _base_status(
            symbols=symbols,
            timeframes=timeframes,
            chunks=[],
            stream_connected_count=0,
            redis_ok=False,
            stats={},
            blocker="websockets package unavailable",
            ws_base=str(args.ws_base),
        )
        _write_status(payload, (Path(args.status_path), Path(args.public_path), Path(args.worklog_path)))
        print(json.dumps(payload, sort_keys=True), flush=True)
        return 2

    redis_holder = _RedisHolder()
    symbols, timeframes, chunks = _runtime_stream_plan(args)
    stats: dict[str, Any] = {
        "messages_received": 0,
        "ohlcv_closed_keys_written": 0,
        "ohlcv_keys_written": 0,
        "ohlcv_closed_atomic_writes": 0,
        "ohlcv_closed_atomic_retries": 0,
        "ohlcv_closed_write_failures": 0,
        "ohlcv_closed_rows_trimmed_for_bytes": 0,
        "ohlcv_closed_rows_deduplicated_or_trimmed_for_row_limit": 0,
        "ohlcv_closed_blocked_keys": {},
        "ohlcv_closed_blocker_tracking_overflow_events": 0,
        "ohlcv_closed_ttl_policy": "set_existing_computed_ttl",
        "kline_current_keys_written": 0,
        "source_keys_written": 0,
        "parse_errors": 0,
        "connection_errors": 0,
        "session_timeouts": 0,
        "connected_chunks": 0,
        "universe_refresh_count": 0,
        "universe_changed": False,
        "universe_added_symbols": [],
        "universe_removed_symbols": [],
        "universe_refresh_seconds": _runtime_cycle_seconds(args),
        "universe_refresh_seconds_semantics": (
            "CONFIGURED_MAXIMUM_NOT_ACTUAL_PLANNED_DURATION"
        ),
        "universe_refresh_configured_maximum_seconds": _runtime_cycle_seconds(
            args
        ),
        "rollover_timing_policy": ROLLOVER_TIMING_POLICY,
        "rollover_gap_classification": ROLLOVER_GAP_CLASSIFICATION,
        "rollover_continuity_guaranteed": False,
        "rollover_runtime_bound_classification": (
            "MONOTONIC_USERSPACE_TIMEOUTS_NOT_OS_HARD_REALTIME_GUARANTEE"
        ),
        "rollover_cycle_deadlines_planned": 0,
        "rollover_session_deadlines_planned": 0,
        "rollover_deadline_disconnects": 0,
        "rollover_reconnect_gap_observations": 0,
        "rollover_session_connect_budget_exhausted": 0,
    }
    label_pipeline_enabled = bool(
        getattr(args, "enable_canonical_5m_label_archive", False)
    )
    label_pipeline = _build_label_pipeline(args, stats)
    if label_pipeline is not None:
        await label_pipeline.initialize()
    status_paths = (Path(args.status_path), Path(args.public_path), Path(args.worklog_path))

    async def write_status_once() -> dict[str, Any]:
        redis_ok = redis_holder.ensure() is not None
        snapshot = dict(stats)
        snapshot["redis_reconnects"] = redis_holder.reconnects
        label_status = (
            label_pipeline.status_snapshot()
            if label_pipeline is not None
            else dict(stats["canonical_5m_label_pipeline"])
        )
        snapshot["canonical_5m_label_pipeline"] = label_status
        blockers: list[str] = []
        if not redis_ok:
            blockers.append("Redis unavailable; websocket data not persisted.")
        closed_window_blocker = _closed_window_status_blocker(stats)
        if closed_window_blocker is not None:
            blockers.append(closed_window_blocker)
        if label_pipeline_enabled and label_status.get("healthy") is not True:
            blockers.append(
                str(
                    label_status.get("blocked_reason")
                    or "CANONICAL_5M_LABEL_PIPELINE_UNHEALTHY"
                )
            )
        payload = _base_status(
            symbols=symbols,
            timeframes=timeframes,
            chunks=chunks,
            stream_connected_count=int(stats.get("connected_chunks") or 0),
            redis_ok=redis_ok,
            stats=snapshot,
            blocker=" | ".join(blockers) if blockers else None,
            ws_base=str(args.ws_base),
        )
        await asyncio.to_thread(_write_status, payload, status_paths)
        _safe_set_json(
            redis_holder,
            _heartbeat_key(),
            payload,
            ex=min(int(args.ttl_seconds), VOLATILE_TTL_CAP_SECONDS),
        )
        return payload

    async def status_writer(stop_at_monotonic: float) -> None:
        while time.monotonic() < stop_at_monotonic:
            payload = await write_status_once()
            print(json.dumps({
                "status": payload["status"],
                "generated_est": payload["generated_est"],
                "stream_count": payload["stream_count"],
                "messages_received": stats.get("messages_received"),
                "ohlcv_keys_written": stats.get("ohlcv_keys_written"),
                "ohlcv_closed_atomic_writes": stats.get(
                    "ohlcv_closed_atomic_writes"
                ),
                "ohlcv_closed_write_failures": stats.get(
                    "ohlcv_closed_write_failures"
                ),
                "ohlcv_closed_blocked_key_count": len(
                    stats.get("ohlcv_closed_blocked_keys") or {}
                ),
                "live_gate": payload["live_gate"],
            }, sort_keys=True), flush=True)
            remaining = stop_at_monotonic - time.monotonic()
            if remaining <= 0.0:
                return
            await asyncio.sleep(
                min(
                    max(1.0, float(args.heartbeat_interval_seconds)),
                    remaining,
                )
            )

    pipeline_task: asyncio.Task[bool] | None = None
    try:
        while True:
            refreshed_symbols, refreshed_timeframes, refreshed_chunks = (
                _runtime_stream_plan(args)
            )
            prior_symbol_set = set(symbols)
            refreshed_symbol_set = set(refreshed_symbols)
            stats["universe_refresh_count"] = int(
                stats.get("universe_refresh_count") or 0
            ) + 1
            stats["universe_changed"] = (
                refreshed_symbols != symbols
                or refreshed_timeframes != timeframes
            )
            stats["universe_added_symbols"] = sorted(
                refreshed_symbol_set - prior_symbol_set
            )
            stats["universe_removed_symbols"] = sorted(
                prior_symbol_set - refreshed_symbol_set
            )
            symbols = refreshed_symbols
            timeframes = refreshed_timeframes
            chunks = refreshed_chunks
            cycle_started_epoch = time.time()
            cycle_started_monotonic = time.monotonic()
            cycle_plan = _plan_rollover_deadline(
                now_epoch_seconds=cycle_started_epoch,
                maximum_seconds=_runtime_cycle_seconds(args),
                timeframes=timeframes,
            )
            stop_at_monotonic = _monotonic_deadline_from_plan(
                plan=cycle_plan,
                now_monotonic_seconds=cycle_started_monotonic,
            )
            _record_rollover_deadline(
                stats,
                plan=cycle_plan,
                scope="cycle",
            )
            stats["connected_chunks"] = 0
            consumer_tasks = [
                asyncio.create_task(
                    _consume_chunk(
                        chunk_id=index,
                        streams=chunk,
                        redis_client=redis_holder,
                        stats=stats,
                        ws_base=str(args.ws_base),
                        ttl_seconds=int(args.ttl_seconds),
                        max_candles=int(args.max_candles),
                        max_seconds_per_session=args.max_seconds_per_session,
                        timeframes=timeframes,
                        stop_at_monotonic=stop_at_monotonic,
                        label_pipeline=label_pipeline,
                    )
                )
                for index, chunk in enumerate(chunks)
            ]
            status_task = asyncio.create_task(
                status_writer(stop_at_monotonic)
            )
            pipeline_task = (
                asyncio.create_task(label_pipeline.run_until(None))
                if label_pipeline is not None
                else None
            )
            cycle_results = await asyncio.gather(
                *consumer_tasks,
                status_task,
                return_exceptions=True,
            )
            pipeline_clean = True
            if label_pipeline is not None and pipeline_task is not None:
                label_pipeline.request_stop()
                try:
                    pipeline_clean = bool(await pipeline_task)
                except Exception as exc:
                    pipeline_clean = False
                    label_pipeline._worker_error = label_pipeline._error_text(
                        "CANONICAL_5M_LABEL_WORKER_TASK_FAILED", exc
                    )
                    label_pipeline._publish_runtime_stats()
                finally:
                    pipeline_task = None
            await write_status_once()
            cycle_exit_code = _runtime_cycle_exit_code(
                label_pipeline_enabled=label_pipeline_enabled,
                pipeline_clean=pipeline_clean,
                cycle_results=list(cycle_results),
            )
            if cycle_exit_code:
                return cycle_exit_code
            if not args.loop:
                return 0
    finally:
        if label_pipeline is not None:
            label_pipeline.request_stop()
        if pipeline_task is not None and not pipeline_task.done():
            assert label_pipeline is not None
            pipeline_task.cancel()
            try:
                await pipeline_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                label_pipeline._worker_error = label_pipeline._error_text(
                    "CANONICAL_5M_LABEL_WORKER_CLEANUP_FAILED", exc
                )
                label_pipeline._publish_runtime_stats()
        if label_pipeline is not None:
            await label_pipeline.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="auto")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-streams-per-connection", type=int, default=120)
    parser.add_argument("--max-candles", type=int, default=100)
    parser.add_argument("--ttl-seconds", type=int, default=900)
    parser.add_argument("--ws-base", default=DEFAULT_WS_BASE)
    parser.add_argument("--total-seconds", type=float, default=86400.0)
    # Each session end is a break-before-make reconnect that can drop a candle
    # (ROLLOVER_GAP_CLASSIFICATION = MITIGATION_NOT_CONTINUITY_PROOF).  At the
    # old 600s (10 min) cadence that was ~144 reconnects/day/chunk, so dropped
    # candles recurred far faster than the ~6h it takes a gap to roll out of the
    # 71-candle core-TA coverage window -- meaning downstream feature-window
    # coverage could stay blocked indefinitely.  A 1h session (24/day) makes
    # gaps rarer than that roll-off so coverage reliably recovers.  Binance
    # allows 24h sessions; dead connections are still caught reactively by the
    # websocket keepalive regardless of this proactive rollover cadence.
    parser.add_argument("--max-seconds-per-session", type=float, default=3600.0)
    parser.add_argument(
        "--universe-refresh-seconds",
        type=float,
        default=None,
        help=(
            "Re-resolve the adaptive symbol universe at this transport cadence; "
            "by default it derives from --max-seconds-per-session so no extra "
            "reconnect cadence is introduced."
        ),
    )
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=30.0)
    parser.add_argument(
        "--enable-canonical-5m-label-archive",
        action="store_true",
        help=(
            "Explicitly enable the trainer 5m archive producer after its "
            "outbox/archive admission has passed operator validation."
        ),
    )
    parser.add_argument(
        "--canonical-5m-label-archive-path",
        default=str(default_canonical_5m_label_archive_path()),
    )
    parser.add_argument(
        "--canonical-5m-label-outbox-path",
        default=str(default_outbox_path()),
    )
    parser.add_argument(
        "--canonical-5m-label-queue-capacity",
        type=int,
        default=DEFAULT_LABEL_QUEUE_CAPACITY,
    )
    parser.add_argument(
        "--canonical-5m-label-batch-rows",
        type=int,
        default=MAX_CLOSE_WAVE_ROWS,
    )
    parser.add_argument(
        "--canonical-5m-label-max-pending-rows",
        type=int,
        default=DEFAULT_MAX_PENDING_ROWS,
    )
    parser.add_argument(
        "--canonical-5m-label-close-wave-flush-seconds",
        type=float,
        default=DEFAULT_LABEL_CLOSE_WAVE_FLUSH_SECONDS,
    )
    parser.add_argument(
        "--canonical-5m-label-archive-retry-seconds",
        type=float,
        default=DEFAULT_LABEL_ARCHIVE_RETRY_SECONDS,
    )
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--public-path", default=str(DEFAULT_PUBLIC_PATH))
    parser.add_argument("--worklog-path", default=str(DEFAULT_WORKLOG_PATH))
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run_loop(args))


if __name__ == "__main__":
    raise SystemExit(main())
