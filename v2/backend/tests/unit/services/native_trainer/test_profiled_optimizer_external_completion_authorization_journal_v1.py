from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_journal_v1 as journal_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_request_v1 as request_module,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_optimizer_external_completion_request_v1 as request_support,
)

adapter_evidence = request_support.adapter_evidence
AUTHORIZATION_ANCHORED = journal_module.AUTHORIZATION_ANCHORED
AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256 = (
    journal_module.AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
)
REQUEST_PREPARED = journal_module.REQUEST_PREPARED
ProfiledOptimizerCompletionAuthorizationJournalV1 = (
    journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1
)
ProfiledOptimizerCompletionAuthorizationJournalV1Error = (
    journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1Error
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256 = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
)
PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN
)
rehydrate_profiled_optimizer_external_completion_prepared_request_v1 = (
    request_module.rehydrate_profiled_optimizer_external_completion_prepared_request_v1
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _journal(tmp_path: Path) -> ProfiledOptimizerCompletionAuthorizationJournalV1:
    root = tmp_path.absolute()
    root.mkdir(parents=True, exist_ok=True)
    return ProfiledOptimizerCompletionAuthorizationJournalV1(
        root / "completion-authorization-journal.sqlite3",
        immutable_store=ImmutableSourcePayloadStore(root / "completion-authorization-cas"),
    )


def _filesystem_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    snapshot: dict[str, tuple[object, ...]] = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        relative = str(path.relative_to(root))
        common = (
            stat.S_IMODE(metadata.st_mode),
            metadata.st_uid,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        if stat.S_ISREG(metadata.st_mode):
            snapshot[relative] = (
                "file",
                *common,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif stat.S_ISDIR(metadata.st_mode):
            snapshot[relative] = ("directory", *common)
        elif stat.S_ISLNK(metadata.st_mode):
            snapshot[relative] = ("symlink", *common, path.readlink())
        else:
            snapshot[relative] = ("other", *common)
    return snapshot


def _journal_evidence_snapshot(
    journal: ProfiledOptimizerCompletionAuthorizationJournalV1,
) -> dict[str, tuple[int, int, int, int, int, int, int, str]]:
    paths = [
        journal.path,
        Path(f"{journal.path}-wal"),
        Path(f"{journal.path}-shm"),
    ]
    paths.extend(
        path
        for path in journal.immutable_store.root_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    snapshot: dict[str, tuple[int, int, int, int, int, int, int, str]] = {}
    for path in sorted(set(paths)):
        if not path.exists():
            continue
        metadata = path.stat()
        snapshot[str(path)] = (
            metadata.st_dev,
            metadata.st_ino,
            stat.S_IMODE(metadata.st_mode),
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshot


def _prepared(evidence: dict[str, Any]) -> Any:
    return request_support._prepared(evidence)


def _derived_prepared(
    prepared: Any,
    *,
    label: str,
    expected_sequence: int | None = None,
    predecessor: str | None = None,
    namespace: str | None = None,
    change_completion: bool = True,
) -> Any:
    request = json.loads(prepared.request_bytes)
    claim = json.loads(
        base64.b64decode(
            request["authorization_claim_template_base64"],
            validate=True,
        )
    )
    completion = json.loads(
        base64.b64decode(request["completion_event_base64"], validate=True)
    )
    challenge = hashlib.sha256(f"{label}:challenge".encode("ascii")).digest()
    challenge_sha = hashlib.sha256(challenge).hexdigest()
    requested_sequence = (
        prepared.expected_authorization_sequence
        if expected_sequence is None
        else expected_sequence
    )
    requested_predecessor = (
        prepared.expected_previous_authorization_event_sha256
        if predecessor is None
        else predecessor
    )

    if change_completion:
        completion["completion_id"] = hashlib.sha256(
            f"{label}:completion".encode("ascii")
        ).hexdigest()
    completion_bytes = _canonical(completion)
    completion_sha = hashlib.sha256(completion_bytes).hexdigest()
    completion_binding = claim["full_consumption_binding"]
    completion_binding["completion_id"] = completion["completion_id"]
    completion_binding["completion_event_sha256"] = completion_sha
    completion_binding["completion_event_byte_count"] = len(completion_bytes)
    claim["authorization_sequence"] = requested_sequence + 1
    claim["previous_authorization_event_sha256"] = requested_predecessor
    claim["authorization_challenge_sha256"] = challenge_sha
    if namespace is not None:
        claim["namespace"] = namespace
        request["authorization_namespace"] = namespace
        request["manifest_head_binding"]["namespace"] = namespace
    claim_bytes = _canonical(claim)

    request["expected_authorization_sequence"] = requested_sequence
    request["expected_previous_authorization_event_sha256"] = requested_predecessor
    request["authorization_challenge_sha256"] = challenge_sha
    request["authorization_challenge_byte_count"] = len(challenge)
    request["authorization_challenge_base64"] = base64.b64encode(challenge).decode("ascii")
    request["authorization_claim_template_sha256"] = hashlib.sha256(
        claim_bytes
    ).hexdigest()
    request["authorization_claim_template_byte_count"] = len(claim_bytes)
    request["authorization_claim_template_base64"] = base64.b64encode(
        claim_bytes
    ).decode("ascii")
    request["completion_event_sha256"] = completion_sha
    request["completion_event_byte_count"] = len(completion_bytes)
    request["completion_event_base64"] = base64.b64encode(completion_bytes).decode(
        "ascii"
    )
    base = {name: value for name, value in request.items() if name != "idempotency_key"}
    request["idempotency_key"] = hashlib.sha256(
        PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical(base)
    ).hexdigest()
    return rehydrate_profiled_optimizer_external_completion_prepared_request_v1(
        request_bytes=_canonical(request),
    )


def _wrong_public_key() -> bytes:
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


def test_empty_initialize_is_separate_non_authorizing_journal(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.initialize()
    report = journal.verify_integrity()

    assert report.operation_count == 0
    assert report.transition_count == 0
    assert report.pending_count == 0
    assert report.terminal_transition_sha256 == (
        AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
    )
    assert report.optimizer_execution_authorized is False
    assert report.checkpoint_write_authorized is False
    assert report.live_execution_authorized is False


def test_prepared_request_and_all_exact_evidence_survive_restart(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    record = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )

    assert record.state == REQUEST_PREPARED
    assert record.prepared == prepared
    for digest in (
        prepared.authorization_challenge_sha256,
        prepared.authorization_claim_template_sha256,
        prepared.request_sha256,
        prepared.completion_event_sha256,
        prepared.final_page_receipt_event_sha256,
        prepared.witness_public_key_sha256,
    ):
        assert journal.immutable_store.path_for(digest).is_file()

    restarted = ProfiledOptimizerCompletionAuthorizationJournalV1(
        journal.path,
        immutable_store=journal.immutable_store,
    )
    pending = restarted.load_pending_requests(
        witness_id=prepared.witness_id,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert len(pending) == 1
    assert pending[0].operation_id == record.operation_id
    assert pending[0].prepared == prepared


def test_completion_lookup_reopens_exact_pending_and_anchored_record(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    lookup = {
        "witness_id": prepared.witness_id,
        "authorization_namespace": prepared.authorization_namespace,
        "completion_event_sha256": prepared.completion_event_sha256,
        "witness_public_key_bytes": adapter_evidence["public_key"],
    }
    assert journal.load_request_for_completion(**lookup) is None

    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    reopened_pending = journal.load_request_for_completion(**lookup)
    assert reopened_pending == pending
    assert reopened_pending is not None
    assert reopened_pending.prepared.request_bytes == prepared.request_bytes

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="COMPLETION_LOOKUP_WITNESS_MISMATCH",
    ):
        journal.load_request_for_completion(
            **{
                **lookup,
                "witness_public_key_bytes": _wrong_public_key(),
            }
        )

    envelope = request_support._signed_envelope(prepared)
    anchored = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    restarted = ProfiledOptimizerCompletionAuthorizationJournalV1(
        journal.path,
        immutable_store=journal.immutable_store,
    )
    reopened_anchor = restarted.load_request_for_completion(**lookup)
    assert reopened_anchor == anchored
    assert reopened_anchor is not None
    assert reopened_anchor.state == AUTHORIZATION_ANCHORED
    assert reopened_anchor.verified is not None
    assert reopened_anchor.verified.authorization_envelope_bytes == envelope


def test_read_only_completion_lookup_is_exact_query_only_and_non_mutating(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    anchored = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=request_support._signed_envelope(prepared),
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    writer_lock = Path(f"{journal.path}.writer.lock")
    writer_lock.unlink()
    before = _journal_evidence_snapshot(journal)
    connect_calls: list[tuple[str, bool]] = []
    statements: list[str] = []
    original_connect = journal_module.sqlite3.connect

    def tracking_connect(database: object, *args: Any, **kwargs: Any) -> Any:
        connection = original_connect(database, *args, **kwargs)
        connect_calls.append((str(database), kwargs.get("uri") is True))
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(journal_module.sqlite3, "connect", tracking_connect)

    reopened = journal.load_request_for_completion_read_only_v1(
        witness_id=prepared.witness_id,
        authorization_namespace=prepared.authorization_namespace,
        completion_event_sha256=prepared.completion_event_sha256,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )

    journal_connections = [
        (database, uri) for database, uri in connect_calls if database != ":memory:"
    ]
    normalized_statements = {"".join(statement.lower().split()) for statement in statements}
    assert reopened == anchored
    assert journal_connections
    assert all(
        uri and database.startswith("file:") and "mode=ro" in database
        for database, uri in journal_connections
    )
    assert all(str(journal.path) not in database for database, _ in connect_calls)
    assert "pragmaquery_only=on" in normalized_statements
    assert _journal_evidence_snapshot(journal) == before
    assert not writer_lock.exists()


def test_read_only_completion_lookup_missing_journal_creates_nothing(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    writer_lock = Path(f"{journal.path}.writer.lock")
    before = _filesystem_snapshot(tmp_path)

    with pytest.raises(ProfiledOptimizerCompletionAuthorizationJournalV1Error):
        journal.load_request_for_completion_read_only_v1(
            witness_id=prepared.witness_id,
            authorization_namespace=prepared.authorization_namespace,
            completion_event_sha256=prepared.completion_event_sha256,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )

    assert not journal.path.exists()
    assert not Path(f"{journal.path}-wal").exists()
    assert not Path(f"{journal.path}-shm").exists()
    assert not writer_lock.exists()
    assert _filesystem_snapshot(tmp_path) == before


def test_read_only_completion_lookup_observes_uncheckpointed_wal_anchor(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    journal.initialize()
    keeper = sqlite3.connect(journal.path, isolation_level=None)
    try:
        assert str(keeper.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("BEGIN")
        assert keeper.execute(
            "SELECT COUNT(*) FROM authorization_journal_operations"
        ).fetchone() == (0,)

        prepared = _prepared(adapter_evidence)
        pending = journal.persist_prepared_request(
            prepared=prepared,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
        anchored = journal.commit_authorization_anchored(
            operation_id=pending.operation_id,
            authorization_envelope_bytes=request_support._signed_envelope(prepared),
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
        wal_path = Path(f"{journal.path}-wal")
        assert wal_path.is_file()
        assert wal_path.stat().st_size > 0
        writer_lock = Path(f"{journal.path}.writer.lock")
        writer_lock.unlink()
        source_paths = (
            journal.path,
            wal_path,
            Path(f"{journal.path}-shm"),
        )
        original_modes = {
            path: stat.S_IMODE(path.stat().st_mode) for path in source_paths if path.exists()
        }
        original_parent_mode = stat.S_IMODE(tmp_path.stat().st_mode)
        try:
            for path in original_modes:
                path.chmod(0o400)
            tmp_path.chmod(0o500)
            before = _journal_evidence_snapshot(journal)

            reopened = journal.load_request_for_completion_read_only_v1(
                witness_id=prepared.witness_id,
                authorization_namespace=prepared.authorization_namespace,
                completion_event_sha256=prepared.completion_event_sha256,
                witness_public_key_bytes=adapter_evidence["public_key"],
            )

            assert reopened == anchored
            assert _journal_evidence_snapshot(journal) == before
            assert not writer_lock.exists()
        finally:
            tmp_path.chmod(original_parent_mode)
            for path, mode in original_modes.items():
                path.chmod(mode)
    finally:
        keeper.rollback()
        keeper.close()


def test_read_only_completion_lookup_rejects_connect_time_scratch_inode_swap(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    journal.initialize()
    prepared = _prepared(adapter_evidence)
    writer_lock = Path(f"{journal.path}.writer.lock")
    writer_lock.unlink()
    before = _journal_evidence_snapshot(journal)
    original_connect = journal_module.sqlite3.connect
    swapped_paths: list[Path] = []

    def swapping_connect(database: object, *args: Any, **kwargs: Any) -> Any:
        database_text = str(database)
        if database_text.startswith("file:") and "mode=ro" in database_text:
            parsed = urlsplit(database_text)
            scratch_path = Path(unquote(parsed.path))
            displaced = scratch_path.with_name("journal-displaced.sqlite3")
            payload = scratch_path.read_bytes()
            mode = stat.S_IMODE(scratch_path.stat().st_mode)
            scratch_path.replace(displaced)
            scratch_path.write_bytes(payload)
            scratch_path.chmod(mode)
            try:
                connection = original_connect(database, *args, **kwargs)
            finally:
                scratch_path.unlink(missing_ok=True)
                displaced.replace(scratch_path)
            swapped_paths.append(scratch_path)
            return connection
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(journal_module.sqlite3, "connect", swapping_connect)

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_SNAPSHOT_INODE_CHANGED",
    ):
        journal.load_request_for_completion_read_only_v1(
            witness_id=prepared.witness_id,
            authorization_namespace=prepared.authorization_namespace,
            completion_event_sha256=prepared.completion_event_sha256,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )

    assert len(swapped_paths) == 1
    assert _journal_evidence_snapshot(journal) == before
    assert not writer_lock.exists()


def test_exact_prepared_replay_is_idempotent_and_changed_material_conflicts(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    first = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    replay = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert replay == first
    assert journal.verify_integrity().transition_count == 1

    changed = _derived_prepared(
        prepared,
        label="changed-challenge-same-completion",
        change_completion=False,
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="PREPARED_REPLAY_CONFLICT",
    ):
        journal.persist_prepared_request(
            prepared=changed,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_only_one_pending_request_is_allowed_per_authorization_namespace(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    second = _derived_prepared(prepared, label="second-pending")

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="NAMESPACE_PENDING_EXISTS",
    ):
        journal.persist_prepared_request(
            prepared=second,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    assert not journal.immutable_store.path_for(second.request_sha256).exists()


def test_changed_witness_key_fails_before_persistence(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="WITNESS_KEY_INVALID",
    ):
        journal.persist_prepared_request(
            prepared=prepared,
            witness_public_key_bytes=_wrong_public_key(),
        )
    assert not journal.immutable_store.path_for(prepared.request_sha256).exists()


def test_signed_authorization_is_reverified_anchored_and_exactly_replayable(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    envelope = request_support._signed_envelope(prepared)
    anchored = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )

    assert anchored.state == AUTHORIZATION_ANCHORED
    assert anchored.verified is not None
    assert anchored.verified.profiled_optimizer_admission_authorized is True
    assert anchored.verified.optimizer_execution_authorized is False
    assert anchored.verified.checkpoint_write_authorized is False
    assert journal.verify_integrity().transition_count == 2
    assert journal.load_pending_requests(
        witness_id=prepared.witness_id,
        witness_public_key_bytes=adapter_evidence["public_key"],
    ) == ()

    replay = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert replay == anchored
    assert journal.verify_integrity().transition_count == 2

    changed_accepted_at = (
        (
            datetime.fromisoformat(
                adapter_evidence["accepted_at"].replace("Z", "+00:00")
            ).astimezone(UTC)
            + timedelta(minutes=1)
        )
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="ANCHOR_REPLAY_CONFLICT",
    ):
        journal.commit_authorization_anchored(
            operation_id=pending.operation_id,
            authorization_envelope_bytes=request_support._signed_envelope(
                prepared,
                accepted_at=changed_accepted_at,
            ),
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_invalid_signature_and_changed_key_leave_request_pending(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    envelope = bytearray(request_support._signed_envelope(prepared))
    envelope[-3] = ord("1") if envelope[-3] != ord("1") else ord("2")

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="RESPONSE_UNVERIFIED",
    ):
        journal.commit_authorization_anchored(
            operation_id=pending.operation_id,
            authorization_envelope_bytes=bytes(envelope),
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="ANCHOR_KEY_MISMATCH",
    ):
        journal.commit_authorization_anchored(
            operation_id=pending.operation_id,
            authorization_envelope_bytes=request_support._signed_envelope(prepared),
            witness_public_key_bytes=_wrong_public_key(),
        )
    assert journal.verify_integrity().pending_count == 1


def test_chain_head_uses_prior_authorization_envelope_not_manifest_head(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    genesis = journal.latest_authorization_head(
        witness_id=prepared.witness_id,
        authorization_namespace=prepared.authorization_namespace,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert genesis.expected_authorization_sequence == 0
    assert genesis.expected_previous_authorization_event_sha256 == (
        PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
    )
    first = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    envelope = request_support._signed_envelope(prepared)
    journal.commit_authorization_anchored(
        operation_id=first.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    head = journal.latest_authorization_head(
        witness_id=prepared.witness_id,
        authorization_namespace=prepared.authorization_namespace,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    envelope_sha = hashlib.sha256(envelope).hexdigest()
    assert head.expected_authorization_sequence == 1
    assert head.expected_previous_authorization_event_sha256 == envelope_sha
    assert envelope_sha != prepared.manifest_head_event_sha256

    successor = _derived_prepared(
        prepared,
        label="successor",
        expected_sequence=head.expected_authorization_sequence,
        predecessor=head.expected_previous_authorization_event_sha256,
    )
    second = journal.persist_prepared_request(
        prepared=successor,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    journal.commit_authorization_anchored(
        operation_id=second.operation_id,
        authorization_envelope_bytes=request_support._signed_envelope(successor),
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count, report.anchored_count) == (
        2,
        4,
        2,
    )


def test_wrong_successor_predecessor_fails_before_cas_write(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    first = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    journal.commit_authorization_anchored(
        operation_id=first.operation_id,
        authorization_envelope_bytes=request_support._signed_envelope(prepared),
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    wrong = _derived_prepared(
        prepared,
        label="wrong-successor",
        expected_sequence=1,
        predecessor=hashlib.sha256(b"not-the-prior-envelope").hexdigest(),
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="PREDECESSOR_MISMATCH",
    ):
        journal.persist_prepared_request(
            prepared=wrong,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    assert not journal.immutable_store.path_for(wrong.request_sha256).exists()


def test_interleaved_namespaces_share_one_valid_global_transition_chain(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    first = _prepared(adapter_evidence)
    second = _derived_prepared(
        first,
        label="other-namespace",
        namespace="unit/profiled-optimizer-completion-other",
    )
    journal.persist_prepared_request(
        prepared=first,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    journal.persist_prepared_request(
        prepared=second,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count, report.namespace_count) == (
        2,
        2,
        2,
    )
    with sqlite3.connect(journal.path) as connection:
        rows = connection.execute(
            """
            SELECT transition_sequence, previous_transition_sha256, transition_sha256
            FROM authorization_journal_transitions ORDER BY transition_sequence
            """
        ).fetchall()
    assert rows[0][0] == 1
    assert rows[0][1] == AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
    assert rows[1][0] == 2
    assert rows[1][1] == rows[0][2]


def test_sql_update_delete_and_wrong_writer_lease_fail_closed(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path / "primary")
    prepared = _prepared(adapter_evidence)
    journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    with sqlite3.connect(journal.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE authorization_journal_operations SET namespace = 'changed'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM authorization_journal_transitions")

    other = _journal(tmp_path / "other")
    with other.writer_lease() as wrong_lease:
        with pytest.raises(
            ProfiledOptimizerCompletionAuthorizationJournalV1Error,
            match="LEASE_INVALID",
        ):
            journal.verify_integrity(writer_lease=wrong_lease)


def test_schema_and_cas_tampering_are_detected(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    cas_journal = _journal(tmp_path / "cas")
    prepared = _prepared(adapter_evidence)
    cas_journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    request_path = cas_journal.immutable_store.path_for(prepared.request_sha256)
    request_path.chmod(0o600)
    request_path.write_bytes(b"tampered-request")
    request_path.chmod(0o400)
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="CAS_REOPEN_FAILED",
    ):
        cas_journal.verify_integrity()

    schema_journal = _journal(tmp_path / "schema")
    schema_journal.initialize()
    with sqlite3.connect(schema_journal.path) as connection:
        connection.execute("DROP TRIGGER authorization_journal_metadata_update_forbidden")
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="SCHEMA_INVALID",
    ):
        schema_journal.verify_integrity()


def test_resource_count_gate_precedes_cas_scan(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    request_path = journal.immutable_store.path_for(prepared.request_sha256)
    request_path.chmod(0o600)
    request_path.write_bytes(b"tampered-request")
    request_path.chmod(0o400)
    monkeypatch.setattr(journal_module, "MAX_AUTHORIZATION_JOURNAL_TRANSITIONS", 0)
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="RESOURCE_LIMIT",
    ):
        journal.verify_integrity()


def test_capacity_reserves_anchor_for_every_pending_request(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    first = _prepared(adapter_evidence)
    second = _derived_prepared(
        first,
        label="capacity-second",
        namespace="unit/profiled-capacity-second",
    )
    third = _derived_prepared(
        first,
        label="capacity-third",
        namespace="unit/profiled-capacity-third",
    )
    monkeypatch.setattr(journal_module, "MAX_AUTHORIZATION_JOURNAL_TRANSITIONS", 4)
    journal.persist_prepared_request(
        prepared=first,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    journal.persist_prepared_request(
        prepared=second,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="TRANSITION_CAPACITY_RESERVED",
    ):
        journal.persist_prepared_request(
            prepared=third,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    assert not journal.immutable_store.path_for(third.request_sha256).exists()


def test_anchored_envelope_is_reverified_from_cas_on_every_integrity_scan(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    envelope = request_support._signed_envelope(prepared)
    anchored = journal.commit_authorization_anchored(
        operation_id=pending.operation_id,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert anchored.verified is not None
    envelope_path = journal.immutable_store.path_for(
        anchored.verified.authorization_envelope_sha256
    )
    envelope_path.chmod(0o600)
    envelope_path.write_bytes(b"tampered-envelope")
    envelope_path.chmod(0o400)
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="ANCHOR_REVERIFY_FAILED",
    ):
        journal.verify_integrity()


def test_prepared_postcommit_reopen_failure_is_recoverable(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    original_open = ProfiledOptimizerCompletionAuthorizationJournalV1._open_connection
    calls = 0

    def fail_postcommit_reopen(
        self: ProfiledOptimizerCompletionAuthorizationJournalV1,
        *,
        writer_lease: Any,
    ) -> sqlite3.Connection:
        nonlocal calls
        calls += 1
        if self is journal and calls == 2:
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "TEST_PREPARED_POSTCOMMIT_REOPEN_FAILED"
            )
        return original_open(self, writer_lease=writer_lease)

    monkeypatch.setattr(
        ProfiledOptimizerCompletionAuthorizationJournalV1,
        "_open_connection",
        fail_postcommit_reopen,
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="TEST_PREPARED_POSTCOMMIT_REOPEN_FAILED",
    ):
        journal.persist_prepared_request(
            prepared=prepared,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    monkeypatch.setattr(
        ProfiledOptimizerCompletionAuthorizationJournalV1,
        "_open_connection",
        original_open,
    )

    restarted = ProfiledOptimizerCompletionAuthorizationJournalV1(
        journal.path,
        immutable_store=journal.immutable_store,
    )
    pending = restarted.load_pending_requests(
        witness_id=prepared.witness_id,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    assert len(pending) == 1
    assert pending[0].prepared == prepared


def test_anchor_postcommit_reopen_failure_is_recoverable(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    prepared = _prepared(adapter_evidence)
    pending = journal.persist_prepared_request(
        prepared=prepared,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )
    original_open = ProfiledOptimizerCompletionAuthorizationJournalV1._open_connection
    calls = 0

    def fail_postcommit_reopen(
        self: ProfiledOptimizerCompletionAuthorizationJournalV1,
        *,
        writer_lease: Any,
    ) -> sqlite3.Connection:
        nonlocal calls
        calls += 1
        if self is journal and calls == 2:
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "TEST_ANCHOR_POSTCOMMIT_REOPEN_FAILED"
            )
        return original_open(self, writer_lease=writer_lease)

    monkeypatch.setattr(
        ProfiledOptimizerCompletionAuthorizationJournalV1,
        "_open_connection",
        fail_postcommit_reopen,
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="TEST_ANCHOR_POSTCOMMIT_REOPEN_FAILED",
    ):
        journal.commit_authorization_anchored(
            operation_id=pending.operation_id,
            authorization_envelope_bytes=request_support._signed_envelope(prepared),
            witness_public_key_bytes=adapter_evidence["public_key"],
        )
    monkeypatch.setattr(
        ProfiledOptimizerCompletionAuthorizationJournalV1,
        "_open_connection",
        original_open,
    )

    restarted = ProfiledOptimizerCompletionAuthorizationJournalV1(
        journal.path,
        immutable_store=journal.immutable_store,
    )
    report = restarted.verify_integrity()
    assert (report.anchored_count, report.pending_count, report.transition_count) == (
        1,
        0,
        2,
    )


def test_module_has_no_network_signing_head_journal_or_runtime_authority() -> None:
    module_path = (
        Path(__file__).resolve().parents[6]
        / "v2/backend/app/services/native_trainer/"
        "profiled_optimizer_external_completion_authorization_journal_v1.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "httpx" not in source
    assert "requests." not in source
    assert "Ed25519PrivateKey" not in source
    assert "profiled_training_external_witness_journal_v1" not in source
    assert "optimizer.step" not in source
    assert "torch.save" not in source
    assert "submit_order" not in source
