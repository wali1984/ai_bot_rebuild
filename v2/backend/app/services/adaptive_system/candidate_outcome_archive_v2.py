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
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, replace
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

# Archive rows declare their public key so signatures are self-describing, but
# that declaration is not an authentication root.  Production consumers pin
# this paper evidence-writer key; rotation therefore requires an audited code
# release instead of accepting a key supplied by the archive being verified.
PINNED_PRODUCTION_WRITER_ID = "candidate-outcome-writer-v2"
PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX = (
    "bbff6e85cd6954ae5aff4ee2ec5d2078de96bf8f8750aaa889d2ea4712c5b4d9"
)

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


@dataclass(frozen=True, slots=True)
class ArchiveMaturationBatchV2:
    records: tuple[CandidateDecisionOutcomeV2, ...]
    horizon_due_candidate_count: int
    selected_actual_pending_count: int
    label_candidate_count: int


@dataclass(frozen=True, slots=True)
class _MaturationIndexEntry:
    archive_sequence: int
    decision_time_ms: int
    supported_horizon_seconds: tuple[int, ...]
    decision_disposition: str


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
    def _locked(self, *, exclusive: bool = True):
        self._ensure_parent()
        descriptor = _open_regular_file(
            self.lock_path,
            os.O_RDWR | os.O_APPEND | os.O_CREAT,
        )
        with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_handle:
            lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_handle.fileno(), lock_mode)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _iter_rows(self) -> Iterable[dict[str, Any]]:
        if not self.archive_path.exists():
            return
        if self.archive_path.is_symlink():
            _raise("symlink_path_forbidden", "archive_path")
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
                yield row

    def _parse_rows(self) -> list[dict[str, Any]]:
        return list(self._iter_rows())

    def _verify_rows_and_select(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        selected_archive_sequences: frozenset[int] | None = None,
        validate_nested_contracts: bool = False,
        append_receipts_by_archive_id: dict[str, ArchiveAppendReceiptV2]
        | None = None,
        candidate_states_out: dict[str, tuple[int, str, str, int]] | None = None,
        maturation_index_out: dict[str, _MaturationIndexEntry] | None = None,
    ) -> tuple[ArchiveVerificationV2, list[dict[str, Any]]]:
        previous_chain_sha256 = GENESIS_CHAIN_SHA256
        archive_ids: set[str] = set()
        candidate_states = (
            candidate_states_out if candidate_states_out is not None else {}
        )
        selected_rows: list[dict[str, Any]] = []
        row_count = 0
        decision_revision_count = 0
        matured_revision_count = 0
        for row_offset, row in enumerate(rows):
            row_index = row_offset + 1
            row_count = row_index
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
            if row["archive_sequence"] == 1:
                decision_revision_count += 1
            else:
                matured_revision_count += 1
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
            if validate_nested_contracts:
                try:
                    candidate_decision_outcome_from_dict(record)
                except CandidateOutcomeContractError as exc:
                    raise CandidateOutcomeArchiveError(
                        f"record:nested_contract_invalid:{exc}"
                    ) from exc
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
            candidate_state = candidate_states.get(row["candidate_id"])
            previous_sequence = candidate_state[0] if candidate_state is not None else 0
            if row["archive_sequence"] != previous_sequence + 1:
                _raise("candidate_revision_not_contiguous", f"row[{row_index}]")
            if candidate_state is None:
                if row["previous_candidate_record_sha256"] is not None:
                    _raise("first_revision_has_previous", f"row[{row_index}]")
                if record.get("matured_labels") is not None:
                    _raise("first_revision_has_labels", f"row[{row_index}]")
            else:
                (
                    _previous_sequence,
                    previous_record_content_sha256,
                    previous_decision_snapshot_sha256,
                    previous_record_available_at_ms,
                ) = candidate_state
                if row["previous_candidate_record_sha256"] != previous_record_content_sha256:
                    _raise("candidate_compare_and_swap_mismatch", f"row[{row_index}]")
                if row["decision_snapshot_sha256"] != previous_decision_snapshot_sha256:
                    _raise("candidate_decision_changed", f"row[{row_index}]")
                if record.get("matured_labels") is None:
                    _raise("second_revision_missing_labels", f"row[{row_index}]")
                if record.get("record_generated_at_ms", 0) < previous_record_available_at_ms:
                    _raise("successor_generated_before_previous_available", f"row[{row_index}]")
            candidate_states[row["candidate_id"]] = (
                row["archive_sequence"],
                row["record_content_sha256"],
                row["decision_snapshot_sha256"],
                int(record.get("record_available_at_ms", 0)),
            )
            if append_receipts_by_archive_id is not None:
                append_receipts_by_archive_id[row["archive_record_id"]] = self._receipt(
                    row,
                    idempotent_replay=True,
                )
            if maturation_index_out is not None:
                supported_horizons = decision.get("supported_horizon_seconds")
                if (
                    type(supported_horizons) is not list
                    or not supported_horizons
                    or any(type(value) is not int or value < 1 for value in supported_horizons)
                ):
                    _raise(
                        "supported_horizon_seconds_invalid",
                        f"row[{row_index}].record.decision",
                    )
                decision_time_ms = decision.get("decision_time_ms")
                disposition = decision.get("decision_disposition")
                if type(decision_time_ms) is not int or decision_time_ms < 1:
                    _raise(
                        "decision_time_ms_invalid",
                        f"row[{row_index}].record.decision",
                    )
                if type(disposition) is not str or not disposition:
                    _raise(
                        "decision_disposition_invalid",
                        f"row[{row_index}].record.decision",
                    )
                maturation_index_out[row["candidate_id"]] = _MaturationIndexEntry(
                    archive_sequence=row["archive_sequence"],
                    decision_time_ms=decision_time_ms,
                    supported_horizon_seconds=tuple(supported_horizons),
                    decision_disposition=disposition,
                )
            if (
                selected_archive_sequences is not None
                and row["archive_sequence"] in selected_archive_sequences
            ):
                selected_rows.append(row)
            previous_chain_sha256 = row["chain_sha256"]
        verification = ArchiveVerificationV2(
            schema_version=ARCHIVE_VERIFICATION_SCHEMA_VERSION,
            archive_path=str(self.archive_path),
            writer_id=self.writer_id,
            writer_public_key_hex=self.writer_public_key_hex,
            row_count=row_count,
            decision_revision_count=decision_revision_count,
            matured_revision_count=matured_revision_count,
            candidate_count=len(candidate_states),
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
        return verification, selected_rows

    def _verify_rows(self, rows: list[dict[str, Any]]) -> ArchiveVerificationV2:
        verification, _ = self._verify_rows_and_select(rows)
        return verification

    def verify(self) -> ArchiveVerificationV2:
        with self._locked(exclusive=False):
            return self._verify_rows(self._parse_rows())

    def read_verified_records_with_verification(
        self,
        *,
        latest_only: bool = False,
    ) -> tuple[ArchiveVerificationV2, tuple[CandidateDecisionOutcomeV2, ...]]:
        """Verify one immutable read view and return its records and receipt.

        Consumers that need both the terminal chain/counts and the authenticated
        records must not parse a growing archive twice.  The shared lock pins a
        single byte-for-byte view while the full signature, hash-chain, CAS and
        nested-contract checks run.  Writers continue to require the exclusive
        lock.
        """

        if type(latest_only) is not bool:
            _raise("must_be_exact_bool", "latest_only")
        with self._locked(exclusive=False):
            rows = self._parse_rows()
            verification = self._verify_rows(rows)
            selected_rows = rows
            if latest_only:
                latest: dict[str, dict[str, Any]] = {}
                for row in rows:
                    latest[row["candidate_id"]] = row
                selected_rows = [latest[candidate_id] for candidate_id in sorted(latest)]
            try:
                records = tuple(
                    candidate_decision_outcome_from_dict(row["record"])
                    for row in selected_rows
                )
            except CandidateOutcomeContractError as exc:
                raise CandidateOutcomeArchiveError(
                    f"record:nested_contract_invalid:{exc}"
                ) from exc
        return verification, records

    def read_verified_records(
        self,
        *,
        latest_only: bool = False,
    ) -> tuple[CandidateDecisionOutcomeV2, ...]:
        """Return records only after signature, chain, and nested contract checks."""

        _, records = self.read_verified_records_with_verification(
            latest_only=latest_only
        )
        return records

    def read_verified_records_by_sequence_with_verification(
        self,
        *,
        archive_sequences: tuple[int, ...],
    ) -> tuple[ArchiveVerificationV2, tuple[CandidateDecisionOutcomeV2, ...]]:
        """Stream-verify the full archive and retain only requested revisions.

        Calibration consumes matured revisions only. Materializing every large
        decision row before filtering made memory grow with both archive
        revisions and eventually exceeded the service envelope. This path still
        verifies every row, signature, hash-chain link, candidate CAS transition
        and safety flag under one shared lock; it only avoids retaining
        unrequested row payloads after each verification step.
        """

        if (
            type(archive_sequences) is not tuple
            or not archive_sequences
            or archive_sequences != tuple(sorted(set(archive_sequences)))
            or any(
                type(sequence) is not int or sequence not in {1, 2}
                for sequence in archive_sequences
            )
        ):
            _raise("canonical_nonempty_subset_of_1_2_required", "archive_sequences")
        with self._locked(exclusive=False):
            verification, selected_rows = self._verify_rows_and_select(
                self._iter_rows(),
                selected_archive_sequences=frozenset(archive_sequences),
                validate_nested_contracts=True,
            )
            try:
                records = tuple(
                    candidate_decision_outcome_from_dict(row["record"])
                    for row in selected_rows
                )
            except CandidateOutcomeContractError as exc:
                raise CandidateOutcomeArchiveError(
                    f"record:nested_contract_invalid:{exc}"
                ) from exc
        return verification, records

    def read_verified_maturation_batch_with_verification(
        self,
        *,
        signed_at_ms: int,
        max_candidates: int,
        actual_close_required_dispositions: frozenset[str],
    ) -> tuple[ArchiveVerificationV2, ArchiveMaturationBatchV2]:
        """Stream-authenticate the archive and retain one bounded due batch.

        The archive contains large immutable evidence snapshots.  Runtime
        maturation needs a compact latest-revision index plus only the selected
        revision-one records; retaining every typed record makes memory grow
        linearly with the full archive.  This method verifies every row,
        signature, hash-chain link, candidate CAS transition, nested contract,
        and safety flag under one shared lock.  It then rereads the same locked
        immutable view only to materialize the exact bounded candidate set.
        """

        _require_positive_int(signed_at_ms, "signed_at_ms")
        if type(max_candidates) is not int or max_candidates < 1:
            _raise("must_be_positive_int", "max_candidates")
        if (
            type(actual_close_required_dispositions) is not frozenset
            or not actual_close_required_dispositions
            or any(
                type(value) is not str or not value
                for value in actual_close_required_dispositions
            )
        ):
            _raise(
                "must_be_nonempty_frozenset_of_strings",
                "actual_close_required_dispositions",
            )

        with self._locked(exclusive=False):
            maturation_index: dict[str, _MaturationIndexEntry] = {}
            verification, _ = self._verify_rows_and_select(
                self._iter_rows(),
                validate_nested_contracts=True,
                maturation_index_out=maturation_index,
            )
            due = sorted(
                (
                    (candidate_id, entry)
                    for candidate_id, entry in maturation_index.items()
                    if entry.archive_sequence == 1
                    and signed_at_ms
                    >= entry.decision_time_ms
                    + max(entry.supported_horizon_seconds) * 1_000
                ),
                key=lambda item: (item[1].decision_time_ms, item[0]),
            )
            selected_actual_pending_count = sum(
                entry.decision_disposition in actual_close_required_dispositions
                for _, entry in due
            )
            label_candidate_ids = [
                candidate_id
                for candidate_id, entry in due
                if entry.decision_disposition
                not in actual_close_required_dispositions
            ]
            selected_ids = frozenset(label_candidate_ids[:max_candidates])
            selected_rows = [
                row
                for row in self._iter_rows()
                if row["archive_sequence"] == 1
                and row["candidate_id"] in selected_ids
            ]
            if {row["candidate_id"] for row in selected_rows} != selected_ids:
                _raise("selected_candidate_set_mismatch", "maturation_batch")
            try:
                records_by_id = {
                    row["candidate_id"]: candidate_decision_outcome_from_dict(
                        row["record"]
                    )
                    for row in selected_rows
                }
            except CandidateOutcomeContractError as exc:
                raise CandidateOutcomeArchiveError(
                    f"record:nested_contract_invalid:{exc}"
                ) from exc
            records = tuple(
                records_by_id[candidate_id]
                for candidate_id in label_candidate_ids[:max_candidates]
            )

        return verification, ArchiveMaturationBatchV2(
            records=records,
            horizon_due_candidate_count=len(due),
            selected_actual_pending_count=selected_actual_pending_count,
            label_candidate_count=len(label_candidate_ids),
        )

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
        receipts, _ = self.append_many_with_verification(
            records,
            signed_at_ms=signed_at_ms,
        )
        return receipts

    def append_many_with_verification(
        self,
        records: tuple[CandidateDecisionOutcomeV2, ...],
        *,
        signed_at_ms: int,
    ) -> tuple[tuple[ArchiveAppendReceiptV2, ...], ArchiveVerificationV2]:
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
                receipts_by_archive_id: dict[str, ArchiveAppendReceiptV2] = {}
                candidate_states: dict[str, tuple[int, str, str, int]] = {}
                verification, _ = self._verify_rows_and_select(
                    self._iter_rows(),
                    append_receipts_by_archive_id=receipts_by_archive_id,
                    candidate_states_out=candidate_states,
                )
                previous_chain_sha256 = verification.terminal_chain_sha256
                pending_rows: list[dict[str, Any]] = []
                receipts: list[ArchiveAppendReceiptV2] = []

                for record in records:
                    record_content_sha256 = record.content_sha256()
                    existing = receipts_by_archive_id.get(record.archive_record_id)
                    if existing is not None:
                        if existing.record_content_sha256 != record_content_sha256:
                            _raise("idempotency_key_content_collision", "archive_record_id")
                        receipts.append(replace(existing, idempotent_replay=True))
                        continue

                    candidate_id = record.decision.candidate_id
                    previous = candidate_states.get(candidate_id)
                    previous_sequence = previous[0] if previous is not None else 0
                    if record.archive_sequence != previous_sequence + 1:
                        _raise("candidate_compare_and_swap_sequence_mismatch", "archive_sequence")
                    if previous is None:
                        if record.archive_sequence != 1:
                            _raise("first_revision_must_be_one", "archive_sequence")
                    else:
                        if (
                            record.previous_archive_record_sha256
                            != previous[1]
                        ):
                            _raise(
                                "candidate_compare_and_swap_hash_mismatch",
                                "previous_archive_record_sha256",
                            )
                        if record.decision.content_sha256() != previous[2]:
                            _raise("decision_snapshot_changed", "record")
                        if record.record_generated_at_ms < previous[3]:
                            _raise("successor_generated_before_previous_available", "record")

                    row_index = verification.row_count + len(pending_rows) + 1
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
                    receipt = self._receipt(row, idempotent_replay=False)
                    receipts_by_archive_id[record.archive_record_id] = receipt
                    candidate_states[candidate_id] = (
                        record.archive_sequence,
                        record_content_sha256,
                        record.decision.content_sha256(),
                        record.record_available_at_ms,
                    )
                    previous_chain_sha256 = chain_sha256
                    receipts.append(receipt)

                final_verification = verification
                if pending_rows:
                    encoded_rows = b"".join(
                        f"{_canonical_json(row)}\n".encode("ascii")
                        for row in pending_rows
                    )
                    descriptor = _open_regular_file(
                        self.archive_path,
                        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    )
                    with os.fdopen(descriptor, "ab", buffering=0) as archive_handle:
                        pre_append_size = os.fstat(archive_handle.fileno()).st_size
                        view = memoryview(encoded_rows)
                        while view:
                            written = os.write(archive_handle.fileno(), view)
                            if written <= 0:
                                _raise("append_write_incomplete", "archive_path")
                            view = view[written:]
                        os.fsync(archive_handle.fileno())
                        expected_size = pre_append_size + len(encoded_rows)
                        if os.fstat(archive_handle.fileno()).st_size != expected_size:
                            _raise("append_size_readback_mismatch", "archive_path")
                    _fsync_directory(self.archive_path.parent)
                    readback_descriptor = _open_regular_file(
                        self.archive_path,
                        os.O_RDONLY,
                    )
                    with os.fdopen(readback_descriptor, "rb", buffering=0) as readback:
                        readback.seek(pre_append_size)
                        if readback.read(len(encoded_rows) + 1) != encoded_rows:
                            _raise("append_content_readback_mismatch", "archive_path")
                    final_verification = ArchiveVerificationV2(
                        schema_version=ARCHIVE_VERIFICATION_SCHEMA_VERSION,
                        archive_path=str(self.archive_path),
                        writer_id=self.writer_id,
                        writer_public_key_hex=self.writer_public_key_hex,
                        row_count=verification.row_count + len(pending_rows),
                        decision_revision_count=(
                            verification.decision_revision_count
                            + sum(row["archive_sequence"] == 1 for row in pending_rows)
                        ),
                        matured_revision_count=(
                            verification.matured_revision_count
                            + sum(row["archive_sequence"] == 2 for row in pending_rows)
                        ),
                        candidate_count=len(candidate_states),
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
                return tuple(receipts), final_verification
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
        with self._locked(exclusive=False):
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
    "PINNED_PRODUCTION_WRITER_ID",
    "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
    "CandidateOutcomeArchiveError",
    "ArchiveAppendReceiptV2",
    "ArchiveMaturationBatchV2",
    "ArchiveVerificationV2",
    "ArchiveCoverageV2",
    "CandidateOutcomeArchiveV2",
]
