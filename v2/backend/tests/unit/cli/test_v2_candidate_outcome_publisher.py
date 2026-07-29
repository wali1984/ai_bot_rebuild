from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.cli.v2_candidate_outcome_publisher import (
    PAPER_INTENTS_KEY,
    PAPER_CLOSED_TRADES_KEY,
    PAPER_REGISTRY_KEY,
    PAPER_STATUS_KEY,
    RUNTIME_STATUS_KEY,
    CandidateOutcomeRuntimeError,
    _acquire_single_writer_lock,
    _load_feature_snapshots,
    _load_signing_key,
    _actual_paper_outcome_from_close,
    _authenticated_actual_close_sources,
    process_cycle,
    process_maturation,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_publisher_v2 import (
    build_publisher_cycle,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_maturer_v2 import (
    _record as _maturation_record,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_maturer_v2 import (
    _rows_and_proof,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_publisher_v2 import (
    _inputs,
    _registry,
)


class _FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def mget(self, keys):
        return [self.values.get(key) for key in keys]

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True


def _client(status, intents) -> _FakeRedis:
    return _FakeRedis(
        {
            PAPER_STATUS_KEY: json.dumps(status),
            PAPER_INTENTS_KEY: json.dumps(intents),
            PAPER_REGISTRY_KEY: json.dumps(_registry()),
            PAPER_CLOSED_TRADES_KEY: json.dumps([]),
        }
    )


def _archive(path: Path) -> CandidateOutcomeArchiveV2:
    key = Ed25519PrivateKey.generate()
    public_key_hex = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id="candidate-outcome-writer-v2",
        writer_public_key_hex=public_key_hex,
        signer=key.sign,
    )


def _write_feature_archive(root: Path, snapshots) -> None:
    for snapshot in snapshots.values():
        append_snapshot(snapshot, root=root, update_checksum_manifest=False)


def test_feature_snapshot_loader_consumes_verified_sharded_index(
    tmp_path: Path,
) -> None:
    _status, intents, snapshots = _inputs(1)
    snapshot = snapshots["snapshot-0"]
    feature_root = tmp_path / "features"

    archived = append_snapshot(
        snapshot,
        root=feature_root,
        update_checksum_manifest=False,
    )
    loaded = _load_feature_snapshots(intents, feature_root)

    assert archived.index_path.parent.parent.parent.name == "snapshot_id"
    assert archived.index_path.parent.parent.name != "snapshot_id"
    assert loaded == {"snapshot-0": snapshot}


@pytest.mark.parametrize("failure_mode", ("missing", "corrupt"))
def test_feature_snapshot_loader_fails_closed_for_unverified_sharded_snapshot(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    _status, intents, snapshots = _inputs(1)
    feature_root = tmp_path / "features"
    if failure_mode == "missing":
        with pytest.raises(
            CandidateOutcomeRuntimeError,
            match="snapshot-0:missing_from_verified_archive",
        ):
            _load_feature_snapshots(intents, feature_root)
        return

    archived = append_snapshot(
        snapshots["snapshot-0"],
        root=feature_root,
        update_checksum_manifest=False,
    )
    corrupt = json.loads(archived.blob_path.read_text(encoding="utf-8"))
    corrupt["features"]["close"] = 999.0
    archived.blob_path.write_text(json.dumps(corrupt), encoding="utf-8")

    with pytest.raises(SnapshotArchiveError, match="CONTENT_SHA256_MISMATCH"):
        _load_feature_snapshots(intents, feature_root)


def test_runtime_batch_archives_exact_cycle_and_is_idempotent(tmp_path: Path) -> None:
    status, intents, snapshots = _inputs()
    feature_root = tmp_path / "features"
    state_root = tmp_path / "state"
    _write_feature_archive(feature_root, snapshots)
    client = _client(status, intents)
    archive = _archive(state_root / "candidate_decision_outcomes_v2.jsonl")

    first = process_cycle(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=feature_root,
        signed_at_ms=1_785_182_500_000,
    )
    assert first["candidate_recording_coverage_100_percent"] is True
    assert first["unexplained_candidate_drops"] == 0
    assert first["archive_batch_append_count"] == 2
    assert first["cycle_idempotent_replay"] is False
    assert first["paper_only"] is True
    assert first["routes_to_live"] is False
    assert first["candidate_outcome_maturer_runtime_integrated"] is False
    assert archive.verify().row_count == 2
    assert json.loads(client.values[RUNTIME_STATUS_KEY])["status"] == "PASS"

    second = process_cycle(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=feature_root,
        signed_at_ms=1_785_182_600_000,
    )
    assert second["cycle_idempotent_replay"] is True
    assert second["archive_batch_append_count"] == 0
    assert archive.verify().row_count == 2


def test_runtime_refuses_missing_snapshot_and_writes_no_archive(tmp_path: Path) -> None:
    status, intents, _ = _inputs(1)
    state_root = tmp_path / "state"
    archive = _archive(state_root / "candidate_decision_outcomes_v2.jsonl")
    with pytest.raises(CandidateOutcomeRuntimeError, match="missing_from_verified_archive"):
        process_cycle(
            client=_client(status, intents),
            archive=archive,
            state_root=state_root,
            feature_archive_root=tmp_path / "missing-features",
            signed_at_ms=1_785_182_500_000,
        )
    assert archive.verify().row_count == 0


def test_corrupt_cycle_receipt_cannot_suppress_reconciliation(tmp_path: Path) -> None:
    status, intents, snapshots = _inputs(1)
    feature_root = tmp_path / "features"
    state_root = tmp_path / "state"
    _write_feature_archive(feature_root, snapshots)
    client = _client(status, intents)
    archive = _archive(state_root / "candidate_decision_outcomes_v2.jsonl")
    first = process_cycle(
        client=client,
        archive=archive,
        state_root=state_root,
        feature_archive_root=feature_root,
        signed_at_ms=1_785_182_500_000,
    )
    receipt_path = state_root / "cycle_receipts" / f"{first['cycle_id']}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_candidate_count"] = 99
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CandidateOutcomeRuntimeError, match="source_candidate_count:mismatch"):
        process_cycle(
            client=client,
            archive=archive,
            state_root=state_root,
            feature_archive_root=feature_root,
            signed_at_ms=1_785_182_600_000,
        )


def test_zero_candidate_cycle_is_durably_receipted(tmp_path: Path) -> None:
    status, intents, _ = _inputs(0)
    state_root = tmp_path / "state"
    archive = _archive(state_root / "candidate_decision_outcomes_v2.jsonl")
    result = process_cycle(
        client=_client(status, intents),
        archive=archive,
        state_root=state_root,
        feature_archive_root=tmp_path / "features",
        signed_at_ms=1_785_182_500_000,
    )
    assert result["source_candidate_count"] == 0
    assert result["candidate_recording_coverage"] == 1.0
    assert result["archive"]["row_count"] == 0
    assert len(tuple((state_root / "cycle_receipts").glob("*.json"))) == 1


def test_signing_key_requires_exact_systemd_credential(monkeypatch, tmp_path: Path) -> None:
    credential_root = tmp_path / "credentials"
    credential_root.mkdir()
    credential_path = credential_root / "candidate_outcome_ed25519_seed"
    credential_path.write_bytes(b"x" * 31)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credential_root))
    with pytest.raises(CandidateOutcomeRuntimeError, match="exactly_32_bytes_required"):
        _load_signing_key()

    credential_path.write_bytes(b"x" * 32)
    _, public_key_hex = _load_signing_key()
    assert len(public_key_hex) == 64


def test_single_writer_lock_fails_closed(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime" / "writer.lock"
    first = _acquire_single_writer_lock(lock_path)
    try:
        with pytest.raises(BlockingIOError):
            _acquire_single_writer_lock(lock_path)
    finally:
        os.close(first)
    second = _acquire_single_writer_lock(lock_path)
    os.close(second)


class _FakeLabelArchive:
    def __init__(self, rows, proof) -> None:
        self.rows = rows
        self.proof = proof

    def verify_integrity(self):
        return {
            "archive_integrity_verified": True,
            "archive_chain_sha256": "d" * 64,
            "rejection_reasons": [],
        }

    def verified_range(self, **kwargs):
        assert kwargs["symbol"] == self.proof["symbol"]
        assert kwargs["start_close_time_ms"] == self.proof["start_close_time_ms"]
        assert kwargs["end_close_time_ms"] == self.proof["end_close_time_ms"]
        assert kwargs["archive_integrity_proof"]["archive_integrity_verified"] is True
        return self.rows, self.proof


class _FakeExtendingLabelArchive(_FakeLabelArchive):
    def __init__(self, rows, proof) -> None:
        super().__init__(rows, proof)
        self.full_verifications = 0
        self.extensions = 0

    def verify_integrity(self):
        self.full_verifications += 1
        return super().verify_integrity()

    def extend_integrity_proof(self, proof):
        assert proof["archive_integrity_verified"] is True
        self.extensions += 1
        return {
            **proof,
            "archive_chain_sha256": "e" * 64,
            "verification_mode": "VERIFIED_APPEND_ONLY_SUFFIX_EXTENSION",
            "rejection_reasons": [],
        }


def test_runtime_matures_due_candidate_with_same_authenticated_streaming_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _maturation_record()
    rows, proof = _rows_and_proof(record)
    archive = _archive(tmp_path / "state" / "candidate_decision_outcomes_v2.jsonl")
    archive.append(record, signed_at_ms=record.record_available_at_ms)
    signed_at_ms = proof["training_observed_at_ms"] + 1
    stream_calls = 0
    streaming_read = archive.read_verified_maturation_batch_with_verification

    def counted_streaming_read(**kwargs):
        nonlocal stream_calls
        stream_calls += 1
        return streaming_read(**kwargs)

    monkeypatch.setattr(
        archive,
        "read_verified_maturation_batch_with_verification",
        counted_streaming_read,
    )
    monkeypatch.setattr(
        archive,
        "read_verified_records_with_verification",
        lambda **_kwargs: pytest.fail(
            "runtime maturation must not use the full record materialization path"
        ),
    )
    monkeypatch.setattr(
        archive,
        "_parse_rows",
        lambda: pytest.fail("runtime maturation must not materialize all archive rows"),
    )

    status = process_maturation(
        archive=archive,
        label_archive=_FakeLabelArchive(rows, proof),  # type: ignore[arg-type]
        signed_at_ms=signed_at_ms,
        max_candidates=10,
    )
    assert status["status"] == "PASS"
    assert status["horizon_due_candidate_count"] == 1
    assert status["newly_matured_candidate_count"] == 1
    assert status["eligible_matured_label_coverage_100_percent"] is True
    assert status["counterfactual_counts_as_paper_profit"] is False
    assert status["archive_verification"]["matured_revision_count"] == 1
    assert status["execution_authority"] is False
    assert status["paper_only"] is True
    assert status["live_gate"] == "blocked_human_only"
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert status["exchange_action_taken"] is False
    assert stream_calls == 1


def test_runtime_uses_and_refreshes_incremental_label_integrity_cache(
    tmp_path: Path,
) -> None:
    record = _maturation_record()
    rows, proof = _rows_and_proof(record)
    archive = _archive(tmp_path / "state" / "candidate_decision_outcomes_v2.jsonl")
    archive.append(record, signed_at_ms=record.record_available_at_ms)
    label_archive = _FakeExtendingLabelArchive(rows, proof)
    cache = {
        "archive_integrity_verified": True,
        "archive_chain_sha256": "d" * 64,
    }

    status = process_maturation(
        archive=archive,
        label_archive=label_archive,  # type: ignore[arg-type]
        signed_at_ms=proof["training_observed_at_ms"] + 1,
        max_candidates=10,
        integrity_proof_cache=cache,
    )

    assert label_archive.full_verifications == 0
    assert label_archive.extensions == 1
    assert cache["archive_chain_sha256"] == "e" * 64
    assert status["canonical_label_archive_verification_mode"] == (
        "VERIFIED_APPEND_ONLY_SUFFIX_EXTENSION"
    )


def _iso(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1_000, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def test_typed_exploration_close_builds_exact_actual_paper_outcome() -> None:
    status, intents, snapshots = _inputs(1)
    intent = intents[0]
    intent.update(
        {
            "paper_fill_allowed": True,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "adaptive_policy_authoritative": True,
            "adaptive_policy_action_id": "adaptive-action-1",
            "adaptive_policy_action_sha256": "1" * 64,
            "adaptive_policy_action_policy_mode": (
                "bounded_information_seeking_exploration"
            ),
            "adaptive_paper_policy_authorization_sha256": "2" * 64,
            "adaptive_policy_paper_cycle_receipt_id": "adaptive-cycle-1",
            "adaptive_policy_paper_cycle_receipt_sha256": "3" * 64,
            "exploration_provenance": True,
            "counts_as_training_feedback": True,
            "counts_as_live_profit": False,
        }
    )
    record = build_publisher_cycle(
        paper_status=status,
        intents=intents,
        registry_payload=_registry(),
        feature_snapshots_by_id=snapshots,
    ).decision_records[0]
    decision_ms = record.decision.decision_time_ms
    close = {
        "adaptive_policy_authoritative": True,
        "adaptive_policy_action_id": "adaptive-action-1",
        "adaptive_policy_action_sha256": "1" * 64,
        "adaptive_policy_action_policy_mode": (
            "bounded_information_seeking_exploration"
        ),
        "adaptive_paper_policy_authorization_sha256": "2" * 64,
        "adaptive_policy_paper_cycle_receipt_id": "adaptive-cycle-1",
        "adaptive_policy_paper_cycle_receipt_sha256": "3" * 64,
        "exploration_provenance": True,
        "counts_as_training_feedback": True,
        "counts_as_live_profit": False,
        "close_position": True,
        "reduce_only": True,
        "remaining_quantity_after_close": 0.0,
        "entry_prediction_id": intent["prediction_id"],
        "preemptive_decision_id": intent["preemptive_decision_id"],
        "policy_id": intent.get("policy_id") or intent["candidate_id"],
        "policy_fingerprint": intent["policy_fingerprint"],
        "checkpoint_generation": _registry()["registry_generation"],
        "checkpoint_id": intent["checkpoint_id"],
        "entry_signal_id": "paper-signal-1",
        "intent_id": "paper-intent-1",
        "entry_fill_id": "paper-fill-1",
        "position_id": "paper-position-1",
        "close_id": "paper-close-1",
        "paper_final_admission_receipt_hash": "4" * 64,
        "entry_generation_time_utc": _iso(decision_ms + 1_000),
        "close_event_time": _iso(decision_ms + 2_000),
        "closed_quantity": 2.0,
        "entry_price": 10.0,
        "gross_notional_usd": 20.0,
        "effective_leverage": 2.0,
        "allocated_margin_usd": 10.0,
        "realized_net_pnl_usd": -0.5,
        "paper_session_id": "paper-session-1",
        "paper_account_epoch": 1,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    paper_status = {
        "paper_session_id": "paper-session-1",
        "paper_account_epoch": 1,
        "paper_account_margin_status": {
            "status": "PASS",
            "accounting_complete": True,
            "invariant_holds": True,
            "used_margin_usd": 0.0,
            "newly_reserved_margin_usd": 0.0,
        },
        "paper_position_fill_reconciliation_status": {
            "status": "PASS",
            "unresolved_position_count": 0,
            "phantom_position_count": 0,
            "wallet_balance_mutation_usd": 0.0,
        },
    }

    sources, source_status = _authenticated_actual_close_sources(
        paper_status=paper_status,
        closed_trades=[close],
    )
    assert sources == {record.decision.candidate_id: close}
    assert source_status["actual_close_source_rejection_counts"] == {}
    actual = _actual_paper_outcome_from_close(
        record=record,
        close=close,
        paper_status=paper_status,
        observed_at_ms=decision_ms + 3_000,
    )
    assert actual.candidate_id == record.decision.candidate_id
    assert actual.realized_pnl_usd == -0.5
    assert actual.realized_pnl_bps == -250.0
    assert actual.open_quantity_after_close == 0.0
    assert actual.places_real_order is False
    assert actual.exchange_action_taken is False
