"""Receipt-backed canonical feature snapshot ledger.

This module is a deliberately unwired v3 storage boundary.  It freezes the
exact tensor ABI and the exact source-read evidence used to construct a feature
snapshot, commits that material to one immutable SQLite ledger transaction, and
only exposes a snapshot to a fixed-cutoff training query after an independent
post-commit readback receipt exists.

The ledger never reads Redis, calls an exchange, publishes a prediction, or
changes trainer behaviour.  Legacy v1 rows may be retained for audit, but can
never become strict-training-eligible.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import struct
import weakref
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_SCHEMA_VERSION = "durable_feature_snapshot_ledger_v3"
FROZEN_ENVELOPE_SCHEMA_VERSION = "canonical_feature_tensor_envelope_v3"
RECORD_SCHEMA_VERSION = "canonical_feature_snapshot_record_v3"
SOURCE_READ_RECEIPT_SCHEMA_VERSION = "feature_source_consumer_read_receipt_v3"
FEATURE_ABI_SCHEMA_VERSION = "ordered_feature_tensor_abi_v3"
APPEND_RECEIPT_SCHEMA_VERSION = "feature_snapshot_ledger_append_receipt_v3"
POSTCOMMIT_RECEIPT_SCHEMA_VERSION = "feature_snapshot_ledger_postcommit_readback_receipt_v3"
PROJECTION_OUTBOX_SCHEMA_VERSION = "feature_snapshot_projection_outbox_v3"
LEDGER_HEAD_SCHEMA_VERSION = "feature_snapshot_ledger_head_v3"
WRITER_LEASE_SCHEMA_VERSION = "feature_snapshot_ledger_writer_lease_v3"
INTEGRITY_PROOF_SCHEMA_VERSION = "feature_snapshot_ledger_integrity_proof_v3"
SOURCE_READ_EVIDENCE_SCHEMA_VERSION = "feature_source_exact_read_evidence_v2"
SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION = "feature_source_finality_evidence_v2"
SOURCE_READ_LOCATOR_SCHEMA_VERSION = "feature_source_read_locator_v2"
FEATURE_SOURCE_BINDING_SCHEMA_VERSION = "feature_source_binding_vector_v1"
FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION = "feature_source_derivation_v1"
FEATURE_REQUIREMENT_POLICY_ID = "v2_hybrid_feature_requirements_v1"

PROVENANCE_CANONICAL_V3 = "CANONICAL_RECEIPT_BACKED_V3"
# Import compatibility only.  A caller using the old symbol still emits the
# exact v3 provenance value and must satisfy the v3 builder contract.
PROVENANCE_CANONICAL_V2 = PROVENANCE_CANONICAL_V3
PROVENANCE_LEGACY_V1_IMPORT = "LEGACY_V1_IMPORT"
LEGACY_INELIGIBILITY_REASON = "LEGACY_V1_IMPORT_PERMANENTLY_TRAINING_INELIGIBLE"
MISSING_FEATURE_INELIGIBILITY_REASON = "MISSING_FEATURE_SLOTS_PRESENT"
STALE_FEATURE_INELIGIBILITY_REASON = "STALE_FEATURE_SLOTS_PRESENT"
SOURCE_UNAVAILABLE_INELIGIBILITY_REASON = "SOURCE_SLOTS_UNAVAILABLE"
OPTIONAL_SOURCE_EVIDENCE_INELIGIBILITY_REASON = (
    "OPTIONAL_FEATURE_SOURCE_EVIDENCE_MISSING"
)
TEMPORAL_REJECTION_INELIGIBILITY_REASON = "TEMPORAL_REJECTION_REASONS_PRESENT"
RETENTION_POLICY = "NO_AUTOMATIC_PRUNING_OPERATOR_MANAGED"

DEFAULT_LEDGER_REL = Path(".local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3")
MAX_FEATURE_SLOTS = 4_096
MAX_SOURCE_RECEIPTS = 512
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_APPEND_BYTES = 64 * 1024 * 1024
MAX_QUERY_BYTES = 64 * 1024 * 1024
MAX_APPEND_ROWS = 1_024
MAX_QUERY_ROWS = 4_096
# A fixed-cutoff page can reference append transactions whose other rows must
# also be proved.  Bound that proof fan-out independently from the public page
# size so fragmented append histories cannot force an unbounded SQL walk.
MAX_QUERY_SQL_ROWS = MAX_QUERY_ROWS * 32
MAX_RECOVERY_TRANSACTIONS = 1_024
DEFAULT_BUSY_TIMEOUT_MS = 60_000
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 131_072
MAX_JSON_STRING_BYTES = 1 * 1024 * 1024
MAX_JSON_NUMBER_BYTES = 128
MAX_JSON_MAP_ENTRIES = 8_192
MAX_JSON_LIST_ITEMS = 65_536
MAX_JSON_AGGREGATE_BYTES = MAX_APPEND_BYTES
MAX_SOURCE_PAYLOAD_BYTES = 256 * 1024 * 1024

_SQLITE_APPLICATION_ID = 0x46534C33  # ``FSL3``
_SQLITE_USER_VERSION = 3
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DURABLE_ID_RE = re.compile(r"^feature_snapshot_v3_[0-9a-f]{64}$")
_TRANSACTION_ID_RE = re.compile(r"^feature_snapshot_append_[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$")
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]{0,5}[mhdw]$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$")
_GENESIS_CHAIN_SHA256 = hashlib.sha256(f"{LEDGER_SCHEMA_VERSION}:GENESIS".encode()).hexdigest()
_WRITER_LEASE_CONSTRUCTION_TOKEN = object()
_MODEL_VECTOR_HASH_DOMAIN = b"canonical_feature_model_vector_v3\0"
_FEATURE_REQUIREMENT_CLASSES = frozenset({"REQUIRED", "OPTIONAL_EVENT_DEPENDENT"})
OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES = frozenset(
    {
        "altdata_confluence_long_score",
        "altdata_confluence_short_score",
        "altdata_derivatives_pressure_score",
        "altdata_exchange_flow_pressure_usd",
        "altdata_freshness_score",
        "altdata_hedge_required_score",
        "altdata_institutional_flow_score",
        "altdata_liquidation_sweep_risk_score",
        "altdata_market_regime_score",
        "altdata_options_pin_risk_score",
        "altdata_reduce_size_score",
        "altdata_social_attention_score",
        "altdata_social_euphoria_risk_score",
        "altdata_symbol_score",
        "altdata_trade_block_score",
        "altdata_wallet_accumulation_score",
        "altdata_wallet_distribution_score",
        "btc_mempool_pressure_score",
        "coingecko_discovery_score",
        "coingecko_liquidity_score",
        "coingecko_momentum_score",
        "coingecko_score",
        "coinglass_derivatives_score",
        "defillama_liquidity_score",
        "defillama_score",
        "defillama_tvl_momentum_score",
        "fear_greed_context",
        "fear_greed_score",
        "last_liq_bps_24h",
        "liquidation_count_1h",
        "liquidation_count_5m",
        "liquidation_direction_bias_1h",
        "liquidation_notional_1h",
        "mempool_context",
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
        "moralis_onchain_risk_score",
        "moralis_smart_wallet_accumulation_score",
        "moralis_smart_wallet_distribution_score",
        "moralis_whale_net_flow_usd",
        "nearest_ask_wall_distance_bps",
        "nearest_bid_wall_distance_bps",
        "news_attention_score",
        "news_sentiment_score",
        "orchestrator_recent_allow_rate",
        "paper_position_present",
        "paper_unrealized_bps",
        "provider_availability_score",
        "public_intel_score",
        "risk_recent_allow_rate",
        "surf_market_price_signal_score",
        "surf_score",
        "whale_ask_pressure_score",
        "whale_ask_wall_notional_usd",
        "whale_bid_pressure_score",
        "whale_bid_wall_notional_usd",
        "whale_total_wall_notional_usd",
        "whale_wall_count_score",
        "whale_wall_event_count",
        "whale_wall_imbalance_score",
        "whale_wall_score",
    }
)
_SOURCE_RECEIPT_KINDS = frozenset({"DIRECT_READ", "COMPOSITE_DERIVATION"})

_SOURCE_READ_LOCATOR_TYPES = frozenset(
    {
        "FILE_CONTENT_ADDRESS",
        "HTTP_RESPONSE_DIGEST",
        "IN_MEMORY_IMMUTABLE_OBJECT",
        "REDIS_VERSIONED_VALUE",
        "SQLITE_IMMUTABLE_ROW",
        "WEBSOCKET_EVENT_DIGEST",
    }
)
_SOURCE_FINALITY_TYPES = frozenset(
    {
        "CLOSED_INTERVAL",
        "IMMUTABLE_EVENT",
        "VERSIONED_SNAPSHOT",
    }
)
_SOURCE_READ_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "read_locator_type",
        "read_locator",
        "read_locator_sha256",
        "read_locator_version",
        "read_completed_at",
    }
)
_SOURCE_FINALITY_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "read_evidence_sha256",
        "read_locator_sha256",
        "finality_type",
        "event_final",
        "finality_cutoff",
        "finality_verified_at",
        "verifier",
    }
)
_SOURCE_CHILD_BINDING_FIELDS = frozenset({"input_role", "receipt_sha256"})
_SOURCE_DERIVATION_FIELDS = frozenset(
    {
        "schema_version",
        "producer_id",
        "producer_version",
        "transform_sha256",
        "configuration_sha256",
    }
)

_SOURCE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "source_label",
        "payload_type",
        "payload_sha256",
        "event_time",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "read_evidence",
        "read_evidence_sha256",
        "read_locator_sha256",
        "finality_evidence",
        "finality_evidence_sha256",
        "receipt_kind",
        "child_read_bindings",
        "derivation_material",
        "derivation_sha256",
        "receipt_sha256",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "provenance_classification",
        "legacy_v1_snapshot_id",
        "symbol",
        "timeframe",
        "feature_snapshot_id",
        "tensor_decision_time",
        "temporal_rejection_reasons",
        "ordered_feature_names",
        "feature_abi",
        "feature_abi_sha256",
        "feature_values",
        "missing_mask",
        "stale_mask",
        "source_availability_mask",
        "ordered_feature_source_labels",
        "feature_source_receipt_sha256s",
        "feature_source_bindings_sha256",
        "model_vector_sha256",
        "source_read_receipts",
        "original_tensor_id",
        "source_lineage_material",
        "source_lineage_sha256",
        "feature_cutoff",
        "masa_feature_cutoff",
        "ppo_feature_cutoff",
        "ppo_decision_time",
        "generated_at",
        "strict_training_eligible",
        "strict_training_ineligibility_reasons",
    }
)
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "durable_snapshot_id",
        "frozen_envelope_sha256",
        "frozen_envelope",
        "record_sha256",
    }
)
_APPEND_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "batch_sha256",
        "attempted_rows",
        "inserted_rows",
        "duplicate_rows",
        "attempted_identities",
        "inserted_identities",
        "duplicate_identities",
        "attempted_dispositions",
        "attempted_identities_sha256",
        "inserted_identities_sha256",
        "duplicate_identities_sha256",
        "total_unique_rows",
        "archive_chain_sha256",
        "commit_prepared_at",
        "precommit_readback_verified",
    }
)
_POSTCOMMIT_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "head_sequence",
        "append_receipt_sha256",
        "inserted_rows",
        "inserted_identities_sha256",
        "projection_outbox_rows",
        "projection_outbox_sha256",
        "postcommit_readback_at",
        "postcommit_readback_verified",
    }
)
_PROJECTION_OUTBOX_FIELDS = frozenset(
    {
        "schema_version",
        "outbox_id",
        "durable_snapshot_id",
        "record_sha256",
        "frozen_envelope_sha256",
        "symbol",
        "timeframe",
        "original_tensor_id",
        "provenance_classification",
        "strict_training_eligible",
        "append_transaction_id",
        "prepared_at",
    }
)
_HEAD_FIELDS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "total_unique_rows",
        "archive_chain_sha256",
        "append_receipt_sha256",
        "commit_prepared_at",
    }
)

_SCHEMA_MANIFEST = {
    "schema_version": LEDGER_SCHEMA_VERSION,
    "sqlite_application_id": _SQLITE_APPLICATION_ID,
    "sqlite_user_version": _SQLITE_USER_VERSION,
    "tables": [
        "feature_snapshot_append_receipts",
        "feature_snapshot_ledger_heads",
        "feature_snapshot_ledger_metadata",
        "feature_snapshot_postcommit_receipts",
        "feature_snapshot_projection_outbox",
        "feature_snapshot_records",
    ],
    "record_contract": sorted(_RECORD_FIELDS),
    "envelope_contract": sorted(_ENVELOPE_FIELDS),
    "source_receipt_contract": sorted(_SOURCE_RECEIPT_FIELDS),
    "source_child_binding_contract": sorted(_SOURCE_CHILD_BINDING_FIELDS),
    "source_derivation_contract": sorted(_SOURCE_DERIVATION_FIELDS),
    "source_read_evidence_contract": sorted(_SOURCE_READ_EVIDENCE_FIELDS),
    "source_finality_evidence_contract": sorted(_SOURCE_FINALITY_EVIDENCE_FIELDS),
    "source_read_locator_schema": SOURCE_READ_LOCATOR_SCHEMA_VERSION,
    "feature_abi_contract_schema": FEATURE_ABI_SCHEMA_VERSION,
    "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
    "optional_event_dependent_feature_names": sorted(
        OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES
    ),
}


class FeatureSnapshotLedgerError(ValueError):
    """Base fail-closed ledger contract error."""


class FeatureSnapshotValidationError(FeatureSnapshotLedgerError):
    """A frozen tensor record violated the canonical v3 contract."""

    def __init__(self, reasons: Iterable[str]) -> None:
        self.reasons = tuple(sorted({str(reason) for reason in reasons}))
        super().__init__("feature_snapshot_validation_failed:" + ",".join(self.reasons))


class FeatureSnapshotIdentityConflictError(FeatureSnapshotLedgerError):
    """An immutable tensor identity was reused for different material."""

    def __init__(self, identities: Iterable[str]) -> None:
        self.identities = tuple(sorted({str(value) for value in identities}))
        super().__init__("feature_snapshot_identity_conflict:" + ",".join(self.identities[:20]))


class FeatureSnapshotReadbackError(FeatureSnapshotLedgerError):
    """Committed evidence could not be independently reproduced."""


class FeatureSnapshotWriterLeaseError(FeatureSnapshotLedgerError):
    """The exact resolved-path writer lease is absent or contended."""


@dataclass(frozen=True)
class FeatureSnapshotAppendResult:
    transaction_id: str
    batch_sha256: str
    attempted_rows: int
    inserted_rows: int
    duplicate_rows: int
    total_unique_rows: int
    archive_chain_sha256: str
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str
    transaction_committed: bool
    transaction_readback_verified: bool


@dataclass(frozen=True)
class FixedCutoffFeatureSnapshot:
    sequence: int
    record: dict[str, Any]
    append_transaction_id: str
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str


@dataclass(frozen=True)
class FeatureSnapshotProjectionOutboxItem:
    sequence: int
    projection: dict[str, Any]
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str


@dataclass(frozen=True)
class FeatureSnapshotIntegrityReport:
    schema_version: str
    verified_records: int
    verified_append_receipts: int
    verified_postcommit_receipts: int
    verified_projection_outbox_rows: int
    total_record_bytes: int
    archive_chain_sha256: str
    integrity_verified: bool


@dataclass
class _QueryReadBudget:
    sql_rows: int = 0
    material_bytes: int = 0

    def charge(self, *, rows: Any, material_bytes: Any) -> None:
        if (
            type(rows) is not int
            or type(material_bytes) is not int
            or rows < 0
            or material_bytes < 0
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_sql_stats_invalid")
        self.sql_rows += rows
        self.material_bytes += material_bytes
        if self.sql_rows > MAX_QUERY_SQL_ROWS:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_query_sql_rows_exceeded:{MAX_QUERY_SQL_ROWS}"
            )
        if self.material_bytes > MAX_QUERY_BYTES:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_query_bytes_exceeded:{MAX_QUERY_BYTES}"
            )


@dataclass(frozen=True)
class _ValidatedQueryRecord:
    row: sqlite3.Row
    validated: dict[str, Any]


@dataclass(frozen=True)
class _ValidatedTransactionProof:
    receipt: dict[str, Any]
    postcommit: dict[str, Any]
    head: dict[str, Any]
    projections_by_durable_id: dict[str, dict[str, Any]]
    inserted_identity_keys: frozenset[tuple[str, str, str]]


@dataclass
class _QueryProofCache:
    records_by_sequence: dict[int, _ValidatedQueryRecord]
    receipts_by_transaction: dict[str, dict[str, Any]]
    postcommit_by_transaction: dict[str, dict[str, Any]]
    heads_by_transaction: dict[str, dict[str, Any]]
    heads_by_sequence: dict[int, dict[str, Any]]
    head_sequences_by_transaction: dict[str, int]
    projections_by_transaction: dict[str, dict[str, dict[str, Any]]]
    transactions: dict[str, _ValidatedTransactionProof]

    @classmethod
    def empty(cls) -> _QueryProofCache:
        return cls(
            records_by_sequence={},
            receipts_by_transaction={},
            postcommit_by_transaction={},
            heads_by_transaction={},
            heads_by_sequence={},
            head_sequences_by_transaction={},
            projections_by_transaction={},
            transactions={},
        )


def default_ledger_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / DEFAULT_LEDGER_REL


def _lexical_absolute_path(path: Path) -> Path:
    """Return an absolute path without following any filesystem symlink."""

    raw_path = os.fspath(Path(path).expanduser())
    return Path(os.path.abspath(raw_path))


def _validate_existing_parent_components(path: Path) -> None:
    """Fail closed when an existing parent component redirects the namespace."""

    exact = _lexical_absolute_path(path)
    cursor = Path(exact.anchor)
    for component in exact.parts[1:-1]:
        cursor /= component
        try:
            component_stat = os.lstat(cursor)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_parent_validation_failed"
            ) from exc
        if stat.S_ISLNK(component_stat.st_mode):
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_parent_symlink_forbidden"
            )
        if not stat.S_ISDIR(component_stat.st_mode):
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_parent_not_directory"
            )


def _feature_snapshot_sqlite_artifact_paths(ledger_path: Path) -> dict[str, Path]:
    exact = _lexical_absolute_path(ledger_path)
    return {
        "main": exact,
        "wal": Path(f"{exact}-wal"),
        "shm": Path(f"{exact}-shm"),
        "journal": Path(f"{exact}-journal"),
        "writer_lock": exact.with_name(exact.name + ".writer.lock"),
    }


def _observed_wal_sidecar_roles(ledger_path: Path) -> frozenset[str]:
    """Return the exact WAL artifact names currently present without following links."""

    artifacts = _feature_snapshot_sqlite_artifact_paths(ledger_path)
    observed: set[str] = set()
    for role in ("wal", "shm"):
        try:
            os.lstat(artifacts[role])
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_storage_artifact_lstat_failed:{role}"
            ) from exc
        observed.add(role)
    return frozenset(observed)


def _open_verified_regular_artifact(path: Path, *, role: str) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(path)
        if stat.S_ISLNK(path_stat.st_mode):
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_storage_artifact_symlink_forbidden:{role}"
            )
        if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(
            path_stat.st_mode
        ):
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_storage_artifact_not_regular:{role}"
            )
        if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_storage_artifact_hardlink_forbidden:{role}"
            )
        descriptor_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        path_identity = (path_stat.st_dev, path_stat.st_ino)
        if descriptor_identity != path_identity:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_storage_artifact_identity_changed:{role}"
            )
        return descriptor, descriptor_stat
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _preflight_storage_artifacts(
    ledger_path: Path,
    *,
    require_main: bool,
    retain_main_descriptor: bool = False,
) -> tuple[int, tuple[int, int] | None]:
    """Validate every SQLite-owned path before SQLite is allowed to open it."""

    exact = _lexical_absolute_path(ledger_path)
    _validate_existing_parent_components(exact)
    artifacts = _feature_snapshot_sqlite_artifact_paths(exact)
    opened: list[int] = []
    retained_descriptor = -1
    main_identity: tuple[int, int] | None = None
    observed: dict[str, os.stat_result] = {}
    identities: dict[tuple[int, int], str] = {}
    try:
        for role, artifact_path in artifacts.items():
            try:
                artifact_lstat = os.lstat(artifact_path)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise FeatureSnapshotLedgerError(
                    f"feature_snapshot_storage_artifact_lstat_failed:{role}"
                ) from exc
            if stat.S_ISLNK(artifact_lstat.st_mode):
                raise FeatureSnapshotLedgerError(
                    f"feature_snapshot_storage_artifact_symlink_forbidden:{role}"
                )
            descriptor, descriptor_stat = _open_verified_regular_artifact(
                artifact_path,
                role=role,
            )
            identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
            prior_role = identities.get(identity)
            if prior_role is not None:
                os.close(descriptor)
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_storage_artifact_identity_collision:"
                    f"{prior_role}:{role}"
                )
            identities[identity] = role
            observed[role] = descriptor_stat
            if role == "main" and retain_main_descriptor:
                retained_descriptor = descriptor
                main_identity = identity
            else:
                opened.append(descriptor)
        main_stat = observed.get("main")
        sqlite_sidecars = {role for role in ("wal", "shm", "journal") if role in observed}
        if main_stat is None:
            if require_main:
                raise FeatureSnapshotLedgerError("feature_snapshot_ledger_missing")
            if sqlite_sidecars:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_storage_orphan_sqlite_sidecar"
                )
        elif main_stat.st_size == 0 and sqlite_sidecars:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_sidecar_for_empty_main"
            )
        if "journal" in observed:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_rollback_journal_forbidden"
            )
        if "shm" in observed and "wal" not in observed:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_storage_orphan_shm_sidecar"
            )
        return retained_descriptor, main_identity
    except BaseException:
        if retained_descriptor >= 0:
            try:
                os.close(retained_descriptor)
            except OSError:
                pass
        raise
    finally:
        for descriptor in opened:
            try:
                os.close(descriptor)
            except OSError:
                pass


def feature_snapshot_writer_lease_path(ledger_path: Path) -> Path:
    exact = _lexical_absolute_path(ledger_path)
    return exact.with_name(exact.name + ".writer.lock")


class FeatureSnapshotWriterLease:
    """Authentic one-shot path-and-inode writer capability."""

    __active_leases: weakref.WeakKeyDictionary[
        FeatureSnapshotWriterLease, tuple[int, int, int, int, int, int, int]
    ] = weakref.WeakKeyDictionary()

    __slots__ = (
        "_ledger_path",
        "_lock_path",
        "_file_descriptor",
        "_lock_device",
        "_lock_inode",
        "_ledger_file_descriptor",
        "_ledger_device",
        "_ledger_inode",
        "_owner_pid",
        "_released",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        ledger_path: Path,
        lock_path: Path,
        file_descriptor: int,
        lock_device: int,
        lock_inode: int,
        ledger_file_descriptor: int = -1,
        ledger_device: int = -1,
        ledger_inode: int = -1,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _WRITER_LEASE_CONSTRUCTION_TOKEN:
            raise FeatureSnapshotWriterLeaseError("writer_lease_must_use_acquire")
        self._ledger_path = Path(ledger_path)
        self._lock_path = Path(lock_path)
        self._file_descriptor = int(file_descriptor)
        self._lock_device = int(lock_device)
        self._lock_inode = int(lock_inode)
        self._ledger_file_descriptor = int(ledger_file_descriptor)
        self._ledger_device = int(ledger_device)
        self._ledger_inode = int(ledger_inode)
        self._owner_pid = os.getpid()
        self._released = False

    def _registry_identity(self) -> tuple[int, int, int, int, int, int, int]:
        return (
            self._owner_pid,
            self._file_descriptor,
            self._lock_device,
            self._lock_inode,
            self._ledger_file_descriptor,
            self._ledger_device,
            self._ledger_inode,
        )

    @classmethod
    def require_exact(
        cls,
        value: Any,
        ledger_path: Path,
    ) -> FeatureSnapshotWriterLease:
        if type(value) is not FeatureSnapshotWriterLease:
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_exact_authentic_type_required"
            )
        value.validate_for(ledger_path)
        return value

    @classmethod
    def acquire(cls, ledger_path: Path) -> FeatureSnapshotWriterLease:
        if cls is not FeatureSnapshotWriterLease:
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_exact_authentic_type_required"
            )
        exact = _lexical_absolute_path(ledger_path)
        _validate_existing_parent_components(exact)
        lock_path = feature_snapshot_writer_lease_path(exact)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        _validate_existing_parent_components(exact)
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise FeatureSnapshotWriterLeaseError("writer_lease_open_failed") from exc
        try:
            lock_stat = os.fstat(descriptor)
            lock_path_stat = os.lstat(lock_path)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise FeatureSnapshotWriterLeaseError("writer_lease_not_regular_file")
            if not stat.S_ISREG(lock_path_stat.st_mode):
                raise FeatureSnapshotWriterLeaseError("writer_lease_not_regular_file")
            if lock_stat.st_nlink != 1 or lock_path_stat.st_nlink != 1:
                raise FeatureSnapshotWriterLeaseError("writer_lease_hardlink_forbidden")
            if (lock_stat.st_dev, lock_stat.st_ino) != (
                lock_path_stat.st_dev,
                lock_path_stat.st_ino,
            ):
                raise FeatureSnapshotWriterLeaseError("writer_lease_inode_changed")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise FeatureSnapshotWriterLeaseError("writer_lease_already_held") from exc
        except BaseException:
            os.close(descriptor)
            raise
        try:
            lease = cls(
                ledger_path=exact,
                lock_path=lock_path,
                file_descriptor=descriptor,
                lock_device=lock_stat.st_dev,
                lock_inode=lock_stat.st_ino,
                _construction_token=_WRITER_LEASE_CONSTRUCTION_TOKEN,
            )
            cls.__active_leases[lease] = lease._registry_identity()
            lease.validate_for(exact)
        except BaseException:
            if "lease" in locals():
                try:
                    lease.release()
                except FeatureSnapshotWriterLeaseError:
                    pass
            else:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise
        return lease

    def _bind_ledger_inode(self, *, create_if_missing: bool) -> None:
        if self._ledger_file_descriptor >= 0:
            return
        _preflight_storage_artifacts(
            self._ledger_path,
            require_main=not create_if_missing,
        )
        flags = os.O_RDWR
        if create_if_missing:
            flags |= os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = -1
        try:
            descriptor = os.open(self._ledger_path, flags, 0o600)
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.lstat(self._ledger_path)
            if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(
                path_stat.st_mode
            ):
                raise FeatureSnapshotWriterLeaseError(
                    "writer_lease_ledger_not_regular_file"
                )
            if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
                raise FeatureSnapshotWriterLeaseError(
                    "writer_lease_ledger_hardlink_forbidden"
                )
            identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
            if identity != (path_stat.st_dev, path_stat.st_ino):
                raise FeatureSnapshotWriterLeaseError(
                    "writer_lease_ledger_inode_changed"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _preflight_storage_artifacts(self._ledger_path, require_main=True)
        except BlockingIOError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_ledger_inode_already_held"
            ) from exc
        except BaseException:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise
        self._ledger_file_descriptor = descriptor
        self._ledger_device = int(descriptor_stat.st_dev)
        self._ledger_inode = int(descriptor_stat.st_ino)
        type(self).__active_leases[self] = self._registry_identity()

    def bind_ledger_inode_for_write(self, ledger_path: Path) -> None:
        self.validate_for(ledger_path)
        if self._ledger_file_descriptor < 0:
            self._bind_ledger_inode(create_if_missing=True)
        self.validate_for(ledger_path)

    @property
    def ledger_path(self) -> Path:
        return self._ledger_path

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def held(self) -> bool:
        try:
            self.validate_for(self._ledger_path)
        except FeatureSnapshotWriterLeaseError:
            return False
        return True

    def validate_for(self, ledger_path: Path) -> None:
        if type(self) is not FeatureSnapshotWriterLease:
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_exact_authentic_type_required"
            )
        if self._released or self._file_descriptor < 0:
            raise FeatureSnapshotWriterLeaseError("writer_lease_not_held")
        registered = type(self).__active_leases.get(self)
        if registered is None or registered != self._registry_identity():
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_exact_authentic_type_required"
            )
        exact = _lexical_absolute_path(ledger_path)
        if exact != self._ledger_path:
            raise FeatureSnapshotWriterLeaseError("writer_lease_path_mismatch")
        if os.getpid() != self._owner_pid:
            raise FeatureSnapshotWriterLeaseError("writer_lease_owner_process_mismatch")
        try:
            descriptor_stat = os.fstat(self._file_descriptor)
            path_stat = os.stat(self._lock_path, follow_symlinks=False)
        except OSError as exc:
            raise FeatureSnapshotWriterLeaseError("writer_lease_validation_failed") from exc
        expected = (self._lock_device, self._lock_inode)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or descriptor_stat.st_nlink != 1
            or path_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino) != expected
            or (path_stat.st_dev, path_stat.st_ino) != expected
        ):
            raise FeatureSnapshotWriterLeaseError("writer_lease_inode_changed")
        try:
            _preflight_storage_artifacts(self._ledger_path, require_main=False)
        except FeatureSnapshotLedgerError as exc:
            raise FeatureSnapshotWriterLeaseError(
                f"writer_lease_storage_preflight_failed:{exc}"
            ) from exc
        if self._ledger_file_descriptor < 0:
            try:
                os.lstat(self._ledger_path)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise FeatureSnapshotWriterLeaseError(
                    "writer_lease_ledger_validation_failed"
                ) from exc
            self._bind_ledger_inode(create_if_missing=False)
        try:
            ledger_descriptor_stat = os.fstat(self._ledger_file_descriptor)
            ledger_path_stat = os.lstat(self._ledger_path)
        except OSError as exc:
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_ledger_validation_failed"
            ) from exc
        ledger_identity = (self._ledger_device, self._ledger_inode)
        if (
            not stat.S_ISREG(ledger_descriptor_stat.st_mode)
            or not stat.S_ISREG(ledger_path_stat.st_mode)
            or ledger_descriptor_stat.st_nlink != 1
            or ledger_path_stat.st_nlink != 1
            or (ledger_descriptor_stat.st_dev, ledger_descriptor_stat.st_ino)
            != ledger_identity
            or (ledger_path_stat.st_dev, ledger_path_stat.st_ino) != ledger_identity
        ):
            raise FeatureSnapshotWriterLeaseError(
                "writer_lease_ledger_inode_changed"
            )

    def contract(self) -> dict[str, Any]:
        self.validate_for(self._ledger_path)
        return {
            "schema_version": WRITER_LEASE_SCHEMA_VERSION,
            "ledger_path": str(self._ledger_path),
            "lock_path": str(self._lock_path),
            "exclusive": True,
            "nonblocking": True,
            "continuously_held": True,
            "exact_path_sidecar_lock_held": True,
            "ledger_inode_lock_held": self._ledger_file_descriptor >= 0,
            "hardlink_aliases_forbidden": True,
        }

    def release(self) -> None:
        if self._released:
            return
        ledger_descriptor = self._ledger_file_descriptor
        descriptor = self._file_descriptor
        self._released = True
        self._ledger_file_descriptor = -1
        self._file_descriptor = -1
        type(self).__active_leases.pop(self, None)
        release_error: BaseException | None = None
        for held_descriptor in (ledger_descriptor, descriptor):
            if held_descriptor < 0:
                continue
            try:
                os.close(held_descriptor)
            except BaseException as exc:
                if release_error is None:
                    release_error = exc
        if release_error is not None:
            raise FeatureSnapshotWriterLeaseError("writer_lease_release_failed") from release_error

    def __enter__(self) -> FeatureSnapshotWriterLease:
        self.validate_for(self._ledger_path)
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


class _FeatureSnapshotReadPathGuard:
    """Keep the exact main-file inode anchored for one SQLite read connection."""

    __slots__ = ("_descriptor", "_device", "_inode", "_ledger_path", "_released")

    def __init__(
        self,
        *,
        ledger_path: Path,
        descriptor: int,
        identity: tuple[int, int],
    ) -> None:
        self._ledger_path = _lexical_absolute_path(ledger_path)
        self._descriptor = int(descriptor)
        self._device = int(identity[0])
        self._inode = int(identity[1])
        self._released = False

    @classmethod
    def acquire(cls, ledger_path: Path) -> _FeatureSnapshotReadPathGuard:
        exact = _lexical_absolute_path(ledger_path)
        descriptor, identity = _preflight_storage_artifacts(
            exact,
            require_main=True,
            retain_main_descriptor=True,
        )
        if descriptor < 0 or identity is None:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_read_path_guard_acquisition_failed"
            )
        guard = cls(ledger_path=exact, descriptor=descriptor, identity=identity)
        try:
            guard.validate()
        except BaseException:
            guard.release()
            raise
        return guard

    def validate(self) -> None:
        if self._released or self._descriptor < 0:
            raise FeatureSnapshotLedgerError("feature_snapshot_read_path_guard_not_held")
        _preflight_storage_artifacts(self._ledger_path, require_main=True)
        try:
            descriptor_stat = os.fstat(self._descriptor)
            path_stat = os.lstat(self._ledger_path)
        except OSError as exc:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_read_path_guard_validation_failed"
            ) from exc
        expected = (self._device, self._inode)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or descriptor_stat.st_nlink != 1
            or path_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino) != expected
            or (path_stat.st_dev, path_stat.st_ino) != expected
        ):
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_read_path_guard_inode_changed"
            )

    def release(self) -> None:
        if self._released:
            return
        descriptor = self._descriptor
        self._released = True
        self._descriptor = -1
        try:
            os.close(descriptor)
        except BaseException as exc:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_read_path_guard_release_failed"
            ) from exc


class _StorageGuardedSQLiteConnection(sqlite3.Connection):
    """SQLite connection whose close revalidates and releases its path guard."""

    def bind_read_guard(self, guard: _FeatureSnapshotReadPathGuard) -> None:
        self._feature_snapshot_read_guard = guard
        self._feature_snapshot_writer_lease = None
        self._feature_snapshot_storage_closed = False

    def bind_writer_lease(self, lease: FeatureSnapshotWriterLease) -> None:
        self._feature_snapshot_read_guard = None
        self._feature_snapshot_writer_lease = lease
        self._feature_snapshot_storage_closed = False

    def close(self) -> None:
        if getattr(self, "_feature_snapshot_storage_closed", False):
            super().close()
            return
        self._feature_snapshot_storage_closed = True
        close_error: BaseException | None = None
        validation_error: BaseException | None = None
        guard = getattr(self, "_feature_snapshot_read_guard", None)
        lease = getattr(self, "_feature_snapshot_writer_lease", None)
        try:
            super().close()
        except BaseException as exc:
            close_error = exc
        try:
            if guard is not None:
                guard.validate()
            elif lease is not None:
                FeatureSnapshotWriterLease.require_exact(lease, lease.ledger_path)
        except BaseException as exc:
            validation_error = exc
        finally:
            if guard is not None:
                try:
                    guard.release()
                except BaseException as exc:
                    if validation_error is None:
                        validation_error = exc
        if close_error is not None:
            raise close_error
        if validation_error is not None:
            raise validation_error


@dataclass
class _StrictJsonBudget:
    nodes: int = 0
    aggregate_bytes: int = 0


def _consume_json_budget(budget: _StrictJsonBudget, encoded_bytes: int) -> None:
    budget.aggregate_bytes += encoded_bytes
    if budget.aggregate_bytes > MAX_JSON_AGGREGATE_BYTES:
        raise FeatureSnapshotValidationError(["STRICT_JSON_AGGREGATE_BYTES_EXCEEDED"])


def _bounded_utf8_byte_count(value: str, *, maximum: int) -> int:
    """Count UTF-8 bytes without allocating an encoded attacker-sized copy.

    ``str.__iter__`` deliberately bypasses methods on a ``str`` subclass.  A
    caller may therefore establish the byte bound before deciding whether an
    exact built-in string is required by its trust boundary.
    """

    if not isinstance(value, str):
        raise TypeError("bounded_utf8_value_not_text")
    if type(maximum) is not int or maximum < 0:
        raise ValueError("bounded_utf8_maximum_invalid")
    total = 0
    for character in str.__iter__(value):
        codepoint = ord(character)
        if codepoint <= 0x7F:
            total += 1
        elif codepoint <= 0x7FF:
            total += 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise UnicodeError("bounded_utf8_surrogate_forbidden")
        elif codepoint <= 0xFFFF:
            total += 3
        else:
            total += 4
        if total > maximum:
            return total
    return total


def _escaped_json_string_bytes(value: str) -> int:
    # ``canonical_json`` uses ensure_ascii=True.  Compute the exact encoded
    # length without invoking the serializer or allocating an escaped copy.
    total = 2  # surrounding quotation marks
    for character in str.__iter__(value):
        codepoint = ord(character)
        if character in {'"', "\\"}:
            total += 2
        elif character in {"\b", "\f", "\n", "\r", "\t"}:
            total += 2
        elif codepoint < 0x20 or 0x7F <= codepoint <= 0xFFFF:
            total += 6
        elif codepoint > 0xFFFF:
            total += 12
        else:
            total += 1
    return total


def _validate_json_tree(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    budget: _StrictJsonBudget | None = None,
) -> None:
    """Preflight a bounded strict-JSON tree before invoking the serializer."""

    if budget is None:
        budget = _StrictJsonBudget()
    if depth > MAX_JSON_DEPTH:
        raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_DEPTH_EXCEEDED"])
    budget.nodes += 1
    if budget.nodes > MAX_JSON_NODES:
        raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_NODES_EXCEEDED"])
    value_type = type(value)
    if value is None:
        _consume_json_budget(budget, 4)
        return
    if value_type is bool:
        _consume_json_budget(budget, 4 if value else 5)
        return
    if isinstance(value, str):
        try:
            encoded_bytes = _bounded_utf8_byte_count(
                value,
                maximum=MAX_JSON_STRING_BYTES,
            )
        except UnicodeError as exc:
            raise FeatureSnapshotValidationError(["STRICT_JSON_STRING_UTF8_INVALID"]) from exc
        if encoded_bytes > MAX_JSON_STRING_BYTES:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_STRING_BYTES_EXCEEDED"])
        if value_type is not str:
            raise FeatureSnapshotValidationError(
                [f"STRICT_JSON_UNSUPPORTED_TYPE:{path}"]
            )
        _consume_json_budget(budget, _escaped_json_string_bytes(value))
        return
    if value_type is int:
        # JSON integer conversion is bounded independently from Python's
        # implementation-specific maximum digit setting.
        approximate_digits = max(1, int(value.bit_length() * 0.30103) + 1)
        if value < 0:
            approximate_digits += 1
        if approximate_digits > MAX_JSON_NUMBER_BYTES:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_NUMBER_BYTES_EXCEEDED"])
        integer_bytes = len(str(value))
        if integer_bytes > MAX_JSON_NUMBER_BYTES:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_NUMBER_BYTES_EXCEEDED"])
        _consume_json_budget(budget, integer_bytes)
        return
    if value_type is float:
        if not math.isfinite(value):
            raise FeatureSnapshotValidationError(["STRICT_JSON_NONFINITE_NUMBER"])
        # CPython's JSON encoder uses the built-in float repr for finite
        # values.  Calling the descriptor directly excludes custom hooks and
        # gives the exact canonical scalar byte count.
        _consume_json_budget(budget, len(float.__repr__(value)))
        return
    if value_type is list:
        if len(value) > MAX_JSON_LIST_ITEMS:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_LIST_ITEMS_EXCEEDED"])
        _consume_json_budget(budget, 2 + max(0, len(value) - 1))
        for index, item in enumerate(value):
            _validate_json_tree(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                budget=budget,
            )
        return
    if value_type is dict:
        if len(value) > MAX_JSON_MAP_ENTRIES:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_MAP_ENTRIES_EXCEEDED"])
        _consume_json_budget(budget, 2 + max(0, len(value) - 1) + len(value))
        for key, item in value.items():
            if not isinstance(key, str):
                raise FeatureSnapshotValidationError(["STRICT_JSON_NONSTRING_KEY"])
            _validate_json_tree(key, path=f"{path}.<key>", depth=depth + 1, budget=budget)
            _validate_json_tree(
                item,
                path=f"{path}.<value>",
                depth=depth + 1,
                budget=budget,
            )
        return
    raise FeatureSnapshotValidationError(
        [f"STRICT_JSON_UNSUPPORTED_TYPE:{path}"]
    )


def canonical_json(value: Any) -> str:
    budget = _StrictJsonBudget()
    _validate_json_tree(value, budget=budget)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise FeatureSnapshotValidationError(["STRICT_JSON_ENCODING_FAILED"]) from exc
    # ``ensure_ascii=True`` guarantees one output character per encoded byte.
    # Equality proves the preflight counted every key, delimiter, nesting
    # token and scalar before serialization.
    if len(encoded) != budget.aggregate_bytes:
        raise FeatureSnapshotValidationError(["STRICT_JSON_BYTE_ACCOUNTING_MISMATCH"])
    return encoded


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _strict_utc(value: Any) -> datetime | None:
    if type(value) is not str or not value or value != value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_utc(value: Any, *, field: str) -> str:
    parsed = _strict_utc(value)
    if parsed is None:
        raise FeatureSnapshotValidationError([f"{field.upper()}_INVALID"])
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _epoch_us(value: Any) -> int | None:
    parsed = _strict_utc(value)
    if parsed is None:
        return None
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _strict_string(value: Any, *, pattern: re.Pattern[str] | None = None) -> str | None:
    if type(value) is not str or not value or value != value.strip():
        return None
    if pattern is not None and pattern.fullmatch(value) is None:
        return None
    return value


def _valid_sha256(value: Any) -> str | None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        return None
    return value


def _canonical_float32(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        packed = struct.pack("!f", parsed)
        runtime_value = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        return None
    if not math.isfinite(runtime_value):
        return None
    if parsed != 0.0 and runtime_value == 0.0:
        return None
    # Collapse signed zero so one runtime tensor has one canonical JSON form.
    return 0.0 if runtime_value == 0.0 else runtime_value


def _binary_vector(value: Any, *, expected: int, reason: str) -> list[int]:
    if not isinstance(value, list) or len(value) != expected:
        raise FeatureSnapshotValidationError([f"{reason}_DIMENSION_MISMATCH"])
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item not in (0, 1) for item in value
    ):
        raise FeatureSnapshotValidationError([f"{reason}_NOT_BINARY"])
    return list(value)


def feature_requirement_classes_for_names(
    ordered_feature_names: Sequence[str],
) -> tuple[str, ...]:
    """Return the sole code-owned requirement class for every exact feature name."""

    return tuple(
        (
            "OPTIONAL_EVENT_DEPENDENT"
            if feature_name in OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES
            else "REQUIRED"
        )
        for feature_name in ordered_feature_names
    )


def feature_abi_contract(
    ordered_feature_names: Sequence[str],
    *,
    feature_requirement_policy_id: str = FEATURE_REQUIREMENT_POLICY_ID,
    ordered_feature_requirement_classes: Sequence[str] | None = None,
) -> dict[str, Any]:
    names = list(ordered_feature_names)
    expected_requirements = list(feature_requirement_classes_for_names(names))
    if feature_requirement_policy_id != FEATURE_REQUIREMENT_POLICY_ID:
        raise FeatureSnapshotValidationError(
            ["FEATURE_REQUIREMENT_POLICY_ID_MISMATCH"]
        )
    if ordered_feature_requirement_classes is None:
        requirements = expected_requirements
    else:
        if isinstance(ordered_feature_requirement_classes, str | bytes) or not isinstance(
            ordered_feature_requirement_classes, Sequence
        ):
            raise FeatureSnapshotValidationError(
                ["ORDERED_FEATURE_REQUIREMENT_CLASSES_NOT_SEQUENCE"]
            )
        if len(ordered_feature_requirement_classes) != len(names):
            raise FeatureSnapshotValidationError(
                ["FEATURE_REQUIREMENT_CLASSES_DIMENSION_MISMATCH"]
            )
        requirements = list(ordered_feature_requirement_classes)
        if requirements != expected_requirements:
            raise FeatureSnapshotValidationError(
                ["FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH"]
            )
    if any(requirement not in _FEATURE_REQUIREMENT_CLASSES for requirement in requirements):
        raise FeatureSnapshotValidationError(["FEATURE_REQUIREMENT_CLASS_INVALID"])
    return {
        "schema_version": FEATURE_ABI_SCHEMA_VERSION,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "ordered_feature_requirement_classes": requirements,
        "feature_values": {
            "dtype": "float32",
            "encoding": "IEEE754_BINARY32_CANONICAL_JSON_DECIMAL",
            "rank": 1,
            "shape": [len(names)],
            "slot_layout": "ORDERED_FEATURE_NAMES",
        },
        "missing_mask": {
            "dtype": "uint8",
            "encoding": "BINARY_0_OR_1",
            "rank": 1,
            "shape": [len(names)],
            "slot_layout": "ORDERED_FEATURE_NAMES",
        },
        "ordered_feature_names": names,
        "source_availability_mask": {
            "dtype": "uint8",
            "encoding": "BINARY_0_OR_1",
            "rank": 1,
            "shape": [len(names)],
            "slot_layout": "ORDERED_FEATURE_NAMES",
        },
        "stale_mask": {
            "dtype": "uint8",
            "encoding": "BINARY_0_OR_1",
            "rank": 1,
            "shape": [len(names)],
            "slot_layout": "ORDERED_FEATURE_NAMES",
        },
        "model_vector": {
            "dtype": "float32",
            "encoding": "IEEE754_BINARY32_BIG_ENDIAN",
            "rank": 1,
            "shape": [len(names) * 4],
            "block_order": [
                "feature_values",
                "missing_mask",
                "stale_mask",
                "source_availability_mask",
            ],
            "block_width": len(names),
        },
    }


def feature_abi_sha256(
    ordered_feature_names: Sequence[str],
    *,
    feature_requirement_policy_id: str = FEATURE_REQUIREMENT_POLICY_ID,
    ordered_feature_requirement_classes: Sequence[str] | None = None,
) -> str:
    return stable_sha256(
        feature_abi_contract(
            ordered_feature_names,
            feature_requirement_policy_id=feature_requirement_policy_id,
            ordered_feature_requirement_classes=ordered_feature_requirement_classes,
        )
    )


def _feature_source_bindings_sha256(
    *,
    ordered_feature_names: Sequence[str],
    ordered_feature_source_labels: Sequence[str],
    feature_source_receipt_sha256s: Sequence[str | None],
) -> str:
    return stable_sha256(
        {
            "schema_version": FEATURE_SOURCE_BINDING_SCHEMA_VERSION,
            "ordered_feature_names": list(ordered_feature_names),
            "ordered_feature_source_labels": list(ordered_feature_source_labels),
            "feature_source_receipt_sha256s": list(feature_source_receipt_sha256s),
        }
    )


def _model_vector_sha256(
    *,
    feature_abi_sha256_value: str,
    feature_values: Sequence[float],
    missing_mask: Sequence[int],
    stale_mask: Sequence[int],
    source_availability_mask: Sequence[int],
) -> str:
    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_HASH_DOMAIN)
    digest.update(bytes.fromhex(feature_abi_sha256_value))
    digest.update(struct.pack(">I", len(feature_values)))
    for value in (
        *feature_values,
        *missing_mask,
        *stale_mask,
        *source_availability_mask,
    ):
        digest.update(struct.pack(">f", float(value)))
    return digest.hexdigest()


def _bounded_builder_sequence_count(
    value: Any,
    *,
    max_items: int,
    type_reason: str,
    count_reason: str,
) -> int:
    # Only exact built-in containers are admitted.  Checking this before
    # ``len`` prevents caller-controlled Sequence hooks from running ahead of
    # the cheap structural gate.
    if type(value) not in (list, tuple):
        raise FeatureSnapshotValidationError([type_reason])
    try:
        item_count = len(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise FeatureSnapshotValidationError([type_reason]) from exc
    if item_count > max_items:
        raise FeatureSnapshotValidationError([count_reason])
    return item_count


def _bounded_builder_mapping_copy(
    value: Any,
    *,
    max_entries: int,
    type_reason: str,
    count_reason: str,
) -> dict[Any, Any]:
    # As above, do not invoke arbitrary Mapping hooks before exact-type
    # admission.  A plain dict has trusted O(1) length and bounded iteration.
    if type(value) is not dict:
        raise FeatureSnapshotValidationError([type_reason])
    try:
        entry_count = len(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise FeatureSnapshotValidationError([type_reason]) from exc
    if entry_count > max_entries:
        raise FeatureSnapshotValidationError([count_reason])
    copied: dict[Any, Any] = {}
    for key, item in value.items():
        if len(copied) >= max_entries:
            raise FeatureSnapshotValidationError([count_reason])
        copied[key] = item
    return copied


def build_source_read_receipt(
    *,
    source_label: str,
    payload_type: str,
    payload_sha256: str,
    payload_byte_count: int,
    event_time: str,
    available_at: str,
    consumer_observed_at: str,
    feature_cutoff: str,
    read_locator_type: str,
    read_locator: str,
    read_locator_version: str,
    finality_type: str,
    finality_cutoff: str,
    finality_verified_at: str,
    finality_verifier: str,
    receipt_kind: str = "DIRECT_READ",
    child_read_bindings: Sequence[Mapping[str, str]] = (),
    derivation_material: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one exact, typed source-read and finality receipt.

    The read locator is bound to the observed payload digest, and the finality
    evidence is in turn bound to that exact read evidence.  Composite outputs
    bind exact child receipt hashes and an exact derivation contract.  Generic
    free-form evidence is intentionally not accepted at this strict v3 boundary.
    """

    _bounded_builder_sequence_count(
        child_read_bindings,
        max_items=MAX_SOURCE_RECEIPTS,
        type_reason="SOURCE_CHILD_BINDINGS_NOT_BOUNDED_SEQUENCE",
        count_reason="SOURCE_CHILD_BINDING_COUNT_EXCEEDED",
    )
    children: list[dict[str, str]] = []
    for binding in child_read_bindings:
        copied_binding = _bounded_builder_mapping_copy(
            binding,
            max_entries=len(_SOURCE_CHILD_BINDING_FIELDS),
            type_reason="SOURCE_CHILD_BINDING_NOT_BOUNDED_OBJECT",
            count_reason="SOURCE_CHILD_BINDING_ENTRY_COUNT_EXCEEDED",
        )
        if set(copied_binding) != _SOURCE_CHILD_BINDING_FIELDS:
            raise FeatureSnapshotValidationError(
                ["SOURCE_CHILD_BINDING_FIELD_SET_MISMATCH"]
            )
        input_role = copied_binding.get("input_role")
        receipt_sha256 = copied_binding.get("receipt_sha256")
        if _strict_string(input_role, pattern=_LABEL_RE) is None:
            raise FeatureSnapshotValidationError(
                ["SOURCE_CHILD_BINDING_ROLE_INVALID"]
            )
        if _valid_sha256(receipt_sha256) is None:
            raise FeatureSnapshotValidationError(
                ["SOURCE_CHILD_BINDING_SHA256_INVALID"]
            )
        children.append(
            {
                "input_role": input_role,
                "receipt_sha256": receipt_sha256,
            }
        )
    children.sort(key=lambda item: (item.get("input_role", ""), item.get("receipt_sha256", "")))
    derivation = (
        _bounded_builder_mapping_copy(
            derivation_material,
            max_entries=len(_SOURCE_DERIVATION_FIELDS),
            type_reason="SOURCE_DERIVATION_NOT_BOUNDED_OBJECT",
            count_reason="SOURCE_DERIVATION_ENTRY_COUNT_EXCEEDED",
        )
        if derivation_material is not None
        else None
    )

    canonical_observed_at = _canonical_utc(
        consumer_observed_at, field="source_consumer_observed_at"
    )
    read_locator_material = {
        "schema_version": SOURCE_READ_LOCATOR_SCHEMA_VERSION,
        "read_locator_type": read_locator_type,
        "read_locator": read_locator,
        "read_locator_version": read_locator_version,
    }
    read_locator_sha256 = stable_sha256(read_locator_material)
    read_evidence: dict[str, Any] = {
        "schema_version": SOURCE_READ_EVIDENCE_SCHEMA_VERSION,
        "source_label": source_label,
        "payload_type": payload_type,
        "payload_sha256": payload_sha256,
        "payload_byte_count": payload_byte_count,
        "read_locator_type": read_locator_type,
        "read_locator": read_locator,
        "read_locator_sha256": read_locator_sha256,
        "read_locator_version": read_locator_version,
        "read_completed_at": canonical_observed_at,
    }
    read_evidence_sha256 = stable_sha256(read_evidence)
    finality_evidence: dict[str, Any] = {
        "schema_version": SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION,
        "source_label": source_label,
        "payload_type": payload_type,
        "payload_sha256": payload_sha256,
        "read_evidence_sha256": read_evidence_sha256,
        "read_locator_sha256": read_locator_sha256,
        "finality_type": finality_type,
        "event_final": True,
        "finality_cutoff": _canonical_utc(finality_cutoff, field="source_finality_cutoff"),
        "finality_verified_at": _canonical_utc(
            finality_verified_at, field="source_finality_verified_at"
        ),
        "verifier": finality_verifier,
    }
    receipt: dict[str, Any] = {
        "schema_version": SOURCE_READ_RECEIPT_SCHEMA_VERSION,
        "source_label": source_label,
        "payload_type": payload_type,
        "payload_sha256": payload_sha256,
        "event_time": _canonical_utc(event_time, field="source_event_time"),
        "available_at": _canonical_utc(available_at, field="source_available_at"),
        "consumer_observed_at": canonical_observed_at,
        "feature_cutoff": _canonical_utc(feature_cutoff, field="source_feature_cutoff"),
        "read_evidence": read_evidence,
        "read_evidence_sha256": read_evidence_sha256,
        "read_locator_sha256": read_locator_sha256,
        "finality_evidence": finality_evidence,
        "finality_evidence_sha256": stable_sha256(finality_evidence),
        "receipt_kind": receipt_kind,
        "child_read_bindings": children,
        "derivation_material": derivation,
        "derivation_sha256": stable_sha256(derivation) if derivation is not None else None,
    }
    receipt["receipt_sha256"] = stable_sha256(receipt)
    # Reuse the full validator so builders and readers enforce one contract.
    _source_receipt_reasons(receipt)
    return receipt


def _strict_training_ineligibility_reasons(
    *,
    provenance_classification: str,
    missing_mask: Sequence[int],
    stale_mask: Sequence[int],
    feature_source_receipt_sha256s: Sequence[str | None],
    ordered_feature_requirement_classes: Sequence[str],
    temporal_rejection_reasons: Sequence[str],
) -> list[str]:
    if provenance_classification == PROVENANCE_LEGACY_V1_IMPORT:
        return [LEGACY_INELIGIBILITY_REASON]
    reasons: list[str] = []
    if any(
        missing == 1 and requirement == "REQUIRED"
        for missing, requirement in zip(
            missing_mask,
            ordered_feature_requirement_classes,
            strict=True,
        )
    ):
        reasons.append(MISSING_FEATURE_INELIGIBILITY_REASON)
    if any(stale_mask):
        reasons.append(STALE_FEATURE_INELIGIBILITY_REASON)
    if any(
        missing == 1
        and requirement == "OPTIONAL_EVENT_DEPENDENT"
        and receipt_sha256 is None
        for missing, requirement, receipt_sha256 in zip(
            missing_mask,
            ordered_feature_requirement_classes,
            feature_source_receipt_sha256s,
            strict=True,
        )
    ):
        reasons.append(OPTIONAL_SOURCE_EVIDENCE_INELIGIBILITY_REASON)
    if temporal_rejection_reasons:
        reasons.append(TEMPORAL_REJECTION_INELIGIBILITY_REASON)
    return reasons


def build_feature_snapshot_record(
    *,
    provenance_classification: str,
    legacy_v1_snapshot_id: str | None,
    symbol: str,
    timeframe: str,
    feature_snapshot_id: str,
    tensor_decision_time: str,
    temporal_rejection_reasons: Sequence[str],
    ordered_feature_names: Sequence[str],
    feature_values: Sequence[int | float],
    missing_mask: Sequence[int],
    stale_mask: Sequence[int],
    source_availability_mask: Sequence[int],
    ordered_feature_source_labels: Sequence[str],
    feature_source_receipt_sha256s: Sequence[str | None],
    source_read_receipts: Sequence[Mapping[str, Any]],
    feature_requirement_policy_id: str,
    ordered_feature_requirement_classes: Sequence[str],
    original_tensor_id: str,
    source_lineage_material: Mapping[str, Any],
    feature_cutoff: str,
    masa_feature_cutoff: str,
    ppo_feature_cutoff: str,
    ppo_decision_time: str,
    generated_at: str,
) -> dict[str, Any]:
    """Freeze one exact 4N tensor, source binding graph, and durable identity."""

    vectors: tuple[tuple[str, Sequence[Any]], ...] = (
        ("ORDERED_FEATURE_NAMES", ordered_feature_names),
        ("FEATURE_VALUES", feature_values),
        ("MISSING_MASK", missing_mask),
        ("STALE_MASK", stale_mask),
        ("SOURCE_AVAILABILITY_MASK", source_availability_mask),
        ("ORDERED_FEATURE_SOURCE_LABELS", ordered_feature_source_labels),
        ("FEATURE_SOURCE_RECEIPT_SHA256S", feature_source_receipt_sha256s),
        ("ORDERED_FEATURE_REQUIREMENT_CLASSES", ordered_feature_requirement_classes),
    )
    for reason, vector in vectors:
        if isinstance(vector, str | bytes):
            raise FeatureSnapshotValidationError([f"{reason}_NOT_SEQUENCE"])
        if len(vector) > MAX_FEATURE_SLOTS:
            raise FeatureSnapshotValidationError(["FEATURE_SLOT_COUNT_INVALID"])
    feature_count = len(ordered_feature_names)
    if feature_count == 0 or any(len(vector) != feature_count for _reason, vector in vectors):
        raise FeatureSnapshotValidationError(["FEATURE_SLOT_DIMENSION_MISMATCH"])
    if isinstance(temporal_rejection_reasons, str | bytes):
        raise FeatureSnapshotValidationError(["TEMPORAL_REJECTION_REASONS_NOT_SEQUENCE"])
    if len(temporal_rejection_reasons) > MAX_FEATURE_SLOTS:
        raise FeatureSnapshotValidationError(["TEMPORAL_REJECTION_REASON_COUNT_EXCEEDED"])
    if isinstance(source_read_receipts, str | bytes):
        raise FeatureSnapshotValidationError(["SOURCE_READ_RECEIPTS_NOT_SEQUENCE"])
    if len(source_read_receipts) > MAX_SOURCE_RECEIPTS:
        raise FeatureSnapshotValidationError(["SOURCE_RECEIPT_COUNT_EXCEEDED"])

    names = list(ordered_feature_names)
    parsed_values = [_canonical_float32(value) for value in feature_values]
    if any(value is None for value in parsed_values):
        raise FeatureSnapshotValidationError(["FEATURE_VALUES_NOT_FINITE_FLOAT32"])
    values = [float(value) for value in parsed_values if value is not None]
    missing = list(missing_mask)
    stale = list(stale_mask)
    availability = list(source_availability_mask)
    feature_sources = list(ordered_feature_source_labels)
    feature_bindings = list(feature_source_receipt_sha256s)
    requirement_classes = list(ordered_feature_requirement_classes)
    temporal_rejections = sorted({str(reason) for reason in temporal_rejection_reasons})

    receipts: list[dict[str, Any]] = []
    for receipt in source_read_receipts:
        if not isinstance(receipt, Mapping):
            raise FeatureSnapshotValidationError(["SOURCE_RECEIPT_NOT_OBJECT"])
        if len(receipt) > MAX_JSON_MAP_ENTRIES:
            raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_MAP_ENTRIES_EXCEEDED"])
        receipts.append(dict(receipt))
    receipts.sort(key=lambda receipt: str(receipt.get("receipt_sha256") or ""))

    if not isinstance(source_lineage_material, Mapping):
        raise FeatureSnapshotValidationError(["SOURCE_LINEAGE_MATERIAL_INVALID"])
    if len(source_lineage_material) > MAX_JSON_MAP_ENTRIES:
        raise FeatureSnapshotValidationError(["STRICT_JSON_MAX_MAP_ENTRIES_EXCEEDED"])

    abi = feature_abi_contract(
        names,
        feature_requirement_policy_id=feature_requirement_policy_id,
        ordered_feature_requirement_classes=requirement_classes,
    )
    abi_sha256 = stable_sha256(abi)
    bindings_sha256 = _feature_source_bindings_sha256(
        ordered_feature_names=names,
        ordered_feature_source_labels=feature_sources,
        feature_source_receipt_sha256s=feature_bindings,
    )
    model_vector_sha256 = _model_vector_sha256(
        feature_abi_sha256_value=abi_sha256,
        feature_values=values,
        missing_mask=missing,
        stale_mask=stale,
        source_availability_mask=availability,
    )
    receipt_sha256s = [receipt.get("receipt_sha256") for receipt in receipts]
    receipt_graph_sha256 = stable_sha256(
        {
            "schema_version": "feature_source_receipt_graph_v1",
            "feature_root_receipt_sha256s": feature_bindings,
            "receipt_sha256s": receipt_sha256s,
        }
    )
    lineage = dict(source_lineage_material)
    lineage_bindings = {
        "feature_abi_sha256": abi_sha256,
        "ordered_feature_source_labels": feature_sources,
        "source_availability_mask": availability,
        "feature_source_receipt_sha256s": feature_bindings,
        "feature_source_bindings_sha256": bindings_sha256,
        "source_read_receipt_sha256s": receipt_sha256s,
        "source_receipt_graph_sha256": receipt_graph_sha256,
        "model_vector_sha256": model_vector_sha256,
    }
    if any(
        key in lineage and lineage[key] != expected
        for key, expected in lineage_bindings.items()
    ):
        raise FeatureSnapshotValidationError(["SOURCE_LINEAGE_RESERVED_BINDING_CONFLICT"])
    lineage.update(lineage_bindings)
    ineligibility_reasons = _strict_training_ineligibility_reasons(
        provenance_classification=provenance_classification,
        missing_mask=missing,
        stale_mask=stale,
        feature_source_receipt_sha256s=feature_bindings,
        ordered_feature_requirement_classes=requirement_classes,
        temporal_rejection_reasons=temporal_rejections,
    )
    envelope: dict[str, Any] = {
        "schema_version": FROZEN_ENVELOPE_SCHEMA_VERSION,
        "provenance_classification": provenance_classification,
        "legacy_v1_snapshot_id": legacy_v1_snapshot_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": feature_snapshot_id,
        "tensor_decision_time": _canonical_utc(
            tensor_decision_time, field="tensor_decision_time"
        ),
        "temporal_rejection_reasons": temporal_rejections,
        "ordered_feature_names": names,
        "feature_abi": abi,
        "feature_abi_sha256": abi_sha256,
        "feature_values": values,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability_mask": availability,
        "ordered_feature_source_labels": feature_sources,
        "feature_source_receipt_sha256s": feature_bindings,
        "feature_source_bindings_sha256": bindings_sha256,
        "model_vector_sha256": model_vector_sha256,
        "source_read_receipts": receipts,
        "original_tensor_id": original_tensor_id,
        "source_lineage_material": lineage,
        "source_lineage_sha256": stable_sha256(lineage),
        "feature_cutoff": _canonical_utc(feature_cutoff, field="feature_cutoff"),
        "masa_feature_cutoff": _canonical_utc(masa_feature_cutoff, field="masa_feature_cutoff"),
        "ppo_feature_cutoff": _canonical_utc(ppo_feature_cutoff, field="ppo_feature_cutoff"),
        "ppo_decision_time": _canonical_utc(ppo_decision_time, field="ppo_decision_time"),
        "generated_at": _canonical_utc(generated_at, field="generated_at"),
        "strict_training_eligible": not ineligibility_reasons,
        "strict_training_ineligibility_reasons": ineligibility_reasons,
    }
    envelope_sha256 = stable_sha256(envelope)
    record: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "durable_snapshot_id": f"feature_snapshot_v3_{envelope_sha256}",
        "frozen_envelope_sha256": envelope_sha256,
        "frozen_envelope": envelope,
    }
    record["record_sha256"] = stable_sha256(record)
    validate_feature_snapshot_record(record)
    return record


def _source_receipt_reasons(receipt: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if set(receipt) != _SOURCE_RECEIPT_FIELDS:
        reasons.append("SOURCE_RECEIPT_FIELD_SET_MISMATCH")
    if receipt.get("schema_version") != SOURCE_READ_RECEIPT_SCHEMA_VERSION:
        reasons.append("SOURCE_RECEIPT_SCHEMA_VERSION_MISMATCH")
    if _strict_string(receipt.get("source_label"), pattern=_LABEL_RE) is None:
        reasons.append("SOURCE_RECEIPT_LABEL_INVALID")
    if _strict_string(receipt.get("payload_type"), pattern=_LABEL_RE) is None:
        reasons.append("SOURCE_RECEIPT_PAYLOAD_TYPE_INVALID")
    if _valid_sha256(receipt.get("payload_sha256")) is None:
        reasons.append("SOURCE_RECEIPT_PAYLOAD_SHA256_INVALID")
    receipt_kind = receipt.get("receipt_kind")
    if receipt_kind not in _SOURCE_RECEIPT_KINDS:
        reasons.append("SOURCE_RECEIPT_KIND_INVALID")
    children_raw = receipt.get("child_read_bindings")
    children = children_raw if isinstance(children_raw, list) else []
    if not isinstance(children_raw, list):
        reasons.append("SOURCE_CHILD_BINDINGS_NOT_LIST")
    elif len(children) > MAX_SOURCE_RECEIPTS:
        reasons.append("SOURCE_CHILD_BINDING_COUNT_EXCEEDED")
    child_roles: list[str] = []
    child_sha256s: list[str] = []
    for child in children:
        if not isinstance(child, Mapping):
            reasons.append("SOURCE_CHILD_BINDING_NOT_OBJECT")
            continue
        if set(child) != _SOURCE_CHILD_BINDING_FIELDS:
            reasons.append("SOURCE_CHILD_BINDING_FIELD_SET_MISMATCH")
        role = _strict_string(child.get("input_role"), pattern=_LABEL_RE)
        if role is None:
            reasons.append("SOURCE_CHILD_BINDING_ROLE_INVALID")
        else:
            child_roles.append(role)
        child_sha256 = _valid_sha256(child.get("receipt_sha256"))
        if child_sha256 is None:
            reasons.append("SOURCE_CHILD_BINDING_SHA256_INVALID")
        else:
            child_sha256s.append(child_sha256)
    if children != sorted(
        children,
        key=lambda item: (
            str(item.get("input_role") or "") if isinstance(item, Mapping) else "",
            str(item.get("receipt_sha256") or "") if isinstance(item, Mapping) else "",
        ),
    ):
        reasons.append("SOURCE_CHILD_BINDINGS_NOT_CANONICAL_ORDER")
    if len(child_roles) != len(set(child_roles)):
        reasons.append("SOURCE_CHILD_BINDING_ROLE_NOT_UNIQUE")
    if len(child_sha256s) != len(set(child_sha256s)):
        reasons.append("SOURCE_CHILD_RECEIPT_SHA256_NOT_UNIQUE")

    derivation = receipt.get("derivation_material")
    derivation_sha256 = receipt.get("derivation_sha256")
    if receipt_kind == "DIRECT_READ":
        if children:
            reasons.append("DIRECT_SOURCE_RECEIPT_HAS_CHILDREN")
        if derivation is not None or derivation_sha256 is not None:
            reasons.append("DIRECT_SOURCE_RECEIPT_HAS_DERIVATION")
    elif receipt_kind == "COMPOSITE_DERIVATION":
        if not children:
            reasons.append("COMPOSITE_SOURCE_RECEIPT_CHILDREN_REQUIRED")
        if not isinstance(derivation, Mapping):
            reasons.append("COMPOSITE_SOURCE_DERIVATION_NOT_OBJECT")
        else:
            if set(derivation) != _SOURCE_DERIVATION_FIELDS:
                reasons.append("SOURCE_DERIVATION_FIELD_SET_MISMATCH")
            if derivation.get("schema_version") != FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION:
                reasons.append("SOURCE_DERIVATION_SCHEMA_VERSION_MISMATCH")
            for field in ("producer_id", "producer_version"):
                if _strict_string(derivation.get(field), pattern=_LABEL_RE) is None:
                    reasons.append(f"SOURCE_DERIVATION_{field.upper()}_INVALID")
            for field in ("transform_sha256", "configuration_sha256"):
                if _valid_sha256(derivation.get(field)) is None:
                    reasons.append(f"SOURCE_DERIVATION_{field.upper()}_INVALID")
            try:
                expected_derivation_sha256 = stable_sha256(derivation)
            except FeatureSnapshotValidationError:
                reasons.append("SOURCE_DERIVATION_NOT_STRICT_JSON")
            else:
                if derivation_sha256 != expected_derivation_sha256:
                    reasons.append("DERIVATION_SHA256_MISMATCH")
    clock_values: dict[str, datetime] = {}
    for field in ("event_time", "available_at", "consumer_observed_at", "feature_cutoff"):
        parsed = _strict_utc(receipt.get(field))
        if parsed is None:
            reasons.append(f"SOURCE_RECEIPT_{field.upper()}_INVALID")
        elif receipt.get(field) != parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"):
            reasons.append(f"SOURCE_RECEIPT_{field.upper()}_NOT_CANONICAL")
        else:
            clock_values[field] = parsed
    if all(key in clock_values for key in ("event_time", "available_at", "consumer_observed_at")):
        if clock_values["event_time"] > clock_values["available_at"]:
            reasons.append("SOURCE_EVENT_TIME_AFTER_AVAILABLE_AT")
        if clock_values["available_at"] > clock_values["consumer_observed_at"]:
            reasons.append("SOURCE_AVAILABLE_AT_AFTER_CONSUMER_OBSERVED_AT")
    if (
        all(key in clock_values for key in ("event_time", "feature_cutoff"))
        and clock_values["event_time"] > clock_values["feature_cutoff"]
    ):
        reasons.append("SOURCE_EVENT_TIME_AFTER_SOURCE_FEATURE_CUTOFF")

    read_evidence = receipt.get("read_evidence")
    if not isinstance(read_evidence, Mapping):
        reasons.append("SOURCE_READ_EVIDENCE_NOT_OBJECT")
        read_evidence = {}
    if set(read_evidence) != _SOURCE_READ_EVIDENCE_FIELDS:
        reasons.append("SOURCE_READ_EVIDENCE_FIELD_SET_MISMATCH")
    if read_evidence.get("schema_version") != SOURCE_READ_EVIDENCE_SCHEMA_VERSION:
        reasons.append("SOURCE_READ_EVIDENCE_SCHEMA_VERSION_MISMATCH")
    if read_evidence.get("source_label") != receipt.get("source_label"):
        reasons.append("SOURCE_READ_EVIDENCE_LABEL_BINDING_MISMATCH")
    if read_evidence.get("payload_type") != receipt.get("payload_type"):
        reasons.append("SOURCE_READ_EVIDENCE_PAYLOAD_TYPE_BINDING_MISMATCH")
    if read_evidence.get("payload_sha256") != receipt.get("payload_sha256"):
        reasons.append("SOURCE_READ_EVIDENCE_PAYLOAD_BINDING_MISMATCH")
    payload_byte_count = read_evidence.get("payload_byte_count")
    if (
        isinstance(payload_byte_count, bool)
        or not isinstance(payload_byte_count, int)
        or payload_byte_count <= 0
        or payload_byte_count > MAX_SOURCE_PAYLOAD_BYTES
    ):
        reasons.append("SOURCE_READ_EVIDENCE_PAYLOAD_BYTE_COUNT_INVALID")
    if read_evidence.get("read_locator_type") not in _SOURCE_READ_LOCATOR_TYPES:
        reasons.append("SOURCE_READ_EVIDENCE_LOCATOR_TYPE_INVALID")
    if _strict_string(read_evidence.get("read_locator")) is None:
        reasons.append("SOURCE_READ_EVIDENCE_LOCATOR_INVALID")
    if _strict_string(read_evidence.get("read_locator_version"), pattern=_LABEL_RE) is None:
        reasons.append("SOURCE_READ_EVIDENCE_LOCATOR_VERSION_INVALID")
    locator_material = {
        "schema_version": SOURCE_READ_LOCATOR_SCHEMA_VERSION,
        "read_locator_type": read_evidence.get("read_locator_type"),
        "read_locator": read_evidence.get("read_locator"),
        "read_locator_version": read_evidence.get("read_locator_version"),
    }
    try:
        expected_read_locator_sha256 = stable_sha256(locator_material)
    except FeatureSnapshotValidationError:
        reasons.append("SOURCE_READ_LOCATOR_NOT_STRICT_JSON")
        expected_read_locator_sha256 = None
    if read_evidence.get("read_locator_sha256") != expected_read_locator_sha256:
        reasons.append("SOURCE_READ_EVIDENCE_LOCATOR_SHA256_MISMATCH")
    if receipt.get("read_locator_sha256") != expected_read_locator_sha256:
        reasons.append("SOURCE_RECEIPT_LOCATOR_BINDING_MISMATCH")
    read_completed_at = _strict_utc(read_evidence.get("read_completed_at"))
    if read_completed_at is None:
        reasons.append("SOURCE_READ_EVIDENCE_COMPLETED_AT_INVALID")
    elif read_evidence.get("read_completed_at") != read_completed_at.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z"):
        reasons.append("SOURCE_READ_EVIDENCE_COMPLETED_AT_NOT_CANONICAL")
    elif read_evidence.get("read_completed_at") != receipt.get("consumer_observed_at"):
        reasons.append("SOURCE_READ_EVIDENCE_OBSERVATION_BINDING_MISMATCH")
    try:
        expected_read_evidence_sha256 = stable_sha256(read_evidence)
    except FeatureSnapshotValidationError:
        reasons.append("SOURCE_READ_EVIDENCE_NOT_STRICT_JSON")
        expected_read_evidence_sha256 = None
    if receipt.get("read_evidence_sha256") != expected_read_evidence_sha256:
        reasons.append("SOURCE_READ_EVIDENCE_SHA256_MISMATCH")

    finality_evidence = receipt.get("finality_evidence")
    if not isinstance(finality_evidence, Mapping):
        reasons.append("SOURCE_FINALITY_EVIDENCE_NOT_OBJECT")
        finality_evidence = {}
    if set(finality_evidence) != _SOURCE_FINALITY_EVIDENCE_FIELDS:
        reasons.append("SOURCE_FINALITY_EVIDENCE_FIELD_SET_MISMATCH")
    if finality_evidence.get("schema_version") != SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION:
        reasons.append("SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION_MISMATCH")
    if finality_evidence.get("source_label") != receipt.get("source_label"):
        reasons.append("SOURCE_FINALITY_EVIDENCE_LABEL_BINDING_MISMATCH")
    if finality_evidence.get("payload_type") != receipt.get("payload_type"):
        reasons.append("SOURCE_FINALITY_EVIDENCE_PAYLOAD_TYPE_BINDING_MISMATCH")
    if finality_evidence.get("payload_sha256") != receipt.get("payload_sha256"):
        reasons.append("SOURCE_FINALITY_EVIDENCE_PAYLOAD_BINDING_MISMATCH")
    if finality_evidence.get("read_evidence_sha256") != expected_read_evidence_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_READ_BINDING_MISMATCH")
    if finality_evidence.get("read_locator_sha256") != expected_read_locator_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_LOCATOR_BINDING_MISMATCH")
    if finality_evidence.get("finality_type") not in _SOURCE_FINALITY_TYPES:
        reasons.append("SOURCE_FINALITY_EVIDENCE_TYPE_INVALID")
    if finality_evidence.get("event_final") is not True:
        reasons.append("SOURCE_FINALITY_EVIDENCE_NOT_FINAL")
    if _strict_string(finality_evidence.get("verifier"), pattern=_LABEL_RE) is None:
        reasons.append("SOURCE_FINALITY_EVIDENCE_VERIFIER_INVALID")
    finality_clocks: dict[str, datetime] = {}
    for field in ("finality_cutoff", "finality_verified_at"):
        parsed = _strict_utc(finality_evidence.get(field))
        if parsed is None:
            reasons.append(f"SOURCE_FINALITY_EVIDENCE_{field.upper()}_INVALID")
        elif finality_evidence.get(field) != parsed.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ):
            reasons.append(f"SOURCE_FINALITY_EVIDENCE_{field.upper()}_NOT_CANONICAL")
        else:
            finality_clocks[field] = parsed
    if "event_time" in clock_values and "finality_cutoff" in finality_clocks:
        if clock_values["event_time"] > finality_clocks["finality_cutoff"]:
            reasons.append("SOURCE_EVENT_TIME_AFTER_FINALITY_CUTOFF")
    if "finality_cutoff" in finality_clocks and "available_at" in clock_values:
        if finality_clocks["finality_cutoff"] > clock_values["available_at"]:
            reasons.append("SOURCE_FINALITY_CUTOFF_AFTER_AVAILABLE_AT")
    if "available_at" in clock_values and "finality_verified_at" in finality_clocks:
        if clock_values["available_at"] > finality_clocks["finality_verified_at"]:
            reasons.append("SOURCE_AVAILABLE_AT_AFTER_FINALITY_VERIFIED_AT")
    if "finality_verified_at" in finality_clocks and "consumer_observed_at" in clock_values:
        if finality_clocks["finality_verified_at"] > clock_values["consumer_observed_at"]:
            reasons.append("SOURCE_FINALITY_VERIFIED_AT_AFTER_CONSUMER_OBSERVED_AT")
    try:
        expected_finality_evidence_sha256 = stable_sha256(finality_evidence)
    except FeatureSnapshotValidationError:
        reasons.append("SOURCE_FINALITY_EVIDENCE_NOT_STRICT_JSON")
        expected_finality_evidence_sha256 = None
    if receipt.get("finality_evidence_sha256") != expected_finality_evidence_sha256:
        reasons.append("SOURCE_FINALITY_EVIDENCE_SHA256_MISMATCH")
    if set(receipt) == _SOURCE_RECEIPT_FIELDS:
        material_without_hash = {
            key: value for key, value in receipt.items() if key != "receipt_sha256"
        }
        try:
            expected = stable_sha256(material_without_hash)
        except FeatureSnapshotValidationError:
            reasons.append("SOURCE_RECEIPT_NOT_STRICT_JSON")
        else:
            if receipt.get("receipt_sha256") != expected:
                reasons.append("SOURCE_RECEIPT_SHA256_MISMATCH")
    if reasons:
        raise FeatureSnapshotValidationError(reasons)
    return reasons


def _source_receipt_graph_reasons(
    *,
    receipts: Sequence[Mapping[str, Any]],
    ordered_feature_source_labels: Sequence[str],
    feature_source_receipt_sha256s: Sequence[str | None],
    source_availability_mask: Sequence[int],
) -> list[str]:
    reasons: list[str] = []
    receipt_hashes = [receipt.get("receipt_sha256") for receipt in receipts]
    valid_receipt_hashes = [
        value for value in receipt_hashes if isinstance(value, str) and _valid_sha256(value)
    ]
    if len(valid_receipt_hashes) != len(set(valid_receipt_hashes)):
        reasons.append("SOURCE_RECEIPT_SHA256_NOT_UNIQUE")
    if receipt_hashes != sorted(receipt_hashes, key=lambda value: str(value or "")):
        reasons.append("SOURCE_RECEIPTS_NOT_CANONICAL_ORDER")
    receipt_by_sha = {
        str(receipt["receipt_sha256"]): receipt
        for receipt in receipts
        if _valid_sha256(receipt.get("receipt_sha256")) is not None
    }

    roots: set[str] = set()
    root_receipt_by_source_label: dict[str, str] = {}
    if (
        len(ordered_feature_source_labels)
        == len(feature_source_receipt_sha256s)
        == len(source_availability_mask)
    ):
        for source_label, binding, available in zip(
            ordered_feature_source_labels,
            feature_source_receipt_sha256s,
            source_availability_mask,
            strict=True,
        ):
            if not isinstance(source_label, str):
                continue
            if binding is None:
                if available == 1:
                    reasons.append("PRESENT_FEATURE_SOURCE_RECEIPT_MISSING")
                continue
            if _valid_sha256(binding) is None:
                reasons.append("FEATURE_SOURCE_RECEIPT_SHA256_INVALID")
                continue
            root = receipt_by_sha.get(binding)
            if root is None:
                reasons.append("FEATURE_SOURCE_RECEIPT_UNRESOLVED")
                continue
            roots.add(binding)
            prior_binding = root_receipt_by_source_label.setdefault(
                source_label, binding
            )
            if prior_binding != binding:
                reasons.append("FEATURE_SOURCE_LABEL_ROOT_RECEIPT_MISMATCH")
            if root.get("source_label") != source_label:
                reasons.append("FEATURE_SOURCE_RECEIPT_LABEL_MISMATCH")

    adjacency: dict[str, list[str]] = {receipt_sha: [] for receipt_sha in receipt_by_sha}
    for parent_sha, parent in receipt_by_sha.items():
        if parent.get("receipt_kind") != "COMPOSITE_DERIVATION":
            continue
        for edge in parent.get("child_read_bindings") or []:
            if not isinstance(edge, Mapping):
                continue
            child_sha = edge.get("receipt_sha256")
            if not isinstance(child_sha, str):
                continue
            child = receipt_by_sha.get(child_sha)
            if child is None:
                reasons.append("COMPOSITE_CHILD_RECEIPT_MISSING")
                continue
            adjacency[parent_sha].append(child_sha)
            for clock_field in (
                "event_time",
                "available_at",
                "consumer_observed_at",
                "feature_cutoff",
            ):
                child_clock = _strict_utc(child.get(clock_field))
                parent_clock = _strict_utc(parent.get(clock_field))
                if (
                    child_clock is not None
                    and parent_clock is not None
                    and child_clock > parent_clock
                ):
                    reasons.append(
                        f"COMPOSITE_CHILD_{clock_field.upper()}_AFTER_PARENT"
                    )
            child_finality = child.get("finality_evidence")
            parent_finality = parent.get("finality_evidence")
            if isinstance(child_finality, Mapping) and isinstance(
                parent_finality, Mapping
            ):
                child_finality_verified_at = _strict_utc(
                    child_finality.get("finality_verified_at")
                )
                parent_finality_verified_at = _strict_utc(
                    parent_finality.get("finality_verified_at")
                )
                if (
                    child_finality_verified_at is not None
                    and parent_finality_verified_at is not None
                    and child_finality_verified_at > parent_finality_verified_at
                ):
                    reasons.append(
                        "COMPOSITE_CHILD_FINALITY_VERIFIED_AT_AFTER_PARENT"
                    )
                parent_available_at = _strict_utc(parent.get("available_at"))
                if (
                    child_finality_verified_at is not None
                    and parent_available_at is not None
                    and child_finality_verified_at > parent_available_at
                ):
                    reasons.append(
                        "COMPOSITE_CHILD_FINALITY_VERIFIED_AT_AFTER_PARENT_AVAILABLE_AT"
                    )
            child_observed_at = _strict_utc(child.get("consumer_observed_at"))
            parent_available_at = _strict_utc(parent.get("available_at"))
            if (
                child_observed_at is not None
                and parent_available_at is not None
                and child_observed_at > parent_available_at
            ):
                reasons.append(
                    "COMPOSITE_CHILD_CONSUMER_OBSERVED_AT_AFTER_PARENT_AVAILABLE_AT"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(receipt_sha: str) -> None:
        if receipt_sha in visiting:
            reasons.append("SOURCE_RECEIPT_GRAPH_CYCLE")
            return
        if receipt_sha in visited:
            return
        visiting.add(receipt_sha)
        for child_sha in adjacency.get(receipt_sha, []):
            visit(child_sha)
        visiting.remove(receipt_sha)
        visited.add(receipt_sha)

    for root_sha in roots:
        visit(root_sha)
    if set(receipt_by_sha) - visited:
        reasons.append("SOURCE_RECEIPT_GRAPH_UNREACHABLE")
    return reasons


def validate_feature_snapshot_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return normalized DB index material for one record."""

    reasons: list[str] = []
    try:
        canonical_record_json = canonical_json(record)
    except FeatureSnapshotValidationError as exc:
        reasons.extend(exc.reasons)
        canonical_record_json = ""
    if set(record) != _RECORD_FIELDS:
        reasons.append("RECORD_FIELD_SET_MISMATCH")
    if record.get("schema_version") != RECORD_SCHEMA_VERSION:
        reasons.append("RECORD_SCHEMA_VERSION_MISMATCH")
    envelope = record.get("frozen_envelope")
    if not isinstance(envelope, Mapping):
        reasons.append("FROZEN_ENVELOPE_NOT_OBJECT")
        envelope = {}
    if set(envelope) != _ENVELOPE_FIELDS:
        reasons.append("FROZEN_ENVELOPE_FIELD_SET_MISMATCH")
    if envelope.get("schema_version") != FROZEN_ENVELOPE_SCHEMA_VERSION:
        reasons.append("FROZEN_ENVELOPE_SCHEMA_VERSION_MISMATCH")

    provenance = envelope.get("provenance_classification")
    if provenance not in {PROVENANCE_CANONICAL_V3, PROVENANCE_LEGACY_V1_IMPORT}:
        reasons.append("PROVENANCE_CLASSIFICATION_INVALID")
    legacy_id = envelope.get("legacy_v1_snapshot_id")
    if provenance == PROVENANCE_LEGACY_V1_IMPORT:
        if _strict_string(legacy_id, pattern=_LABEL_RE) is None:
            reasons.append("LEGACY_V1_SNAPSHOT_ID_REQUIRED")
    elif legacy_id is not None:
        reasons.append("CANONICAL_V3_HAS_LEGACY_V1_SNAPSHOT_ID")

    symbol = _strict_string(envelope.get("symbol"), pattern=_SYMBOL_RE)
    if symbol is None:
        reasons.append("SYMBOL_INVALID")
    timeframe = _strict_string(envelope.get("timeframe"), pattern=_TIMEFRAME_RE)
    if timeframe is None:
        reasons.append("TIMEFRAME_INVALID")
    original_tensor_id = _strict_string(envelope.get("original_tensor_id"), pattern=_LABEL_RE)
    if original_tensor_id is None:
        reasons.append("ORIGINAL_TENSOR_ID_INVALID")
    feature_snapshot_id = _strict_string(
        envelope.get("feature_snapshot_id"), pattern=_LABEL_RE
    )
    if feature_snapshot_id is None:
        reasons.append("FEATURE_SNAPSHOT_ID_INVALID")

    temporal_raw = envelope.get("temporal_rejection_reasons")
    temporal_rejections = temporal_raw if isinstance(temporal_raw, list) else []
    if not isinstance(temporal_raw, list):
        reasons.append("TEMPORAL_REJECTION_REASONS_NOT_LIST")
    elif len(temporal_rejections) > MAX_FEATURE_SLOTS:
        reasons.append("TEMPORAL_REJECTION_REASON_COUNT_EXCEEDED")
    elif any(_strict_string(reason, pattern=_LABEL_RE) is None for reason in temporal_rejections):
        reasons.append("TEMPORAL_REJECTION_REASON_INVALID")
    elif temporal_rejections != sorted(set(temporal_rejections)):
        reasons.append("TEMPORAL_REJECTION_REASONS_NOT_CANONICAL")

    names_raw = envelope.get("ordered_feature_names")
    names = names_raw if isinstance(names_raw, list) else []
    if not names or len(names) > MAX_FEATURE_SLOTS:
        reasons.append("FEATURE_SLOT_COUNT_INVALID")
    elif any(_strict_string(name, pattern=_LABEL_RE) is None for name in names):
        reasons.append("FEATURE_NAME_INVALID")
    elif len(set(names)) != len(names):
        reasons.append("FEATURE_NAMES_NOT_UNIQUE")
    values_raw = envelope.get("feature_values")
    values = values_raw if isinstance(values_raw, list) else []
    if len(values) != len(names):
        reasons.append("FEATURE_VALUES_DIMENSION_MISMATCH")
    else:
        canonical_values = [_canonical_float32(value) for value in values]
        if any(value is None for value in canonical_values):
            reasons.append("FEATURE_VALUES_NOT_FINITE_FLOAT32")
        elif any(
            not isinstance(value, float)
            or value != canonical
            or (value == 0.0 and math.copysign(1.0, value) < 0.0)
            for value, canonical in zip(values, canonical_values, strict=True)
        ):
            reasons.append("FEATURE_VALUES_NOT_CANONICAL_FLOAT32")
    masks: dict[str, list[int]] = {}
    for field in ("missing_mask", "stale_mask"):
        try:
            masks[field] = _binary_vector(
                envelope.get(field), expected=len(names), reason=field.upper()
            )
        except FeatureSnapshotValidationError as exc:
            reasons.extend(exc.reasons)
    missing = masks.get("missing_mask", [])
    stale = masks.get("stale_mask", [])
    if len(values) == len(missing) and any(
        missing_flag == 1 and value != 0.0
        for value, missing_flag in zip(values, missing, strict=True)
    ):
        reasons.append("MISSING_FEATURE_VALUE_NOT_ZERO")

    source_labels_raw = envelope.get("ordered_feature_source_labels")
    source_labels = source_labels_raw if isinstance(source_labels_raw, list) else []
    if len(source_labels) != len(names):
        reasons.append("ORDERED_FEATURE_SOURCE_LABELS_DIMENSION_MISMATCH")
    elif any(
        _strict_string(source_label, pattern=_LABEL_RE) is None
        for source_label in source_labels
    ):
        reasons.append("SOURCE_LABEL_INVALID")
    try:
        availability = _binary_vector(
            envelope.get("source_availability_mask"),
            expected=len(names),
            reason="SOURCE_AVAILABILITY_MASK",
        )
    except FeatureSnapshotValidationError as exc:
        reasons.extend(exc.reasons)
        availability = []
    if len(availability) == len(missing) and any(
        available != 1 - missing_flag
        for available, missing_flag in zip(availability, missing, strict=True)
    ):
        reasons.append("SOURCE_AVAILABILITY_MISSING_MASK_MISMATCH")

    bindings_raw = envelope.get("feature_source_receipt_sha256s")
    feature_bindings = bindings_raw if isinstance(bindings_raw, list) else []
    if len(feature_bindings) != len(names):
        reasons.append("FEATURE_SOURCE_RECEIPT_SHA256S_DIMENSION_MISMATCH")
    elif any(
        binding is not None and _valid_sha256(binding) is None
        for binding in feature_bindings
    ):
        reasons.append("FEATURE_SOURCE_RECEIPT_SHA256_INVALID")

    abi_raw = envelope.get("feature_abi")
    abi = abi_raw if isinstance(abi_raw, Mapping) else {}
    policy_id = _strict_string(abi.get("feature_requirement_policy_id"), pattern=_LABEL_RE)
    if policy_id is None:
        reasons.append("FEATURE_REQUIREMENT_POLICY_ID_INVALID")
        policy_id = ""
    requirements_raw = abi.get("ordered_feature_requirement_classes")
    requirement_classes = requirements_raw if isinstance(requirements_raw, list) else []
    if len(requirement_classes) != len(names):
        reasons.append("FEATURE_REQUIREMENT_CLASSES_DIMENSION_MISMATCH")
    elif any(
        requirement not in _FEATURE_REQUIREMENT_CLASSES
        for requirement in requirement_classes
    ):
        reasons.append("FEATURE_REQUIREMENT_CLASS_INVALID")
    expected_abi = feature_abi_contract(
        names,
        feature_requirement_policy_id=policy_id,
        ordered_feature_requirement_classes=requirement_classes,
    )
    if envelope.get("feature_abi") != expected_abi:
        reasons.append("FEATURE_ABI_CONTRACT_MISMATCH")
    expected_abi_sha256 = stable_sha256(expected_abi)
    if envelope.get("feature_abi_sha256") != expected_abi_sha256:
        reasons.append("FEATURE_ABI_SHA256_MISMATCH")
    try:
        expected_bindings_sha256 = _feature_source_bindings_sha256(
            ordered_feature_names=names,
            ordered_feature_source_labels=source_labels,
            feature_source_receipt_sha256s=feature_bindings,
        )
    except FeatureSnapshotValidationError as exc:
        reasons.extend(exc.reasons)
        expected_bindings_sha256 = None
    if envelope.get("feature_source_bindings_sha256") != expected_bindings_sha256:
        reasons.append("FEATURE_SOURCE_BINDINGS_SHA256_MISMATCH")
    if (
        len(values)
        == len(missing)
        == len(stale)
        == len(availability)
        == len(names)
        and _valid_sha256(expected_abi_sha256) is not None
    ):
        expected_model_vector_sha256 = _model_vector_sha256(
            feature_abi_sha256_value=expected_abi_sha256,
            feature_values=values,
            missing_mask=missing,
            stale_mask=stale,
            source_availability_mask=availability,
        )
        if envelope.get("model_vector_sha256") != expected_model_vector_sha256:
            reasons.append("MODEL_VECTOR_SHA256_MISMATCH")

    expected_ineligibility_reasons = (
        _strict_training_ineligibility_reasons(
            provenance_classification=str(provenance),
            missing_mask=missing,
            stale_mask=stale,
            feature_source_receipt_sha256s=feature_bindings,
            ordered_feature_requirement_classes=requirement_classes,
            temporal_rejection_reasons=temporal_rejections,
        )
        if len(missing)
        == len(stale)
        == len(feature_bindings)
        == len(requirement_classes)
        == len(names)
        else []
    )
    if envelope.get("strict_training_ineligibility_reasons") != (expected_ineligibility_reasons):
        reasons.append("STRICT_TRAINING_INELIGIBILITY_REASONS_MISMATCH")
    if envelope.get("strict_training_eligible") is not (not expected_ineligibility_reasons):
        reasons.append("STRICT_TRAINING_ELIGIBILITY_MISMATCH")

    receipts_raw = envelope.get("source_read_receipts")
    receipts = receipts_raw if isinstance(receipts_raw, list) else []
    if len(receipts) > MAX_SOURCE_RECEIPTS:
        reasons.append("SOURCE_RECEIPT_COUNT_EXCEEDED")
    receipt_mappings: list[Mapping[str, Any]] = []
    for raw_receipt in receipts:
        if not isinstance(raw_receipt, Mapping):
            reasons.append("SOURCE_RECEIPT_NOT_OBJECT")
            continue
        try:
            _source_receipt_reasons(raw_receipt)
        except FeatureSnapshotValidationError as exc:
            reasons.extend(exc.reasons)
        receipt_mappings.append(raw_receipt)
    reasons.extend(
        _source_receipt_graph_reasons(
            receipts=receipt_mappings,
            ordered_feature_source_labels=source_labels,
            feature_source_receipt_sha256s=feature_bindings,
            source_availability_mask=availability,
        )
    )

    lineage = envelope.get("source_lineage_material")
    if not isinstance(lineage, Mapping) or not lineage:
        reasons.append("SOURCE_LINEAGE_MATERIAL_INVALID")
    else:
        try:
            lineage_hash = stable_sha256(lineage)
        except FeatureSnapshotValidationError as exc:
            reasons.extend(exc.reasons)
        else:
            if envelope.get("source_lineage_sha256") != lineage_hash:
                reasons.append("SOURCE_LINEAGE_SHA256_MISMATCH")
        receipt_sha256s = [receipt.get("receipt_sha256") for receipt in receipt_mappings]
        lineage_expected = {
            "feature_abi_sha256": expected_abi_sha256,
            "ordered_feature_source_labels": source_labels,
            "source_availability_mask": availability,
            "feature_source_receipt_sha256s": feature_bindings,
            "feature_source_bindings_sha256": expected_bindings_sha256,
            "source_read_receipt_sha256s": receipt_sha256s,
            "source_receipt_graph_sha256": stable_sha256(
                {
                    "schema_version": "feature_source_receipt_graph_v1",
                    "feature_root_receipt_sha256s": feature_bindings,
                    "receipt_sha256s": receipt_sha256s,
                }
            ),
            "model_vector_sha256": envelope.get("model_vector_sha256"),
        }
        if any(lineage.get(key) != value for key, value in lineage_expected.items()):
            reasons.append("SOURCE_LINEAGE_RESERVED_BINDING_MISMATCH")

    clocks: dict[str, datetime] = {}
    for field in (
        "feature_cutoff",
        "masa_feature_cutoff",
        "ppo_feature_cutoff",
        "tensor_decision_time",
        "ppo_decision_time",
    ):
        parsed = _strict_utc(envelope.get(field))
        if parsed is None:
            reasons.append(f"{field.upper()}_INVALID")
        elif envelope.get(field) != parsed.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ):
            reasons.append(f"{field.upper()}_NOT_CANONICAL")
        else:
            clocks[field] = parsed
    generated = envelope.get("generated_at")
    parsed_generated = _strict_utc(generated)
    if parsed_generated is None:
        reasons.append("GENERATED_AT_INVALID")
    elif generated != parsed_generated.isoformat(timespec="microseconds").replace("+00:00", "Z"):
        reasons.append("GENERATED_AT_NOT_CANONICAL")
    else:
        clocks["generated_at"] = parsed_generated
    if all(field in clocks for field in ("feature_cutoff", "ppo_feature_cutoff")):
        if clocks["feature_cutoff"] > clocks["ppo_feature_cutoff"]:
            reasons.append("FEATURE_CUTOFF_AFTER_PPO_FEATURE_CUTOFF")
    if all(
        field in clocks
        for field in (
            "masa_feature_cutoff",
            "ppo_feature_cutoff",
            "tensor_decision_time",
            "ppo_decision_time",
        )
    ):
        if clocks["masa_feature_cutoff"] > clocks["ppo_feature_cutoff"]:
            reasons.append("MASA_FEATURE_CUTOFF_AFTER_PPO_FEATURE_CUTOFF")
        if clocks["ppo_feature_cutoff"] > clocks["tensor_decision_time"]:
            reasons.append("PPO_FEATURE_CUTOFF_AFTER_TENSOR_DECISION_TIME")
        if clocks["tensor_decision_time"] > clocks["ppo_decision_time"]:
            reasons.append("TENSOR_DECISION_TIME_AFTER_PPO_DECISION_TIME")
    if "feature_cutoff" in clocks and "tensor_decision_time" in clocks:
        if clocks["feature_cutoff"] > clocks["tensor_decision_time"]:
            reasons.append("FEATURE_CUTOFF_AFTER_TENSOR_DECISION_TIME")
    if "generated_at" in clocks and "tensor_decision_time" in clocks:
        if clocks["generated_at"] > clocks["tensor_decision_time"]:
            reasons.append("GENERATED_AT_AFTER_TENSOR_DECISION_TIME")
    if "generated_at" in clocks:
        for cutoff_field in (
            "feature_cutoff",
            "masa_feature_cutoff",
            "ppo_feature_cutoff",
        ):
            if cutoff_field in clocks and clocks["generated_at"] < clocks[cutoff_field]:
                reasons.append(f"GENERATED_AT_BEFORE_{cutoff_field.upper()}")

    decision = clocks.get("tensor_decision_time")
    global_feature_cutoff = clocks.get("feature_cutoff")
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        receipt_clocks = {
            field: _strict_utc(receipt.get(field))
            for field in ("event_time", "available_at", "consumer_observed_at", "feature_cutoff")
        }
        if decision is not None:
            for field, parsed in receipt_clocks.items():
                if parsed is not None and parsed > decision:
                    reasons.append(f"SOURCE_{field.upper()}_AFTER_TENSOR_DECISION_TIME")
        if (
            global_feature_cutoff is not None
            and receipt_clocks["feature_cutoff"] is not None
            and receipt_clocks["feature_cutoff"] > global_feature_cutoff
        ):
            reasons.append("SOURCE_FEATURE_CUTOFF_AFTER_GLOBAL_FEATURE_CUTOFF")
        generated_at = clocks.get("generated_at")
        if generated_at is not None:
            available_at = receipt_clocks["available_at"]
            consumer_observed_at = receipt_clocks["consumer_observed_at"]
            if available_at is not None and generated_at < available_at:
                reasons.append("GENERATED_AT_BEFORE_SOURCE_AVAILABLE_AT")
            if consumer_observed_at is not None and generated_at < consumer_observed_at:
                reasons.append("GENERATED_AT_BEFORE_SOURCE_CONSUMER_OBSERVED_AT")

    if not reasons:
        envelope_hash = stable_sha256(envelope)
        if record.get("frozen_envelope_sha256") != envelope_hash:
            reasons.append("FROZEN_ENVELOPE_SHA256_MISMATCH")
        durable_id = record.get("durable_snapshot_id")
        expected_id = f"feature_snapshot_v3_{envelope_hash}"
        if (
            durable_id != expected_id
            or not isinstance(durable_id, str)
            or _DURABLE_ID_RE.fullmatch(durable_id) is None
        ):
            reasons.append("DURABLE_SNAPSHOT_ID_MISMATCH")
        material_without_record_hash = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if record.get("record_sha256") != stable_sha256(material_without_record_hash):
            reasons.append("RECORD_SHA256_MISMATCH")

    record_bytes = len(canonical_record_json.encode("utf-8"))
    if record_bytes > MAX_RECORD_BYTES:
        reasons.append("RECORD_BYTES_EXCEEDED")
    if reasons:
        raise FeatureSnapshotValidationError(reasons)
    assert symbol is not None
    assert timeframe is not None
    assert original_tensor_id is not None
    assert feature_snapshot_id is not None
    assert provenance in {PROVENANCE_CANONICAL_V3, PROVENANCE_LEGACY_V1_IMPORT}
    return {
        "record": dict(record),
        "record_json": canonical_record_json,
        "record_bytes": record_bytes,
        "durable_snapshot_id": str(record["durable_snapshot_id"]),
        "record_sha256": str(record["record_sha256"]),
        "frozen_envelope_sha256": str(record["frozen_envelope_sha256"]),
        "provenance_classification": str(provenance),
        "legacy_v1_snapshot_id": legacy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "original_tensor_id": original_tensor_id,
        "feature_abi_sha256": str(envelope["feature_abi_sha256"]),
        "source_lineage_sha256": str(envelope["source_lineage_sha256"]),
        "feature_cutoff_us": _epoch_us(envelope["feature_cutoff"]),
        "masa_feature_cutoff_us": _epoch_us(envelope["masa_feature_cutoff"]),
        "ppo_feature_cutoff_us": _epoch_us(envelope["ppo_feature_cutoff"]),
        "ppo_decision_time_us": _epoch_us(envelope["ppo_decision_time"]),
        "strict_training_eligible": int(bool(envelope["strict_training_eligible"])),
    }


def _schema_manifest_sha256() -> str:
    return stable_sha256(_SCHEMA_MANIFEST)


def _sqlite_schema_sha256(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return stable_sha256(
        [
            {
                "type": str(row["type"]),
                "name": str(row["name"]),
                "table_name": str(row["tbl_name"]),
                "sql": str(row["sql"]),
            }
            for row in rows
        ]
    )


def _parse_canonical_json_object(
    value: Any,
    *,
    reason: str,
    max_bytes: int = MAX_APPEND_BYTES,
) -> dict[str, Any]:
    if not isinstance(value, str):
        raise FeatureSnapshotReadbackError(f"{reason}:not_text")
    try:
        encoded_bytes = _bounded_utf8_byte_count(value, maximum=max_bytes)
    except UnicodeError as exc:
        raise FeatureSnapshotReadbackError(f"{reason}:invalid_utf8") from exc
    if encoded_bytes > max_bytes:
        raise FeatureSnapshotReadbackError(f"{reason}:bytes_exceeded")
    if type(value) is not str:
        raise FeatureSnapshotReadbackError(f"{reason}:not_exact_text")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FeatureSnapshotReadbackError(f"{reason}:invalid_json") from exc
    if not isinstance(parsed, dict):
        raise FeatureSnapshotReadbackError(f"{reason}:not_object")
    try:
        canonical = canonical_json(parsed)
    except FeatureSnapshotValidationError as exc:
        raise FeatureSnapshotReadbackError(f"{reason}:not_strict_json") from exc
    if canonical != value:
        raise FeatureSnapshotReadbackError(f"{reason}:not_canonical_json")
    return parsed


def _record_chain_sha256(
    *,
    sequence: int,
    durable_snapshot_id: str,
    record_sha256: str,
    previous_chain_sha256: str,
    append_transaction_id: str,
) -> str:
    return stable_sha256(
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "sequence": sequence,
            "durable_snapshot_id": durable_snapshot_id,
            "record_sha256": record_sha256,
            "previous_chain_sha256": previous_chain_sha256,
            "append_transaction_id": append_transaction_id,
        }
    )


def _identity_material(validated: Mapping[str, Any]) -> dict[str, str]:
    return {
        "durable_snapshot_id": str(validated["durable_snapshot_id"]),
        "record_sha256": str(validated["record_sha256"]),
        "original_tensor_id": str(validated["original_tensor_id"]),
    }


class DurableFeatureSnapshotLedger:
    """Immutable SQLite ledger and bounded point-in-time reader."""

    def __init__(
        self,
        path: Path,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        self.path = _lexical_absolute_path(path)
        self._writer_lease = writer_lease
        if writer_lease is not None:
            FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)

    @contextmanager
    def writer_lease(
        self,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> Iterator[FeatureSnapshotWriterLease]:
        held = writer_lease if writer_lease is not None else self._writer_lease
        acquired_here = held is None
        if held is None:
            held = FeatureSnapshotWriterLease.acquire(self.path)
        try:
            FeatureSnapshotWriterLease.require_exact(held, self.path)
            yield held
            FeatureSnapshotWriterLease.require_exact(held, self.path)
        finally:
            if acquired_here:
                held.release()

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")

    def _preflight_write_target(self) -> None:
        """Classify a write target using only its immutable main-file checkpoint.

        This probe is deliberately separate from operational reads.  It may
        admit a pristine main file only when no WAL artifacts exist; it never
        opens a normal WAL-aware connection or mutates foreign sidecars.
        """

        _preflight_storage_artifacts(self.path, require_main=False)
        try:
            os.lstat(self.path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_ledger_preflight_lstat_failed"
            ) from exc
        guard = _FeatureSnapshotReadPathGuard.acquire(self.path)
        connection: _StorageGuardedSQLiteConnection | None = None
        try:
            guard.validate()
            sidecars_before_probe = _observed_wal_sidecar_roles(self.path)
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro&immutable=1",
                uri=True,
                timeout=60.0,
                factory=_StorageGuardedSQLiteConnection,
            )
            guard.validate()
            self._configure_connection(connection)
            connection.execute("PRAGMA query_only=ON")
            guard.validate()
            if _observed_wal_sidecar_roles(self.path) != sidecars_before_probe:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_wal_sidecar_set_changed_during_immutable_probe"
                )
            objects = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE sql IS NOT NULL
                  AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if objects is None:
                if sidecars_before_probe:
                    raise FeatureSnapshotLedgerError(
                        "feature_snapshot_checkpoint_provenance_unattested"
                    )
                application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if application_id != 0 or user_version != 0:
                    raise FeatureSnapshotLedgerError(
                        "feature_snapshot_ledger_partial_or_foreign_schema"
                    )
                return
            metadata = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'feature_snapshot_ledger_metadata'
                """
            ).fetchone()
            if metadata is None:
                if sidecars_before_probe:
                    raise FeatureSnapshotLedgerError(
                        "feature_snapshot_checkpoint_provenance_unattested"
                    )
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_ledger_partial_or_foreign_schema"
                )
            self._validate_schema(connection)
        except sqlite3.Error as exc:
            raise FeatureSnapshotLedgerError(
                "feature_snapshot_ledger_readonly_preflight_failed"
            ) from exc
        finally:
            close_error: BaseException | None = None
            if connection is not None:
                try:
                    connection.close()
                except BaseException as exc:
                    close_error = exc
            try:
                guard.validate()
            finally:
                guard.release()
            if close_error is not None:
                raise close_error

    def _open_readonly_connection(
        self,
        *,
        query_only: bool,
    ) -> _StorageGuardedSQLiteConnection:
        guard = _FeatureSnapshotReadPathGuard.acquire(self.path)
        connection: _StorageGuardedSQLiteConnection | None = None
        guard_bound_to_connection = False
        try:
            guard.validate()
            sidecars_before_probe = _observed_wal_sidecar_roles(self.path)
            # ``immutable=1`` reads only the already-checkpointed main inode and
            # never opens or creates WAL/SHM.  A normal WAL-aware read is not
            # permitted until that immutable main file independently proves it
            # is one of our fully initialized canonical ledgers.
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro&immutable=1",
                uri=True,
                timeout=60.0,
                factory=_StorageGuardedSQLiteConnection,
            )
            guard.validate()
            self._configure_connection(connection)
            if query_only:
                connection.execute("PRAGMA query_only=ON")
            guard.validate()
            sidecars_after_probe = _observed_wal_sidecar_roles(self.path)
            if sidecars_after_probe != sidecars_before_probe:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_wal_sidecar_set_changed_during_immutable_probe"
                )
            try:
                self._validate_schema(connection)
            except (FeatureSnapshotLedgerError, sqlite3.Error) as exc:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_checkpoint_provenance_unattested"
                ) from exc
            connection.close()
            connection = None
            guard.validate()
            if _observed_wal_sidecar_roles(self.path) != sidecars_before_probe:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_wal_sidecar_set_changed_after_immutable_probe"
                )

            # The immutable handle is attestation-only.  Operational reads must
            # use normal SQLite locking/snapshot semantics so a transaction
            # begun later observes every commit completed before that BEGIN.
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro",
                uri=True,
                timeout=60.0,
                factory=_StorageGuardedSQLiteConnection,
            )
            connection.bind_read_guard(guard)
            guard_bound_to_connection = True
            guard.validate()
            self._configure_connection(connection)
            if query_only:
                connection.execute("PRAGMA query_only=ON")
            guard.validate()
            return connection
        except BaseException:
            try:
                if connection is not None:
                    try:
                        connection.close()
                    except BaseException:  # noqa: S110 - preserve primary failure
                        pass
            finally:
                if not guard_bound_to_connection:
                    try:
                        guard.release()
                    except BaseException:  # noqa: S110 - preserve primary failure
                        pass
            raise

    def _connect_write(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
        initialize: bool = False,
    ) -> sqlite3.Connection:
        held = FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        if initialize:
            _validate_existing_parent_components(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _validate_existing_parent_components(self.path)
            held.bind_ledger_inode_for_write(self.path)
        else:
            FeatureSnapshotWriterLease.require_exact(held, self.path)
            if held._ledger_file_descriptor < 0:
                raise FeatureSnapshotLedgerError("feature_snapshot_ledger_missing")
        _preflight_storage_artifacts(self.path, require_main=True)
        self._preflight_write_target()
        FeatureSnapshotWriterLease.require_exact(held, self.path)
        connection: _StorageGuardedSQLiteConnection | None = None
        try:
            connection = sqlite3.connect(
                str(self.path),
                timeout=60.0,
                factory=_StorageGuardedSQLiteConnection,
            )
            connection.bind_writer_lease(held)
            FeatureSnapshotWriterLease.require_exact(held, self.path)
            self._configure_connection(connection)
            mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
            if mode != "wal":
                raise FeatureSnapshotLedgerError("feature_snapshot_ledger_wal_required")
            connection.execute("PRAGMA synchronous=FULL")
            if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_ledger_synchronous_full_required"
                )
            FeatureSnapshotWriterLease.require_exact(held, self.path)
            return connection
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    def _connect_readonly(self) -> sqlite3.Connection:
        return self._open_readonly_connection(query_only=True)

    def initialize(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        with self.writer_lease(writer_lease) as held:
            self._initialize_locked(writer_lease=held)

    def _initialize_locked(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> None:
        connection = self._connect_write(writer_lease=writer_lease, initialize=True)
        try:
            metadata_table = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'feature_snapshot_ledger_metadata'
                """
            ).fetchone()
            if metadata_table is not None:
                self._validate_schema(connection)
                FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
                return
            unexpected_objects = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE sql IS NOT NULL
                  AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if unexpected_objects is not None:
                raise FeatureSnapshotLedgerError(
                    "feature_snapshot_ledger_partial_or_foreign_schema"
                )
            connection.executescript(
                f"""
                BEGIN IMMEDIATE;
                PRAGMA application_id={_SQLITE_APPLICATION_ID};
                PRAGMA user_version={_SQLITE_USER_VERSION};

                CREATE TABLE IF NOT EXISTS feature_snapshot_append_receipts (
                    transaction_id TEXT PRIMARY KEY,
                    batch_sha256 TEXT NOT NULL,
                    attempted_rows INTEGER NOT NULL,
                    inserted_rows INTEGER NOT NULL,
                    duplicate_rows INTEGER NOT NULL,
                    receipt_sha256 TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    commit_prepared_at TEXT NOT NULL,
                    precommit_readback_verified INTEGER NOT NULL
                        CHECK(precommit_readback_verified = 1)
                ) STRICT;

                CREATE TABLE IF NOT EXISTS feature_snapshot_records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    durable_snapshot_id TEXT NOT NULL UNIQUE,
                    original_tensor_id TEXT NOT NULL UNIQUE,
                    legacy_v1_snapshot_id TEXT UNIQUE,
                    provenance_classification TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    feature_abi_sha256 TEXT NOT NULL,
                    source_lineage_sha256 TEXT NOT NULL,
                    feature_cutoff_us INTEGER NOT NULL,
                    masa_feature_cutoff_us INTEGER NOT NULL,
                    ppo_feature_cutoff_us INTEGER NOT NULL,
                    ppo_decision_time_us INTEGER NOT NULL,
                    strict_training_eligible INTEGER NOT NULL
                        CHECK(strict_training_eligible IN (0, 1)),
                    frozen_envelope_sha256 TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL,
                    previous_chain_sha256 TEXT NOT NULL,
                    record_chain_sha256 TEXT NOT NULL UNIQUE,
                    append_transaction_id TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    FOREIGN KEY(append_transaction_id)
                        REFERENCES feature_snapshot_append_receipts(transaction_id)
                        DEFERRABLE INITIALLY DEFERRED
                ) STRICT;

                CREATE INDEX IF NOT EXISTS feature_snapshot_fixed_cutoff_index
                    ON feature_snapshot_records(
                        strict_training_eligible,
                        ppo_decision_time_us,
                        sequence
                    );
                CREATE INDEX IF NOT EXISTS feature_snapshot_fixed_sequence_index
                    ON feature_snapshot_records(
                        strict_training_eligible,
                        sequence,
                        ppo_decision_time_us
                    );
                CREATE INDEX IF NOT EXISTS feature_snapshot_symbol_timeframe_index
                    ON feature_snapshot_records(
                        symbol,
                        timeframe,
                        ppo_decision_time_us,
                        sequence
                    );
                CREATE INDEX IF NOT EXISTS feature_snapshot_append_transaction_index
                    ON feature_snapshot_records(append_transaction_id, sequence);

                CREATE TABLE IF NOT EXISTS feature_snapshot_projection_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    durable_snapshot_id TEXT NOT NULL UNIQUE,
                    append_transaction_id TEXT NOT NULL,
                    projection_sha256 TEXT NOT NULL UNIQUE,
                    projection_json TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    FOREIGN KEY(durable_snapshot_id)
                        REFERENCES feature_snapshot_records(durable_snapshot_id),
                    FOREIGN KEY(append_transaction_id)
                        REFERENCES feature_snapshot_append_receipts(transaction_id)
                        DEFERRABLE INITIALLY DEFERRED
                ) STRICT;
                CREATE INDEX IF NOT EXISTS feature_snapshot_projection_transaction_index
                    ON feature_snapshot_projection_outbox(
                        append_transaction_id, durable_snapshot_id
                    );

                CREATE TABLE IF NOT EXISTS feature_snapshot_postcommit_receipts (
                    transaction_id TEXT PRIMARY KEY,
                    head_sequence INTEGER NOT NULL UNIQUE,
                    append_receipt_sha256 TEXT NOT NULL UNIQUE,
                    readback_receipt_sha256 TEXT NOT NULL UNIQUE,
                    readback_receipt_json TEXT NOT NULL,
                    postcommit_readback_at TEXT NOT NULL,
                    postcommit_readback_at_us INTEGER NOT NULL,
                    FOREIGN KEY(transaction_id)
                        REFERENCES feature_snapshot_append_receipts(transaction_id),
                    FOREIGN KEY(head_sequence)
                        REFERENCES feature_snapshot_ledger_heads(head_sequence)
                ) STRICT;

                CREATE INDEX IF NOT EXISTS feature_snapshot_postcommit_cutoff_index
                    ON feature_snapshot_postcommit_receipts(
                        postcommit_readback_at_us,
                        transaction_id
                    );

                CREATE TABLE IF NOT EXISTS feature_snapshot_ledger_heads (
                    head_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL UNIQUE,
                    total_unique_rows INTEGER NOT NULL,
                    archive_chain_sha256 TEXT NOT NULL,
                    head_sha256 TEXT NOT NULL UNIQUE,
                    head_json TEXT NOT NULL,
                    commit_prepared_at TEXT NOT NULL,
                    FOREIGN KEY(transaction_id)
                        REFERENCES feature_snapshot_append_receipts(transaction_id)
                        DEFERRABLE INITIALLY DEFERRED
                ) STRICT;

                CREATE TABLE IF NOT EXISTS feature_snapshot_ledger_metadata (
                    metadata_key TEXT PRIMARY KEY,
                    metadata_value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                ) STRICT;

                CREATE TRIGGER IF NOT EXISTS feature_snapshot_records_no_update
                BEFORE UPDATE ON feature_snapshot_records
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_records_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_records_no_delete
                BEFORE DELETE ON feature_snapshot_records
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_records_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_append_receipts_no_update
                BEFORE UPDATE ON feature_snapshot_append_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_append_receipts_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_append_receipts_no_delete
                BEFORE DELETE ON feature_snapshot_append_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_append_receipts_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_postcommit_receipts_no_update
                BEFORE UPDATE ON feature_snapshot_postcommit_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_postcommit_receipts_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_postcommit_receipts_no_delete
                BEFORE DELETE ON feature_snapshot_postcommit_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_postcommit_receipts_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_projection_outbox_no_update
                BEFORE UPDATE ON feature_snapshot_projection_outbox
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_projection_outbox_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_projection_outbox_no_delete
                BEFORE DELETE ON feature_snapshot_projection_outbox
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_projection_outbox_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_ledger_heads_no_update
                BEFORE UPDATE ON feature_snapshot_ledger_heads
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_ledger_heads_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_ledger_heads_no_delete
                BEFORE DELETE ON feature_snapshot_ledger_heads
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_ledger_heads_are_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_ledger_metadata_no_update
                BEFORE UPDATE ON feature_snapshot_ledger_metadata
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_ledger_metadata_is_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS feature_snapshot_ledger_metadata_no_delete
                BEFORE DELETE ON feature_snapshot_ledger_metadata
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_ledger_metadata_is_immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS feature_snapshot_record_bytes_bounded
                BEFORE INSERT ON feature_snapshot_records
                WHEN length(CAST(NEW.record_json AS BLOB)) > {MAX_RECORD_BYTES}
                BEGIN
                    SELECT RAISE(ABORT, 'feature_snapshot_record_bytes_exceeded');
                END;
                """
            )
            metadata_created_at = utc_now()
            metadata = {
                "ledger_schema_version": LEDGER_SCHEMA_VERSION,
                "schema_manifest_sha256": _schema_manifest_sha256(),
                "sqlite_schema_sha256": _sqlite_schema_sha256(connection),
                "genesis_chain_sha256": _GENESIS_CHAIN_SHA256,
                "retention_policy": RETENTION_POLICY,
                "automatic_pruning_enabled": "false",
                "legacy_v1_training_eligibility": "permanently_false",
            }
            for key, value in metadata.items():
                connection.execute(
                    """
                    INSERT OR IGNORE INTO feature_snapshot_ledger_metadata(
                        metadata_key, metadata_value, created_at
                    ) VALUES (?, ?, ?)
                    """,
                    (key, value, metadata_created_at),
                )
            connection.commit()
            self._validate_schema(connection)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        if int(connection.execute("PRAGMA application_id").fetchone()[0]) != _SQLITE_APPLICATION_ID:
            raise FeatureSnapshotLedgerError("ledger_application_id_mismatch")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != _SQLITE_USER_VERSION:
            raise FeatureSnapshotLedgerError("ledger_user_version_mismatch")
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            raise FeatureSnapshotLedgerError("ledger_foreign_keys_not_enabled")
        metadata_rows = connection.execute(
            """
            SELECT metadata_key, metadata_value
            FROM feature_snapshot_ledger_metadata
            ORDER BY metadata_key
            """
        ).fetchall()
        actual_metadata = {
            str(row["metadata_key"]): str(row["metadata_value"]) for row in metadata_rows
        }
        expected_metadata = {
            "ledger_schema_version": LEDGER_SCHEMA_VERSION,
            "schema_manifest_sha256": _schema_manifest_sha256(),
            "sqlite_schema_sha256": _sqlite_schema_sha256(connection),
            "genesis_chain_sha256": _GENESIS_CHAIN_SHA256,
            "retention_policy": RETENTION_POLICY,
            "automatic_pruning_enabled": "false",
            "legacy_v1_training_eligibility": "permanently_false",
        }
        if actual_metadata != expected_metadata:
            raise FeatureSnapshotLedgerError("ledger_metadata_contract_mismatch")
        required_objects = {
            "feature_snapshot_append_receipts": "table",
            "feature_snapshot_records": "table",
            "feature_snapshot_projection_outbox": "table",
            "feature_snapshot_postcommit_receipts": "table",
            "feature_snapshot_ledger_heads": "table",
            "feature_snapshot_ledger_metadata": "table",
            "feature_snapshot_records_no_update": "trigger",
            "feature_snapshot_records_no_delete": "trigger",
            "feature_snapshot_append_receipts_no_update": "trigger",
            "feature_snapshot_append_receipts_no_delete": "trigger",
            "feature_snapshot_postcommit_receipts_no_update": "trigger",
            "feature_snapshot_postcommit_receipts_no_delete": "trigger",
            "feature_snapshot_projection_outbox_no_update": "trigger",
            "feature_snapshot_projection_outbox_no_delete": "trigger",
            "feature_snapshot_ledger_heads_no_update": "trigger",
            "feature_snapshot_ledger_heads_no_delete": "trigger",
            "feature_snapshot_ledger_metadata_no_update": "trigger",
            "feature_snapshot_ledger_metadata_no_delete": "trigger",
            "feature_snapshot_record_bytes_bounded": "trigger",
        }
        objects = connection.execute(
            """
            SELECT name, type FROM sqlite_master
            WHERE type IN ('table', 'trigger')
            """
        ).fetchall()
        actual_objects = {
            str(row["name"]): str(row["type"])
            for row in objects
            if str(row["name"]) in required_objects
        }
        if actual_objects != required_objects:
            raise FeatureSnapshotLedgerError("ledger_required_schema_objects_mismatch")

    def _ensure_initialized(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> None:
        self._initialize_locked(writer_lease=writer_lease)

    @staticmethod
    def _latest_head(connection: sqlite3.Connection) -> tuple[int, str]:
        row = connection.execute(
            """
            SELECT total_unique_rows, archive_chain_sha256
            FROM feature_snapshot_ledger_heads
            ORDER BY head_sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return 0, _GENESIS_CHAIN_SHA256
        return int(row["total_unique_rows"]), str(row["archive_chain_sha256"])

    @staticmethod
    def _validated_append_receipt_row(row: sqlite3.Row) -> dict[str, Any]:
        material = _parse_canonical_json_object(
            row["receipt_json"], reason="append_receipt_json_invalid"
        )
        reasons: list[str] = []
        if set(material) != _APPEND_RECEIPT_FIELDS:
            reasons.append("APPEND_RECEIPT_FIELD_SET_MISMATCH")
        if material.get("schema_version") != APPEND_RECEIPT_SCHEMA_VERSION:
            reasons.append("APPEND_RECEIPT_SCHEMA_VERSION_MISMATCH")
        transaction_id = material.get("transaction_id")
        if (
            not isinstance(transaction_id, str)
            or _TRANSACTION_ID_RE.fullmatch(transaction_id) is None
        ):
            reasons.append("APPEND_TRANSACTION_ID_INVALID")
        for field in ("batch_sha256", "archive_chain_sha256"):
            if _valid_sha256(material.get(field)) is None:
                reasons.append(f"APPEND_RECEIPT_{field.upper()}_INVALID")
        for field in (
            "attempted_rows",
            "inserted_rows",
            "duplicate_rows",
            "total_unique_rows",
        ):
            value = material.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reasons.append(f"APPEND_RECEIPT_{field.upper()}_INVALID")
        if (
            isinstance(material.get("attempted_rows"), int)
            and isinstance(material.get("inserted_rows"), int)
            and isinstance(material.get("duplicate_rows"), int)
            and material["attempted_rows"] != material["inserted_rows"] + material["duplicate_rows"]
        ):
            reasons.append("APPEND_RECEIPT_ROW_COUNTS_INCONSISTENT")
        if (
            isinstance(material.get("attempted_rows"), int)
            and material["attempted_rows"] > MAX_APPEND_ROWS
        ):
            reasons.append("APPEND_RECEIPT_ATTEMPTED_ROWS_EXCEEDED")
        if (
            isinstance(material.get("inserted_rows"), int)
            and material["inserted_rows"] > MAX_APPEND_ROWS
        ):
            reasons.append("APPEND_RECEIPT_INSERTED_ROWS_EXCEEDED")
        identity_lists: dict[str, list[Any]] = {}
        for prefix in ("attempted", "inserted", "duplicate"):
            field = f"{prefix}_identities"
            raw = material.get(field)
            if not isinstance(raw, list):
                reasons.append(f"APPEND_RECEIPT_{field.upper()}_INVALID")
                continue
            identity_lists[prefix] = raw
            for identity in raw:
                if not isinstance(identity, Mapping) or set(identity) != {
                    "durable_snapshot_id",
                    "record_sha256",
                    "original_tensor_id",
                }:
                    reasons.append("APPEND_RECEIPT_IDENTITY_INVALID")
                    continue
                if (
                    not isinstance(identity.get("durable_snapshot_id"), str)
                    or _DURABLE_ID_RE.fullmatch(str(identity.get("durable_snapshot_id"))) is None
                ):
                    reasons.append("APPEND_RECEIPT_DURABLE_ID_INVALID")
                if _valid_sha256(identity.get("record_sha256")) is None:
                    reasons.append("APPEND_RECEIPT_RECORD_SHA256_INVALID")
                if _strict_string(identity.get("original_tensor_id"), pattern=_LABEL_RE) is None:
                    reasons.append("APPEND_RECEIPT_ORIGINAL_TENSOR_ID_INVALID")
            expected_hash = stable_sha256(raw)
            if material.get(f"{prefix}_identities_sha256") != expected_hash:
                reasons.append(f"APPEND_RECEIPT_{prefix.upper()}_IDENTITIES_SHA256_MISMATCH")
        for prefix, count_field in (
            ("attempted", "attempted_rows"),
            ("inserted", "inserted_rows"),
            ("duplicate", "duplicate_rows"),
        ):
            if prefix in identity_lists and isinstance(material.get(count_field), int):
                if len(identity_lists[prefix]) != material[count_field]:
                    reasons.append(f"APPEND_RECEIPT_{prefix.upper()}_IDENTITY_COUNT_MISMATCH")
        dispositions = material.get("attempted_dispositions")
        if not isinstance(dispositions, list) or any(
            disposition not in {"INSERTED", "DUPLICATE"} for disposition in dispositions
        ):
            reasons.append("APPEND_RECEIPT_ATTEMPTED_DISPOSITIONS_INVALID")
        elif (
            isinstance(material.get("attempted_rows"), int)
            and len(dispositions) != material["attempted_rows"]
        ):
            reasons.append("APPEND_RECEIPT_ATTEMPTED_DISPOSITION_COUNT_MISMATCH")
        elif all(prefix in identity_lists for prefix in ("attempted", "inserted", "duplicate")):
            inserted_index = 0
            duplicate_index = 0
            for attempted_identity, disposition in zip(
                identity_lists["attempted"], dispositions, strict=True
            ):
                if disposition == "INSERTED":
                    if (
                        inserted_index >= len(identity_lists["inserted"])
                        or identity_lists["inserted"][inserted_index] != attempted_identity
                    ):
                        reasons.append("APPEND_RECEIPT_INSERTED_DISPOSITION_IDENTITY_MISMATCH")
                        break
                    inserted_index += 1
                else:
                    if (
                        duplicate_index >= len(identity_lists["duplicate"])
                        or identity_lists["duplicate"][duplicate_index] != attempted_identity
                    ):
                        reasons.append("APPEND_RECEIPT_DUPLICATE_DISPOSITION_IDENTITY_MISMATCH")
                        break
                    duplicate_index += 1
            if inserted_index != len(identity_lists["inserted"]) or duplicate_index != len(
                identity_lists["duplicate"]
            ):
                reasons.append("APPEND_RECEIPT_DISPOSITIONS_NOT_EXACT_PARTITION")
        if "attempted" in identity_lists:
            batch_sha256 = stable_sha256(
                {
                    "schema_version": "feature_snapshot_append_batch_v3",
                    "attempted_identities": identity_lists["attempted"],
                }
            )
            if material.get("batch_sha256") != batch_sha256:
                reasons.append("APPEND_RECEIPT_BATCH_SHA256_MISMATCH")
            expected_transaction_id = f"feature_snapshot_append_{batch_sha256}"
            if material.get("transaction_id") != expected_transaction_id:
                reasons.append("APPEND_RECEIPT_TRANSACTION_ID_MISMATCH")
        prepared = _strict_utc(material.get("commit_prepared_at"))
        if prepared is None:
            reasons.append("APPEND_RECEIPT_COMMIT_PREPARED_AT_INVALID")
        elif material.get("commit_prepared_at") != prepared.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"):
            reasons.append("APPEND_RECEIPT_COMMIT_PREPARED_AT_NOT_CANONICAL")
        if material.get("precommit_readback_verified") is not True:
            reasons.append("APPEND_RECEIPT_PRECOMMIT_READBACK_NOT_VERIFIED")
        receipt_sha256 = stable_sha256(material)
        column_pairs = (
            ("transaction_id", transaction_id),
            ("batch_sha256", material.get("batch_sha256")),
            ("attempted_rows", material.get("attempted_rows")),
            ("inserted_rows", material.get("inserted_rows")),
            ("duplicate_rows", material.get("duplicate_rows")),
            ("receipt_sha256", receipt_sha256),
            ("commit_prepared_at", material.get("commit_prepared_at")),
            ("precommit_readback_verified", 1),
        )
        for column, expected in column_pairs:
            if row[column] != expected:
                reasons.append(f"APPEND_RECEIPT_COLUMN_{column.upper()}_MISMATCH")
        if reasons:
            raise FeatureSnapshotReadbackError(
                "append_receipt_invalid:" + ",".join(sorted(set(reasons)))
            )
        material["receipt_sha256"] = receipt_sha256
        return material

    @staticmethod
    def _validated_projection_row(row: sqlite3.Row) -> dict[str, Any]:
        material = _parse_canonical_json_object(
            row["projection_json"],
            reason="projection_outbox_json_invalid",
            max_bytes=MAX_RECORD_BYTES,
        )
        reasons: list[str] = []
        if set(material) != _PROJECTION_OUTBOX_FIELDS:
            reasons.append("PROJECTION_OUTBOX_FIELD_SET_MISMATCH")
        if material.get("schema_version") != PROJECTION_OUTBOX_SCHEMA_VERSION:
            reasons.append("PROJECTION_OUTBOX_SCHEMA_VERSION_MISMATCH")
        outbox_id = material.get("outbox_id")
        durable_id = material.get("durable_snapshot_id")
        if outbox_id != f"feature_snapshot_projection_{durable_id}":
            reasons.append("PROJECTION_OUTBOX_ID_MISMATCH")
        if not isinstance(durable_id, str) or _DURABLE_ID_RE.fullmatch(durable_id) is None:
            reasons.append("PROJECTION_OUTBOX_DURABLE_ID_INVALID")
        for field in ("record_sha256", "frozen_envelope_sha256"):
            if _valid_sha256(material.get(field)) is None:
                reasons.append(f"PROJECTION_OUTBOX_{field.upper()}_INVALID")
        if _strict_string(material.get("symbol"), pattern=_SYMBOL_RE) is None:
            reasons.append("PROJECTION_OUTBOX_SYMBOL_INVALID")
        if _strict_string(material.get("timeframe"), pattern=_TIMEFRAME_RE) is None:
            reasons.append("PROJECTION_OUTBOX_TIMEFRAME_INVALID")
        if _strict_string(material.get("original_tensor_id"), pattern=_LABEL_RE) is None:
            reasons.append("PROJECTION_OUTBOX_ORIGINAL_TENSOR_ID_INVALID")
        if material.get("provenance_classification") not in {
            PROVENANCE_CANONICAL_V3,
            PROVENANCE_LEGACY_V1_IMPORT,
        }:
            reasons.append("PROJECTION_OUTBOX_PROVENANCE_INVALID")
        if material.get("strict_training_eligible") not in (True, False):
            reasons.append("PROJECTION_OUTBOX_ELIGIBILITY_INVALID")
        if (
            not isinstance(material.get("append_transaction_id"), str)
            or _TRANSACTION_ID_RE.fullmatch(str(material.get("append_transaction_id"))) is None
        ):
            reasons.append("PROJECTION_OUTBOX_TRANSACTION_ID_INVALID")
        prepared = _strict_utc(material.get("prepared_at"))
        if prepared is None:
            reasons.append("PROJECTION_OUTBOX_PREPARED_AT_INVALID")
        projection_sha256 = stable_sha256(material)
        for column, expected in (
            ("outbox_id", outbox_id),
            ("durable_snapshot_id", durable_id),
            ("append_transaction_id", material.get("append_transaction_id")),
            ("projection_sha256", projection_sha256),
            ("prepared_at", material.get("prepared_at")),
        ):
            if row[column] != expected:
                reasons.append(f"PROJECTION_OUTBOX_COLUMN_{column.upper()}_MISMATCH")
        if reasons:
            raise FeatureSnapshotReadbackError(
                "projection_outbox_invalid:" + ",".join(sorted(set(reasons)))
            )
        material["projection_sha256"] = projection_sha256
        return material

    @staticmethod
    def _validated_postcommit_row(row: sqlite3.Row) -> dict[str, Any]:
        material = _parse_canonical_json_object(
            row["readback_receipt_json"], reason="postcommit_receipt_json_invalid"
        )
        reasons: list[str] = []
        if set(material) != _POSTCOMMIT_RECEIPT_FIELDS:
            reasons.append("POSTCOMMIT_RECEIPT_FIELD_SET_MISMATCH")
        if material.get("schema_version") != POSTCOMMIT_RECEIPT_SCHEMA_VERSION:
            reasons.append("POSTCOMMIT_RECEIPT_SCHEMA_VERSION_MISMATCH")
        if (
            not isinstance(material.get("transaction_id"), str)
            or _TRANSACTION_ID_RE.fullmatch(str(material.get("transaction_id"))) is None
        ):
            reasons.append("POSTCOMMIT_TRANSACTION_ID_INVALID")
        head_sequence = material.get("head_sequence")
        if (
            isinstance(head_sequence, bool)
            or not isinstance(head_sequence, int)
            or head_sequence <= 0
        ):
            reasons.append("POSTCOMMIT_HEAD_SEQUENCE_INVALID")
        for field in (
            "append_receipt_sha256",
            "inserted_identities_sha256",
            "projection_outbox_sha256",
        ):
            if _valid_sha256(material.get(field)) is None:
                reasons.append(f"POSTCOMMIT_{field.upper()}_INVALID")
        for field in ("inserted_rows", "projection_outbox_rows"):
            value = material.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reasons.append(f"POSTCOMMIT_{field.upper()}_INVALID")
            elif value > MAX_APPEND_ROWS:
                reasons.append(f"POSTCOMMIT_{field.upper()}_EXCEEDED")
        if material.get("inserted_rows") != material.get("projection_outbox_rows"):
            reasons.append("POSTCOMMIT_PROJECTION_COUNT_MISMATCH")
        readback_time = _strict_utc(material.get("postcommit_readback_at"))
        if readback_time is None:
            reasons.append("POSTCOMMIT_READBACK_AT_INVALID")
        elif material.get("postcommit_readback_at") != readback_time.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"):
            reasons.append("POSTCOMMIT_READBACK_AT_NOT_CANONICAL")
        if material.get("postcommit_readback_verified") is not True:
            reasons.append("POSTCOMMIT_READBACK_NOT_VERIFIED")
        receipt_sha256 = stable_sha256(material)
        for column, expected in (
            ("transaction_id", material.get("transaction_id")),
            ("head_sequence", material.get("head_sequence")),
            ("append_receipt_sha256", material.get("append_receipt_sha256")),
            ("readback_receipt_sha256", receipt_sha256),
            ("postcommit_readback_at", material.get("postcommit_readback_at")),
            ("postcommit_readback_at_us", _epoch_us(material.get("postcommit_readback_at"))),
        ):
            if row[column] != expected:
                reasons.append(f"POSTCOMMIT_COLUMN_{column.upper()}_MISMATCH")
        if reasons:
            raise FeatureSnapshotReadbackError(
                "postcommit_receipt_invalid:" + ",".join(sorted(set(reasons)))
            )
        material["readback_receipt_sha256"] = receipt_sha256
        return material

    @staticmethod
    def _validated_head_row(row: sqlite3.Row) -> dict[str, Any]:
        material = _parse_canonical_json_object(row["head_json"], reason="ledger_head_json_invalid")
        reasons: list[str] = []
        if set(material) != _HEAD_FIELDS:
            reasons.append("LEDGER_HEAD_FIELD_SET_MISMATCH")
        if material.get("schema_version") != LEDGER_HEAD_SCHEMA_VERSION:
            reasons.append("LEDGER_HEAD_SCHEMA_VERSION_MISMATCH")
        if (
            not isinstance(material.get("transaction_id"), str)
            or _TRANSACTION_ID_RE.fullmatch(str(material.get("transaction_id"))) is None
        ):
            reasons.append("LEDGER_HEAD_TRANSACTION_ID_INVALID")
        if _valid_sha256(material.get("archive_chain_sha256")) is None:
            reasons.append("LEDGER_HEAD_ARCHIVE_CHAIN_INVALID")
        if _valid_sha256(material.get("append_receipt_sha256")) is None:
            reasons.append("LEDGER_HEAD_APPEND_RECEIPT_SHA256_INVALID")
        total = material.get("total_unique_rows")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            reasons.append("LEDGER_HEAD_TOTAL_ROWS_INVALID")
        if _strict_utc(material.get("commit_prepared_at")) is None:
            reasons.append("LEDGER_HEAD_COMMIT_PREPARED_AT_INVALID")
        head_sha256 = stable_sha256(material)
        for column, expected in (
            ("transaction_id", material.get("transaction_id")),
            ("total_unique_rows", material.get("total_unique_rows")),
            ("archive_chain_sha256", material.get("archive_chain_sha256")),
            ("head_sha256", head_sha256),
            ("commit_prepared_at", material.get("commit_prepared_at")),
        ):
            if row[column] != expected:
                reasons.append(f"LEDGER_HEAD_COLUMN_{column.upper()}_MISMATCH")
        if reasons:
            raise FeatureSnapshotReadbackError(
                "ledger_head_invalid:" + ",".join(sorted(set(reasons)))
            )
        material["head_sha256"] = head_sha256
        return material

    @staticmethod
    def _validated_record_row(row: sqlite3.Row) -> dict[str, Any]:
        record = _parse_canonical_json_object(
            row["record_json"],
            reason="feature_snapshot_record_json_invalid",
            max_bytes=MAX_RECORD_BYTES,
        )
        try:
            validated = validate_feature_snapshot_record(record)
        except FeatureSnapshotValidationError as exc:
            raise FeatureSnapshotReadbackError(str(exc)) from exc
        expected_columns = {
            "durable_snapshot_id": validated["durable_snapshot_id"],
            "original_tensor_id": validated["original_tensor_id"],
            "legacy_v1_snapshot_id": validated["legacy_v1_snapshot_id"],
            "provenance_classification": validated["provenance_classification"],
            "symbol": validated["symbol"],
            "timeframe": validated["timeframe"],
            "feature_abi_sha256": validated["feature_abi_sha256"],
            "source_lineage_sha256": validated["source_lineage_sha256"],
            "feature_cutoff_us": validated["feature_cutoff_us"],
            "masa_feature_cutoff_us": validated["masa_feature_cutoff_us"],
            "ppo_feature_cutoff_us": validated["ppo_feature_cutoff_us"],
            "ppo_decision_time_us": validated["ppo_decision_time_us"],
            "strict_training_eligible": validated["strict_training_eligible"],
            "frozen_envelope_sha256": validated["frozen_envelope_sha256"],
            "record_sha256": validated["record_sha256"],
        }
        mismatches = [
            column for column, expected in expected_columns.items() if row[column] != expected
        ]
        if mismatches:
            raise FeatureSnapshotReadbackError(
                "feature_snapshot_record_column_mismatch:" + ",".join(mismatches)
            )
        return validated

    @staticmethod
    def _bounded_validated_records(
        records: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        validated_rows: list[dict[str, Any]] = []
        total_bytes = 0
        for raw in records:
            if len(validated_rows) >= MAX_APPEND_ROWS:
                raise FeatureSnapshotLedgerError(
                    f"feature_snapshot_append_row_limit_exceeded:{MAX_APPEND_ROWS}"
                )
            if not isinstance(raw, Mapping):
                raise FeatureSnapshotValidationError(["FEATURE_SNAPSHOT_ROW_NOT_OBJECT"])
            validated = validate_feature_snapshot_record(raw)
            total_bytes += int(validated["record_bytes"])
            if total_bytes > MAX_APPEND_BYTES:
                raise FeatureSnapshotLedgerError(
                    f"feature_snapshot_append_bytes_exceeded:{MAX_APPEND_BYTES}"
                )
            validated_rows.append(validated)
        if not validated_rows:
            raise FeatureSnapshotLedgerError("feature_snapshot_append_batch_empty")
        return validated_rows

    def _assert_current_head(self, connection: sqlite3.Connection) -> tuple[int, str]:
        total_rows, chain_sha256 = self._latest_head(connection)
        last_record = connection.execute(
            """
            SELECT sequence, record_chain_sha256
            FROM feature_snapshot_records
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
        actual_last_sequence = int(last_record["sequence"]) if last_record is not None else 0
        if total_rows != actual_last_sequence:
            raise FeatureSnapshotReadbackError("ledger_head_record_sequence_mismatch")
        actual_chain = (
            str(last_record["record_chain_sha256"])
            if last_record is not None
            else _GENESIS_CHAIN_SHA256
        )
        if actual_chain != chain_sha256:
            raise FeatureSnapshotReadbackError("ledger_head_archive_chain_mismatch")
        latest_head = connection.execute(
            """
            SELECT head.transaction_id, head.total_unique_rows,
                   head.archive_chain_sha256, head.head_sha256,
                   head.head_json, head.commit_prepared_at,
                   receipt.batch_sha256, receipt.attempted_rows,
                   receipt.inserted_rows, receipt.duplicate_rows,
                   receipt.receipt_sha256, receipt.receipt_json,
                   receipt.precommit_readback_verified
            FROM feature_snapshot_ledger_heads AS head
            JOIN feature_snapshot_append_receipts AS receipt
              ON receipt.transaction_id = head.transaction_id
            ORDER BY head.head_sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if latest_head is None:
            if total_rows != 0 or chain_sha256 != _GENESIS_CHAIN_SHA256:
                raise FeatureSnapshotReadbackError("ledger_nonempty_state_without_head")
        else:
            head = self._validated_head_row(latest_head)
            receipt = self._validated_append_receipt_row(latest_head)
            if (
                head["append_receipt_sha256"] != receipt["receipt_sha256"]
                or head["total_unique_rows"] != total_rows
                or head["archive_chain_sha256"] != chain_sha256
            ):
                raise FeatureSnapshotReadbackError("ledger_latest_head_receipt_mismatch")
        return total_rows, chain_sha256

    def append_snapshots(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> FeatureSnapshotAppendResult:
        validated_rows = self._bounded_validated_records(records)
        with self.writer_lease(writer_lease) as held:
            self._ensure_initialized(writer_lease=held)
            self._recover_pending_postcommit_readbacks_locked(
                max_transactions=MAX_RECOVERY_TRANSACTIONS,
                writer_lease=held,
            )
            return self._append_snapshots_locked(validated_rows, writer_lease=held)

    def append_snapshot(
        self,
        record: Mapping[str, Any],
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> FeatureSnapshotAppendResult:
        return self.append_snapshots([record], writer_lease=writer_lease)

    def _append_snapshots_locked(
        self,
        validated_rows: Sequence[Mapping[str, Any]],
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> FeatureSnapshotAppendResult:
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        attempted_identities = [_identity_material(row) for row in validated_rows]
        batch_material = {
            "schema_version": "feature_snapshot_append_batch_v3",
            "attempted_identities": attempted_identities,
        }
        batch_sha256 = stable_sha256(batch_material)
        transaction_id = f"feature_snapshot_append_{batch_sha256}"
        connection = self._connect_write(writer_lease=writer_lease)
        existing_transaction = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            total_before, previous_chain = self._assert_current_head(connection)
            existing_receipt_row = connection.execute(
                """
                SELECT transaction_id, batch_sha256, attempted_rows,
                       inserted_rows, duplicate_rows, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM feature_snapshot_append_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if existing_receipt_row is not None:
                existing = self._validated_append_receipt_row(existing_receipt_row)
                if (
                    existing["batch_sha256"] != batch_sha256
                    or existing["attempted_identities"] != attempted_identities
                ):
                    raise FeatureSnapshotIdentityConflictError([transaction_id])
                connection.commit()
                existing_transaction = True
            else:
                commit_prepared_at = utc_now()
                commit_prepared_at_us = _epoch_us(commit_prepared_at)
                if commit_prepared_at_us is None:
                    raise FeatureSnapshotLedgerError("ledger_commit_prepared_at_invalid")
                prior_commit_row = connection.execute(
                    """
                    SELECT commit_prepared_at
                    FROM feature_snapshot_ledger_heads
                    ORDER BY head_sequence DESC
                    LIMIT 1
                    """
                ).fetchone()
                if prior_commit_row is not None:
                    prior_commit_us = _epoch_us(prior_commit_row["commit_prepared_at"])
                    if prior_commit_us is None or commit_prepared_at_us < prior_commit_us:
                        raise FeatureSnapshotLedgerError("ledger_commit_clock_moved_backwards")
                future_decision_ids = [
                    str(validated["durable_snapshot_id"])
                    for validated in validated_rows
                    if int(validated["ppo_decision_time_us"]) > commit_prepared_at_us
                ]
                if future_decision_ids:
                    raise FeatureSnapshotValidationError(
                        ["PPO_DECISION_TIME_AFTER_LEDGER_COMMIT_PREPARATION"]
                    )
                inserted: list[dict[str, Any]] = []
                duplicates: list[dict[str, Any]] = []
                dispositions: list[str] = []
                conflicts: list[str] = []
                seen_durable: dict[str, str] = {}
                seen_original: dict[str, str] = {}
                seen_legacy: dict[str, str] = {}
                for validated in validated_rows:
                    durable_id = str(validated["durable_snapshot_id"])
                    record_sha256 = str(validated["record_sha256"])
                    original_tensor_id = str(validated["original_tensor_id"])
                    legacy_id = validated["legacy_v1_snapshot_id"]
                    prior_durable = seen_durable.get(durable_id)
                    prior_original = seen_original.get(original_tensor_id)
                    prior_legacy = (
                        seen_legacy.get(str(legacy_id)) if legacy_id is not None else None
                    )
                    if prior_durable is not None:
                        if prior_durable != record_sha256:
                            conflicts.append(f"durable_snapshot_id:{durable_id}")
                        else:
                            duplicates.append(_identity_material(validated))
                            dispositions.append("DUPLICATE")
                        continue
                    if prior_original is not None and prior_original != durable_id:
                        conflicts.append(f"original_tensor_id:{original_tensor_id}")
                        continue
                    if prior_legacy is not None and prior_legacy != durable_id:
                        conflicts.append(f"legacy_v1_snapshot_id:{legacy_id}")
                        continue
                    seen_durable[durable_id] = record_sha256
                    seen_original[original_tensor_id] = durable_id
                    if legacy_id is not None:
                        seen_legacy[str(legacy_id)] = durable_id

                    existing_rows = connection.execute(
                        """
                        SELECT durable_snapshot_id, original_tensor_id,
                               legacy_v1_snapshot_id, record_sha256, record_json
                        FROM feature_snapshot_records
                        WHERE durable_snapshot_id = ?
                           OR original_tensor_id = ?
                           OR (? IS NOT NULL AND legacy_v1_snapshot_id = ?)
                        """,
                        (durable_id, original_tensor_id, legacy_id, legacy_id),
                    ).fetchall()
                    if existing_rows:
                        exact = all(
                            str(row["durable_snapshot_id"]) == durable_id
                            and str(row["original_tensor_id"]) == original_tensor_id
                            and row["legacy_v1_snapshot_id"] == legacy_id
                            and str(row["record_sha256"]) == record_sha256
                            and str(row["record_json"]) == validated["record_json"]
                            for row in existing_rows
                        )
                        if exact:
                            duplicates.append(_identity_material(validated))
                            dispositions.append("DUPLICATE")
                        else:
                            conflicts.append(f"immutable_identity:{original_tensor_id}")
                        continue

                    sequence = total_before + len(inserted) + 1
                    record_chain = _record_chain_sha256(
                        sequence=sequence,
                        durable_snapshot_id=durable_id,
                        record_sha256=record_sha256,
                        previous_chain_sha256=previous_chain,
                        append_transaction_id=transaction_id,
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO feature_snapshot_records(
                            durable_snapshot_id, original_tensor_id,
                            legacy_v1_snapshot_id, provenance_classification,
                            symbol, timeframe, feature_abi_sha256,
                            source_lineage_sha256, feature_cutoff_us,
                            masa_feature_cutoff_us, ppo_feature_cutoff_us,
                            ppo_decision_time_us, strict_training_eligible,
                            frozen_envelope_sha256, record_sha256, record_json,
                            previous_chain_sha256, record_chain_sha256,
                            append_transaction_id, archived_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            durable_id,
                            original_tensor_id,
                            legacy_id,
                            validated["provenance_classification"],
                            validated["symbol"],
                            validated["timeframe"],
                            validated["feature_abi_sha256"],
                            validated["source_lineage_sha256"],
                            validated["feature_cutoff_us"],
                            validated["masa_feature_cutoff_us"],
                            validated["ppo_feature_cutoff_us"],
                            validated["ppo_decision_time_us"],
                            validated["strict_training_eligible"],
                            validated["frozen_envelope_sha256"],
                            record_sha256,
                            validated["record_json"],
                            previous_chain,
                            record_chain,
                            transaction_id,
                            commit_prepared_at,
                        ),
                    )
                    if int(cursor.lastrowid or 0) != sequence:
                        raise FeatureSnapshotReadbackError(
                            "feature_snapshot_sequence_not_contiguous"
                        )
                    projection = {
                        "schema_version": PROJECTION_OUTBOX_SCHEMA_VERSION,
                        "outbox_id": f"feature_snapshot_projection_{durable_id}",
                        "durable_snapshot_id": durable_id,
                        "record_sha256": record_sha256,
                        "frozen_envelope_sha256": validated["frozen_envelope_sha256"],
                        "symbol": validated["symbol"],
                        "timeframe": validated["timeframe"],
                        "original_tensor_id": original_tensor_id,
                        "provenance_classification": validated["provenance_classification"],
                        "strict_training_eligible": bool(validated["strict_training_eligible"]),
                        "append_transaction_id": transaction_id,
                        "prepared_at": commit_prepared_at,
                    }
                    projection_json = canonical_json(projection)
                    projection_sha256 = stable_sha256(projection)
                    connection.execute(
                        """
                        INSERT INTO feature_snapshot_projection_outbox(
                            outbox_id, durable_snapshot_id,
                            append_transaction_id, projection_sha256,
                            projection_json, prepared_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            projection["outbox_id"],
                            durable_id,
                            transaction_id,
                            projection_sha256,
                            projection_json,
                            commit_prepared_at,
                        ),
                    )
                    inserted.append(_identity_material(validated))
                    dispositions.append("INSERTED")
                    previous_chain = record_chain

                if conflicts:
                    raise FeatureSnapshotIdentityConflictError(conflicts)
                total_unique_rows = total_before + len(inserted)
                receipt_material = {
                    "schema_version": APPEND_RECEIPT_SCHEMA_VERSION,
                    "transaction_id": transaction_id,
                    "batch_sha256": batch_sha256,
                    "attempted_rows": len(attempted_identities),
                    "inserted_rows": len(inserted),
                    "duplicate_rows": len(duplicates),
                    "attempted_identities": attempted_identities,
                    "inserted_identities": inserted,
                    "duplicate_identities": duplicates,
                    "attempted_dispositions": dispositions,
                    "attempted_identities_sha256": stable_sha256(attempted_identities),
                    "inserted_identities_sha256": stable_sha256(inserted),
                    "duplicate_identities_sha256": stable_sha256(duplicates),
                    "total_unique_rows": total_unique_rows,
                    "archive_chain_sha256": previous_chain,
                    "commit_prepared_at": commit_prepared_at,
                    "precommit_readback_verified": True,
                }
                receipt_json = canonical_json(receipt_material)
                receipt_sha256 = stable_sha256(receipt_material)
                connection.execute(
                    """
                    INSERT INTO feature_snapshot_append_receipts(
                        transaction_id, batch_sha256, attempted_rows,
                        inserted_rows, duplicate_rows, receipt_sha256,
                        receipt_json, commit_prepared_at,
                        precommit_readback_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        transaction_id,
                        batch_sha256,
                        len(attempted_identities),
                        len(inserted),
                        len(duplicates),
                        receipt_sha256,
                        receipt_json,
                        commit_prepared_at,
                    ),
                )
                head_material = {
                    "schema_version": LEDGER_HEAD_SCHEMA_VERSION,
                    "transaction_id": transaction_id,
                    "total_unique_rows": total_unique_rows,
                    "archive_chain_sha256": previous_chain,
                    "append_receipt_sha256": receipt_sha256,
                    "commit_prepared_at": commit_prepared_at,
                }
                head_json = canonical_json(head_material)
                head_sha256 = stable_sha256(head_material)
                connection.execute(
                    """
                    INSERT INTO feature_snapshot_ledger_heads(
                        transaction_id, total_unique_rows,
                        archive_chain_sha256, head_sha256, head_json,
                        commit_prepared_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        total_unique_rows,
                        previous_chain,
                        head_sha256,
                        head_json,
                        commit_prepared_at,
                    ),
                )
                # Exact same-transaction readback before the durability boundary.
                receipt_row = connection.execute(
                    """
                    SELECT transaction_id, batch_sha256, attempted_rows,
                           inserted_rows, duplicate_rows, receipt_sha256,
                           receipt_json, commit_prepared_at,
                           precommit_readback_verified
                    FROM feature_snapshot_append_receipts
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
                if receipt_row is None:
                    raise FeatureSnapshotReadbackError("append_receipt_precommit_readback_missing")
                checked_receipt = self._validated_append_receipt_row(receipt_row)
                if checked_receipt["receipt_sha256"] != receipt_sha256:
                    raise FeatureSnapshotReadbackError("append_receipt_precommit_hash_mismatch")
                inserted_rows = connection.execute(
                    """
                    SELECT durable_snapshot_id, record_sha256
                    FROM feature_snapshot_records
                    WHERE append_transaction_id = ?
                    ORDER BY sequence
                    """,
                    (transaction_id,),
                ).fetchall()
                if [
                    {
                        "durable_snapshot_id": str(row["durable_snapshot_id"]),
                        "record_sha256": str(row["record_sha256"]),
                    }
                    for row in inserted_rows
                ] != [
                    {
                        "durable_snapshot_id": item["durable_snapshot_id"],
                        "record_sha256": item["record_sha256"],
                    }
                    for item in inserted
                ]:
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_precommit_readback_mismatch"
                    )
                outbox_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM feature_snapshot_projection_outbox
                        WHERE append_transaction_id = ?
                        """,
                        (transaction_id,),
                    ).fetchone()[0]
                )
                if outbox_count != len(inserted):
                    raise FeatureSnapshotReadbackError("projection_outbox_precommit_count_mismatch")
                connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        # This deliberately occurs after the first commit and independent reopen.
        # A failure here is a recoverable, fail-closed crash gap.
        self._complete_postcommit_readback(
            transaction_id=transaction_id,
            writer_lease=writer_lease,
        )
        result = self._result_for_transaction(transaction_id)
        if existing_transaction and result.batch_sha256 != batch_sha256:
            raise FeatureSnapshotIdentityConflictError([transaction_id])
        return result

    def _verify_transaction_readback(
        self,
        transaction_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
        if _TRANSACTION_ID_RE.fullmatch(transaction_id) is None:
            raise FeatureSnapshotReadbackError("append_transaction_id_invalid")
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            self._validate_schema(connection)
            receipt_row = connection.execute(
                """
                SELECT transaction_id, batch_sha256, attempted_rows,
                       inserted_rows, duplicate_rows, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM feature_snapshot_append_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if receipt_row is None:
                raise FeatureSnapshotReadbackError("append_receipt_readback_missing")
            receipt = self._validated_append_receipt_row(receipt_row)
            head_row = connection.execute(
                """
                SELECT head_sequence, transaction_id, total_unique_rows,
                       archive_chain_sha256, head_sha256, head_json,
                       commit_prepared_at
                FROM feature_snapshot_ledger_heads
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if head_row is None:
                raise FeatureSnapshotReadbackError("append_ledger_head_missing")
            head = self._validated_head_row(head_row)
            prior_head = connection.execute(
                """
                SELECT total_unique_rows, archive_chain_sha256,
                       commit_prepared_at
                FROM feature_snapshot_ledger_heads
                WHERE head_sequence < ?
                ORDER BY head_sequence DESC
                LIMIT 1
                """,
                (head_row["head_sequence"],),
            ).fetchone()
            prior_total = int(prior_head["total_unique_rows"]) if prior_head is not None else 0
            prior_chain = (
                str(prior_head["archive_chain_sha256"])
                if prior_head is not None
                else _GENESIS_CHAIN_SHA256
            )
            if prior_head is not None:
                prior_prepared = _strict_utc(prior_head["commit_prepared_at"])
                current_prepared = _strict_utc(receipt["commit_prepared_at"])
                if (
                    prior_prepared is None
                    or current_prepared is None
                    or current_prepared < prior_prepared
                ):
                    raise FeatureSnapshotReadbackError(
                        "append_receipt_commit_clock_moved_backwards"
                    )

            record_cursor = connection.execute(
                """
                SELECT sequence, durable_snapshot_id, original_tensor_id,
                       legacy_v1_snapshot_id, provenance_classification,
                       symbol, timeframe, feature_abi_sha256,
                       source_lineage_sha256, feature_cutoff_us,
                       masa_feature_cutoff_us, ppo_feature_cutoff_us,
                       ppo_decision_time_us, strict_training_eligible,
                       frozen_envelope_sha256, record_sha256, record_json,
                       previous_chain_sha256, record_chain_sha256,
                       append_transaction_id, archived_at
                FROM feature_snapshot_records
                WHERE append_transaction_id = ?
                ORDER BY sequence
                """,
                (transaction_id,),
            )
            inserted_identities: list[dict[str, str]] = []
            projection_hashes: list[str] = []
            transaction_record_bytes = 0
            expected_chain = prior_chain
            receipt_commit_us = _epoch_us(receipt["commit_prepared_at"])
            if receipt_commit_us is None:
                raise FeatureSnapshotReadbackError("append_receipt_commit_clock_invalid")
            while True:
                row = record_cursor.fetchone()
                if row is None:
                    break
                if len(inserted_identities) >= MAX_APPEND_ROWS:
                    raise FeatureSnapshotReadbackError("append_transaction_row_limit_exceeded")
                validated = self._validated_record_row(row)
                transaction_record_bytes += int(validated["record_bytes"])
                if transaction_record_bytes > MAX_APPEND_BYTES:
                    raise FeatureSnapshotReadbackError("append_transaction_payload_bytes_exceeded")
                if row["archived_at"] != receipt["commit_prepared_at"]:
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_archived_at_receipt_mismatch"
                    )
                sequence = int(row["sequence"])
                expected_sequence = prior_total + len(inserted_identities) + 1
                if sequence != expected_sequence:
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_transaction_sequence_not_contiguous"
                    )
                previous_chain = str(row["previous_chain_sha256"])
                if previous_chain != expected_chain:
                    raise FeatureSnapshotReadbackError("feature_snapshot_previous_chain_mismatch")
                record_chain = _record_chain_sha256(
                    sequence=sequence,
                    durable_snapshot_id=str(row["durable_snapshot_id"]),
                    record_sha256=str(row["record_sha256"]),
                    previous_chain_sha256=previous_chain,
                    append_transaction_id=transaction_id,
                )
                if row["record_chain_sha256"] != record_chain:
                    raise FeatureSnapshotReadbackError("feature_snapshot_record_chain_mismatch")
                if int(validated["ppo_decision_time_us"]) > receipt_commit_us:
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_decision_after_commit_preparation"
                    )
                identity = _identity_material(validated)
                inserted_identities.append(identity)
                projection_row = connection.execute(
                    """
                    SELECT outbox_id, durable_snapshot_id,
                           append_transaction_id, projection_sha256,
                           projection_json, prepared_at
                    FROM feature_snapshot_projection_outbox
                    WHERE durable_snapshot_id = ?
                    """,
                    (row["durable_snapshot_id"],),
                ).fetchone()
                if projection_row is None:
                    raise FeatureSnapshotReadbackError("feature_snapshot_projection_outbox_missing")
                projection = self._validated_projection_row(projection_row)
                if (
                    projection["record_sha256"] != row["record_sha256"]
                    or projection["frozen_envelope_sha256"] != row["frozen_envelope_sha256"]
                    or projection["append_transaction_id"] != transaction_id
                    or projection["prepared_at"] != receipt["commit_prepared_at"]
                ):
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_projection_binding_mismatch"
                    )
                projection_hashes.append(str(projection["projection_sha256"]))
                expected_chain = record_chain
            if inserted_identities != receipt["inserted_identities"]:
                raise FeatureSnapshotReadbackError(
                    "append_receipt_inserted_identities_readback_mismatch"
                )
            if len(inserted_identities) != receipt["inserted_rows"]:
                raise FeatureSnapshotReadbackError(
                    "append_receipt_inserted_row_count_readback_mismatch"
                )
            for duplicate in receipt["duplicate_identities"]:
                duplicate_row = connection.execute(
                    """
                    SELECT durable_snapshot_id, original_tensor_id,
                           record_sha256
                    FROM feature_snapshot_records
                    WHERE durable_snapshot_id = ?
                    """,
                    (duplicate["durable_snapshot_id"],),
                ).fetchone()
                if (
                    duplicate_row is None
                    or duplicate_row["record_sha256"] != duplicate["record_sha256"]
                    or duplicate_row["original_tensor_id"] != duplicate["original_tensor_id"]
                ):
                    raise FeatureSnapshotReadbackError(
                        "append_receipt_duplicate_identity_not_reproducible"
                    )
            transaction_outbox_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM feature_snapshot_projection_outbox
                    WHERE append_transaction_id = ?
                    """,
                    (transaction_id,),
                ).fetchone()[0]
            )
            if transaction_outbox_count != len(inserted_identities):
                raise FeatureSnapshotReadbackError("append_transaction_projection_count_mismatch")
            if (
                head["append_receipt_sha256"] != receipt["receipt_sha256"]
                or receipt["total_unique_rows"] != prior_total + len(inserted_identities)
                or head["total_unique_rows"] != receipt["total_unique_rows"]
                or head["archive_chain_sha256"] != receipt["archive_chain_sha256"]
                or receipt["archive_chain_sha256"] != expected_chain
                or head["commit_prepared_at"] != receipt["commit_prepared_at"]
            ):
                raise FeatureSnapshotReadbackError("append_ledger_head_binding_mismatch")
            connection.commit()
            return receipt, inserted_identities, projection_hashes
        finally:
            connection.close()

    def _complete_postcommit_readback(
        self,
        *,
        transaction_id: str,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> None:
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        receipt, inserted_identities, projection_hashes = self._verify_transaction_readback(
            transaction_id
        )
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            connection.execute("BEGIN IMMEDIATE")
            head_row = connection.execute(
                """
                SELECT head_sequence
                FROM feature_snapshot_ledger_heads
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if head_row is None:
                raise FeatureSnapshotReadbackError("postcommit_ledger_head_missing")
            head_sequence = int(head_row["head_sequence"])
            existing_row = connection.execute(
                """
                SELECT transaction_id, head_sequence, append_receipt_sha256,
                       readback_receipt_sha256, readback_receipt_json,
                       postcommit_readback_at, postcommit_readback_at_us
                FROM feature_snapshot_postcommit_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if existing_row is None:
                latest_postcommit_sequence = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(head_sequence), 0)
                        FROM feature_snapshot_postcommit_receipts
                        """
                    ).fetchone()[0]
                )
                if latest_postcommit_sequence != head_sequence - 1:
                    raise FeatureSnapshotReadbackError("postcommit_receipt_sequence_gap")
                postcommit_at = utc_now()
                material = {
                    "schema_version": POSTCOMMIT_RECEIPT_SCHEMA_VERSION,
                    "transaction_id": transaction_id,
                    "head_sequence": head_sequence,
                    "append_receipt_sha256": receipt["receipt_sha256"],
                    "inserted_rows": len(inserted_identities),
                    "inserted_identities_sha256": stable_sha256(inserted_identities),
                    "projection_outbox_rows": len(projection_hashes),
                    "projection_outbox_sha256": stable_sha256(projection_hashes),
                    "postcommit_readback_at": postcommit_at,
                    "postcommit_readback_verified": True,
                }
                material_json = canonical_json(material)
                material_sha256 = stable_sha256(material)
                connection.execute(
                    """
                    INSERT INTO feature_snapshot_postcommit_receipts(
                        transaction_id, head_sequence,
                        append_receipt_sha256,
                        readback_receipt_sha256, readback_receipt_json,
                        postcommit_readback_at, postcommit_readback_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        head_sequence,
                        receipt["receipt_sha256"],
                        material_sha256,
                        material_json,
                        postcommit_at,
                        _epoch_us(postcommit_at),
                    ),
                )
                existing_row = connection.execute(
                    """
                    SELECT transaction_id, head_sequence, append_receipt_sha256,
                           readback_receipt_sha256, readback_receipt_json,
                           postcommit_readback_at, postcommit_readback_at_us
                    FROM feature_snapshot_postcommit_receipts
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
            if existing_row is None:
                raise FeatureSnapshotReadbackError("postcommit_receipt_write_readback_missing")
            checked = self._validated_postcommit_row(existing_row)
            if (
                checked["head_sequence"] != head_sequence
                or checked["append_receipt_sha256"] != receipt["receipt_sha256"]
                or checked["inserted_rows"] != len(inserted_identities)
                or checked["inserted_identities_sha256"] != stable_sha256(inserted_identities)
                or checked["projection_outbox_sha256"] != stable_sha256(projection_hashes)
                or int(_epoch_us(checked["postcommit_readback_at"]) or -1)
                < int(_epoch_us(receipt["commit_prepared_at"]) or 0)
            ):
                raise FeatureSnapshotReadbackError(
                    "postcommit_receipt_transaction_binding_mismatch"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        # A second independent reopen proves the postcommit receipt itself.
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            stored = connection.execute(
                """
                SELECT transaction_id, head_sequence, append_receipt_sha256,
                       readback_receipt_sha256, readback_receipt_json,
                       postcommit_readback_at, postcommit_readback_at_us
                FROM feature_snapshot_postcommit_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if stored is None:
                raise FeatureSnapshotReadbackError(
                    "postcommit_receipt_independent_readback_missing"
                )
            independently_checked = self._validated_postcommit_row(stored)
            if independently_checked["head_sequence"] != head_sequence:
                raise FeatureSnapshotReadbackError(
                    "postcommit_receipt_independent_head_sequence_mismatch"
                )
            connection.commit()
        finally:
            connection.close()
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)

    def _result_for_transaction(self, transaction_id: str) -> FeatureSnapshotAppendResult:
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            receipt_row = connection.execute(
                """
                SELECT transaction_id, batch_sha256, attempted_rows,
                       inserted_rows, duplicate_rows, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM feature_snapshot_append_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            post_row = connection.execute(
                """
                SELECT transaction_id, head_sequence, append_receipt_sha256,
                       readback_receipt_sha256, readback_receipt_json,
                       postcommit_readback_at, postcommit_readback_at_us
                FROM feature_snapshot_postcommit_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if receipt_row is None or post_row is None:
                raise FeatureSnapshotReadbackError("append_transaction_not_fully_attested")
            receipt = self._validated_append_receipt_row(receipt_row)
            post = self._validated_postcommit_row(post_row)
            head_row = connection.execute(
                """
                SELECT head_sequence
                FROM feature_snapshot_ledger_heads
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if (
                head_row is None
                or post["head_sequence"] != int(head_row["head_sequence"])
                or post["append_receipt_sha256"] != receipt["receipt_sha256"]
            ):
                raise FeatureSnapshotReadbackError("append_postcommit_receipt_binding_mismatch")
            if int(_epoch_us(post["postcommit_readback_at"]) or -1) < int(
                _epoch_us(receipt["commit_prepared_at"]) or 0
            ):
                raise FeatureSnapshotReadbackError(
                    "append_postcommit_receipt_clock_precedes_commit"
                )
            connection.commit()
            return FeatureSnapshotAppendResult(
                transaction_id=transaction_id,
                batch_sha256=str(receipt["batch_sha256"]),
                attempted_rows=int(receipt["attempted_rows"]),
                inserted_rows=int(receipt["inserted_rows"]),
                duplicate_rows=int(receipt["duplicate_rows"]),
                total_unique_rows=int(receipt["total_unique_rows"]),
                archive_chain_sha256=str(receipt["archive_chain_sha256"]),
                append_receipt_sha256=str(receipt["receipt_sha256"]),
                postcommit_receipt_sha256=str(post["readback_receipt_sha256"]),
                postcommit_readback_at=str(post["postcommit_readback_at"]),
                transaction_committed=True,
                transaction_readback_verified=True,
            )
        finally:
            connection.close()

    def recover_pending_postcommit_readbacks(
        self,
        *,
        max_transactions: int = MAX_RECOVERY_TRANSACTIONS,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "status": "NO_LEDGER_TO_RECOVER",
                "pending_transactions": 0,
                "recovered_transactions": 0,
            }
        with self.writer_lease(writer_lease) as held:
            return self._recover_pending_postcommit_readbacks_locked(
                max_transactions=max_transactions,
                writer_lease=held,
            )

    def _recover_pending_postcommit_readbacks_locked(
        self,
        *,
        max_transactions: int,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> dict[str, Any]:
        if (
            isinstance(max_transactions, bool)
            or not isinstance(max_transactions, int)
            or max_transactions <= 0
            or max_transactions > MAX_RECOVERY_TRANSACTIONS
        ):
            raise FeatureSnapshotLedgerError("postcommit_recovery_transaction_limit_invalid")
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            self._validate_schema(connection)
            latest_postcommit_sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(head_sequence), 0)
                    FROM feature_snapshot_postcommit_receipts
                    """
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT transaction_id, head_sequence
                FROM feature_snapshot_ledger_heads
                WHERE head_sequence > ?
                ORDER BY head_sequence
                LIMIT ?
                """,
                (latest_postcommit_sequence, max_transactions + 1),
            ).fetchall()
            connection.commit()
        finally:
            connection.close()
        if len(rows) > max_transactions:
            raise FeatureSnapshotLedgerError("postcommit_recovery_transaction_limit_exceeded")
        transaction_ids = [str(row["transaction_id"]) for row in rows]
        for transaction_id in transaction_ids:
            self._complete_postcommit_readback(
                transaction_id=transaction_id,
                writer_lease=writer_lease,
            )
        FeatureSnapshotWriterLease.require_exact(writer_lease, self.path)
        return {
            "status": (
                "RECOVERED_PENDING_POSTCOMMIT_READBACKS"
                if transaction_ids
                else "NO_PENDING_POSTCOMMIT_READBACKS"
            ),
            "pending_transactions": len(transaction_ids),
            "recovered_transactions": len(transaction_ids),
            "transaction_ids": transaction_ids,
            "starting_postcommit_head_sequence": latest_postcommit_sequence,
        }

    @staticmethod
    def _validated_limit(value: Any, *, maximum: int, reason: str) -> int:
        if type(value) is not int or value <= 0 or value > maximum:
            raise FeatureSnapshotLedgerError(f"{reason}:{maximum}")
        return value

    @staticmethod
    def _validated_after_sequence(value: Any, *, reason: str) -> int:
        if (
            type(value) is not int
            or value < 0
            or value > 9_223_372_036_854_775_807
        ):
            raise FeatureSnapshotLedgerError(reason)
        return value

    @staticmethod
    def _charge_query_stats(
        stats: sqlite3.Row,
        *,
        budget: _QueryReadBudget,
        maximum_rows: int,
        maximum_single_bytes: int,
        reason: str,
    ) -> int:
        raw_rows = stats["material_rows"]
        raw_bytes = stats["material_bytes"]
        raw_max_bytes = stats["max_material_bytes"]
        if (
            type(raw_rows) is not int
            or type(raw_bytes) is not int
            or type(raw_max_bytes) is not int
        ):
            raise FeatureSnapshotReadbackError(f"{reason}:sql_stats_invalid")
        if raw_rows < 0 or raw_bytes < 0 or raw_max_bytes < 0:
            raise FeatureSnapshotReadbackError(f"{reason}:sql_stats_invalid")
        if raw_rows > maximum_rows:
            raise FeatureSnapshotReadbackError(f"{reason}:row_limit_exceeded")
        if raw_max_bytes > maximum_single_bytes:
            raise FeatureSnapshotLedgerError(
                f"{reason}:bytes_exceeded:{maximum_single_bytes}"
            )
        budget.charge(rows=raw_rows, material_bytes=raw_bytes)
        return raw_rows

    @staticmethod
    def _begin_query_snapshot(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN DEFERRED")
        if not connection.in_transaction:
            raise FeatureSnapshotLedgerError("feature_snapshot_query_transaction_not_active")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        read_uncommitted = connection.execute("PRAGMA read_uncommitted").fetchone()
        if query_only is None or type(query_only[0]) is not int or query_only[0] != 1:
            raise FeatureSnapshotLedgerError("feature_snapshot_query_not_readonly")
        if (
            read_uncommitted is None
            or type(read_uncommitted[0]) is not int
            or read_uncommitted[0] != 0
        ):
            raise FeatureSnapshotLedgerError("feature_snapshot_query_read_uncommitted_forbidden")

    def _load_query_record(
        self,
        connection: sqlite3.Connection,
        *,
        sequence: int,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> _ValidatedQueryRecord:
        cached = cache.records_by_sequence.get(sequence)
        if cached is not None:
            return cached
        stats = connection.execute(
            """
            SELECT COUNT(*) AS material_rows,
                   COALESCE(SUM(
                       48
                       + COALESCE(length(CAST(durable_snapshot_id AS BLOB)), 0)
                       + COALESCE(length(CAST(original_tensor_id AS BLOB)), 0)
                       + COALESCE(length(CAST(legacy_v1_snapshot_id AS BLOB)), 0)
                       + COALESCE(length(CAST(provenance_classification AS BLOB)), 0)
                       + COALESCE(length(CAST(symbol AS BLOB)), 0)
                       + COALESCE(length(CAST(timeframe AS BLOB)), 0)
                       + COALESCE(length(CAST(feature_abi_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(source_lineage_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(frozen_envelope_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(record_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(record_json AS BLOB)), 0)
                       + COALESCE(length(CAST(previous_chain_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(record_chain_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(append_transaction_id AS BLOB)), 0)
                       + COALESCE(length(CAST(archived_at AS BLOB)), 0)
                   ), 0) AS material_bytes,
                   COALESCE(MAX(length(CAST(record_json AS BLOB))), 0)
                       AS max_material_bytes
            FROM feature_snapshot_records
            WHERE sequence = ?
            """,
            (sequence,),
        ).fetchone()
        if stats is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_record_stats_missing")
        material_rows = self._charge_query_stats(
            stats,
            budget=budget,
            maximum_rows=1,
            maximum_single_bytes=MAX_RECORD_BYTES,
            reason="feature_snapshot_query_record_json",
        )
        if material_rows != 1:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_record_missing")
        row = connection.execute(
            """
            SELECT sequence, durable_snapshot_id, original_tensor_id,
                   legacy_v1_snapshot_id, provenance_classification,
                   symbol, timeframe, feature_abi_sha256,
                   source_lineage_sha256, feature_cutoff_us,
                   masa_feature_cutoff_us, ppo_feature_cutoff_us,
                   ppo_decision_time_us, strict_training_eligible,
                   frozen_envelope_sha256, record_sha256, record_json,
                   previous_chain_sha256, record_chain_sha256,
                   append_transaction_id, archived_at
            FROM feature_snapshot_records
            WHERE sequence = ?
            """,
            (sequence,),
        ).fetchone()
        if row is None or type(row["sequence"]) is not int or row["sequence"] != sequence:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_record_reopen_mismatch")
        if (
            type(row["append_transaction_id"]) is not str
            or _TRANSACTION_ID_RE.fullmatch(row["append_transaction_id"]) is None
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_record_transaction_invalid")
        archived_at = _strict_utc(row["archived_at"])
        if archived_at is None or row["archived_at"] != archived_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_record_archived_at_invalid")
        material = _ValidatedQueryRecord(
            row=row,
            validated=self._validated_record_row(row),
        )
        cache.records_by_sequence[sequence] = material
        return material

    def _load_query_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> dict[str, Any]:
        cached = cache.receipts_by_transaction.get(transaction_id)
        if cached is not None:
            return cached
        stats = connection.execute(
            """
            SELECT COUNT(*) AS material_rows,
                   COALESCE(SUM(
                       32
                       + COALESCE(length(CAST(transaction_id AS BLOB)), 0)
                       + COALESCE(length(CAST(batch_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(receipt_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(receipt_json AS BLOB)), 0)
                       + COALESCE(length(CAST(commit_prepared_at AS BLOB)), 0)
                   ), 0) AS material_bytes,
                   COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0)
                       AS max_material_bytes
            FROM feature_snapshot_append_receipts
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if stats is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_receipt_stats_missing")
        if (
            self._charge_query_stats(
                stats,
                budget=budget,
                maximum_rows=1,
                maximum_single_bytes=MAX_APPEND_BYTES,
                reason="feature_snapshot_query_append_receipt_json",
            )
            != 1
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_append_receipt_missing")
        row = connection.execute(
            """
            SELECT transaction_id, batch_sha256, attempted_rows,
                   inserted_rows, duplicate_rows, receipt_sha256,
                   receipt_json, commit_prepared_at,
                   precommit_readback_verified
            FROM feature_snapshot_append_receipts
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_append_receipt_missing")
        receipt = self._validated_append_receipt_row(row)
        cache.receipts_by_transaction[transaction_id] = receipt
        return receipt

    def _load_query_postcommit(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> dict[str, Any]:
        cached = cache.postcommit_by_transaction.get(transaction_id)
        if cached is not None:
            return cached
        stats = connection.execute(
            """
            SELECT COUNT(*) AS material_rows,
                   COALESCE(SUM(
                       16
                       + COALESCE(length(CAST(transaction_id AS BLOB)), 0)
                       + COALESCE(length(CAST(append_receipt_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(readback_receipt_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(readback_receipt_json AS BLOB)), 0)
                       + COALESCE(length(CAST(postcommit_readback_at AS BLOB)), 0)
                   ), 0) AS material_bytes,
                   COALESCE(MAX(length(CAST(readback_receipt_json AS BLOB))), 0)
                       AS max_material_bytes
            FROM feature_snapshot_postcommit_receipts
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if stats is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_postcommit_stats_missing")
        if (
            self._charge_query_stats(
                stats,
                budget=budget,
                maximum_rows=1,
                maximum_single_bytes=MAX_APPEND_BYTES,
                reason="feature_snapshot_query_postcommit_receipt_json",
            )
            != 1
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_postcommit_receipt_missing")
        row = connection.execute(
            """
            SELECT transaction_id, head_sequence, append_receipt_sha256,
                   readback_receipt_sha256, readback_receipt_json,
                   postcommit_readback_at, postcommit_readback_at_us
            FROM feature_snapshot_postcommit_receipts
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_postcommit_receipt_missing")
        postcommit = self._validated_postcommit_row(row)
        cache.postcommit_by_transaction[transaction_id] = postcommit
        return postcommit

    def _load_query_head_by_sequence(
        self,
        connection: sqlite3.Connection,
        *,
        head_sequence: int,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> dict[str, Any]:
        cached = cache.heads_by_sequence.get(head_sequence)
        if cached is not None:
            return cached
        stats = connection.execute(
            """
            SELECT COUNT(*) AS material_rows,
                   COALESCE(SUM(
                       16
                       + COALESCE(length(CAST(transaction_id AS BLOB)), 0)
                       + COALESCE(length(CAST(archive_chain_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(head_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(head_json AS BLOB)), 0)
                       + COALESCE(length(CAST(commit_prepared_at AS BLOB)), 0)
                   ), 0) AS material_bytes,
                   COALESCE(MAX(length(CAST(head_json AS BLOB))), 0)
                       AS max_material_bytes
            FROM feature_snapshot_ledger_heads
            WHERE head_sequence = ?
            """,
            (head_sequence,),
        ).fetchone()
        if stats is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_stats_missing")
        if (
            self._charge_query_stats(
                stats,
                budget=budget,
                maximum_rows=1,
                maximum_single_bytes=MAX_APPEND_BYTES,
                reason="feature_snapshot_query_head_json",
            )
            != 1
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_missing")
        row = connection.execute(
            """
            SELECT head_sequence, transaction_id, total_unique_rows,
                   archive_chain_sha256, head_sha256, head_json,
                   commit_prepared_at
            FROM feature_snapshot_ledger_heads
            WHERE head_sequence = ?
            """,
            (head_sequence,),
        ).fetchone()
        if row is None or type(row["head_sequence"]) is not int:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_missing")
        head = self._validated_head_row(row)
        transaction_id = str(head["transaction_id"])
        cache.heads_by_transaction[transaction_id] = head
        cache.heads_by_sequence[head_sequence] = head
        cache.head_sequences_by_transaction[transaction_id] = head_sequence
        return head

    def _load_query_head_for_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> dict[str, Any]:
        cached = cache.heads_by_transaction.get(transaction_id)
        if cached is not None:
            return cached
        row = connection.execute(
            """
            SELECT head_sequence
            FROM feature_snapshot_ledger_heads
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if row is None or type(row["head_sequence"]) is not int:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_missing")
        head = self._load_query_head_by_sequence(
            connection,
            head_sequence=row["head_sequence"],
            cache=cache,
            budget=budget,
        )
        if head["transaction_id"] != transaction_id:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_reopen_mismatch")
        return head

    def _load_query_projections(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> dict[str, dict[str, Any]]:
        cached = cache.projections_by_transaction.get(transaction_id)
        if cached is not None:
            return cached
        stats = connection.execute(
            """
            SELECT COUNT(*) AS material_rows,
                   COALESCE(SUM(
                       COALESCE(length(CAST(outbox_id AS BLOB)), 0)
                       + COALESCE(length(CAST(durable_snapshot_id AS BLOB)), 0)
                       + COALESCE(length(CAST(append_transaction_id AS BLOB)), 0)
                       + COALESCE(length(CAST(projection_sha256 AS BLOB)), 0)
                       + COALESCE(length(CAST(projection_json AS BLOB)), 0)
                       + COALESCE(length(CAST(prepared_at AS BLOB)), 0)
                   ), 0) AS material_bytes,
                   COALESCE(MAX(length(CAST(projection_json AS BLOB))), 0)
                       AS max_material_bytes
            FROM feature_snapshot_projection_outbox
            WHERE append_transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if stats is None:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_projection_stats_missing")
        projection_count = self._charge_query_stats(
            stats,
            budget=budget,
            maximum_rows=MAX_APPEND_ROWS,
            maximum_single_bytes=MAX_RECORD_BYTES,
            reason="feature_snapshot_query_projection_json",
        )
        rows = connection.execute(
            """
            SELECT projection.outbox_id,
                   projection.durable_snapshot_id,
                   projection.append_transaction_id,
                   projection.projection_sha256,
                   projection.projection_json,
                   projection.prepared_at
            FROM feature_snapshot_projection_outbox AS projection
            JOIN feature_snapshot_records AS record
              ON record.durable_snapshot_id = projection.durable_snapshot_id
            WHERE projection.append_transaction_id = ?
            ORDER BY record.sequence
            LIMIT ?
            """,
            (transaction_id, MAX_APPEND_ROWS + 1),
        ).fetchall()
        if len(rows) != projection_count:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_projection_reopen_mismatch")
        projections: dict[str, dict[str, Any]] = {}
        for row in rows:
            projection = self._validated_projection_row(row)
            durable_id = str(projection["durable_snapshot_id"])
            if durable_id in projections:
                raise FeatureSnapshotReadbackError(
                    "feature_snapshot_query_projection_identity_duplicate"
                )
            projections[durable_id] = projection
        cache.projections_by_transaction[transaction_id] = projections
        return projections

    def _validate_query_record_chain(
        self,
        connection: sqlite3.Connection,
        material: _ValidatedQueryRecord,
    ) -> None:
        row = material.row
        sequence = int(row["sequence"])
        previous_chain = row["previous_chain_sha256"]
        if type(previous_chain) is not str or _valid_sha256(previous_chain) is None:
            raise FeatureSnapshotReadbackError("fixed_cutoff_record_previous_chain_invalid")
        if sequence == 1:
            expected_previous = _GENESIS_CHAIN_SHA256
        else:
            predecessor = connection.execute(
                """
                SELECT record_chain_sha256
                FROM feature_snapshot_records
                WHERE sequence = ?
                  AND typeof(record_chain_sha256) = 'text'
                  AND length(CAST(record_chain_sha256 AS BLOB)) = 64
                """,
                (sequence - 1,),
            ).fetchone()
            if predecessor is None or _valid_sha256(predecessor["record_chain_sha256"]) is None:
                raise FeatureSnapshotReadbackError("fixed_cutoff_record_predecessor_missing")
            expected_previous = str(predecessor["record_chain_sha256"])
        if previous_chain != expected_previous:
            raise FeatureSnapshotReadbackError("fixed_cutoff_record_previous_chain_mismatch")
        expected_chain = _record_chain_sha256(
            sequence=sequence,
            durable_snapshot_id=str(row["durable_snapshot_id"]),
            record_sha256=str(row["record_sha256"]),
            previous_chain_sha256=previous_chain,
            append_transaction_id=str(row["append_transaction_id"]),
        )
        if row["record_chain_sha256"] != expected_chain:
            raise FeatureSnapshotReadbackError("fixed_cutoff_record_chain_mismatch")

    def _attest_query_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> None:
        state = connection.execute(
            """
            SELECT (SELECT COUNT(*) FROM feature_snapshot_records) AS record_rows,
                   (SELECT COALESCE(MIN(sequence), 0)
                      FROM feature_snapshot_records) AS first_sequence,
                   (SELECT COALESCE(MAX(sequence), 0)
                      FROM feature_snapshot_records) AS tail_sequence,
                   (SELECT COUNT(*) FROM feature_snapshot_projection_outbox)
                       AS projection_rows,
                   (SELECT COUNT(*) FROM feature_snapshot_append_receipts)
                       AS receipt_rows,
                   (SELECT COUNT(*) FROM feature_snapshot_ledger_heads) AS head_rows,
                   (SELECT COALESCE(MIN(head_sequence), 0)
                      FROM feature_snapshot_ledger_heads) AS first_head_sequence,
                   (SELECT COALESCE(MAX(head_sequence), 0)
                      FROM feature_snapshot_ledger_heads) AS latest_head_sequence,
                   (SELECT COALESCE(MAX(length(CAST(record_json AS BLOB))), 0)
                      FROM feature_snapshot_records) AS max_record_json_bytes,
                   (SELECT COALESCE(MAX(length(CAST(projection_json AS BLOB))), 0)
                      FROM feature_snapshot_projection_outbox)
                       AS max_projection_json_bytes,
                   (SELECT COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0)
                      FROM feature_snapshot_append_receipts) AS max_receipt_json_bytes,
                   (SELECT COALESCE(MAX(length(CAST(head_json AS BLOB))), 0)
                      FROM feature_snapshot_ledger_heads) AS max_head_json_bytes,
                   (SELECT COALESCE(MAX(length(CAST(readback_receipt_json AS BLOB))), 0)
                      FROM feature_snapshot_postcommit_receipts)
                       AS max_postcommit_json_bytes
            """
        ).fetchone()
        if state is None or any(type(state[field]) is not int for field in state.keys()):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_ledger_state_invalid")
        record_rows = int(state["record_rows"])
        first_sequence = int(state["first_sequence"])
        tail_sequence = int(state["tail_sequence"])
        projection_rows = int(state["projection_rows"])
        receipt_rows = int(state["receipt_rows"])
        head_rows = int(state["head_rows"])
        first_head_sequence = int(state["first_head_sequence"])
        latest_head_sequence = int(state["latest_head_sequence"])
        max_record_json_bytes = int(state["max_record_json_bytes"])
        max_projection_json_bytes = int(state["max_projection_json_bytes"])
        max_receipt_json_bytes = int(state["max_receipt_json_bytes"])
        max_head_json_bytes = int(state["max_head_json_bytes"])
        max_postcommit_json_bytes = int(state["max_postcommit_json_bytes"])
        if min(
            record_rows,
            first_sequence,
            tail_sequence,
            projection_rows,
            receipt_rows,
            head_rows,
            first_head_sequence,
            latest_head_sequence,
            max_record_json_bytes,
            max_projection_json_bytes,
            max_receipt_json_bytes,
            max_head_json_bytes,
            max_postcommit_json_bytes,
        ) < 0:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_ledger_state_invalid")
        if max_record_json_bytes > MAX_RECORD_BYTES:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_query_record_json:bytes_exceeded:{MAX_RECORD_BYTES}"
            )
        if max_projection_json_bytes > MAX_RECORD_BYTES:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_query_projection_json:bytes_exceeded:{MAX_RECORD_BYTES}"
            )
        if max(
            max_receipt_json_bytes,
            max_head_json_bytes,
            max_postcommit_json_bytes,
        ) > MAX_APPEND_BYTES:
            raise FeatureSnapshotLedgerError(
                f"feature_snapshot_query_proof_json:bytes_exceeded:{MAX_APPEND_BYTES}"
            )
        if (record_rows == 0 and first_sequence != 0) or (
            record_rows > 0 and (first_sequence != 1 or record_rows != tail_sequence)
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_tail_sequence_mismatch")
        if projection_rows != record_rows:
            raise FeatureSnapshotReadbackError("feature_snapshot_query_projection_count_mismatch")
        if (
            (head_rows == 0 and first_head_sequence != 0)
            or (
                head_rows > 0
                and (first_head_sequence != 1 or head_rows != latest_head_sequence)
            )
            or receipt_rows != head_rows
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_count_mismatch")
        if head_rows == 0:
            if record_rows != 0 or projection_rows != 0 or receipt_rows != 0:
                raise FeatureSnapshotReadbackError("feature_snapshot_query_state_without_head")
            return
        head = self._load_query_head_by_sequence(
            connection,
            head_sequence=latest_head_sequence,
            cache=cache,
            budget=budget,
        )
        transaction_id = str(head["transaction_id"])
        receipt = self._load_query_receipt(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        tail = self._load_query_record(
            connection,
            sequence=tail_sequence,
            cache=cache,
            budget=budget,
        )
        self._validate_query_record_chain(connection, tail)
        if (
            head["append_receipt_sha256"] != receipt["receipt_sha256"]
            or head["total_unique_rows"] != record_rows
            or receipt["total_unique_rows"] != record_rows
            or head["archive_chain_sha256"] != tail.row["record_chain_sha256"]
            or receipt["archive_chain_sha256"] != head["archive_chain_sha256"]
            or head["commit_prepared_at"] != receipt["commit_prepared_at"]
        ):
            raise FeatureSnapshotReadbackError("feature_snapshot_query_head_tail_mismatch")

    def _load_query_transaction_proof(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> _ValidatedTransactionProof:
        cached = cache.transactions.get(transaction_id)
        if cached is not None:
            return cached
        receipt = self._load_query_receipt(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        postcommit = self._load_query_postcommit(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        head = self._load_query_head_for_transaction(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        projections = self._load_query_projections(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        projection_hashes = [
            str(projection["projection_sha256"]) for projection in projections.values()
        ]
        inserted_identity_keys = frozenset(
            (
                str(identity["durable_snapshot_id"]),
                str(identity["record_sha256"]),
                str(identity["original_tensor_id"]),
            )
            for identity in receipt["inserted_identities"]
        )
        if len(inserted_identity_keys) != len(receipt["inserted_identities"]):
            raise FeatureSnapshotReadbackError(
                "feature_snapshot_query_receipt_identity_duplicate"
            )
        postcommit_us = _epoch_us(postcommit["postcommit_readback_at"])
        prepared_us = _epoch_us(receipt["commit_prepared_at"])
        if (
            postcommit["head_sequence"]
            != cache.head_sequences_by_transaction.get(transaction_id)
            or head["append_receipt_sha256"] != receipt["receipt_sha256"]
            or head["total_unique_rows"] != receipt["total_unique_rows"]
            or head["archive_chain_sha256"] != receipt["archive_chain_sha256"]
            or head["commit_prepared_at"] != receipt["commit_prepared_at"]
            or postcommit["append_receipt_sha256"] != receipt["receipt_sha256"]
            or postcommit["inserted_rows"] != receipt["inserted_rows"]
            or postcommit["inserted_identities_sha256"]
            != receipt["inserted_identities_sha256"]
            or postcommit["projection_outbox_rows"] != len(projection_hashes)
            or postcommit["projection_outbox_sha256"] != stable_sha256(projection_hashes)
            or postcommit_us is None
            or prepared_us is None
            or postcommit_us < prepared_us
        ):
            raise FeatureSnapshotReadbackError("fixed_cutoff_postcommit_binding_mismatch")
        proof = _ValidatedTransactionProof(
            receipt=receipt,
            postcommit=postcommit,
            head=head,
            projections_by_durable_id=projections,
            inserted_identity_keys=inserted_identity_keys,
        )
        cache.transactions[transaction_id] = proof
        return proof

    def _validate_query_evidence(
        self,
        connection: sqlite3.Connection,
        material: _ValidatedQueryRecord,
        *,
        training_observed_at_us: int,
        cache: _QueryProofCache,
        budget: _QueryReadBudget,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        self._validate_query_record_chain(connection, material)
        row = material.row
        validated = material.validated
        transaction_id = str(row["append_transaction_id"])
        proof = self._load_query_transaction_proof(
            connection,
            transaction_id=transaction_id,
            cache=cache,
            budget=budget,
        )
        identity = _identity_material(validated)
        identity_key = (
            identity["durable_snapshot_id"],
            identity["record_sha256"],
            identity["original_tensor_id"],
        )
        if identity_key not in proof.inserted_identity_keys:
            raise FeatureSnapshotReadbackError("fixed_cutoff_record_not_bound_to_append_receipt")
        postcommit_us = _epoch_us(proof.postcommit["postcommit_readback_at"])
        if postcommit_us is None or postcommit_us > training_observed_at_us:
            raise FeatureSnapshotReadbackError("fixed_cutoff_postcommit_after_training_observed_at")
        projection = proof.projections_by_durable_id.get(str(row["durable_snapshot_id"]))
        if projection is None:
            raise FeatureSnapshotReadbackError("fixed_cutoff_projection_missing")
        expected_projection_bindings = {
            "durable_snapshot_id": row["durable_snapshot_id"],
            "record_sha256": row["record_sha256"],
            "frozen_envelope_sha256": row["frozen_envelope_sha256"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "original_tensor_id": row["original_tensor_id"],
            "provenance_classification": row["provenance_classification"],
            "strict_training_eligible": bool(row["strict_training_eligible"]),
            "append_transaction_id": row["append_transaction_id"],
            "prepared_at": proof.receipt["commit_prepared_at"],
        }
        if any(
            projection.get(field) != expected
            for field, expected in expected_projection_bindings.items()
        ):
            raise FeatureSnapshotReadbackError("fixed_cutoff_projection_binding_mismatch")
        return validated, proof.receipt, proof.postcommit, projection

    def query_fixed_cutoff(
        self,
        *,
        decision_time_cutoff: str,
        training_observed_at: str,
        limit: int = MAX_QUERY_ROWS,
        symbol: str | None = None,
        timeframe: str | None = None,
        after_sequence: int = 0,
    ) -> list[FixedCutoffFeatureSnapshot]:
        """Return only fully attested v3 rows observable at a fixed cutoff.

        ``decision_time_cutoff`` bounds every row's PPO decision.  The separate
        ``training_observed_at`` clock bounds the durable postcommit receipt;
        neither clock is inferred from the other.  Pass the last returned
        ``sequence`` as ``after_sequence`` for starvation-free keyset paging.
        """

        bounded_limit = self._validated_limit(
            limit, maximum=MAX_QUERY_ROWS, reason="feature_snapshot_query_row_limit_invalid"
        )
        bounded_after_sequence = self._validated_after_sequence(
            after_sequence,
            reason="feature_snapshot_query_after_sequence_invalid",
        )
        decision_cutoff_us = _epoch_us(decision_time_cutoff)
        observed_us = _epoch_us(training_observed_at)
        if decision_cutoff_us is None:
            raise FeatureSnapshotLedgerError("decision_time_cutoff_invalid")
        if observed_us is None:
            raise FeatureSnapshotLedgerError("training_observed_at_invalid")
        if decision_cutoff_us > observed_us:
            raise FeatureSnapshotLedgerError("decision_time_cutoff_after_training_observed_at")
        if symbol is not None and _strict_string(symbol, pattern=_SYMBOL_RE) is None:
            raise FeatureSnapshotLedgerError("feature_snapshot_query_symbol_invalid")
        if timeframe is not None and _strict_string(timeframe, pattern=_TIMEFRAME_RE) is None:
            raise FeatureSnapshotLedgerError("feature_snapshot_query_timeframe_invalid")
        connection = self._connect_readonly()
        results: list[FixedCutoffFeatureSnapshot] = []
        cache = _QueryProofCache.empty()
        budget = _QueryReadBudget()
        try:
            self._begin_query_snapshot(connection)
            self._validate_schema(connection)
            self._attest_query_snapshot(connection, cache=cache, budget=budget)
            row_cursor = connection.execute(
                """
                SELECT record.sequence
                FROM feature_snapshot_records AS record
                JOIN feature_snapshot_postcommit_receipts AS post
                  ON post.transaction_id = record.append_transaction_id
                WHERE record.strict_training_eligible = 1
                  AND record.sequence > ?
                  AND record.ppo_decision_time_us <= ?
                  AND post.postcommit_readback_at_us <= ?
                  AND (? IS NULL OR record.symbol = ?)
                  AND (? IS NULL OR record.timeframe = ?)
                ORDER BY record.sequence
                LIMIT ?
                """,
                (
                    bounded_after_sequence,
                    decision_cutoff_us,
                    observed_us,
                    symbol,
                    symbol,
                    timeframe,
                    timeframe,
                    bounded_limit,
                ),
            )
            while True:
                sequence_row = row_cursor.fetchone()
                if sequence_row is None:
                    break
                if type(sequence_row["sequence"]) is not int:
                    raise FeatureSnapshotReadbackError(
                        "feature_snapshot_query_sequence_invalid"
                    )
                material = self._load_query_record(
                    connection,
                    sequence=int(sequence_row["sequence"]),
                    cache=cache,
                    budget=budget,
                )
                validated, receipt, post, _projection = self._validate_query_evidence(
                    connection,
                    material,
                    training_observed_at_us=observed_us,
                    cache=cache,
                    budget=budget,
                )
                row = material.row
                envelope = validated["record"]["frozen_envelope"]
                if envelope["provenance_classification"] != PROVENANCE_CANONICAL_V3:
                    raise FeatureSnapshotReadbackError(
                        "legacy_feature_snapshot_entered_strict_query"
                    )
                results.append(
                    FixedCutoffFeatureSnapshot(
                        sequence=int(row["sequence"]),
                        record=dict(validated["record"]),
                        append_transaction_id=str(row["append_transaction_id"]),
                        append_receipt_sha256=str(receipt["receipt_sha256"]),
                        postcommit_receipt_sha256=str(post["readback_receipt_sha256"]),
                        postcommit_readback_at=str(post["postcommit_readback_at"]),
                    )
                )
            connection.rollback()
            return results
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def get_snapshot(self, durable_snapshot_id: str) -> FixedCutoffFeatureSnapshot | None:
        if (
            type(durable_snapshot_id) is not str
            or _DURABLE_ID_RE.fullmatch(durable_snapshot_id) is None
        ):
            raise FeatureSnapshotLedgerError("durable_snapshot_id_invalid")
        connection = self._connect_readonly()
        cache = _QueryProofCache.empty()
        budget = _QueryReadBudget()
        try:
            self._begin_query_snapshot(connection)
            self._validate_schema(connection)
            self._attest_query_snapshot(connection, cache=cache, budget=budget)
            sequence_row = connection.execute(
                """
                SELECT sequence
                FROM feature_snapshot_records
                WHERE durable_snapshot_id = ?
                """,
                (durable_snapshot_id,),
            ).fetchone()
            if sequence_row is None:
                connection.rollback()
                return None
            if type(sequence_row["sequence"]) is not int:
                raise FeatureSnapshotReadbackError("feature_snapshot_query_sequence_invalid")
            material = self._load_query_record(
                connection,
                sequence=int(sequence_row["sequence"]),
                cache=cache,
                budget=budget,
            )
            if material.row["durable_snapshot_id"] != durable_snapshot_id:
                raise FeatureSnapshotReadbackError(
                    "feature_snapshot_query_record_identity_mismatch"
                )
            proof = self._load_query_transaction_proof(
                connection,
                transaction_id=str(material.row["append_transaction_id"]),
                cache=cache,
                budget=budget,
            )
            postcommit_us = _epoch_us(proof.postcommit["postcommit_readback_at"])
            if postcommit_us is None:
                raise FeatureSnapshotReadbackError("snapshot_postcommit_receipt_missing")
            validated, receipt, post, _projection = self._validate_query_evidence(
                connection,
                material,
                training_observed_at_us=postcommit_us,
                cache=cache,
                budget=budget,
            )
            row = material.row
            connection.rollback()
            return FixedCutoffFeatureSnapshot(
                sequence=int(row["sequence"]),
                record=dict(validated["record"]),
                append_transaction_id=str(row["append_transaction_id"]),
                append_receipt_sha256=str(receipt["receipt_sha256"]),
                postcommit_receipt_sha256=str(post["readback_receipt_sha256"]),
                postcommit_readback_at=str(post["postcommit_readback_at"]),
            )
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def query_projection_outbox(
        self,
        *,
        limit: int = MAX_QUERY_ROWS,
        after_sequence: int = 0,
    ) -> list[FeatureSnapshotProjectionOutboxItem]:
        """Return postcommit-attested projections after an immutable cursor."""

        bounded_limit = self._validated_limit(
            limit,
            maximum=MAX_QUERY_ROWS,
            reason="projection_outbox_query_row_limit_invalid",
        )
        bounded_after_sequence = self._validated_after_sequence(
            after_sequence,
            reason="projection_outbox_query_after_sequence_invalid",
        )
        connection = self._connect_readonly()
        output: list[FeatureSnapshotProjectionOutboxItem] = []
        cache = _QueryProofCache.empty()
        budget = _QueryReadBudget()
        try:
            self._begin_query_snapshot(connection)
            self._validate_schema(connection)
            self._attest_query_snapshot(connection, cache=cache, budget=budget)
            row_cursor = connection.execute(
                """
                SELECT record.sequence
                FROM feature_snapshot_projection_outbox AS projection
                JOIN feature_snapshot_records AS record
                  ON record.durable_snapshot_id = projection.durable_snapshot_id
                JOIN feature_snapshot_postcommit_receipts AS post
                  ON post.transaction_id = projection.append_transaction_id
                WHERE record.sequence > ?
                ORDER BY record.sequence
                LIMIT ?
                """,
                (bounded_after_sequence, bounded_limit),
            )
            while True:
                sequence_row = row_cursor.fetchone()
                if sequence_row is None:
                    break
                if type(sequence_row["sequence"]) is not int:
                    raise FeatureSnapshotReadbackError(
                        "projection_outbox_query_sequence_invalid"
                    )
                material = self._load_query_record(
                    connection,
                    sequence=int(sequence_row["sequence"]),
                    cache=cache,
                    budget=budget,
                )
                proof = self._load_query_transaction_proof(
                    connection,
                    transaction_id=str(material.row["append_transaction_id"]),
                    cache=cache,
                    budget=budget,
                )
                postcommit_us = _epoch_us(proof.postcommit["postcommit_readback_at"])
                if postcommit_us is None:
                    raise FeatureSnapshotReadbackError(
                        "projection_outbox_postcommit_clock_invalid"
                    )
                _, receipt, post, projection = self._validate_query_evidence(
                    connection,
                    material,
                    training_observed_at_us=postcommit_us,
                    cache=cache,
                    budget=budget,
                )
                if (
                    projection["append_transaction_id"] != receipt["transaction_id"]
                    or post["postcommit_readback_verified"] is not True
                ):
                    raise FeatureSnapshotReadbackError(
                        "projection_outbox_postcommit_binding_mismatch"
                    )
                output.append(
                    FeatureSnapshotProjectionOutboxItem(
                        sequence=int(material.row["sequence"]),
                        projection=dict(projection),
                        append_receipt_sha256=str(receipt["receipt_sha256"]),
                        postcommit_receipt_sha256=str(post["readback_receipt_sha256"]),
                        postcommit_readback_at=str(post["postcommit_readback_at"]),
                    )
                )
            connection.rollback()
            return output
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def verify_integrity_streaming(
        self,
        *,
        chunk_size: int = 256,
    ) -> FeatureSnapshotIntegrityReport:
        """Stream the full immutable ledger and reproduce every hash binding."""

        bounded_chunk = self._validated_limit(
            chunk_size,
            maximum=MAX_QUERY_ROWS,
            reason="integrity_chunk_size_invalid",
        )
        record_chunk = min(
            bounded_chunk,
            max(1, MAX_QUERY_BYTES // MAX_RECORD_BYTES),
        )
        proof_chunk = min(bounded_chunk, 16)
        connection = self._connect_readonly()
        verified_records = 0
        verified_outbox = 0
        total_record_bytes = 0
        previous_chain = _GENESIS_CHAIN_SHA256
        try:
            connection.execute("BEGIN")
            self._validate_schema(connection)
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]) != "ok":
                raise FeatureSnapshotReadbackError("sqlite_quick_check_failed")
            foreign_key_violation = connection.execute("PRAGMA foreign_key_check").fetchone()
            if foreign_key_violation is not None:
                raise FeatureSnapshotReadbackError("integrity_foreign_key_check_failed")
            record_cursor = connection.execute(
                """
                SELECT sequence, durable_snapshot_id, original_tensor_id,
                       legacy_v1_snapshot_id, provenance_classification,
                       symbol, timeframe, feature_abi_sha256,
                       source_lineage_sha256, feature_cutoff_us,
                       masa_feature_cutoff_us, ppo_feature_cutoff_us,
                       ppo_decision_time_us, strict_training_eligible,
                       frozen_envelope_sha256, record_sha256, record_json,
                       previous_chain_sha256, record_chain_sha256,
                       append_transaction_id, archived_at
                FROM feature_snapshot_records
                ORDER BY sequence
                """
            )
            while True:
                rows = record_cursor.fetchmany(record_chunk)
                if not rows:
                    break
                for row in rows:
                    expected_sequence = verified_records + 1
                    if int(row["sequence"]) != expected_sequence:
                        raise FeatureSnapshotReadbackError(
                            "integrity_record_sequence_not_contiguous"
                        )
                    validated = self._validated_record_row(row)
                    total_record_bytes += int(validated["record_bytes"])
                    if row["previous_chain_sha256"] != previous_chain:
                        raise FeatureSnapshotReadbackError(
                            "integrity_record_previous_chain_mismatch"
                        )
                    expected_chain = _record_chain_sha256(
                        sequence=expected_sequence,
                        durable_snapshot_id=str(row["durable_snapshot_id"]),
                        record_sha256=str(row["record_sha256"]),
                        previous_chain_sha256=previous_chain,
                        append_transaction_id=str(row["append_transaction_id"]),
                    )
                    if row["record_chain_sha256"] != expected_chain:
                        raise FeatureSnapshotReadbackError("integrity_record_chain_mismatch")
                    if _strict_utc(row["archived_at"]) is None:
                        raise FeatureSnapshotReadbackError("integrity_record_archived_at_invalid")
                    projection_row = connection.execute(
                        """
                        SELECT outbox_id, durable_snapshot_id,
                               append_transaction_id, projection_sha256,
                               projection_json, prepared_at
                        FROM feature_snapshot_projection_outbox
                        WHERE durable_snapshot_id = ?
                        """,
                        (row["durable_snapshot_id"],),
                    ).fetchone()
                    if projection_row is None:
                        raise FeatureSnapshotReadbackError("integrity_projection_outbox_missing")
                    projection = self._validated_projection_row(projection_row)
                    if (
                        projection["record_sha256"] != row["record_sha256"]
                        or projection["append_transaction_id"] != row["append_transaction_id"]
                    ):
                        raise FeatureSnapshotReadbackError("integrity_projection_binding_mismatch")
                    previous_chain = expected_chain
                    verified_records += 1
                    verified_outbox += 1

            outbox_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM feature_snapshot_projection_outbox"
                ).fetchone()[0]
            )
            if outbox_count != verified_records:
                raise FeatureSnapshotReadbackError("integrity_projection_outbox_count_mismatch")

            verified_receipts = 0
            verified_postcommit = 0
            receipt_cursor = connection.execute(
                """
                SELECT transaction_id, batch_sha256, attempted_rows,
                       inserted_rows, duplicate_rows, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM feature_snapshot_append_receipts
                ORDER BY rowid
                """
            )
            while True:
                receipt_rows = receipt_cursor.fetchmany(proof_chunk)
                if not receipt_rows:
                    break
                for receipt_row in receipt_rows:
                    receipt = self._validated_append_receipt_row(receipt_row)
                    verified_receipt, identities, projection_hashes = (
                        self._verify_transaction_readback(str(receipt["transaction_id"]))
                    )
                    if verified_receipt["receipt_sha256"] != receipt["receipt_sha256"]:
                        raise FeatureSnapshotReadbackError(
                            "integrity_append_receipt_reopen_mismatch"
                        )
                    if len(identities) > MAX_APPEND_ROWS:
                        raise FeatureSnapshotReadbackError(
                            "integrity_append_transaction_row_bound_exceeded"
                        )
                    post_row = connection.execute(
                        """
                        SELECT transaction_id, head_sequence, append_receipt_sha256,
                               readback_receipt_sha256,
                               readback_receipt_json,
                               postcommit_readback_at,
                               postcommit_readback_at_us
                        FROM feature_snapshot_postcommit_receipts
                        WHERE transaction_id = ?
                        """,
                        (receipt["transaction_id"],),
                    ).fetchone()
                    if post_row is None:
                        raise FeatureSnapshotReadbackError("integrity_postcommit_receipt_missing")
                    post = self._validated_postcommit_row(post_row)
                    if (
                        post["head_sequence"] != verified_receipts + 1
                        or post["append_receipt_sha256"] != receipt["receipt_sha256"]
                        or post["inserted_rows"] != len(identities)
                        or post["inserted_identities_sha256"] != stable_sha256(identities)
                        or post["projection_outbox_sha256"] != stable_sha256(projection_hashes)
                        or int(_epoch_us(post["postcommit_readback_at"]) or -1)
                        < int(_epoch_us(receipt["commit_prepared_at"]) or 0)
                    ):
                        raise FeatureSnapshotReadbackError(
                            "integrity_postcommit_transaction_binding_mismatch"
                        )
                    verified_receipts += 1
                    verified_postcommit += 1

            postcommit_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM feature_snapshot_postcommit_receipts"
                ).fetchone()[0]
            )
            if postcommit_count != verified_receipts:
                raise FeatureSnapshotReadbackError("integrity_postcommit_receipt_count_mismatch")

            expected_head_sequence = 0
            expected_total = 0
            expected_head_chain = _GENESIS_CHAIN_SHA256
            head_cursor = connection.execute(
                """
                SELECT head.head_sequence, head.transaction_id,
                       head.total_unique_rows, head.archive_chain_sha256,
                       head.head_sha256, head.head_json,
                       head.commit_prepared_at,
                       receipt.batch_sha256, receipt.attempted_rows,
                       receipt.inserted_rows, receipt.duplicate_rows,
                       receipt.receipt_sha256, receipt.receipt_json,
                       receipt.precommit_readback_verified
                FROM feature_snapshot_ledger_heads AS head
                JOIN feature_snapshot_append_receipts AS receipt
                  ON receipt.transaction_id = head.transaction_id
                ORDER BY head.head_sequence
                """
            )
            while True:
                head_rows = head_cursor.fetchmany(proof_chunk)
                if not head_rows:
                    break
                for row in head_rows:
                    expected_head_sequence += 1
                    if int(row["head_sequence"]) != expected_head_sequence:
                        raise FeatureSnapshotReadbackError("integrity_head_sequence_not_contiguous")
                    head = self._validated_head_row(row)
                    receipt = self._validated_append_receipt_row(row)
                    expected_total += int(receipt["inserted_rows"])
                    if head["total_unique_rows"] != expected_total:
                        raise FeatureSnapshotReadbackError("integrity_head_total_not_cumulative")
                    if receipt["inserted_rows"]:
                        transaction_tail = connection.execute(
                            """
                            SELECT record_chain_sha256
                            FROM feature_snapshot_records
                            WHERE append_transaction_id = ?
                            ORDER BY sequence DESC
                            LIMIT 1
                            """,
                            (head["transaction_id"],),
                        ).fetchone()
                        if transaction_tail is None:
                            raise FeatureSnapshotReadbackError(
                                "integrity_head_transaction_tail_missing"
                            )
                        expected_head_chain = str(transaction_tail["record_chain_sha256"])
                    if head["archive_chain_sha256"] != expected_head_chain:
                        raise FeatureSnapshotReadbackError(
                            "integrity_head_chain_transition_mismatch"
                        )
                    if head["append_receipt_sha256"] != receipt["receipt_sha256"]:
                        raise FeatureSnapshotReadbackError(
                            "integrity_head_receipt_binding_mismatch"
                        )

            if expected_head_sequence != verified_receipts:
                raise FeatureSnapshotReadbackError("integrity_head_receipt_count_mismatch")
            if expected_total != verified_records:
                raise FeatureSnapshotReadbackError("integrity_head_final_total_mismatch")
            if expected_head_chain != previous_chain:
                raise FeatureSnapshotReadbackError("integrity_head_final_chain_mismatch")
            connection.commit()
            return FeatureSnapshotIntegrityReport(
                schema_version=INTEGRITY_PROOF_SCHEMA_VERSION,
                verified_records=verified_records,
                verified_append_receipts=verified_receipts,
                verified_postcommit_receipts=verified_postcommit,
                verified_projection_outbox_rows=verified_outbox,
                total_record_bytes=total_record_bytes,
                archive_chain_sha256=previous_chain,
                integrity_verified=True,
            )
        finally:
            connection.close()


__all__ = [
    "APPEND_RECEIPT_SCHEMA_VERSION",
    "DurableFeatureSnapshotLedger",
    "FeatureSnapshotAppendResult",
    "FeatureSnapshotIdentityConflictError",
    "FeatureSnapshotIntegrityReport",
    "FeatureSnapshotLedgerError",
    "FeatureSnapshotProjectionOutboxItem",
    "FeatureSnapshotReadbackError",
    "FeatureSnapshotValidationError",
    "FeatureSnapshotWriterLease",
    "FeatureSnapshotWriterLeaseError",
    "FEATURE_ABI_SCHEMA_VERSION",
    "FEATURE_REQUIREMENT_POLICY_ID",
    "FEATURE_SOURCE_BINDING_SCHEMA_VERSION",
    "FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION",
    "FixedCutoffFeatureSnapshot",
    "FROZEN_ENVELOPE_SCHEMA_VERSION",
    "LEGACY_INELIGIBILITY_REASON",
    "LEDGER_SCHEMA_VERSION",
    "MAX_APPEND_BYTES",
    "MAX_APPEND_ROWS",
    "MAX_FEATURE_SLOTS",
    "MAX_QUERY_BYTES",
    "MAX_QUERY_ROWS",
    "MAX_QUERY_SQL_ROWS",
    "MAX_RECORD_BYTES",
    "MAX_SOURCE_RECEIPTS",
    "MISSING_FEATURE_INELIGIBILITY_REASON",
    "OPTIONAL_EVENT_DEPENDENT_FEATURE_NAMES",
    "POSTCOMMIT_RECEIPT_SCHEMA_VERSION",
    "PROVENANCE_CANONICAL_V2",
    "PROVENANCE_CANONICAL_V3",
    "PROVENANCE_LEGACY_V1_IMPORT",
    "RECORD_SCHEMA_VERSION",
    "SOURCE_READ_RECEIPT_SCHEMA_VERSION",
    "SOURCE_READ_EVIDENCE_SCHEMA_VERSION",
    "SOURCE_READ_LOCATOR_SCHEMA_VERSION",
    "SOURCE_FINALITY_EVIDENCE_SCHEMA_VERSION",
    "SOURCE_UNAVAILABLE_INELIGIBILITY_REASON",
    "STALE_FEATURE_INELIGIBILITY_REASON",
    "build_feature_snapshot_record",
    "build_source_read_receipt",
    "canonical_json",
    "default_ledger_path",
    "feature_abi_contract",
    "feature_abi_sha256",
    "feature_requirement_classes_for_names",
    "feature_snapshot_writer_lease_path",
    "stable_sha256",
    "validate_feature_snapshot_record",
]
