"""Durable authenticated archive for ``CandidateDecisionOutcomeV2`` records.

This service is evidence-only.  It cannot submit, modify, or authorize an
order.  Every write is serialized under an OS file lock, verified against the
entire existing hash/signature chain, and appended with ``fsync``.  Candidate
revisions use compare-and-swap semantics: revision two must name the exact
revision-one content hash and preserve the decision snapshot.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
    CandidateOutcomeContractError,
    candidate_decision_outcome_from_dict,
)

ARCHIVE_ROW_SCHEMA_VERSION = "candidate_outcome_archive_row_v2"
ARCHIVE_RECEIPT_SCHEMA_VERSION = "candidate_outcome_archive_append_receipt_v2"
ARCHIVE_VERIFICATION_SCHEMA_VERSION = "candidate_outcome_archive_verification_v2"
ARCHIVE_COVERAGE_SCHEMA_VERSION = "candidate_outcome_archive_coverage_v2"
SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_DOMAIN = b"v2/adaptive-system/candidate-outcome-archive/v2\0"
GENESIS_CHAIN_SHA256 = "0" * 64

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")


class CandidateOutcomeArchiveError(RuntimeError):
    pass


def _raise(reason: str, field: str) -> None:
    raise CandidateOutcomeArchiveError(f"{field}:{reason}")


def _require_identifier(value: object, field: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _raise("must_be_non_empty_without_whitespace", field)


def _require_sha256(value: object, field: str) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_positive_int(value: object, field: str) -> None:
    if type(value) is not int or value < 1:
        _raise("must_be_positive_int", field)


def _json_primitive(value: object) -> object:
    if type(value) is dict:
        output: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                _raise("json_keys_must_be_exact_strings", "record")
            output[key] = _json_primitive(item)
        return output
    if type(value) in {tuple, list}:
        return [_json_primitive(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _raise("nonfinite_float", "record")
        return value
    _raise("unsupported_json_type", "record")


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _signature_material(row: dict[str, Any]) -> bytes:
    fields = {
        "schema_version": row["schema_version"],
        "receipt_id": row["receipt_id"],
        "writer_id": row["writer_id"],
        "writer_public_key_hex": row["writer_public_key_hex"],
        "signature_algorithm": row["signature_algorithm"],
        "row_index": row["row_index"],
        "archive_record_id": row["archive_record_id"],
        "candidate_id": row["candidate_id"],
        "archive_sequence": row["archive_sequence"],
        "decision_snapshot_sha256": row["decision_snapshot_sha256"],
        "record_content_sha256": row["record_content_sha256"],
        "previous_candidate_record_sha256": row["previous_candidate_record_sha256"],
        "previous_chain_sha256": row["previous_chain_sha256"],
        "chain_sha256": row["chain_sha256"],
        "signed_at_ms": row["signed_at_ms"],
        "paper_only": row["paper_only"],
        "live_gate": row["live_gate"],
        "routes_to_live": row["routes_to_live"],
        "places_real_order": row["places_real_order"],
        "exchange_action_taken": row["exchange_action_taken"],
    }
    return SIGNATURE_DOMAIN + _canonical_json(fields).encode("utf-8")


def _chain_sha256(
    *,
    previous_chain_sha256: str,
    row_index: int,
    archive_record_id: str,
    candidate_id: str,
    archive_sequence: int,
    record_content_sha256: str,
) -> str:
    return _sha256(
        {
            "previous_chain_sha256": previous_chain_sha256,
            "row_index": row_index,
            "archive_record_id": archive_record_id,
            "candidate_id": candidate_id,
            "archive_sequence": archive_sequence,
            "record_content_sha256": record_content_sha256,
        }
    )


def _receipt_id(fields: dict[str, Any]) -> str:
    return f"candidate_archive_receipt_{_sha256(fields)[:40]}"


def _open_regular_file(path: Path, flags: int) -> int:
    descriptor = os.open(
        path,
        flags | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        _raise("regular_file_required", str(path))
    return descriptor


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class ArchiveAppendReceiptV2:
    schema_version: str
    receipt_id: str
    archive_record_id: str
    candidate_id: str
    archive_sequence: int
    record_content_sha256: str
    chain_sha256: str
    signature_hex: str
    signed_at_ms: int
    idempotent_replay: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool


@dataclass(frozen=True, slots=True)
class ArchiveVerificationV2:
    schema_version: str
    archive_path: str
    writer_id: str
    writer_public_key_hex: str
    row_count: int
    decision_revision_count: int
    matured_revision_count: int
    candidate_count: int
    terminal_chain_sha256: str
    duplicate_archive_record_count: int
    invalid_row_count: int
    verified: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool


@dataclass(frozen=True, slots=True)
class ArchiveCoverageV2:
    schema_version: str
    expected_candidate_count: int
    recorded_candidate_count: int
    eligible_matured_candidate_count: int
    matured_candidate_count: int
    missing_candidate_ids: tuple[str, ...]
    unexpected_candidate_ids: tuple[str, ...]
    missing_matured_candidate_ids: tuple[str, ...]
    unexpected_matured_candidate_ids: tuple[str, ...]
    candidate_recording_coverage: float
    eligible_matured_label_coverage: float
    unexplained_candidate_drops: int
    candidate_recording_coverage_100_percent: bool
    matured_label_coverage_100_percent: bool
    unexplained_candidate_drops_zero: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool


class CandidateOutcomeArchiveV2:
    """Authenticated JSONL archive with append-only candidate CAS semantics."""

    def __init__(
        self,
        *,
        archive_path: Path,
        writer_id: str,
        writer_public_key_hex: str,
        signer: Callable[[bytes], bytes] | None,
    ) -> None:
        if not isinstance(archive_path, Path):
            _raise("must_be_Path", "archive_path")
        if not archive_path.is_absolute() or ".." in archive_path.parts:
            _raise("must_be_absolute_without_parent_traversal", "archive_path")
        _require_identifier(writer_id, "writer_id")
        if (
            type(writer_public_key_hex) is not str
            or _SHA256_RE.fullmatch(writer_public_key_hex) is None
        ):
            _raise("must_be_32_byte_lowercase_hex", "writer_public_key_hex")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(writer_public_key_hex))
        except (ValueError, TypeError) as exc:
            raise CandidateOutcomeArchiveError("writer_public_key_hex:invalid_ed25519_key") from exc
        if signer is not None and not callable(signer):
            _raise("must_be_callable_or_none", "signer")
        self.archive_path = archive_path
        self.lock_path = archive_path.with_suffix(f"{archive_path.suffix}.lock")
        self.writer_id = writer_id
        self.writer_public_key_hex = writer_public_key_hex
        self._public_key = public_key
        self._signer = signer

    def _ensure_parent(self) -> None:
        parent = self.archive_path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.resolve() != Path(os.path.abspath(parent)):
            _raise("symlink_parent_forbidden", "archive_path")
        for path in (self.archive_path, self.lock_path):
            if path.is_symlink():
                _raise("symlink_path_forbidden", str(path))
            if path.exists() and not path.is_file():
                _raise("regular_file_required", str(path))

    @contextmanager
    def _locked(self):
        self._ensure_parent()
        descriptor = _open_regular_file(
            self.lock_path,
            os.O_RDWR | os.O_APPEND | os.O_CREAT,
        )
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _parse_rows(self) -> list[dict[str, Any]]:
        if not self.archive_path.exists():
            return []
        if self.archive_path.is_symlink():
            _raise("symlink_path_forbidden", "archive_path")
        rows: list[dict[str, Any]] = []
        descriptor = _open_regular_file(self.archive_path, os.O_RDONLY)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\n")
                if not line:
                    _raise("blank_or_partial_row", f"line[{line_number}]")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CandidateOutcomeArchiveError(
                        f"line[{line_number}]:invalid_or_partial_json"
                    ) from exc
                if type(row) is not dict:
                    _raise("must_be_object", f"line[{line_number}]")
                rows.append(row)
        return rows

    def _verify_rows(self, rows: list[dict[str, Any]]) -> ArchiveVerificationV2:
        previous_chain_sha256 = GENESIS_CHAIN_SHA256
        archive_ids: set[str] = set()
        candidate_rows: dict[str, list[dict[str, Any]]] = {}
        for row_offset, row in enumerate(rows):
            row_index = row_offset + 1
            required_keys = {
                "schema_version",
                "receipt_id",
                "writer_id",
                "writer_public_key_hex",
                "signature_algorithm",
                "signature_hex",
                "row_index",
                "archive_record_id",
                "candidate_id",
                "archive_sequence",
                "decision_snapshot_sha256",
                "record_content_sha256",
                "previous_candidate_record_sha256",
                "previous_chain_sha256",
                "chain_sha256",
                "signed_at_ms",
                "record",
                "paper_only",
                "live_gate",
                "routes_to_live",
                "places_real_order",
                "exchange_action_taken",
            }
            if set(row) != required_keys:
                _raise("exact_row_keys_required", f"row[{row_index}]")
            if type(row["schema_version"]) is not str or row["schema_version"] != (
                ARCHIVE_ROW_SCHEMA_VERSION
            ):
                _raise("invalid_schema_version", f"row[{row_index}]")
            if row["writer_id"] != self.writer_id or type(row["writer_id"]) is not str:
                _raise("writer_id_mismatch", f"row[{row_index}]")
            if (
                row["writer_public_key_hex"] != self.writer_public_key_hex
                or type(row["writer_public_key_hex"]) is not str
            ):
                _raise("writer_public_key_mismatch", f"row[{row_index}]")
            if row["signature_algorithm"] != SIGNATURE_ALGORITHM:
                _raise("signature_algorithm_mismatch", f"row[{row_index}]")
            if type(row["row_index"]) is not int or row["row_index"] != row_index:
                _raise("row_index_not_contiguous", f"row[{row_index}]")
            for field in ("archive_record_id", "candidate_id", "receipt_id"):
                _require_identifier(row[field], f"row[{row_index}].{field}")
            if row["archive_record_id"] in archive_ids:
                _raise("duplicate_archive_record_id", f"row[{row_index}]")
            archive_ids.add(row["archive_record_id"])
            if type(row["archive_sequence"]) is not int or row["archive_sequence"] not in {
                1,
                2,
            }:
                _raise("archive_sequence_invalid", f"row[{row_index}]")
            _require_positive_int(row["signed_at_ms"], f"row[{row_index}].signed_at_ms")
            for field in (
                "decision_snapshot_sha256",
                "record_content_sha256",
                "previous_chain_sha256",
                "chain_sha256",
            ):
                _require_sha256(row[field], f"row[{row_index}].{field}")
            if row["previous_candidate_record_sha256"] is not None:
                _require_sha256(
                    row["previous_candidate_record_sha256"],
                    f"row[{row_index}].previous_candidate_record_sha256",
                )
            if row["previous_chain_sha256"] != previous_chain_sha256:
                _raise("previous_chain_mismatch", f"row[{row_index}]")
            expected_chain = _chain_sha256(
                previous_chain_sha256=previous_chain_sha256,
                row_index=row_index,
                archive_record_id=row["archive_record_id"],
                candidate_id=row["candidate_id"],
                archive_sequence=row["archive_sequence"],
                record_content_sha256=row["record_content_sha256"],
            )
            if row["chain_sha256"] != expected_chain:
                _raise("chain_sha256_mismatch", f"row[{row_index}]")
            if type(row["record"]) is not dict:
                _raise("record_must_be_object", f"row[{row_index}]")
            if _sha256(row["record"]) != row["record_content_sha256"]:
                _raise("record_content_sha256_mismatch", f"row[{row_index}]")
            record = row["record"]
            if record.get("archive_record_id") != row["archive_record_id"]:
                _raise("archive_record_id_payload_mismatch", f"row[{row_index}]")
            if record.get("archive_sequence") != row["archive_sequence"]:
                _raise("archive_sequence_payload_mismatch", f"row[{row_index}]")
            decision = record.get("decision")
            if type(decision) is not dict:
                _raise("decision_payload_missing", f"row[{row_index}]")
            if decision.get("candidate_id") != row["candidate_id"]:
                _raise("candidate_id_payload_mismatch", f"row[{row_index}]")
            if _sha256(decision) != row["decision_snapshot_sha256"]:
                _raise("decision_snapshot_sha256_mismatch", f"row[{row_index}]")
            if row["signed_at_ms"] < record.get("record_available_at_ms", 0):
                _raise("signed_before_record_available", f"row[{row_index}]")
            if row["paper_only"] is not True or record.get("paper_only") is not True:
                _raise("paper_only_required", f"row[{row_index}]")
            if row["live_gate"] != "blocked_human_only" or record.get("live_gate") != (
                "blocked_human_only"
            ):
                _raise("live_gate_mismatch", f"row[{row_index}]")
            for field in ("routes_to_live", "places_real_order", "exchange_action_taken"):
                if row[field] is not False or record.get(field) is not False:
                    _raise("no_live_authority_required", f"row[{row_index}].{field}")
            signature_hex = row["signature_hex"]
            if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
                _raise("invalid_signature_hex", f"row[{row_index}]")
            try:
                self._public_key.verify(bytes.fromhex(signature_hex), _signature_material(row))
            except InvalidSignature as exc:
                raise CandidateOutcomeArchiveError(f"row[{row_index}]:signature_invalid") from exc
            candidate_history = candidate_rows.setdefault(row["candidate_id"], [])
            if row["archive_sequence"] != len(candidate_history) + 1:
                _raise("candidate_revision_not_contiguous", f"row[{row_index}]")
            if not candidate_history:
                if row["previous_candidate_record_sha256"] is not None:
                    _raise("first_revision_has_previous", f"row[{row_index}]")
                if record.get("matured_labels") is not None:
                    _raise("first_revision_has_labels", f"row[{row_index}]")
            else:
                previous = candidate_history[-1]
                if row["previous_candidate_record_sha256"] != previous["record_content_sha256"]:
                    _raise("candidate_compare_and_swap_mismatch", f"row[{row_index}]")
                if row["decision_snapshot_sha256"] != previous["decision_snapshot_sha256"]:
                    _raise("candidate_decision_changed", f"row[{row_index}]")
                if record.get("matured_labels") is None:
                    _raise("second_revision_missing_labels", f"row[{row_index}]")
                if record.get("record_generated_at_ms", 0) < previous["record"].get(
                    "record_available_at_ms", 0
                ):
                    _raise("successor_generated_before_previous_available", f"row[{row_index}]")
            candidate_history.append(row)
            previous_chain_sha256 = row["chain_sha256"]
        return ArchiveVerificationV2(
            schema_version=ARCHIVE_VERIFICATION_SCHEMA_VERSION,
            archive_path=str(self.archive_path),
            writer_id=self.writer_id,
            writer_public_key_hex=self.writer_public_key_hex,
            row_count=len(rows),
            decision_revision_count=sum(row["archive_sequence"] == 1 for row in rows),
            matured_revision_count=sum(row["archive_sequence"] == 2 for row in rows),
            candidate_count=len(candidate_rows),
            terminal_chain_sha256=previous_chain_sha256,
            duplicate_archive_record_count=0,
            invalid_row_count=0,
            verified=True,
            paper_only=True,
            live_gate="blocked_human_only",
            routes_to_live=False,
            places_real_order=False,
            exchange_action_taken=False,
        )

    def verify(self) -> ArchiveVerificationV2:
        with self._locked():
            return self._verify_rows(self._parse_rows())

    def read_verified_records(
        self,
        *,
        latest_only: bool = False,
    ) -> tuple[CandidateDecisionOutcomeV2, ...]:
        """Return records only after signature, chain, and nested contract checks."""

        if type(latest_only) is not bool:
            _raise("must_be_exact_bool", "latest_only")
        with self._locked():
            rows = self._parse_rows()
            self._verify_rows(rows)
            try:
                records = tuple(
                    candidate_decision_outcome_from_dict(row["record"])
                    for row in rows
                )
            except CandidateOutcomeContractError as exc:
                raise CandidateOutcomeArchiveError(
                    f"record:nested_contract_invalid:{exc}"
                ) from exc
        if not latest_only:
            return records
        latest: dict[str, CandidateDecisionOutcomeV2] = {}
        for record in records:
            latest[record.decision.candidate_id] = record
        return tuple(latest[candidate_id] for candidate_id in sorted(latest))

    def append(
        self,
        record: CandidateDecisionOutcomeV2,
        *,
        signed_at_ms: int,
    ) -> ArchiveAppendReceiptV2:
        return self.append_many((record,), signed_at_ms=signed_at_ms)[0]

    def append_many(
        self,
        records: tuple[CandidateDecisionOutcomeV2, ...],
        *,
        signed_at_ms: int,
    ) -> tuple[ArchiveAppendReceiptV2, ...]:
        """Append one complete cycle under one lock and one archive verification.

        Candidate coverage cycles can contain hundreds of records.  Verifying
        the full authenticated chain once per record would make runtime cost
        quadratic as the archive grows.  This batch method preserves the same
        per-record signatures, chain links, CAS rules, idempotency and fsync
        durability while parsing/verifying the existing prefix only once.
        """

        if type(records) is not tuple or not records:
            _raise("nonempty_tuple_required", "records")
        _require_positive_int(signed_at_ms, "signed_at_ms")
        for index, record in enumerate(records):
            if type(record) is not CandidateDecisionOutcomeV2:
                _raise("CandidateDecisionOutcomeV2_required", f"records[{index}]")
            if signed_at_ms < record.record_available_at_ms:
                _raise("cannot_sign_before_record_available", f"records[{index}].signed_at_ms")
        if self._signer is None:
            _raise("external_signer_required", "signer")

        with self._locked():
            try:
                rows = self._parse_rows()
                verification = self._verify_rows(rows)
                rows_by_archive_id = {row["archive_record_id"]: row for row in rows}
                candidate_rows: dict[str, list[dict[str, Any]]] = {}
                for row in rows:
                    candidate_rows.setdefault(row["candidate_id"], []).append(row)
                previous_chain_sha256 = verification.terminal_chain_sha256
                pending_rows: list[dict[str, Any]] = []
                receipts: list[ArchiveAppendReceiptV2] = []

                for record in records:
                    record_content_sha256 = record.content_sha256()
                    existing = rows_by_archive_id.get(record.archive_record_id)
                    if existing is not None:
                        if existing["record_content_sha256"] != record_content_sha256:
                            _raise("idempotency_key_content_collision", "archive_record_id")
                        receipts.append(self._receipt(existing, idempotent_replay=True))
                        continue

                    history = candidate_rows.setdefault(record.decision.candidate_id, [])
                    if record.archive_sequence != len(history) + 1:
                        _raise("candidate_compare_and_swap_sequence_mismatch", "archive_sequence")
                    if not history:
                        if record.archive_sequence != 1:
                            _raise("first_revision_must_be_one", "archive_sequence")
                    else:
                        previous = history[-1]
                        if (
                            record.previous_archive_record_sha256
                            != previous["record_content_sha256"]
                        ):
                            _raise(
                                "candidate_compare_and_swap_hash_mismatch",
                                "previous_archive_record_sha256",
                            )
                        if record.decision.content_sha256() != previous[
                            "decision_snapshot_sha256"
                        ]:
                            _raise("decision_snapshot_changed", "record")
                        if record.record_generated_at_ms < previous["record"][
                            "record_available_at_ms"
                        ]:
                            _raise("successor_generated_before_previous_available", "record")

                    row_index = len(rows) + len(pending_rows) + 1
                    chain_sha256 = _chain_sha256(
                        previous_chain_sha256=previous_chain_sha256,
                        row_index=row_index,
                        archive_record_id=record.archive_record_id,
                        candidate_id=record.decision.candidate_id,
                        archive_sequence=record.archive_sequence,
                        record_content_sha256=record_content_sha256,
                    )
                    receipt_material = {
                        "writer_id": self.writer_id,
                        "row_index": row_index,
                        "archive_record_id": record.archive_record_id,
                        "candidate_id": record.decision.candidate_id,
                        "archive_sequence": record.archive_sequence,
                        "record_content_sha256": record_content_sha256,
                        "chain_sha256": chain_sha256,
                        "signed_at_ms": signed_at_ms,
                    }
                    row: dict[str, Any] = {
                        "schema_version": ARCHIVE_ROW_SCHEMA_VERSION,
                        "receipt_id": _receipt_id(receipt_material),
                        "writer_id": self.writer_id,
                        "writer_public_key_hex": self.writer_public_key_hex,
                        "signature_algorithm": SIGNATURE_ALGORITHM,
                        "signature_hex": "",
                        "row_index": row_index,
                        "archive_record_id": record.archive_record_id,
                        "candidate_id": record.decision.candidate_id,
                        "archive_sequence": record.archive_sequence,
                        "decision_snapshot_sha256": record.decision.content_sha256(),
                        "record_content_sha256": record_content_sha256,
                        "previous_candidate_record_sha256": (
                            record.previous_archive_record_sha256
                        ),
                        "previous_chain_sha256": previous_chain_sha256,
                        "chain_sha256": chain_sha256,
                        "signed_at_ms": signed_at_ms,
                        "record": record.to_dict(),
                        "paper_only": True,
                        "live_gate": "blocked_human_only",
                        "routes_to_live": False,
                        "places_real_order": False,
                        "exchange_action_taken": False,
                    }
                    signature = self._signer(_signature_material(row))
                    if type(signature) is not bytes or len(signature) != 64:
                        _raise("signer_must_return_64_bytes", "signer")
                    try:
                        self._public_key.verify(signature, _signature_material(row))
                    except InvalidSignature as exc:
                        raise CandidateOutcomeArchiveError(
                            "signer:signature_does_not_match_pinned_public_key"
                        ) from exc
                    row["signature_hex"] = signature.hex()
                    pending_rows.append(row)
                    rows_by_archive_id[record.archive_record_id] = row
                    history.append(row)
                    previous_chain_sha256 = chain_sha256
                    receipts.append(self._receipt(row, idempotent_replay=False))

                if pending_rows:
                    descriptor = _open_regular_file(
                        self.archive_path,
                        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    )
                    with os.fdopen(descriptor, "a", encoding="utf-8") as archive_handle:
                        for row in pending_rows:
                            archive_handle.write(_canonical_json(row))
                            archive_handle.write("\n")
                        archive_handle.flush()
                        os.fsync(archive_handle.fileno())
                    _fsync_directory(self.archive_path.parent)
                    self._verify_rows([*rows, *pending_rows])
                return tuple(receipts)
            except OSError as exc:
                raise CandidateOutcomeArchiveError(
                    f"archive_path:secure_append_failed:{type(exc).__name__}"
                ) from exc

    @staticmethod
    def _receipt(row: dict[str, Any], *, idempotent_replay: bool) -> ArchiveAppendReceiptV2:
        return ArchiveAppendReceiptV2(
            schema_version=ARCHIVE_RECEIPT_SCHEMA_VERSION,
            receipt_id=row["receipt_id"],
            archive_record_id=row["archive_record_id"],
            candidate_id=row["candidate_id"],
            archive_sequence=row["archive_sequence"],
            record_content_sha256=row["record_content_sha256"],
            chain_sha256=row["chain_sha256"],
            signature_hex=row["signature_hex"],
            signed_at_ms=row["signed_at_ms"],
            idempotent_replay=idempotent_replay,
            paper_only=True,
            live_gate="blocked_human_only",
            routes_to_live=False,
            places_real_order=False,
            exchange_action_taken=False,
        )

    def coverage(
        self,
        *,
        expected_candidate_ids: tuple[str, ...],
        eligible_matured_candidate_ids: tuple[str, ...],
    ) -> ArchiveCoverageV2:
        for field, values in (
            ("expected_candidate_ids", expected_candidate_ids),
            ("eligible_matured_candidate_ids", eligible_matured_candidate_ids),
        ):
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                _raise("must_be_sorted_unique_tuple", field)
            for index, value in enumerate(values):
                _require_identifier(value, f"{field}[{index}]")
        with self._locked():
            rows = self._parse_rows()
            self._verify_rows(rows)
        recorded = tuple(
            sorted(row["candidate_id"] for row in rows if row["archive_sequence"] == 1)
        )
        matured = tuple(sorted(row["candidate_id"] for row in rows if row["archive_sequence"] == 2))
        expected_set = set(expected_candidate_ids)
        eligible_set = set(eligible_matured_candidate_ids)
        recorded_set = set(recorded)
        matured_set = set(matured)
        missing_candidates = tuple(sorted(expected_set - recorded_set))
        unexpected_candidates = tuple(sorted(recorded_set - expected_set))
        missing_matured = tuple(sorted(eligible_set - matured_set))
        unexpected_matured = tuple(sorted(matured_set - eligible_set))
        candidate_coverage = (
            len(expected_set & recorded_set) / len(expected_set) if expected_set else 1.0
        )
        matured_coverage = (
            len(eligible_set & matured_set) / len(eligible_set) if eligible_set else 1.0
        )
        unexplained_drops = len(missing_candidates) + len(missing_matured)
        return ArchiveCoverageV2(
            schema_version=ARCHIVE_COVERAGE_SCHEMA_VERSION,
            expected_candidate_count=len(expected_set),
            recorded_candidate_count=len(recorded_set),
            eligible_matured_candidate_count=len(eligible_set),
            matured_candidate_count=len(matured_set),
            missing_candidate_ids=missing_candidates,
            unexpected_candidate_ids=unexpected_candidates,
            missing_matured_candidate_ids=missing_matured,
            unexpected_matured_candidate_ids=unexpected_matured,
            candidate_recording_coverage=candidate_coverage,
            eligible_matured_label_coverage=matured_coverage,
            unexplained_candidate_drops=unexplained_drops,
            candidate_recording_coverage_100_percent=(
                not missing_candidates and not unexpected_candidates
            ),
            matured_label_coverage_100_percent=(not missing_matured and not unexpected_matured),
            unexplained_candidate_drops_zero=unexplained_drops == 0,
            paper_only=True,
            live_gate="blocked_human_only",
            routes_to_live=False,
            places_real_order=False,
            exchange_action_taken=False,
        )


__all__ = [
    "ARCHIVE_ROW_SCHEMA_VERSION",
    "ARCHIVE_RECEIPT_SCHEMA_VERSION",
    "ARCHIVE_VERIFICATION_SCHEMA_VERSION",
    "ARCHIVE_COVERAGE_SCHEMA_VERSION",
    "SIGNATURE_ALGORITHM",
    "SIGNATURE_DOMAIN",
    "GENESIS_CHAIN_SHA256",
    "CandidateOutcomeArchiveError",
    "ArchiveAppendReceiptV2",
    "ArchiveVerificationV2",
    "ArchiveCoverageV2",
    "CandidateOutcomeArchiveV2",
]
