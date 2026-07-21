"""Unwired quarantine bridge from the active feature ABI to ledger v3.

The active feature producer does not emit a runtime cycle identifier, immutable
CAS addresses, or an attestation about whether its input was historically
reused.  This module therefore makes none of those claims.  It accepts the
producer's real ``v2_feature_ohlcv_consumer_selection_v1`` shape and separately
requires a factory-authenticated canonical OHLCV capture whose exact selection
fields match the publication.

This boundary records only the safe intersection of those two evidence graphs:

* the exact 446-slot deployed ABI and requirement classes are retained;
* nine raw latest-candle leaves are re-derived from the exact selected row;
* ``ohlcv_close`` and ``ohlcv_volume`` are explicit, receipt-bound identity
  alias transforms rather than being mislabeled as raw leaves;
* every other slot is zero-valued and missing-masked, never inferred or filled;
* the v4 economic, producer, ingestion, source-availability, consumer-read,
  feature-generation, publication, decision, and absent execution clocks stay
  distinct in lineage;
* the resulting canonical v3 row is necessarily training-ineligible, is
  appended with the ledger's postcommit readback, and is then proved absent
  from the fixed-cutoff strict-training query.

The API has no Redis lookup, receipt pointer, archive scan, historical-import
surface, production call site, or downstream authority.  In particular, a
matching capture-publication pair does not prove recency or same-cycle origin.
A later production adapter must add a real cycle/freshness attestation before
using stronger language or replacing any missing mask.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
    CanonicalOhlcvAtomicReceiptCapture,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotAppendResult,
    FeatureSnapshotLedgerError,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
    build_source_read_receipt,
)
from v2.backend.app.services.native_trainer.feature_resolution_plan_v4 import (
    FEATURE_RESOLUTION_PLAN_V4,
    FEATURE_RESOLUTION_PLAN_V4_SHA256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)
from v2.backend.app.services.native_trainer.runtime_feature_publication_receipt import (
    FeaturePublicationReceiptValidationError,
    VerifiedFeaturePublication,
    derive_feature_publication_slot_bindings,
)

RUNTIME_FEATURE_LEDGER_BRIDGE_SCHEMA_VERSION = "runtime_feature_snapshot_ledger_bridge_v1"
RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION = (
    "UNWIRED_ACTIVE_PRODUCER_ABI_CAPTURE_PUBLICATION_BOUND_OHLCV_PARTIAL_"
    "SOURCE_SCOPE_V3_QUARANTINE_NO_CYCLE_OR_HISTORY_ATTESTATION"
)
RUNTIME_FEATURE_LEDGER_BRIDGE_STATUS = (
    "UNWIRED_APPEND_POSTCOMMIT_VERIFIED_STRICT_TRAINING_QUARANTINED"
)
RUNTIME_FEATURE_LEDGER_SOURCE_SCOPE_REASON = "RUNTIME_AUTHENTICATED_SOURCE_SCOPE_INCOMPLETE"
RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS = "NOT_ATTESTED_ACTIVE_PRODUCER_ABI_HAS_NO_CYCLE_ID"
RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS = (
    "NOT_ATTESTED_BY_ACTIVE_PRODUCER_ABI_OR_FACTORY_RESULTS"
)
ACTIVE_OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION = "v2_feature_ohlcv_consumer_selection_v1"

# These nine names are raw leaves of the latest canonical candle.  Derived
# ratios, complements, TA, rolling windows, and cross-source values are
# deliberately excluded until their complete transform/receipt graph is bound.
DIRECT_LATEST_CANDLE_FEATURES = frozenset(
    {
        "quote_volume",
        "volume",
        "open",
        "high",
        "low",
        "close",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)

# TensorBuilder emits these two names through explicit identity aliases.  They
# remain receipt-bound to the same exact latest row, but are not raw leaves.
RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS = (
    ("ohlcv_close", "close", "TENSOR_BUILDER_OHLCV_CLOSE_IDENTITY_ALIAS_V1"),
    ("ohlcv_volume", "volume", "TENSOR_BUILDER_OHLCV_VOLUME_IDENTITY_ALIAS_V1"),
)
_ALIAS_RECEIPT_SOURCE_LABEL_BY_FEATURE = {
    "ohlcv_close": "v2:market:ohlcv:derived:ohlcv_close",
    "ohlcv_volume": "v2:market:ohlcv:derived:ohlcv_volume",
}
_ALIAS_SCALAR_PAYLOAD_SCHEMA_VERSION = "runtime_ohlcv_alias_scalar_payload_v1"
_ALIAS_SCALAR_PAYLOAD_TYPE = "RUNTIME_OHLCV_ALIAS_FLOAT32_SCALAR_V1"
_ALIAS_TRANSFORM_CONTRACT_SCHEMA_VERSION = "runtime_ohlcv_alias_transform_contract_v1"
_ALIAS_SOURCE_BY_FEATURE = {
    alias: source for alias, source, _transform_id in RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS
}
_AUTHENTICATED_LATEST_CANDLE_FEATURES = DIRECT_LATEST_CANDLE_FEATURES | frozenset(
    _ALIAS_SOURCE_BY_FEATURE
)

_ACTIVE_SELECTION_FIELDS = frozenset(
    {
        "schema_version",
        "selection_mode",
        "selected_source_keys",
        "legacy_raw_key_considered",
        "closed_key",
        "raw_key_row_count",
        "closed_key_row_count",
        "selected_row_count",
        "consumer_observation_cutoff_ms",
        "consumer_observation_clock_source",
        "expected_latest_finalized_close_time",
        "atomic_source_read_succeeded",
        "atomic_batch_id",
        "atomic_batch_material_json",
        "atomic_batch_material_sha256",
        "atomic_server_observed_at",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "exact_source_schema_validated",
        "entire_contiguous_suffix_bound",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_candle_ids",
        "selected_first_candle_id",
        "selected_latest_candle_id",
        "selected_identity_storage",
        "selected_candle_id_chain_sha256",
        "selected_rows_material_sha256",
        "source_gap_indices",
        "source_gap_missing_interval_counts",
        "selected_source_provenance_counts",
        "selected_backfilled_row_count",
        "binding_selection_material_json",
        "binding_selection_sha256",
        "consumer_selection_material_json",
        "consumer_selection_sha256",
        "selection_material_retained_in_snapshot",
        "selection_rejection_reasons",
        "durable_source_receipt_emitted",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "live_execution_authorized",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CLOCK_FIELDS = (
    "economic_event_time",
    "producer_event_time",
    "ingested_at",
    "available_at",
    "consumer_observed_at",
    "generated_at",
    "publication_available_at",
    "publication_postcommit_at",
    "decision_time",
)


class RuntimeFeatureSnapshotLedgerBridgeError(RuntimeError):
    """The unwired partial evidence cannot be truthfully recorded in v3."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise RuntimeFeatureSnapshotLedgerBridgeError(*reasons) from None


_RESULT_CONSTRUCTION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class RuntimeFeatureSnapshotLedgerBridgeResult:
    """Factory-only quarantine append result whose authority stays false."""

    schema_version: str
    evidence_classification: str
    status: str
    cycle_binding_status: str
    historical_import_status: str
    feature_snapshot_id: str
    durable_snapshot_id: str
    record_sha256: str
    append_transaction_id: str
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str
    feature_slot_count: int
    authenticated_available_slot_count: int
    quarantined_missing_slot_count: int
    unresolved_required_plan_slot_count: int
    strict_training_eligible: bool
    fixed_cutoff_training_visible: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    blocker_reasons: tuple[str, ...]
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _RESULT_CONSTRUCTION_TOKEN:
            _fail("RUNTIME_FEATURE_LEDGER_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
        if (
            self.schema_version != RUNTIME_FEATURE_LEDGER_BRIDGE_SCHEMA_VERSION
            or self.evidence_classification != RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION
            or self.status != RUNTIME_FEATURE_LEDGER_BRIDGE_STATUS
            or self.cycle_binding_status != RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS
            or self.historical_import_status != RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS
            or self.feature_slot_count != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
            or self.authenticated_available_slot_count + self.quarantined_missing_slot_count
            != self.feature_slot_count
            or any(
                value is not False
                for value in (
                    self.strict_training_eligible,
                    self.fixed_cutoff_training_visible,
                    self.trainer_admission_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                )
            )
            or not self.blocker_reasons
        ):
            _fail("RUNTIME_FEATURE_LEDGER_RESULT_QUARANTINE_INVARIANT_INVALID")


def _parse_clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if type(value) is not str or not value or not value.endswith("Z"):
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    parsed = parsed.astimezone(UTC)
    if parsed < datetime(1970, 1, 1, tzinfo=UTC):
        _fail(reason)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _ms_clock(value: object, *, reason: str) -> str:
    if type(value) is not int or value < 0:
        _fail(reason)
    try:
        parsed = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        _fail(reason)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _float32(value: object, *, reason: str) -> tuple[float, str]:
    if isinstance(value, bool) or type(value) not in (int, float):
        _fail(reason)
    try:
        parsed = float(cast(int | float, value))
        packed = struct.pack("!f", parsed)
        runtime = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail(reason)
    if not math.isfinite(parsed) or not math.isfinite(runtime):
        _fail(reason)
    if parsed != 0.0 and runtime == 0.0:
        _fail(reason)
    return (0.0 if runtime == 0.0 else runtime), packed.hex()


def _address(address: object) -> dict[str, object]:
    fields = ("schema_version", "payload_sha256", "payload_byte_count", "relative_path")
    if any(not hasattr(address, field) for field in fields):
        _fail("RUNTIME_FEATURE_LEDGER_SOURCE_CAS_ADDRESS_INVALID")
    material = {field: getattr(address, field) for field in fields}
    if (
        type(material["payload_sha256"]) is not str
        or _SHA256_RE.fullmatch(cast(str, material["payload_sha256"])) is None
        or type(material["payload_byte_count"]) is not int
        or cast(int, material["payload_byte_count"]) <= 0
        or type(material["relative_path"]) is not str
        or not material["relative_path"]
    ):
        _fail("RUNTIME_FEATURE_LEDGER_SOURCE_CAS_ADDRESS_INVALID")
    return material


def _snapshot_mapping(
    snapshot_payload: str | bytes,
) -> tuple[dict[str, Any], bytes, list[dict[str, Any]]]:
    # The receipt module performs the bounded duplicate-key/strict-number
    # validation while deriving the leaves.  Parse only after that admission.
    try:
        bindings = [
            dict(item) for item in derive_feature_publication_slot_bindings(snapshot_payload)
        ]
    except FeaturePublicationReceiptValidationError as exc:
        if str(exc) == "FEATURE_PUBLICATION_JSON_DUPLICATE_KEY":
            _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_JSON_DUPLICATE_KEY")
        _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_PAYLOAD_INVALID")
    raw = snapshot_payload.encode("utf-8") if type(snapshot_payload) is str else snapshot_payload
    if type(raw) is not bytes:
        _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_PAYLOAD_TYPE_INVALID")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_PAYLOAD_INVALID")
    if type(parsed) is not dict:
        _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_PAYLOAD_INVALID")
    return cast(dict[str, Any], parsed), raw, bindings


def _direct_source_values(latest: object) -> dict[str, object]:
    required = (
        "quote_volume",
        "volume",
        "open",
        "high",
        "low",
        "close",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    )
    if any(not hasattr(latest, field) for field in required):
        _fail("RUNTIME_FEATURE_LEDGER_LATEST_CANDLE_SCHEMA_INVALID")
    return {
        "quote_volume": latest.quote_volume,
        "volume": latest.volume,
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "num_trades": latest.num_trades,
        "taker_buy_base_vol": latest.taker_buy_base_vol,
        "taker_buy_quote_vol": latest.taker_buy_quote_vol,
    }


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ):
        _fail("RUNTIME_FEATURE_LEDGER_SELECTION_MATERIAL_INVALID")


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _expected_active_selection(
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> dict[str, object]:
    """Rebuild the successful active-producer selection from exact capture."""

    binding = capture.full_window_binding
    selected_rows = capture.validated_window.rows[
        binding.selected_source_start_index : binding.selected_source_end_index_exclusive
    ]
    selected_rows_material_sha256 = _canonical_json_sha256([asdict(row) for row in selected_rows])
    provenance_counts = {
        source: sum(row.source == source for row in selected_rows)
        for source in ("binance_rest", "binance_wss")
        if any(row.source == source for row in selected_rows)
    }
    selection_material = {
        "schema_version": ACTIVE_OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION,
        "source_key": capture.source_key,
        "atomic_batch_id": capture.atomic_batch_id,
        "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
        "exact_payload_sha256": capture.full_source_payload_address.payload_sha256,
        "exact_payload_byte_count": (capture.full_source_payload_address.payload_byte_count),
        "consumer_observation_cutoff_ms": capture.consumer_observed_at_ms,
        "expected_latest_finalized_close_time": (binding.expected_latest_finalized_close_time),
        "binding_selection_sha256": binding.selection_sha256,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_row_count": binding.selected_row_count,
        "selected_candle_ids": list(binding.selected_candle_ids),
        "selected_candle_id_chain_sha256": (binding.selected_candle_id_chain_sha256),
        "selected_rows_material_sha256": selected_rows_material_sha256,
        "selected_raw_payload_hashes": [row.raw_payload_hash for row in selected_rows],
        "selected_source_provenance": [
            {
                "candle_id": row.candle_id,
                "source": row.source,
                "is_backfilled": row.is_backfilled,
                "source_sequence_id": row.source_sequence_id,
                "raw_payload_hash": row.raw_payload_hash,
            }
            for row in selected_rows
        ],
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    return {
        "schema_version": ACTIVE_OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION,
        "selection_mode": ("ATOMIC_CANONICAL_CLOSED_FULL_CONTIGUOUS_SUFFIX_BOUND"),
        "selected_source_keys": [capture.source_key],
        "legacy_raw_key_considered": False,
        "closed_key": capture.source_key,
        "raw_key_row_count": 0,
        "closed_key_row_count": capture.validated_window.row_count,
        "selected_row_count": binding.selected_row_count,
        "consumer_observation_cutoff_ms": capture.consumer_observed_at_ms,
        "consumer_observation_clock_source": "LOCAL_CLOCK_AFTER_ATOMIC_RESPONSE",
        "expected_latest_finalized_close_time": (binding.expected_latest_finalized_close_time),
        "atomic_source_read_succeeded": True,
        "atomic_batch_id": capture.atomic_batch_id,
        "atomic_batch_material_json": None,
        "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
        "atomic_server_observed_at": capture.atomic_server_observed_at,
        "exact_payload_sha256": capture.full_source_payload_address.payload_sha256,
        "exact_payload_byte_count": (capture.full_source_payload_address.payload_byte_count),
        "exact_source_schema_validated": True,
        "entire_contiguous_suffix_bound": True,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_candle_ids": None,
        "selected_first_candle_id": binding.selected_candle_ids[0],
        "selected_latest_candle_id": binding.selected_candle_ids[-1],
        "selected_identity_storage": "HASH_CHAIN_AND_BOUNDARIES_ONLY",
        "selected_candle_id_chain_sha256": (binding.selected_candle_id_chain_sha256),
        "selected_rows_material_sha256": selected_rows_material_sha256,
        "source_gap_indices": list(binding.gap_indices),
        "source_gap_missing_interval_counts": list(binding.gap_missing_interval_counts),
        "selected_source_provenance_counts": provenance_counts,
        "selected_backfilled_row_count": sum(row.is_backfilled for row in selected_rows),
        "binding_selection_material_json": None,
        "binding_selection_sha256": binding.selection_sha256,
        "consumer_selection_material_json": None,
        "consumer_selection_sha256": _canonical_json_sha256(selection_material),
        "selection_material_retained_in_snapshot": False,
        "selection_rejection_reasons": [],
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }


def _validate_active_selection_binding(
    *,
    snapshot: dict[str, Any],
    selection: dict[str, Any],
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> None:
    if set(selection) != _ACTIVE_SELECTION_FIELDS:
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_ABI_MISMATCH")
    expected = _expected_active_selection(capture)
    if selection.get("schema_version") != expected["schema_version"]:
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_SCHEMA_MISMATCH")
    if (
        selection.get("consumer_observation_cutoff_ms")
        != expected["consumer_observation_cutoff_ms"]
        or selection.get("consumer_observation_clock_source")
        != expected["consumer_observation_clock_source"]
        or snapshot.get("source_observation_time")
        != _ms_clock(
            capture.consumer_observed_at_ms,
            reason="RUNTIME_FEATURE_LEDGER_CAPTURE_OBSERVATION_TIME_INVALID",
        )
    ):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_OBSERVATION_BINDING_MISMATCH")
    expected_finalized_close = expected["expected_latest_finalized_close_time"]
    if (
        selection.get("expected_latest_finalized_close_time") != expected_finalized_close
        or snapshot.get("expected_latest_finalized_candle_close_time")
        != _ms_clock(
            expected_finalized_close,
            reason="RUNTIME_FEATURE_LEDGER_EXPECTED_FINALIZED_CLOSE_INVALID",
        )
        or snapshot.get("latest_finalized_candle_available_at_decision") is not True
    ):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_FINALIZED_CUTOFF_BINDING_MISMATCH")
    if selection.get("exact_source_schema_validated") is not True:
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_SCHEMA_ATTESTATION_INVALID")
    if (
        selection.get("entire_contiguous_suffix_bound") is not True
        or selection.get("selection_mode") != "ATOMIC_CANONICAL_CLOSED_FULL_CONTIGUOUS_SUFFIX_BOUND"
        or selection.get("selection_rejection_reasons") != []
    ):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_CONTIGUITY_INVALID")
    if (
        selection.get("selected_backfilled_row_count") != expected["selected_backfilled_row_count"]
        or selection.get("selected_source_provenance_counts")
        != expected["selected_source_provenance_counts"]
    ):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_BACKFILL_BINDING_MISMATCH")

    remaining = set(_ACTIVE_SELECTION_FIELDS) - {
        "schema_version",
        "consumer_observation_cutoff_ms",
        "consumer_observation_clock_source",
        "expected_latest_finalized_close_time",
        "exact_source_schema_validated",
        "entire_contiguous_suffix_bound",
        "selection_mode",
        "selection_rejection_reasons",
        "selected_backfilled_row_count",
        "selected_source_provenance_counts",
    }
    if any(selection.get(name) != expected[name] for name in remaining):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_CAPTURE_BINDING_MISMATCH")
    if (
        snapshot.get("ohlcv_selection_mode") != selection["selection_mode"]
        or snapshot.get("source_ohlcv_key") != capture.source_key
        or snapshot.get("source_ohlcv_keys") != [capture.source_key]
        or snapshot.get("ohlcv_raw_row_count") != selection["raw_key_row_count"]
        or snapshot.get("ohlcv_closed_key_row_count") != selection["closed_key_row_count"]
        or snapshot.get("ohlcv_selected_row_count") != selection["selected_row_count"]
    ):
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_TOP_LEVEL_SELECTION_BINDING_MISMATCH")


def _validate_unwired_capture_publication_binding(
    *,
    snapshot: dict[str, Any],
    snapshot_raw: bytes,
    bindings: list[dict[str, Any]],
    publication: VerifiedFeaturePublication,
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> tuple[list[dict[str, Any]], object, object, dict[str, datetime]]:
    if "runtime_feature_cycle_id" in snapshot:
        _fail("RUNTIME_FEATURE_LEDGER_UNSUPPORTED_CYCLE_ASSERTION")
    if hashlib.sha256(snapshot_raw).hexdigest() != publication.snapshot_payload_sha256:
        _fail("RUNTIME_FEATURE_LEDGER_PUBLICATION_PAYLOAD_BINDING_MISMATCH")
    if (
        snapshot.get("feature_snapshot_id") != publication.feature_snapshot_id
        or snapshot.get("symbol") != capture.validated_window.symbol
        or snapshot.get("timeframe") != capture.validated_window.timeframe
        or snapshot.get("symbol") != publication.receipt.get("symbol")
        or snapshot.get("timeframe") != publication.receipt.get("timeframe")
    ):
        _fail("RUNTIME_FEATURE_LEDGER_IDENTITY_BINDING_MISMATCH")
    if (
        publication.slot_count != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
        or publication.complete_slot_coverage is not True
        or publication.publication_binding_authenticated is not True
        or publication.receipt.get("feature_source_registry_sha256")
        != FEATURE_SOURCE_REGISTRY_V4_SHA256
        or publication.receipt.get("feature_resolution_plan_sha256")
        != FEATURE_RESOLUTION_PLAN_V4_SHA256
        or publication.receipt.get("feature_abi_sha256") != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
        or publication.receipt.get("feature_requirement_policy_id") != FEATURE_REQUIREMENT_POLICY_ID
    ):
        _fail("RUNTIME_FEATURE_LEDGER_PUBLICATION_CONTRACT_MISMATCH")
    if (
        publication.source_scope_complete is not False
        or publication.per_field_source_receipts_complete is not False
        or publication.trainer_admission_authorized is not False
        or publication.prediction_authorized is not False
        or publication.paper_trading_authorized is not False
        or publication.live_execution_authorized is not False
    ):
        _fail("RUNTIME_FEATURE_LEDGER_UPSTREAM_AUTHORITY_INVARIANT_CHANGED")

    # Property access freshly revalidates the full payload, selected row spans,
    # per-row v4 receipts, suffix manifest, and immutable CAS objects.
    selected = capture.selected_candles
    if not selected:
        _fail("RUNTIME_FEATURE_LEDGER_SELECTED_CANDLE_SET_EMPTY")
    latest_capture = selected[-1]
    latest = capture.validated_window.rows[latest_capture.source_index]
    selection = snapshot.get("ohlcv_consumer_selection")
    if type(selection) is not dict:
        _fail("RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_MISSING")
    _validate_active_selection_binding(
        snapshot=snapshot,
        selection=cast(dict[str, Any], selection),
        capture=capture,
    )
    if (
        latest.source != "binance_wss"
        or latest.is_backfilled is not False
        or latest.is_closed is not True
        or latest.feature_eligible is not True
    ):
        _fail("RUNTIME_FEATURE_LEDGER_LATEST_CANDLE_NOT_WSS_NONBACKFILLED_FINAL")

    latest_receipt = latest_capture.source_read_receipt.receipt
    clock_text = {
        "economic_event_time": latest_receipt["economic_event_time"],
        "producer_event_time": latest_receipt["producer_event_time"],
        "ingested_at": latest_receipt["ingested_at"],
        "available_at": latest_receipt["available_at"],
        "consumer_observed_at": latest_receipt["consumer_observed_at"],
        "generated_at": snapshot.get("generated_at"),
        "publication_available_at": publication.snapshot_available_at,
        "publication_postcommit_at": publication.receipt_postcommit_observed_at,
        "decision_time": publication.consumer_reopened_at,
    }
    parsed_clocks: dict[str, datetime] = {}
    for clock_field in _CLOCK_FIELDS:
        _canonical, parsed = _parse_clock(
            clock_text[clock_field],
            reason=f"RUNTIME_FEATURE_LEDGER_{clock_field.upper()}_INVALID",
        )
        parsed_clocks[clock_field] = parsed
    ordered = [parsed_clocks[clock_field] for clock_field in _CLOCK_FIELDS]
    if any(left > right for left, right in zip(ordered, ordered[1:], strict=False)):
        _fail("RUNTIME_FEATURE_LEDGER_CAUSAL_CLOCK_ORDER_INVALID")
    cutoff, cutoff_clock = _parse_clock(
        snapshot.get("feature_cutoff"),
        reason="RUNTIME_FEATURE_LEDGER_FEATURE_CUTOFF_INVALID",
    )
    expected_cutoff = _ms_clock(
        latest.candle_close_time,
        reason="RUNTIME_FEATURE_LEDGER_CANDLE_CLOSE_INVALID",
    )
    if cutoff != expected_cutoff or cutoff_clock >= parsed_clocks["decision_time"]:
        _fail("RUNTIME_FEATURE_LEDGER_FINALIZED_CUTOFF_BINDING_INVALID")
    if any(
        snapshot.get(name) is not True
        for name in (
            "candle_closed_confirmed",
            "latest_candle_temporally_valid",
            "exact_source_clock_valid",
        )
    ):
        _fail("RUNTIME_FEATURE_LEDGER_SNAPSHOT_FINALITY_ATTESTATION_INVALID")
    if snapshot.get("event_time") != _ms_clock(
        latest.event_time,
        reason="RUNTIME_FEATURE_LEDGER_PRODUCER_EVENT_TIME_INVALID",
    ):
        _fail("RUNTIME_FEATURE_LEDGER_PRODUCER_EVENT_BINDING_MISMATCH")
    if snapshot.get("ingested_at") != _ms_clock(
        latest.ingested_at,
        reason="RUNTIME_FEATURE_LEDGER_INGESTED_AT_INVALID",
    ):
        _fail("RUNTIME_FEATURE_LEDGER_INGESTED_AT_BINDING_MISMATCH")
    if snapshot.get("source_available_at") != _ms_clock(
        latest.available_at,
        reason="RUNTIME_FEATURE_LEDGER_SOURCE_AVAILABLE_AT_INVALID",
    ):
        _fail("RUNTIME_FEATURE_LEDGER_SOURCE_AVAILABLE_AT_BINDING_MISMATCH")

    return bindings, latest, latest_capture, parsed_clocks


def _v3_latest_candle_receipt(latest_capture: object) -> dict[str, Any]:
    receipt_v4 = latest_capture.source_read_receipt.receipt
    read = cast(dict[str, Any], receipt_v4["read_evidence"])
    finality = cast(dict[str, Any], receipt_v4["finality_evidence"])
    try:
        return build_source_read_receipt(
            source_label="v2:market:ohlcv",
            payload_type=CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
            payload_sha256=receipt_v4["payload_sha256"],
            payload_byte_count=receipt_v4["payload_byte_count"],
            event_time=receipt_v4["economic_event_time"],
            available_at=receipt_v4["available_at"],
            consumer_observed_at=receipt_v4["consumer_observed_at"],
            feature_cutoff=receipt_v4["feature_cutoff"],
            read_locator_type=read["read_locator_type"],
            read_locator=read["read_locator"],
            read_locator_version=read["read_locator_version"],
            finality_type=finality["finality_type"],
            finality_cutoff=finality["finality_cutoff"],
            finality_verified_at=finality["finality_verified_at"],
            finality_verifier=finality["verifier"],
        )
    except FeatureSnapshotValidationError as exc:
        raise RuntimeFeatureSnapshotLedgerBridgeError(
            "RUNTIME_FEATURE_LEDGER_V4_TO_V3_RECEIPT_CONVERSION_INVALID"
        ) from exc


def _v3_alias_composite_receipts(
    *,
    snapshot: dict[str, Any],
    publication: VerifiedFeaturePublication,
    source_values: dict[str, object],
    canonical_row_receipt: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build distinct alias roots over the exact canonical-row child receipt."""

    child_receipt_sha256 = cast(str, canonical_row_receipt["receipt_sha256"])
    alias_receipts: dict[str, dict[str, Any]] = {}
    alias_evidence: dict[str, dict[str, Any]] = {}
    for alias, source_name, transform_id in RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS:
        _value, scalar_hex = _float32(
            source_values[source_name],
            reason="RUNTIME_FEATURE_LEDGER_ALIAS_SOURCE_VALUE_INVALID",
        )
        transform_contract = {
            "schema_version": _ALIAS_TRANSFORM_CONTRACT_SCHEMA_VERSION,
            "operation": "CANONICAL_ROW_LEAF_TO_IEEE754_BINARY32_IDENTITY_ALIAS",
            "source_payload_type": CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
            "scalar_encoding": "IEEE754_BINARY32_BIG_ENDIAN_HEX",
        }
        configuration_contract = {
            "schema_version": _ALIAS_TRANSFORM_CONTRACT_SCHEMA_VERSION,
            "feature_name": alias,
            "source_feature_name": source_name,
            "transform_id": transform_id,
            "authenticated_source_label": (_ALIAS_RECEIPT_SOURCE_LABEL_BY_FEATURE[alias]),
        }
        transform_sha256 = _canonical_json_sha256(transform_contract)
        configuration_sha256 = _canonical_json_sha256(configuration_contract)
        scalar_material = {
            "schema_version": _ALIAS_SCALAR_PAYLOAD_SCHEMA_VERSION,
            "feature_snapshot_id": snapshot["feature_snapshot_id"],
            "snapshot_payload_sha256": publication.snapshot_payload_sha256,
            "feature_name": alias,
            "source_feature_name": source_name,
            "source_read_receipt_sha256": child_receipt_sha256,
            "source_value_float32_be_hex": scalar_hex,
            "derived_value_float32_be_hex": scalar_hex,
            "transform_sha256": transform_sha256,
            "configuration_sha256": configuration_sha256,
        }
        scalar_bytes = _canonical_json_bytes(scalar_material)
        scalar_sha256 = hashlib.sha256(scalar_bytes).hexdigest()
        child_read_bindings = [
            {
                "input_role": "canonical_ohlcv_latest_row",
                "receipt_sha256": child_receipt_sha256,
            }
        ]
        derivation_material = {
            "schema_version": FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
            "producer_id": "runtime_feature_snapshot_ledger_bridge",
            "producer_version": "runtime_ohlcv_alias_transform_v1",
            "transform_sha256": transform_sha256,
            "configuration_sha256": configuration_sha256,
        }
        try:
            alias_receipt = build_source_read_receipt(
                source_label=_ALIAS_RECEIPT_SOURCE_LABEL_BY_FEATURE[alias],
                payload_type=_ALIAS_SCALAR_PAYLOAD_TYPE,
                payload_sha256=scalar_sha256,
                payload_byte_count=len(scalar_bytes),
                event_time=canonical_row_receipt["event_time"],
                available_at=snapshot["generated_at"],
                consumer_observed_at=snapshot["generated_at"],
                feature_cutoff=canonical_row_receipt["feature_cutoff"],
                read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
                read_locator=(f"{snapshot['feature_snapshot_id']}:features:{alias}"),
                read_locator_version=publication.snapshot_payload_sha256,
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=snapshot["generated_at"],
                finality_verified_at=snapshot["generated_at"],
                finality_verifier=("runtime_feature_snapshot_ledger_bridge_alias_v1"),
                receipt_kind="COMPOSITE_DERIVATION",
                child_read_bindings=child_read_bindings,
                derivation_material=derivation_material,
            )
        except FeatureSnapshotValidationError as exc:
            raise RuntimeFeatureSnapshotLedgerBridgeError(
                "RUNTIME_FEATURE_LEDGER_ALIAS_COMPOSITE_RECEIPT_INVALID"
            ) from exc
        if (
            alias_receipt.get("source_label") != _ALIAS_RECEIPT_SOURCE_LABEL_BY_FEATURE[alias]
            or alias_receipt.get("payload_type") != _ALIAS_SCALAR_PAYLOAD_TYPE
            or alias_receipt.get("payload_sha256") != scalar_sha256
            or alias_receipt.get("read_evidence", {}).get("payload_byte_count") != len(scalar_bytes)
            or alias_receipt.get("receipt_kind") != "COMPOSITE_DERIVATION"
            or alias_receipt.get("child_read_bindings") != child_read_bindings
            or alias_receipt.get("derivation_material") != derivation_material
        ):
            _fail("RUNTIME_FEATURE_LEDGER_ALIAS_COMPOSITE_RECEIPT_BINDING_INVALID")
        alias_receipts[alias] = alias_receipt
        alias_evidence[alias] = {
            "source_label": _ALIAS_RECEIPT_SOURCE_LABEL_BY_FEATURE[alias],
            "root_receipt_sha256": alias_receipt["receipt_sha256"],
            "child_receipt_sha256": child_receipt_sha256,
            "scalar_payload_sha256": scalar_sha256,
            "scalar_payload_byte_count": len(scalar_bytes),
            "scalar_material": scalar_material,
            "transform_contract": transform_contract,
            "configuration_contract": configuration_contract,
        }
    return alias_receipts, alias_evidence


def append_unwired_runtime_feature_snapshot_quarantine(
    *,
    snapshot_payload: str | bytes,
    verified_publication: VerifiedFeaturePublication,
    ohlcv_capture: CanonicalOhlcvAtomicReceiptCapture,
    ledger: DurableFeatureSnapshotLedger,
) -> RuntimeFeatureSnapshotLedgerBridgeResult:
    """Append a capture-publication intersection and prove quarantine.

    The active ABI supplies no cycle or historical-import attestation, so this
    function deliberately asserts neither.  It cannot create a strict-training
    eligible row and raises before append on any identity, clock, selection,
    CAS, finality, ABI, raw-leaf, or alias-transform mismatch.
    """

    if type(verified_publication) is not VerifiedFeaturePublication:
        _fail("RUNTIME_FEATURE_LEDGER_VERIFIED_PUBLICATION_REQUIRED")
    if type(ohlcv_capture) is not CanonicalOhlcvAtomicReceiptCapture:
        _fail("RUNTIME_FEATURE_LEDGER_CANONICAL_OHLCV_CAPTURE_REQUIRED")
    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("RUNTIME_FEATURE_LEDGER_EXACT_LEDGER_REQUIRED")
    snapshot, snapshot_raw, bindings = _snapshot_mapping(snapshot_payload)
    bindings, latest, latest_capture, parsed_clocks = _validate_unwired_capture_publication_binding(
        snapshot=snapshot,
        snapshot_raw=snapshot_raw,
        bindings=bindings,
        publication=verified_publication,
        capture=ohlcv_capture,
    )
    source_values = _direct_source_values(latest)
    slots = FEATURE_SOURCE_REGISTRY_V4.slots
    if (
        len(slots) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
        or len(bindings) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
        or FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID != FEATURE_REQUIREMENT_POLICY_ID
    ):
        _fail("RUNTIME_FEATURE_LEDGER_PINNED_ABI_INVALID")

    v3_receipt = _v3_latest_candle_receipt(latest_capture)
    receipt_sha256 = cast(str, v3_receipt["receipt_sha256"])
    alias_receipts, alias_evidence = _v3_alias_composite_receipts(
        snapshot=snapshot,
        publication=verified_publication,
        source_values=source_values,
        canonical_row_receipt=v3_receipt,
    )
    values: list[float] = []
    missing: list[int] = []
    stale: list[int] = []
    availability: list[int] = []
    source_labels: list[str] = []
    source_receipt_sha256s: list[str | None] = []
    requirements: list[str] = []
    trusted_names: list[str] = []
    blocked_names: list[str] = []
    for slot, binding in zip(slots, bindings, strict=True):
        if (
            binding.get("ordinal") != slot.ordinal
            or binding.get("feature_name") != slot.feature_name
            or binding.get("configured_source_label") != slot.configured_source_label
            or binding.get("requirement_class") != slot.requirement_class
        ):
            _fail("RUNTIME_FEATURE_LEDGER_SLOT_BINDING_DRIFT")
        requirements.append(slot.requirement_class)
        if slot.feature_name in _AUTHENTICATED_LATEST_CANDLE_FEATURES:
            if slot.configured_source_label != "v2:market:ohlcv":
                _fail("RUNTIME_FEATURE_LEDGER_DIRECT_SOURCE_LABEL_INVALID")
            source_name = _ALIAS_SOURCE_BY_FEATURE.get(
                slot.feature_name,
                slot.feature_name,
            )
            value, source_hex = _float32(
                source_values[source_name],
                reason="RUNTIME_FEATURE_LEDGER_DIRECT_SOURCE_VALUE_INVALID",
            )
            if (
                binding.get("value_status") != "PRESENT_FINITE_VALUE_BOUND"
                or binding.get("published_value_float32_be_hex") != source_hex
            ):
                reason = (
                    "RUNTIME_FEATURE_LEDGER_ALIAS_PUBLISHED_VALUE_MISMATCH"
                    if slot.feature_name in _ALIAS_SOURCE_BY_FEATURE
                    else "RUNTIME_FEATURE_LEDGER_DIRECT_PUBLISHED_VALUE_MISMATCH"
                )
                _fail(reason)
            values.append(value)
            missing.append(0)
            availability.append(1)
            if slot.feature_name in alias_receipts:
                alias_receipt = alias_receipts[slot.feature_name]
                source_labels.append(cast(str, alias_receipt["source_label"]))
                source_receipt_sha256s.append(cast(str, alias_receipt["receipt_sha256"]))
            else:
                source_labels.append(slot.configured_source_label)
                source_receipt_sha256s.append(receipt_sha256)
            trusted_names.append(slot.feature_name)
        else:
            values.append(0.0)
            missing.append(1)
            availability.append(0)
            source_labels.append(slot.configured_source_label)
            source_receipt_sha256s.append(None)
            blocked_names.append(slot.feature_name)
        stale.append(0)

    unresolved_required = tuple(
        slot.feature_name
        for slot in FEATURE_RESOLUTION_PLAN_V4.slots
        if slot.requirement_class == "REQUIRED" and slot.unresolved_reason is not None
    )
    blockers = (
        "UNWIRED_ACTIVE_PRODUCER_ABI_HAS_NO_CYCLE_OR_HISTORY_ATTESTATION",
        "ONLY_CANONICAL_OHLCV_SOURCE_INTERSECTION_AUTHENTICATED",
        "NON_OHLCV_PER_SLOT_POSITIVE_OR_TYPED_NEGATIVE_RECEIPTS_ABSENT",
        "PINNED_V4_REQUIRED_RESOLUTION_PLAN_HAS_UNRESOLVED_SLOTS",
        "STRICT_FIXED_CUTOFF_TRAINING_HELD",
    )
    latest_v4_receipt = latest_capture.source_read_receipt.receipt
    source_lineage: dict[str, Any] = {
        "schema_version": RUNTIME_FEATURE_LEDGER_BRIDGE_SCHEMA_VERSION,
        "evidence_classification": (RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION),
        "producer_abi_selection_schema_version": (ACTIVE_OHLCV_CONSUMER_SELECTION_SCHEMA_VERSION),
        "cycle_binding_status": RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS,
        "historical_import_status": (RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS),
        "capture_publication_binding_authenticated": True,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "feature_abi_sha256_v4": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "runtime_publication_receipt_sha256": verified_publication.receipt_sha256,
        "runtime_publication_snapshot_payload_sha256": (
            verified_publication.snapshot_payload_sha256
        ),
        "runtime_publication_archive_key": verified_publication.snapshot_archive_key,
        "canonical_ohlcv_atomic_batch_id": ohlcv_capture.atomic_batch_id,
        "canonical_ohlcv_atomic_batch_material_sha256": (
            ohlcv_capture.atomic_batch_material_sha256
        ),
        "canonical_ohlcv_full_source_payload_cas_address": _address(
            ohlcv_capture.full_source_payload_address
        ),
        "canonical_ohlcv_suffix_manifest_cas_address": _address(
            ohlcv_capture.suffix_manifest_address
        ),
        "canonical_ohlcv_suffix_digest_sha256": ohlcv_capture.suffix_digest_sha256,
        "latest_candle_source_payload_cas_address": _address(latest_capture.source_payload_address),
        "latest_candle_source_read_receipt_v4": latest_v4_receipt,
        "direct_latest_candle_feature_names": sorted(DIRECT_LATEST_CANDLE_FEATURES),
        "receipt_bound_latest_candle_alias_transforms": [
            {
                "feature_name": alias,
                "source_feature_name": source_name,
                "transform_id": transform_id,
                "configured_source_label": "v2:market:ohlcv",
                **alias_evidence[alias],
            }
            for alias, source_name, transform_id in (RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS)
        ],
        "clock_semantics": {
            "economic_event_time": latest_v4_receipt["economic_event_time"],
            "producer_event_time": latest_v4_receipt["producer_event_time"],
            "ingested_at": latest_v4_receipt["ingested_at"],
            "source_available_at": latest_v4_receipt["available_at"],
            "source_read_completed_at": latest_v4_receipt["consumer_observed_at"],
            "generated_at": snapshot["generated_at"],
            "publication_available_at": verified_publication.snapshot_available_at,
            "publication_postcommit_at": (verified_publication.receipt_postcommit_observed_at),
            "decision_time": verified_publication.consumer_reopened_at,
            "feature_cutoff": snapshot["feature_cutoff"],
            "execution_time": None,
        },
        "authenticated_available_feature_names": trusted_names,
        "quarantined_missing_feature_names": blocked_names,
        "unresolved_required_plan_feature_names": list(unresolved_required),
        "source_scope_complete": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "blocker_reasons": list(blockers),
    }
    cutoff = _ms_clock(
        latest.candle_close_time,
        reason="RUNTIME_FEATURE_LEDGER_CANDLE_CLOSE_INVALID",
    )
    generated_at = (
        parsed_clocks["generated_at"].isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    decision_time = (
        parsed_clocks["decision_time"].isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    try:
        record = build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol=cast(str, snapshot["symbol"]),
            timeframe=cast(str, snapshot["timeframe"]),
            feature_snapshot_id=cast(str, snapshot["feature_snapshot_id"]),
            tensor_decision_time=decision_time,
            temporal_rejection_reasons=[RUNTIME_FEATURE_LEDGER_SOURCE_SCOPE_REASON],
            ordered_feature_names=[slot.feature_name for slot in slots],
            feature_values=values,
            missing_mask=missing,
            stale_mask=stale,
            source_availability_mask=availability,
            ordered_feature_source_labels=source_labels,
            feature_source_receipt_sha256s=source_receipt_sha256s,
            source_read_receipts=[v3_receipt, *alias_receipts.values()],
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=requirements,
            original_tensor_id=(f"runtime_v3_quarantine_{snapshot['feature_snapshot_id']}"),
            source_lineage_material=source_lineage,
            feature_cutoff=cutoff,
            masa_feature_cutoff=cutoff,
            ppo_feature_cutoff=cutoff,
            ppo_decision_time=decision_time,
            generated_at=generated_at,
        )
    except FeatureSnapshotValidationError as exc:
        raise RuntimeFeatureSnapshotLedgerBridgeError(
            "RUNTIME_FEATURE_LEDGER_V3_RECORD_INVALID"
        ) from exc
    envelope = cast(dict[str, Any], record["frozen_envelope"])
    if (
        envelope["strict_training_eligible"] is not False
        or not envelope["strict_training_ineligibility_reasons"]
    ):
        _fail("RUNTIME_FEATURE_LEDGER_QUARANTINE_INVARIANT_INVALID")

    try:
        append_result: FeatureSnapshotAppendResult = ledger.append_snapshot(record)
        stored = ledger.get_snapshot(cast(str, record["durable_snapshot_id"]))
    except FeatureSnapshotLedgerError as exc:
        raise RuntimeFeatureSnapshotLedgerBridgeError(
            "RUNTIME_FEATURE_LEDGER_APPEND_OR_READBACK_FAILED"
        ) from exc
    if (
        append_result.transaction_committed is not True
        or append_result.transaction_readback_verified is not True
        or stored is None
        or stored.record != record
        or stored.append_transaction_id != append_result.transaction_id
        or stored.append_receipt_sha256 != append_result.append_receipt_sha256
        or stored.postcommit_receipt_sha256 != append_result.postcommit_receipt_sha256
    ):
        _fail("RUNTIME_FEATURE_LEDGER_POSTCOMMIT_READBACK_BINDING_INVALID")
    try:
        visible = ledger.query_fixed_cutoff(
            decision_time_cutoff=decision_time,
            training_observed_at=append_result.postcommit_readback_at,
            symbol=cast(str, snapshot["symbol"]),
            timeframe=cast(str, snapshot["timeframe"]),
        )
    except FeatureSnapshotLedgerError as exc:
        raise RuntimeFeatureSnapshotLedgerBridgeError(
            "RUNTIME_FEATURE_LEDGER_FIXED_CUTOFF_QUARANTINE_CHECK_FAILED"
        ) from exc
    durable_id = cast(str, record["durable_snapshot_id"])
    fixed_cutoff_visible = any(
        item.record.get("durable_snapshot_id") == durable_id for item in visible
    )
    if fixed_cutoff_visible:
        _fail("RUNTIME_FEATURE_LEDGER_DIRTY_ROW_ENTERED_FIXED_CUTOFF_QUERY")

    return RuntimeFeatureSnapshotLedgerBridgeResult(
        schema_version=RUNTIME_FEATURE_LEDGER_BRIDGE_SCHEMA_VERSION,
        evidence_classification=RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION,
        status=RUNTIME_FEATURE_LEDGER_BRIDGE_STATUS,
        cycle_binding_status=RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS,
        historical_import_status=RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS,
        feature_snapshot_id=cast(str, snapshot["feature_snapshot_id"]),
        durable_snapshot_id=durable_id,
        record_sha256=cast(str, record["record_sha256"]),
        append_transaction_id=append_result.transaction_id,
        append_receipt_sha256=append_result.append_receipt_sha256,
        postcommit_receipt_sha256=append_result.postcommit_receipt_sha256,
        postcommit_readback_at=append_result.postcommit_readback_at,
        feature_slot_count=FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        authenticated_available_slot_count=len(trusted_names),
        quarantined_missing_slot_count=len(blocked_names),
        unresolved_required_plan_slot_count=len(unresolved_required),
        strict_training_eligible=False,
        fixed_cutoff_training_visible=False,
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        blocker_reasons=blockers,
        _construction_token=_RESULT_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "DIRECT_LATEST_CANDLE_FEATURES",
    "RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS",
    "RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS",
    "RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION",
    "RUNTIME_FEATURE_LEDGER_BRIDGE_SCHEMA_VERSION",
    "RUNTIME_FEATURE_LEDGER_BRIDGE_STATUS",
    "RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS",
    "RUNTIME_FEATURE_LEDGER_SOURCE_SCOPE_REASON",
    "RuntimeFeatureSnapshotLedgerBridgeError",
    "RuntimeFeatureSnapshotLedgerBridgeResult",
    "append_unwired_runtime_feature_snapshot_quarantine",
]
