from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.cli.v2_candidate_outcome_publisher import (
    PAPER_INTENTS_KEY,
    PAPER_REGISTRY_KEY,
    PAPER_STATUS_KEY,
    RUNTIME_STATUS_KEY,
    CandidateOutcomeRuntimeError,
    _acquire_single_writer_lock,
    _load_signing_key,
    process_cycle,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    append_snapshot,
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
