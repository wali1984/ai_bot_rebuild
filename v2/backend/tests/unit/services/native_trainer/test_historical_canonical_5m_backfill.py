from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer import (
    historical_canonical_5m_backfill as backfill,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    LABEL_SLOT_MILLISECONDS,
    Canonical5mArchiveWriterLease,
    Canonical5mArchiveWriterLeaseError,
    DurableCanonical5mLabelArchive,
    canonical_json,
)

BASE_OPEN_MS = 1_700_000_000_000 // LABEL_SLOT_MILLISECONDS * LABEL_SLOT_MILLISECONDS
OBSERVED_AT_MS = BASE_OPEN_MS + 2_000 * LABEL_SLOT_MILLISECONDS


def _raw_kline(open_ms: int) -> list[object]:
    return [
        open_ms,
        "100.0",
        "110.0",
        "90.0",
        "105.0",
        "12.0",
        open_ms + LABEL_SLOT_MILLISECONDS - 1,
        "1260.0",
        42,
        "6.0",
        "630.0",
        "0",
    ]


class FakeTransport:
    def __init__(
        self,
        *,
        received_at_ms: int = OBSERVED_AT_MS,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        rows_factory: (Callable[[backfill.BinanceKlineRequest], object] | None) = None,
    ) -> None:
        self.received_at_ms = received_at_ms
        self.status_code = status_code
        self.headers = headers or {}
        self.rows_factory = rows_factory or self._rows
        self.requests: list[backfill.BinanceKlineRequest] = []

    @staticmethod
    def _rows(request: backfill.BinanceKlineRequest) -> list[object]:
        return [
            _raw_kline(request.start_open_time_ms + index * LABEL_SLOT_MILLISECONDS)
            for index in range(request.limit)
        ]

    def fetch(
        self,
        request: backfill.BinanceKlineRequest,
    ) -> backfill.PublicHttpResponse:
        self.requests.append(request)
        return backfill.PublicHttpResponse(
            status_code=self.status_code,
            headers=self.headers,
            body=json.dumps(
                self.rows_factory(request),
                separators=(",", ":"),
            ).encode(),
            received_at_ms=self.received_at_ms,
        )


class NoCallTransport:
    def fetch(
        self,
        request: backfill.BinanceKlineRequest,
    ) -> backfill.PublicHttpResponse:
        raise AssertionError(f"transport unexpectedly called: {request.url}")


def _spec(
    tmp_path: Path,
    *,
    slots: int,
    page_limit: int = 1_000,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    valid_until_ms: int = OBSERVED_AT_MS + 60_000,
) -> backfill.BackfillJobSpec:
    archive_path = (tmp_path / "labels.sqlite3").resolve()
    cutoff = BASE_OPEN_MS + slots * LABEL_SLOT_MILLISECONDS
    return backfill.BackfillJobSpec(
        archive_path=archive_path,
        symbols=symbols,
        start_open_time_ms=BASE_OPEN_MS,
        end_open_time_ms_exclusive=cutoff,
        authority_cutoff=backfill.WssAuthorityCutoffAttestation(
            attestation_id="operator-fixed-cutoff-test",
            archive_path=archive_path,
            authority_cutoff_open_time_ms=cutoff,
            attested_at_ms=OBSERVED_AT_MS - 1_000,
            valid_until_ms=valid_until_ms,
            producer_archive_writes_inactive=True,
            operator_authorized=True,
        ),
        page_limit=page_limit,
    ).validated()


def _inactive_probe(spec: backfill.BackfillJobSpec) -> dict[str, object]:
    return {
        "probe_method": "fake_no_process_probe_v1",
        "producer_worker_id": "v2_binance_kline_wss_loop",
        "archive_path": str(spec.archive_path),
        "observed_at_ms": OBSERVED_AT_MS,
        "active_process_ids": [],
        "wss_archive_producer_inactive": True,
        "process_probe_role": "SECONDARY_EVIDENCE_ONLY",
        "shared_exact_archive_writer_lease_is_primary": True,
    }


def _renewed_spec(
    spec: backfill.BackfillJobSpec,
    *,
    attestation_id: str = "operator-fixed-cutoff-renewal",
    valid_until_ms: int = OBSERVED_AT_MS + 120_000,
) -> backfill.BackfillJobSpec:
    return backfill.BackfillJobSpec(
        archive_path=spec.archive_path,
        symbols=spec.symbols,
        start_open_time_ms=spec.start_open_time_ms,
        end_open_time_ms_exclusive=spec.end_open_time_ms_exclusive,
        authority_cutoff=backfill.WssAuthorityCutoffAttestation(
            attestation_id=attestation_id,
            archive_path=spec.archive_path,
            authority_cutoff_open_time_ms=spec.end_open_time_ms_exclusive,
            attested_at_ms=OBSERVED_AT_MS - 500,
            valid_until_ms=valid_until_ms,
            producer_archive_writes_inactive=True,
            operator_authorized=True,
        ),
        page_limit=spec.page_limit,
    ).validated()


def _run(
    tmp_path: Path,
    *,
    spec: backfill.BackfillJobSpec,
    transport: backfill.PublicKlineTransport,
    max_pages: int = 10,
    max_slots: int = 100,
    probe: Callable[[], Mapping[str, object]] | None = None,
    before_public_request: (Callable[[backfill.BinanceKlineRequest], None] | None) = None,
) -> dict[str, object]:
    return backfill.run_historical_5m_backfill(
        spec=spec,
        bounds=backfill.BackfillRunBounds(
            max_pages=max_pages,
            max_slots=max_slots,
            local_weight_budget_per_minute=120,
        ),
        state_path=tmp_path / "backfill.sqlite3",
        transport=transport,
        clock_ms=lambda: OBSERVED_AT_MS,
        wss_inactive_probe=probe or (lambda: _inactive_probe(spec)),
        before_public_request=before_public_request,
    )


def _wss_candle(open_ms: int, *, symbol: str = "BTCUSDT") -> dict:
    close_ms = open_ms + LABEL_SLOT_MILLISECONDS - 1
    message = {
        "E": close_ms + 1,
        "k": {
            "t": open_ms,
            "T": close_ms,
            "x": True,
            "o": "100.0",
            "h": "110.0",
            "l": "90.0",
            "c": "105.0",
            "v": "12.0",
            "q": "1260.0",
            "n": 42,
            "V": "6.0",
            "Q": "630.0",
        },
    }
    return canonical_from_binance_wss(
        message,
        symbol=symbol,
        timeframe="5m",
        ingested_at=close_ms + 2,
    ).to_dict()


def test_wss_authority_attestation_omitted_authorization_fails_closed(
    tmp_path: Path,
) -> None:
    archive_path = (tmp_path / "labels.sqlite3").resolve()
    cutoff = BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS
    attestation = backfill.WssAuthorityCutoffAttestation(
        attestation_id="operator-fixed-cutoff-test",
        archive_path=archive_path,
        authority_cutoff_open_time_ms=cutoff,
        attested_at_ms=OBSERVED_AT_MS - 1_000,
        valid_until_ms=OBSERVED_AT_MS + 60_000,
    )

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="wss_archive_producer_not_attested_inactive",
    ):
        attestation.validated(observed_at_ms=OBSERVED_AT_MS)


def test_empty_archive_full_workflow_seals_every_boundary(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=3, page_limit=3)
    transport = FakeTransport()

    result = _run(tmp_path, spec=spec, transport=transport)

    assert result["job_complete"] is True
    assert result["phase"] == "COMPLETE_READY_FOR_WSS_ACTIVATION"
    assert result["inventory_checkpoint_sealed"] is True
    assert result["inventory_manifest_sealed"] is True
    assert result["rest_intent_manifest_sealed"] is True
    assert result["all_sparse_inventory_sealed_before_rest_append"] is True
    assert result["all_rest_intents_sealed_before_public_request"] is True
    assert result["full_archive_integrity_scans_this_run"] == 2
    assert result["wss_activation_performed"] is False
    assert len(transport.requests) == 1
    assert transport.requests[0].limit == 3

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_inventory_pages").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_rest_intent_manifests").fetchone()[0]
            == 1
        )
        receipt = connection.execute(
            """
            SELECT initialization_receipt_sha256, initialization_receipt_json
            FROM backfill_inventory_checkpoints
            """
        ).fetchone()
        assert receipt is not None
        assert receipt[0] == backfill._sha256_bytes(receipt[1].encode())


def test_rest_requests_only_proven_gaps_and_preserves_wss_identity(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=3, page_limit=3)
    archive = DurableCanonical5mLabelArchive(spec.archive_path)
    wss = _wss_candle(BASE_OPEN_MS)
    archive.append_candles([wss])
    transport = FakeTransport()

    result = _run(tmp_path, spec=spec, transport=transport)

    assert result["job_complete"] is True
    assert len(transport.requests) == 1
    assert transport.requests[0].start_open_time_ms == (BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS)
    assert transport.requests[0].limit == 2
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        end_close_time_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        training_observed_at=OBSERVED_AT_MS,
        limit=1,
    )
    assert proof["status"] == "VERIFIED_CANONICAL_5M_LABEL_RANGE"
    assert rows == [wss]
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        manifest = json.loads(
            connection.execute("SELECT manifest_json FROM backfill_inventory_manifests").fetchone()[
                0
            ]
        )
        cursor = connection.execute(
            """
            SELECT next_open_time_ms, end_open_time_ms_exclusive, complete
            FROM backfill_symbol_cursors WHERE job_id = ?
            """,
            (spec.job_id,),
        ).fetchone()
    assert manifest["occupied_slot_count"] == 1
    assert manifest["proven_absent_slot_count"] == 2
    assert cursor == (
        spec.end_open_time_ms_exclusive,
        spec.end_open_time_ms_exclusive,
        1,
    )
    assert (
        backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3").next_cursor(spec.job_id)
        is None
    )


def test_zero_byte_archive_creation_crash_recovers_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    original_bind = Canonical5mArchiveWriterLease.bind_archive_inode_for_write

    def _bind_then_crash(
        lease: Canonical5mArchiveWriterLease,
        archive_path: Path,
    ) -> None:
        original_bind(lease, archive_path)
        raise RuntimeError("simulated_zero_byte_archive_creation_crash")

    monkeypatch.setattr(
        Canonical5mArchiveWriterLease,
        "bind_archive_inode_for_write",
        _bind_then_crash,
    )
    with pytest.raises(RuntimeError, match="zero_byte_archive_creation"):
        _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert spec.archive_path.is_file()
    assert spec.archive_path.stat().st_size == 0
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_inventory_checkpoints").fetchone()[0]
            == 0
        )

    monkeypatch.setattr(
        Canonical5mArchiveWriterLease,
        "bind_archive_inode_for_write",
        original_bind,
    )
    result = _run(tmp_path, spec=spec, transport=FakeTransport())

    assert result["job_complete"] is True
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        receipt = connection.execute(
            """
            SELECT initialization_receipt_sha256
            FROM backfill_inventory_checkpoints
            """
        ).fetchone()
    assert receipt is not None
    assert len(str(receipt[0])) == 64


def test_crash_after_empty_genesis_regenerates_same_initialization_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    original_seal = backfill.Historical5mBackfillStore.seal_inventory_checkpoint
    captured_receipt_sha256: list[str] = []

    def _crash_before_checkpoint(
        _store: backfill.Historical5mBackfillStore,
        **kwargs: object,
    ) -> None:
        receipt = kwargs["initialization_receipt"]
        assert isinstance(receipt, Mapping)
        captured_receipt_sha256.append(str(receipt["initialization_receipt_sha256"]))
        raise RuntimeError("simulated_post_genesis_precheckpoint_crash")

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "seal_inventory_checkpoint",
        _crash_before_checkpoint,
    )
    with pytest.raises(RuntimeError, match="precheckpoint_crash"):
        _run(tmp_path, spec=spec, transport=NoCallTransport())

    integrity = DurableCanonical5mLabelArchive(spec.archive_path).verify_integrity()
    assert integrity["archive_integrity_verified"] is True
    assert integrity["verified_rows"] == 0
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "seal_inventory_checkpoint",
        original_seal,
    )

    result = _run(tmp_path, spec=spec, transport=FakeTransport())

    assert result["job_complete"] is True
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        sealed_receipt = connection.execute(
            """
            SELECT initialization_receipt_sha256,
                   initialization_receipt_json
            FROM backfill_inventory_checkpoints
            """
        ).fetchone()
    sealed_receipt_json = str(sealed_receipt[1])
    assert str(sealed_receipt[0]) == backfill._sha256_bytes(sealed_receipt_json.encode())
    sealed_receipt_payload = json.loads(sealed_receipt_json)
    assert captured_receipt_sha256 == [sealed_receipt_payload["initialization_receipt_sha256"]]


def test_nonzero_foreign_archive_still_fails_closed_without_rewrite(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    foreign_bytes = b"nonzero-foreign-database"
    spec.archive_path.write_bytes(foreign_bytes)

    with pytest.raises(sqlite3.DatabaseError):
        _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert spec.archive_path.read_bytes() == foreign_bytes


def test_fully_wss_occupied_job_seals_every_cursor_without_rest(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=3, page_limit=3)
    archive = DurableCanonical5mLabelArchive(spec.archive_path)
    archive.append_candles(
        [_wss_candle(BASE_OPEN_MS + slot * LABEL_SLOT_MILLISECONDS) for slot in range(3)]
    )

    result = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert result["job_complete"] is True
    assert result["slot_receipt_counts"] == {}
    store = backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3")
    assert store.next_cursor(spec.job_id) is None
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert connection.execute(
            """
            SELECT next_open_time_ms, end_open_time_ms_exclusive, complete
            FROM backfill_symbol_cursors WHERE job_id = ?
            """,
            (spec.job_id,),
        ).fetchone() == (
            spec.end_open_time_ms_exclusive,
            spec.end_open_time_ms_exclusive,
            1,
        )


def test_every_inventory_page_is_durable_before_first_transport_call(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=5, page_limit=2)
    assert (
        _run(
            tmp_path,
            spec=spec,
            transport=NoCallTransport(),
            max_pages=1,
        )["inventory_pages_sealed"]
        == 1
    )
    assert (
        _run(
            tmp_path,
            spec=spec,
            transport=NoCallTransport(),
            max_pages=1,
        )["inventory_pages_sealed"]
        == 2
    )

    def _assert_preconditions(_: backfill.BinanceKlineRequest) -> None:
        with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM backfill_inventory_pages").fetchone()[0]
                == 3
            )
            assert (
                connection.execute("SELECT COUNT(*) FROM backfill_inventory_manifests").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_rest_intent_manifests"
                ).fetchone()[0]
                == 1
            )

    transport = FakeTransport()
    third = _run(
        tmp_path,
        spec=spec,
        transport=transport,
        max_pages=1,
        before_public_request=_assert_preconditions,
    )
    assert third["inventory_pages_sealed"] == 3
    assert len(transport.requests) == 1


def test_inventory_resume_does_not_reprobe_sealed_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=6, page_limit=2)
    calls: list[int] = []
    original = DurableCanonical5mLabelArchive.verified_coverage

    def _counted(self: DurableCanonical5mLabelArchive, **kwargs: object):
        calls.append(int(kwargs["start_close_time_ms"]))
        return original(self, **kwargs)

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "verified_coverage",
        _counted,
    )
    for _ in range(3):
        _run(
            tmp_path,
            spec=spec,
            transport=FakeTransport(),
            max_pages=1,
        )

    assert calls == [
        BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        BASE_OPEN_MS + 3 * LABEL_SLOT_MILLISECONDS - 1,
        BASE_OPEN_MS + 5 * LABEL_SLOT_MILLISECONDS - 1,
    ]


def test_manifest_materialization_crash_is_repaired_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=4, page_limit=2)
    original = backfill.Historical5mBackfillStore.ensure_page_intent
    calls = 0

    def _crash_on_second(
        self: backfill.Historical5mBackfillStore,
        **kwargs: object,
    ):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated_intent_materialization_crash")
        return original(self, **kwargs)

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "ensure_page_intent",
        _crash_on_second,
    )
    with pytest.raises(RuntimeError, match="materialization_crash"):
        _run(tmp_path, spec=spec, transport=NoCallTransport())
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "ensure_page_intent",
        original,
    )

    transport = FakeTransport()
    result = _run(tmp_path, spec=spec, transport=transport)

    assert result["job_complete"] is True
    assert len(transport.requests) == 2
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM backfill_pages").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_rest_intent_manifests").fetchone()[0]
            == 1
        )


def test_stale_checkpoint_blocks_resume_before_transport(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=4, page_limit=2)
    _run(
        tmp_path,
        spec=spec,
        transport=NoCallTransport(),
        max_pages=1,
    )
    DurableCanonical5mLabelArchive(spec.archive_path).append_candles(
        [_wss_candle(BASE_OPEN_MS + 2 * LABEL_SLOT_MILLISECONDS)]
    )

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="inventory_checkpoint_stale",
    ):
        _run(tmp_path, spec=spec, transport=NoCallTransport())


def test_active_wss_probe_blocks_before_state_or_archive_creation(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    active = _inactive_probe(spec)
    active["active_process_ids"] = [123]
    active["wss_archive_producer_inactive"] = False

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="wss_archive_producer_runtime_active",
    ):
        _run(
            tmp_path,
            spec=spec,
            transport=NoCallTransport(),
            probe=lambda: active,
        )

    assert not (tmp_path / "backfill.sqlite3").exists()
    assert not spec.archive_path.exists()


def test_archive_scoped_lock_blocks_second_runner_before_transport(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    with Canonical5mArchiveWriterLease.acquire(spec.archive_path):
        with pytest.raises(
            backfill.Historical5mBackfillError,
            match="archive_writer_lease_unavailable",
        ):
            _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert not (tmp_path / "backfill.sqlite3").exists()
    assert not spec.archive_path.exists()


def test_retry_never_appends_after_arbitrary_zero_row_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)

    def _crash_before_archive_append(*_: object, **__: object) -> object:
        raise RuntimeError("simulated_preappend_crash")

    original_append = DurableCanonical5mLabelArchive.append_candles
    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "append_candles",
        _crash_before_archive_append,
    )
    with pytest.raises(RuntimeError, match="preappend_crash"):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "append_candles",
        lambda *_args, **_kwargs: pytest.fail("retry attempted archive append"),
    )
    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "verified_range",
        lambda *_args, **_kwargs: (
            None,
            {
                "status": "BLOCKED_CANONICAL_5M_LABEL_RANGE_UNVERIFIED",
                "rejection_reasons": ["LABEL_ARCHIVE_SQLITE_READ_FAILED"],
                "loaded_rows": 0,
            },
        ),
    )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="empty_archive_range_not_verified",
    ):
        _run(tmp_path, spec=spec, transport=NoCallTransport())

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "append_candles",
        original_append,
    )


def test_crash_after_archive_commit_recovers_exact_transaction_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=2, page_limit=2)
    original_verify_commit = DurableCanonical5mLabelArchive._verify_committed_transaction

    def _crash_after_transaction_a(
        self: DurableCanonical5mLabelArchive,
        **_: object,
    ) -> None:
        raise RuntimeError("simulated_crash_after_archive_transaction_a")

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "_verify_committed_transaction",
        _crash_after_transaction_a,
    )
    transport = FakeTransport()
    with pytest.raises(RuntimeError, match="archive_transaction_a"):
        _run(tmp_path, spec=spec, transport=transport)
    assert len(transport.requests) == 1

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "_verify_committed_transaction",
        original_verify_commit,
    )
    result = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert result["job_complete"] is True
    assert result["prepared_pages_recovered"] == 1
    assert result["slot_receipt_counts"] == {"RECONCILED_CRASH_COMMITTED_REST_APPEND": 2}
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        recovery = connection.execute(
            """
            SELECT evidence_json FROM backfill_recovered_append_intents
            """
        ).fetchone()
        assert recovery is not None
        evidence = json.loads(recovery[0])
        attestation = evidence["exact_tail_transaction_attestation"]
        assert attestation["status"] == ("VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION")
        assert attestation["transaction_scope_verified"] is True
        assert attestation["terminal_full_integrity_verification_required"] is True
        outbox = connection.execute(
            """
            SELECT DISTINCT archive_transaction_id,
                            archive_append_receipt_sha256
            FROM backfill_outbox_rows
            """
        ).fetchall()
        assert outbox == [
            (
                attestation["transaction_id"],
                attestation["append_receipt_sha256"],
            )
        ]
        terminal = json.loads(
            connection.execute(
                "SELECT verification_json FROM backfill_final_verifications"
            ).fetchone()[0]
        )
        assert terminal["exact_transaction_identities_verified"] is True
        assert len(terminal["exact_transaction_identity_proofs"]) == 1
        assert (
            terminal["exact_transaction_identity_proofs"][0]["evidence_kind"]
            == "RECOVERED_EXACT_TAIL_ATTESTATION"
        )


def test_renewed_authority_receipt_resumes_same_crash_intent_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = _spec(tmp_path, slots=2, page_limit=2)
    renewed = _renewed_spec(original)
    assert renewed.job_id == original.job_id
    original_verify_commit = DurableCanonical5mLabelArchive._verify_committed_transaction

    def _crash_after_transaction_a(
        self: DurableCanonical5mLabelArchive,
        **_: object,
    ) -> None:
        raise RuntimeError("simulated_expiry_boundary_transaction_a_crash")

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "_verify_committed_transaction",
        _crash_after_transaction_a,
    )
    with pytest.raises(RuntimeError, match="expiry_boundary"):
        _run(tmp_path, spec=original, transport=FakeTransport())

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "_verify_committed_transaction",
        original_verify_commit,
    )
    resumed = _run(tmp_path, spec=renewed, transport=NoCallTransport())

    assert resumed["job_complete"] is True
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        receipts = connection.execute(
            """
            SELECT receipt_sha256, attestation_id
            FROM backfill_authority_receipts
            ORDER BY first_observed_at_ms, receipt_sha256
            """
        ).fetchall()
        assert {row[1] for row in receipts} == {
            "operator-fixed-cutoff-test",
            "operator-fixed-cutoff-renewal",
        }
        attempt = connection.execute(
            """
            SELECT attempt.authority_receipt_sha256,
                   resolution.reconciliation_authority_receipt_sha256,
                   resolution.resolution_kind
            FROM backfill_append_attempts AS attempt
            JOIN backfill_append_attempt_resolutions AS resolution
              ON resolution.attempt_id = attempt.attempt_id
            """
        ).fetchone()
        assert attempt == (
            original.authority_cutoff.receipt_sha256,
            renewed.authority_cutoff.receipt_sha256,
            "RECONCILED_CRASH_COMMITTED_REST_APPEND",
        )
        terminal = json.loads(
            connection.execute(
                "SELECT verification_json FROM backfill_final_verifications"
            ).fetchone()[0]
        )
        assert len(terminal["authority_receipt_bindings"]) == 2
        assert terminal["current_authority_receipt_sha256"] == (
            renewed.authority_cutoff.receipt_sha256
        )
        attempt_summary = terminal["append_attempt_authority_summary"]
        assert set(attempt_summary) == {
            "schema_version",
            "job_id",
            "attempt_count",
            "empty_no_commit_resolution_count",
            "terminal_resolution_count",
            "attempt_authority_chain_sha256",
            "all_attempts_resolved",
        }
        assert attempt_summary["schema_version"] == (
            "canonical_5m_append_attempt_authority_summary_v1"
        )
        assert attempt_summary["job_id"] == original.job_id
        assert attempt_summary["attempt_count"] == 1
        assert attempt_summary["empty_no_commit_resolution_count"] == 0
        assert attempt_summary["terminal_resolution_count"] == 1
        assert attempt_summary["all_attempts_resolved"] is True
        assert len(attempt_summary["attempt_authority_chain_sha256"]) == 64
        int(attempt_summary["attempt_authority_chain_sha256"], 16)


def test_same_attestation_id_cannot_be_reused_for_different_receipt(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    conflicting = _renewed_spec(
        spec,
        attestation_id="operator-fixed-cutoff-test",
    )
    store = backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3")
    store.ensure_job(spec, created_at_ms=OBSERVED_AT_MS)

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="attestation_id_reused_with_conflicting_receipt",
    ):
        store.ensure_job(conflicting, created_at_ms=OBSERVED_AT_MS)


def test_completed_job_renewal_does_not_mutate_sealed_authority_set(
    tmp_path: Path,
) -> None:
    original = _spec(tmp_path, slots=1)
    assert (
        _run(
            tmp_path,
            spec=original,
            transport=FakeTransport(),
        )["job_complete"]
        is True
    )
    renewed = _renewed_spec(original)
    assert renewed.job_id == original.job_id

    def _terminal_state() -> tuple[object, ...]:
        with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
            return (
                connection.execute(
                    """
                    SELECT receipt_sha256, attestation_id,
                           authority_scope_sha256, receipt_json,
                           attested_at_ms, valid_until_ms,
                           first_observed_at_ms
                    FROM backfill_authority_receipts
                    WHERE job_id = ? ORDER BY receipt_sha256
                    """,
                    (original.job_id,),
                ).fetchall(),
                connection.execute(
                    """
                    SELECT authority_receipt_count,
                           final_verification_sealed
                    FROM backfill_job_progress WHERE job_id = ?
                    """,
                    (original.job_id,),
                ).fetchone(),
                connection.execute(
                    """
                    SELECT verification_sha256, verification_json,
                           header_sha256, header_json, verified_at_ms
                    FROM backfill_final_verifications WHERE job_id = ?
                    """,
                    (original.job_id,),
                ).fetchone(),
            )

    before = _terminal_state()
    resumed = _run(
        tmp_path,
        spec=renewed,
        transport=NoCallTransport(),
    )
    after = _terminal_state()

    assert resumed["job_complete"] is True
    assert after == before
    assert len(after[0]) == 1
    sealed = json.loads(str(after[2][1]))
    assert sealed["current_authority_receipt_sha256"] == (original.authority_cutoff.receipt_sha256)
    assert len(sealed["authority_receipt_bindings"]) == 1
    assert renewed.authority_cutoff.receipt_sha256 not in {row[0] for row in after[0]}


def test_proven_empty_retry_records_distinct_resolved_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    original_append = DurableCanonical5mLabelArchive.append_candles

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "append_candles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated_preappend_side_effect_unknown")
        ),
    )
    with pytest.raises(RuntimeError, match="side_effect_unknown"):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "append_candles",
        original_append,
    )
    resumed = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert resumed["job_complete"] is True
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        attempts = connection.execute(
            """
            SELECT attempt.attempt_ordinal, resolution.resolution_kind
            FROM backfill_append_attempts AS attempt
            JOIN backfill_append_attempt_resolutions AS resolution
              ON resolution.attempt_id = attempt.attempt_id
            ORDER BY attempt.attempt_ordinal
            """
        ).fetchall()
        assert attempts == [
            (1, "PROVEN_EMPTY_NO_ARCHIVE_COMMIT"),
            (2, "ARCHIVED_REST_PROVEN_ABSENT_SLOT"),
        ]


def test_atomic_terminal_state_rolls_back_every_projection_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=2, page_limit=2)
    original_advance = backfill.Historical5mBackfillStore._advance_cursor

    def _crash_before_atomic_commit(*_: object, **__: object) -> None:
        raise RuntimeError("simulated_atomic_terminal_crash")

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "_advance_cursor",
        _crash_before_atomic_commit,
    )
    with pytest.raises(RuntimeError, match="atomic_terminal_crash"):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert connection.execute("SELECT status FROM backfill_pages").fetchone()[0] == "PREPARED"
        assert connection.execute(
            "SELECT status, COUNT(*) FROM backfill_outbox_rows GROUP BY status"
        ).fetchall() == [("PREPARED", 2)]
        assert connection.execute("SELECT COUNT(*) FROM backfill_slot_receipts").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_archive_transactions").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_recovered_append_intents").fetchone()[
                0
            ]
            == 0
        )
        assert connection.execute(
            """
            SELECT next_open_time_ms, complete FROM backfill_symbol_cursors
            """
        ).fetchone() == (BASE_OPEN_MS, 0)
        assert connection.execute(
            """
            SELECT page_prepared_count, page_complete_count,
                   slot_receipt_total, archive_transaction_count,
                   recovered_append_count
            FROM backfill_job_progress
            """
        ).fetchone() == (1, 0, 0, 0, 0)

    assert (
        DurableCanonical5mLabelArchive(spec.archive_path).verify_integrity()["verified_rows"] == 2
    )
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "_advance_cursor",
        original_advance,
    )

    resumed = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert resumed["job_complete"] is True
    assert resumed["prepared_pages_recovered"] == 1
    assert resumed["slot_receipt_counts"] == {"RECONCILED_CRASH_COMMITTED_REST_APPEND": 2}


def test_final_seal_rolls_back_cursor_projection_with_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=3, page_limit=3)
    DurableCanonical5mLabelArchive(spec.archive_path).append_candles([_wss_candle(BASE_OPEN_MS)])
    original_seal = backfill.Historical5mBackfillStore.seal_final_verification

    def _reject_final_receipt_insert(
        self: backfill.Historical5mBackfillStore,
        **kwargs: object,
    ) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TRIGGER reject_test_final_verification_insert
                BEFORE INSERT ON backfill_final_verifications
                BEGIN
                    SELECT RAISE(ABORT, 'simulated_final_seal_crash');
                END;
                """
            )
        original_seal(self, **kwargs)

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "seal_final_verification",
        _reject_final_receipt_insert,
    )
    with pytest.raises(sqlite3.IntegrityError, match="final_seal_crash"):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert connection.execute(
            """
            SELECT next_open_time_ms, complete
            FROM backfill_symbol_cursors WHERE job_id = ?
            """,
            (spec.job_id,),
        ).fetchone() == (BASE_OPEN_MS, 0)
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_final_verifications").fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER reject_test_final_verification_insert")

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "seal_final_verification",
        original_seal,
    )
    resumed = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert resumed["job_complete"] is True
    store = backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3")
    assert store.next_cursor(spec.job_id) is None


def test_page_terminalization_uses_one_transaction_at_page_scale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1_000, page_limit=1_000)
    terminal_sql: list[str] = []
    cursor_advances = 0
    original_commit = backfill.Historical5mBackfillStore.commit_page_terminal_state
    original_advance = backfill.Historical5mBackfillStore._advance_cursor

    def _traced_commit(
        self: backfill.Historical5mBackfillStore,
        **kwargs: object,
    ) -> int:
        original_connect = self._connect

        def _traced_connect() -> sqlite3.Connection:
            connection = original_connect()
            connection.set_trace_callback(terminal_sql.append)
            return connection

        self._connect = _traced_connect  # type: ignore[method-assign]
        try:
            return original_commit(self, **kwargs)
        finally:
            self.__dict__.pop("_connect", None)

    def _counted_advance(
        self: backfill.Historical5mBackfillStore,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        symbol: str,
    ) -> None:
        nonlocal cursor_advances
        cursor_advances += 1
        original_advance(
            self,
            connection,
            job_id=job_id,
            symbol=symbol,
        )

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "commit_page_terminal_state",
        _traced_commit,
    )
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "_advance_cursor",
        _counted_advance,
    )

    result = _run(
        tmp_path,
        spec=spec,
        transport=FakeTransport(),
        max_slots=2_000,
    )

    transaction_control = [
        " ".join(statement.split()).upper()
        for statement in terminal_sql
        if " ".join(statement.split()).upper() in {"BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"}
    ]
    assert result["job_complete"] is True
    assert result["slot_receipt_counts"] == {"ARCHIVED_REST_PROVEN_ABSENT_SLOT": 1_000}
    assert transaction_control == ["BEGIN IMMEDIATE", "COMMIT"]
    assert cursor_advances == 1
    assert not hasattr(backfill.Historical5mBackfillStore, "record_slot_receipt")
    assert not hasattr(backfill.Historical5mBackfillStore, "record_archive_transaction")
    assert not hasattr(backfill.Historical5mBackfillStore, "record_recovered_append_intent")
    assert not hasattr(backfill.Historical5mBackfillStore, "complete_page_if_terminal")


def test_matching_range_without_exact_transaction_attestation_is_not_recovered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)

    def _crash_before_transaction_receipt(*_: object, **__: object) -> None:
        raise RuntimeError("simulated_crash_before_backfill_transaction_receipt")

    original_record = backfill.Historical5mBackfillStore.commit_page_terminal_state
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "commit_page_terminal_state",
        _crash_before_transaction_receipt,
    )
    with pytest.raises(RuntimeError, match="transaction_receipt"):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "commit_page_terminal_state",
        original_record,
    )
    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "attest_exact_tail_transaction",
        lambda *_args, **_kwargs: {
            "status": "BLOCKED_CANONICAL_5M_EXACT_TAIL_TRANSACTION_UNVERIFIED",
            "rejection_reasons": ["INJECTED_UNVERIFIED_ATTESTATION"],
        },
    )

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="requires_exact_tail_transaction_attestation",
    ):
        _run(tmp_path, spec=spec, transport=NoCallTransport())

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_recovered_append_intents").fetchone()[
                0
            ]
            == 0
        )


def test_terminal_proof_change_before_receipt_seal_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    original_verify = DurableCanonical5mLabelArchive.verify_integrity
    calls = 0

    def _verify_then_change(self: DurableCanonical5mLabelArchive):
        nonlocal calls
        calls += 1
        proof = original_verify(self)
        if calls == 2:
            self.append_candles([_wss_candle(spec.end_open_time_ms_exclusive)])
        return proof

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "verify_integrity",
        _verify_then_change,
    )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="terminal_integrity_proof_stale",
    ):
        _run(tmp_path, spec=spec, transport=FakeTransport())

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM backfill_final_verifications").fetchone()[0]
            == 0
        )


def test_shared_lease_blocks_append_after_current_check_before_final_seal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    original_seal = backfill.Historical5mBackfillStore.seal_final_verification
    blocked: list[str] = []

    def _attempt_concurrent_append_then_seal(
        self: backfill.Historical5mBackfillStore,
        **kwargs: object,
    ) -> None:
        with pytest.raises(
            Canonical5mArchiveWriterLeaseError,
            match="already_held",
        ) as captured:
            DurableCanonical5mLabelArchive(spec.archive_path).append_candles(
                [_wss_candle(spec.end_open_time_ms_exclusive)]
            )
        blocked.append(str(captured.value))
        original_seal(self, **kwargs)

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "seal_final_verification",
        _attempt_concurrent_append_then_seal,
    )

    result = _run(tmp_path, spec=spec, transport=FakeTransport())

    assert result["job_complete"] is True
    assert result["wss_activation_ready"] is True
    assert blocked and "writer_lease_already_held" in blocked[0]
    integrity = DurableCanonical5mLabelArchive(spec.archive_path).verify_integrity()
    assert integrity["verified_rows"] == 1


def test_completed_fixed_cutoff_is_not_current_readiness_after_tail_advances(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    first = _run(tmp_path, spec=spec, transport=FakeTransport())
    assert first["wss_activation_ready"] is True

    DurableCanonical5mLabelArchive(spec.archive_path).append_candles(
        [_wss_candle(spec.end_open_time_ms_exclusive)]
    )
    resumed = _run(tmp_path, spec=spec, transport=NoCallTransport())

    assert resumed["job_complete"] is True
    assert resumed["full_archive_integrity_scans_this_run"] == 1
    assert resumed["wss_activation_ready"] is False
    assert resumed["archive_advanced_after_fixed_cutoff_completion"] is True
    assert resumed["phase"] == ("HISTORICAL_FIXED_CUTOFF_COMPLETE_ARCHIVE_TAIL_ADVANCED")
    assert len(str(resumed["post_completion_integrity_revalidation_sha256"])) == 64


def test_ordinary_resume_uses_compact_headers_not_full_manifests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=6, page_limit=2)
    with pytest.raises(AssertionError, match="transport unexpectedly called"):
        _run(
            tmp_path,
            spec=spec,
            transport=NoCallTransport(),
            max_pages=10,
        )

    def _full_document_forbidden(*_: object, **__: object) -> object:
        raise AssertionError("ordinary_resume_loaded_full_growing_document")

    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "inventory_manifest",
        _full_document_forbidden,
    )
    monkeypatch.setattr(
        backfill.Historical5mBackfillStore,
        "rest_intent_manifest",
        _full_document_forbidden,
    )
    transport = FakeTransport()

    resumed = _run(
        tmp_path,
        spec=spec,
        transport=transport,
        max_pages=1,
    )

    assert resumed["job_complete"] is False
    assert resumed["rest_page_counts"] == {"INTENT": 2, "COMPLETE": 1}
    assert len(transport.requests) == 1


def test_completed_resume_and_status_use_bounded_compact_queries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=6, page_limit=2)
    assert _run(tmp_path, spec=spec, transport=FakeTransport())["job_complete"] is True

    def _full_document_forbidden(*_: object, **__: object) -> object:
        raise AssertionError("completed_resume_loaded_full_growing_document")

    for method_name in (
        "inventory_manifest",
        "rest_intent_manifest",
        "final_verification",
    ):
        monkeypatch.setattr(
            backfill.Historical5mBackfillStore,
            method_name,
            _full_document_forbidden,
        )

    resumed = _run(tmp_path, spec=spec, transport=NoCallTransport())
    assert resumed["job_complete"] is True
    assert resumed["full_archive_integrity_scans_this_run"] == 0

    store = backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3")
    statements: list[str] = []
    original_connect = store._connect

    def _traced_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", _traced_connect)
    status = store.status(spec.job_id)
    select_statements = [
        " ".join(statement.split()).lower()
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert status["job_complete"] is True
    assert len(select_statements) == 2
    assert all(
        growing_table not in " ".join(select_statements)
        for growing_table in (
            "backfill_pages",
            "backfill_outbox_rows",
            "backfill_slot_receipts ",
            "backfill_archive_transactions",
            "backfill_recovered_append_intents",
        )
    )

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        header_rows = (
            connection.execute(
                """
                SELECT header_sha256, header_json
                FROM backfill_inventory_manifests
                """
            ).fetchone(),
            connection.execute(
                """
                SELECT header_sha256, header_json
                FROM backfill_rest_intent_manifests
                """
            ).fetchone(),
            connection.execute(
                """
                SELECT header_sha256, header_json
                FROM backfill_final_verifications
                """
            ).fetchone(),
        )
        for header_sha, header_json in header_rows:
            assert len(header_json.encode()) < 2_048
            assert header_sha == backfill._sha256_bytes(header_json.encode())


def test_recovered_tail_attestation_validator_rebuilds_exact_material(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=2, page_limit=2)
    archive = DurableCanonical5mLabelArchive(spec.archive_path)
    candles = [_wss_candle(BASE_OPEN_MS), _wss_candle(BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS)]
    archive.append_candles(candles)
    proof = archive.attest_exact_tail_transaction(candles)

    assert (
        backfill._validated_exact_tail_attestation(
            attestation=proof,
            archive_path=spec.archive_path,
            payloads=candles,
        )["transaction_scope_verified"]
        is True
    )

    wrong_hash = dict(proof)
    wrong_hash["transaction_id"] = "canonical_5m_append_" + "f" * 32
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="attestation_hash_mismatch",
    ):
        backfill._validated_exact_tail_attestation(
            attestation=wrong_hash,
            archive_path=spec.archive_path,
            payloads=candles,
        )

    wrong_fields = dict(proof)
    wrong_fields["unexpected"] = True
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="attestation_fields_invalid",
    ):
        backfill._validated_exact_tail_attestation(
            attestation=wrong_fields,
            archive_path=spec.archive_path,
            payloads=candles,
        )

    wrong_bindings = dict(proof)
    wrong_bindings["transaction_bindings"] = [
        {**dict(binding), "fabricated": True} for binding in proof["transaction_bindings"]
    ]
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="transaction_bindings_missing",
    ):
        backfill._validated_exact_tail_attestation(
            attestation=wrong_bindings,
            archive_path=spec.archive_path,
            payloads=candles,
        )


def test_unfinal_response_is_rejected_before_outbox_or_archive_append(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    close_ms = BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="response_clock_moved_backward_during_request",
    ):
        _run(
            tmp_path,
            spec=spec,
            transport=FakeTransport(received_at_ms=close_ms),
        )

    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM backfill_outbox_rows").fetchone()[0] == 0
        assert connection.execute("SELECT status FROM backfill_pages").fetchone()[0] == "INTENT"


@pytest.mark.parametrize(
    ("status_code", "floor_seconds"),
    ((429, 120), (418, 1_800)),
)
def test_rate_limit_receipt_enforces_durable_cooldown_floor(
    tmp_path: Path,
    status_code: int,
    floor_seconds: int,
) -> None:
    spec = _spec(tmp_path, slots=1)
    first_transport = FakeTransport(
        status_code=status_code,
        headers={"Retry-After": "30"},
        rows_factory=lambda _: {"code": -1003},
    )

    first = _run(tmp_path, spec=spec, transport=first_transport)
    assert first["paused_reason"] == f"binance_http_{status_code}_cooldown"
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        page_id, retry_not_before_ms = connection.execute(
            "SELECT page_id, retry_not_before_ms FROM backfill_pages"
        ).fetchone()
    assert retry_not_before_ms == OBSERVED_AT_MS + floor_seconds * 1_000

    store = backfill.Historical5mBackfillStore(tmp_path / "backfill.sqlite3")
    store.record_page_error(
        page_id=page_id,
        error="shorter_retry_must_not_replace_floor",
        retry_not_before_ms=OBSERVED_AT_MS + 1_000,
    )
    with sqlite3.connect(tmp_path / "backfill.sqlite3") as connection:
        assert (
            connection.execute("SELECT retry_not_before_ms FROM backfill_pages").fetchone()[0]
            == OBSERVED_AT_MS + floor_seconds * 1_000
        )

    second = _run(tmp_path, spec=spec, transport=FakeTransport())
    assert second["paused_reason"] == "durable_retry_cooldown_active"


@pytest.mark.parametrize(
    ("status_code", "retry_after", "expected_delta_ms"),
    (
        (429, None, 120_000),
        (429, "1", 120_000),
        (429, "121.25", 121_250),
        (429, "nan", 120_000),
        (429, "inf", 120_000),
        (418, "invalid", 1_800_000),
        (418, "1", 1_800_000),
        (418, "1801.5", 1_801_500),
    ),
)
def test_retry_after_honors_larger_values_and_never_undercuts_status_floor(
    status_code: int,
    retry_after: str | None,
    expected_delta_ms: int,
) -> None:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    response = backfill.PublicHttpResponse(
        status_code=status_code,
        headers=headers,
        body=b"{}",
        received_at_ms=OBSERVED_AT_MS,
    )

    assert backfill._retry_after_ms(response) == OBSERVED_AT_MS + expected_delta_ms


def test_retry_after_rejects_non_rate_status_and_invalid_response_clock() -> None:
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="non_rate_limit_response",
    ):
        backfill._retry_after_ms(
            backfill.PublicHttpResponse(
                status_code=500,
                headers={},
                body=b"{}",
                received_at_ms=OBSERVED_AT_MS,
            )
        )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="rate_limit_response_clock_invalid",
    ):
        backfill._retry_after_ms(
            backfill.PublicHttpResponse(
                status_code=429,
                headers={},
                body=b"{}",
                received_at_ms=1,
            )
        )


def test_request_weight_bounds_cover_utc_minute_run_and_backward_clock() -> None:
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="backfill_weight_budget_invalid",
    ):
        backfill.BackfillRunBounds(local_weight_budget_per_minute=121).validated()
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="backfill_run_request_weight_invalid",
    ):
        backfill.BackfillRunBounds(max_request_weight_per_run=121).validated()

    request = backfill.BinanceKlineRequest(
        symbol="BTCUSDT",
        start_open_time_ms=BASE_OPEN_MS,
        end_close_time_ms=BASE_OPEN_MS + 1_000 * LABEL_SLOT_MILLISECONDS - 1,
        limit=1_000,
    )
    minute_governor = backfill.LocalWeightGovernor(
        budget_per_minute=5,
        max_weight_per_run=15,
    )
    minute_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS)
    with pytest.raises(
        backfill.Historical5mBackfillPaused,
        match="utc_minute_budget_exhausted",
    ):
        minute_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS + 1)
    minute_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS + 60_000)
    assert minute_governor.request_weight_reserved_this_run == 10
    assert minute_governor.request_weight_reserved_current_utc_minute == 5

    run_governor = backfill.LocalWeightGovernor(
        budget_per_minute=5,
        max_weight_per_run=10,
    )
    run_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS)
    run_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS + 60_000)
    with pytest.raises(
        backfill.Historical5mBackfillPaused,
        match="run_budget_exhausted",
    ):
        run_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS + 120_000)

    backward_governor = backfill.LocalWeightGovernor(
        budget_per_minute=10,
        max_weight_per_run=10,
    )
    backward_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS + 1)
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="clock_moved_backward",
    ):
        backward_governor.reserve(request, observed_at_ms=OBSERVED_AT_MS)


def test_cutoff_and_lease_contracts_fail_closed(tmp_path: Path) -> None:
    expired = _spec(
        tmp_path,
        slots=1,
        valid_until_ms=OBSERVED_AT_MS - 1,
    )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="attestation_expired_or_invalid",
    ):
        _run(tmp_path, spec=expired, transport=NoCallTransport())

    valid = _spec(tmp_path, slots=1)
    mismatched = backfill.BackfillJobSpec(
        archive_path=valid.archive_path,
        symbols=valid.symbols,
        start_open_time_ms=valid.start_open_time_ms,
        end_open_time_ms_exclusive=(valid.end_open_time_ms_exclusive + LABEL_SLOT_MILLISECONDS),
        authority_cutoff=valid.authority_cutoff,
        page_limit=valid.page_limit,
    )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="end_must_equal_fixed_wss_authority_cutoff",
    ):
        mismatched.validated()


def test_request_contract_is_public_and_credential_free() -> None:
    request = backfill.BinanceKlineRequest(
        symbol="BTCUSDT",
        start_open_time_ms=BASE_OPEN_MS,
        end_close_time_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        limit=1,
    )

    contract = request.contract()
    assert request.url.startswith(
        "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m"
    )
    assert contract["auth_headers_present"] is False
    assert contract["credentials_used"] is False
    assert contract["places_orders"] is False
    assert backfill.BinanceKlineRequest.from_contract(contract) == request
    assert canonical_json(contract) == canonical_json(
        backfill.BinanceKlineRequest.from_contract(contract).contract()
    )


@pytest.mark.parametrize("artifact_index", range(5))
def test_state_path_cannot_alias_archive_or_its_sidecars_before_mutation(
    tmp_path: Path,
    artifact_index: int,
) -> None:
    spec = _spec(tmp_path, slots=1)
    state_path = backfill.historical_backfill_sqlite_artifact_paths(spec.archive_path)[
        artifact_index
    ]

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="state_path_collides_with_archive_artifact",
    ):
        backfill.run_historical_5m_backfill(
            spec=spec,
            bounds=backfill.BackfillRunBounds(max_pages=1, max_slots=1),
            state_path=state_path,
            transport=NoCallTransport(),
            clock_ms=lambda: OBSERVED_AT_MS,
            wss_inactive_probe=lambda: (_ for _ in ()).throw(
                AssertionError("path rejection must precede runtime probing")
            ),
        )

    assert not spec.archive_path.exists()
    assert not Path(str(spec.archive_path) + ".writer.lock").exists()


def test_state_path_hard_link_to_archive_is_rejected_without_modification(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path, slots=1)
    marker = b"operator-archive-marker"
    spec.archive_path.write_bytes(marker)
    state_path = tmp_path / "state-hard-link.sqlite3"
    os.link(spec.archive_path, state_path)

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="state_path_collides_with_archive_artifact",
    ):
        backfill.run_historical_5m_backfill(
            spec=spec,
            bounds=backfill.BackfillRunBounds(max_pages=1, max_slots=1),
            state_path=state_path,
            transport=NoCallTransport(),
            clock_ms=lambda: OBSERVED_AT_MS,
            wss_inactive_probe=lambda: (_ for _ in ()).throw(
                AssertionError("path rejection must precede runtime probing")
            ),
        )

    assert spec.archive_path.read_bytes() == marker
    assert state_path.read_bytes() == marker


def test_existing_legacy_job_schema_is_rejected_read_only_before_new_job(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "backfill.sqlite3"
    store = backfill.Historical5mBackfillStore(state_path)
    first = _spec(tmp_path, slots=1)
    store.ensure_job(first, created_at_ms=OBSERVED_AT_MS)
    with sqlite3.connect(state_path) as connection:
        connection.execute("UPDATE backfill_jobs SET schema_version = 'legacy_v2'")
    before = state_path.stat().st_mtime_ns
    second = _spec(tmp_path, slots=2)

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="state_schema_migration_required",
    ):
        store.ensure_job(second, created_at_ms=OBSERVED_AT_MS)

    assert state_path.stat().st_mtime_ns == before
    with sqlite3.connect(state_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM backfill_jobs").fetchone()[0] == 1


def test_existing_tampered_trigger_schema_is_rejected_before_reuse(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "backfill.sqlite3"
    store = backfill.Historical5mBackfillStore(state_path)
    spec = _spec(tmp_path, slots=1)
    store.ensure_job(spec, created_at_ms=OBSERVED_AT_MS)
    with sqlite3.connect(state_path) as connection:
        connection.execute("DROP TRIGGER backfill_outbox_no_delete")
        connection.execute(
            """
            CREATE TRIGGER backfill_outbox_no_delete
            BEFORE DELETE ON backfill_outbox_rows
            BEGIN
                SELECT 1;
            END
            """
        )

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="state_schema_migration_required",
    ):
        store.ensure_job(spec, created_at_ms=OBSERVED_AT_MS)


def test_work_page_queries_use_bounded_covering_index_without_temp_sort(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "backfill.sqlite3"
    store = backfill.Historical5mBackfillStore(state_path)
    store.initialize()
    with sqlite3.connect(state_path) as connection:
        for status in ("PREPARED", "INTENT"):
            plan = list(
                connection.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT page_id FROM backfill_pages
                    WHERE job_id = ? AND status = ?
                    ORDER BY start_open_time_ms, page_id
                    LIMIT ?
                    """,
                    ("job", status, 4),
                )
            )
            rendered = " ".join(str(row[3]) for row in plan)
            assert "backfill_pages_job_status_start_page_v3" in rendered
            assert "TEMP B-TREE" not in rendered


def test_huge_retry_after_clamps_to_sqlite_integer_without_losing_floor() -> None:
    response = backfill.PublicHttpResponse(
        status_code=418,
        headers={"retry-after": "1e308"},
        body=b"[]",
        received_at_ms=OBSERVED_AT_MS,
    )

    assert backfill._retry_after_ms(response) == backfill.MAX_SQLITE_INTEGER


def test_unfinal_payload_validation_remains_independently_fail_closed() -> None:
    request = backfill.BinanceKlineRequest(
        symbol="BTCUSDT",
        start_open_time_ms=BASE_OPEN_MS,
        end_close_time_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        limit=1,
    )
    response = backfill.PublicHttpResponse(
        status_code=200,
        headers={},
        body=json.dumps([_raw_kline(BASE_OPEN_MS)]).encode(),
        received_at_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
    )

    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="contains_unfinal_candle",
    ):
        backfill._validate_response_payloads(request=request, response=response)


def test_urllib_transport_rejects_nonfinite_timeout_redirects_and_oversized_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="http_timeout_invalid",
    ):
        backfill.UrllibPublicKlineTransport(
            timeout_seconds=float("nan"),
            clock_ms=lambda: OBSERVED_AT_MS,
        )

    transport = backfill.UrllibPublicKlineTransport(
        timeout_seconds=1.0,
        clock_ms=lambda: OBSERVED_AT_MS,
    )
    monkeypatch.setattr(
        transport._opener,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid request must not reach opener")
        ),
    )
    invalid = backfill.BinanceKlineRequest(
        symbol="BTCUSDT",
        start_open_time_ms=BASE_OPEN_MS,
        end_close_time_ms=BASE_OPEN_MS + LABEL_SLOT_MILLISECONDS - 1,
        limit=1_001,
    )
    with pytest.raises(
        backfill.Historical5mBackfillError,
        match="request_limit_invalid",
    ):
        transport.fetch(invalid)

    assert (
        backfill._RejectRedirectHandler().redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://example.invalid/redirected",
        )
        is None
    )
