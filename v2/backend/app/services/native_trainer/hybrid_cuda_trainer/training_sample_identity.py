"""Authenticated sample inventory and checkpoint-bound holdout manifests.

This module is the producer counterpart of the persistent trainer's holdout
verifier.  It never derives authority from Redis or from mutable trust-row
metadata.  Every admitted sample must reopen as one exact, postcommit-attested
v3 durable feature-ledger record at a fixed observation cutoff.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import sqlite3
import stat
import struct
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    ARCHIVE_SCHEMA_VERSION as CANONICAL_LABEL_ARCHIVE_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveError,
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    content_sha256 as durable_snapshot_content_sha256,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    LEDGER_SCHEMA_VERSION as FEATURE_LEDGER_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    MAX_QUERY_ROWS as FEATURE_LEDGER_MAX_QUERY_ROWS,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    SAFE_QUERY_PAGE_ROWS as FEATURE_LEDGER_SAFE_QUERY_PAGE_ROWS,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotIntegrityReport,
    FeatureSnapshotLedgerError,
    FixedCutoffFeatureSnapshot,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    default_ledger_path as default_feature_snapshot_ledger_path,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    COST_COMPONENT_FIELD_ALIASES,
    HORIZON_SECONDS,
    build_trusted_replay_row,
    target_action_index,
    timeframe_seconds,
)

from .config import DEFAULT_TIMEFRAMES
from .data_loader import TrainingExample

MANIFEST_SCHEMA_VERSION = "trusted_replay_train_validation_holdout_manifest_v2"
MANIFEST_SPLIT_METHOD = "STRICT_TEMPORAL_ORDER_NO_RANDOM_ROW_SPLIT"
PARTITION_SCHEMA_VERSION = "trusted_replay_checkpoint_holdout_partition_v1"
FEATURE_SAMPLE_IDENTITY_DOMAIN = "durable_feature_snapshot_record_holdout_identity_v1"
SAMPLE_IDENTITY_DOMAIN = "durable_feature_snapshot_labeled_training_identity_v3"
LABEL_BINDING_SCHEMA_VERSION = "checkpoint_training_label_binding_v2"
OPTIONAL_MISSING_EVIDENCE_SEMANTICS = "STRUCTURAL_REQUIREMENT_CLASS_AND_MASK_ONLY"
FEATURE_HIGH_WATER_SCHEMA_VERSION = "durable_feature_snapshot_ledger_high_water_v1"
LABEL_HIGH_WATER_SCHEMA_VERSION = "durable_canonical_5m_label_archive_high_water_v1"
GOAL_ID = "V2_TRUSTED_REPLAY_BOOTSTRAP_PAPER_EXPLORATION_AND_ONLINE_LEARNING_ACTIVATION"
MANIFEST_FILENAME = "trusted_replay_train_validation_holdout_manifest.json"
MAX_SAMPLE_IDENTITIES = 250_000
MAX_MANIFEST_BYTES = 1024 * 1024
SUPPORTED_DURABLE_LABEL_ROW_SOURCE = "trusted_replay_archive"
ENTRY_PRICE_FIELD_ALIASES = ("close", "last_price", "price_last", "ohlcv_close")
PROJECTION_AUDIT_SCHEMA_VERSION = "checkpoint_partition_manifest_projection_audit_v1"
FEATURE_LEDGER_GENESIS_SHA256 = hashlib.sha256(
    f"{FEATURE_LEDGER_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
LABEL_ARCHIVE_GENESIS_SHA256 = hashlib.sha256(
    f"{CANONICAL_LABEL_ARCHIVE_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()


class TrainingSampleIdentityError(RuntimeError):
    """An exact optimizer/checkpoint sample proof could not be reproduced."""


def _fail(reason: str) -> Never:
    raise TrainingSampleIdentityError(reason)


def stable_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _valid_sha256(value: Any) -> str | None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        return None
    return value


def _strict_utc(value: Any) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_utc(value: Any, *, reason: str) -> str:
    parsed = _strict_utc(value)
    if parsed is None:
        _fail(reason)
    assert parsed is not None
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _strict_prior_observation(value: datetime, *, reason: str) -> datetime:
    """Return the greatest representable instant strictly before ``value``.

    Cycle observations are exclusive upper bounds.  This prevents a receipt
    appended after preflight from becoming visible merely because its durable
    clock has the same precision/value as the captured cycle clock.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        _fail(reason)
    normalized = value.astimezone(UTC)
    try:
        return normalized - timedelta(microseconds=1)
    except OverflowError as exc:
        raise TrainingSampleIdentityError(reason) from exc


def _epoch_microseconds(value: datetime) -> int:
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def sample_identity_set_sha256(identities: Iterable[str]) -> str:
    return _identity_set_sha256(identities, domain=SAMPLE_IDENTITY_DOMAIN)


def feature_identity_set_sha256(identities: Iterable[str]) -> str:
    return _identity_set_sha256(
        identities,
        domain=FEATURE_SAMPLE_IDENTITY_DOMAIN,
    )


def _identity_set_sha256(
    identities: Iterable[str],
    *,
    domain: str,
) -> str:
    raw = [str(value) for value in identities]
    if len(raw) > MAX_SAMPLE_IDENTITIES:
        _fail("TRAINING_SAMPLE_IDENTITY_INVENTORY_EXCEEDS_BOUND")
    if any(_valid_sha256(value) is None for value in raw):
        _fail("TRAINING_SAMPLE_IDENTITY_INVALID")
    if len(raw) != len(set(raw)):
        _fail("TRAINING_SAMPLE_IDENTITY_DUPLICATE")
    ordered = sorted(raw)
    return stable_json_sha256(
        {
            "schema_version": domain,
            "ordered_sample_identity_sha256s": ordered,
        }
    )


def feature_sample_identity(
    item: FixedCutoffFeatureSnapshot,
) -> tuple[dict[str, Any], str]:
    record = item.record
    envelope_raw = record.get("frozen_envelope")
    if not isinstance(envelope_raw, Mapping):
        _fail("DURABLE_FEATURE_ENVELOPE_MISSING")
    envelope = dict(envelope_raw)
    identity = {
        "schema_version": FEATURE_SAMPLE_IDENTITY_DOMAIN,
        "durable_snapshot_id": record.get("durable_snapshot_id"),
        "record_sha256": record.get("record_sha256"),
        "original_tensor_id": envelope.get("original_tensor_id"),
        "symbol": envelope.get("symbol"),
        "timeframe": envelope.get("timeframe"),
        "ppo_decision_time": envelope.get("ppo_decision_time"),
    }
    identity_sha256 = stable_json_sha256(identity)
    if _valid_sha256(identity_sha256) is None:
        _fail("DURABLE_FEATURE_SAMPLE_IDENTITY_INVALID")
    return identity, identity_sha256


def _strict_json_material_sha256(value: Any, *, reason: str) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(reason) from exc
    if not encoded or len(encoded) > MAX_MANIFEST_BYTES:
        _fail(reason)
    return hashlib.sha256(encoded).hexdigest()


def _label_float64_sha256(value: Any) -> str:
    if isinstance(value, bool):
        _fail("TRAINING_SAMPLE_AFTER_COST_LABEL_INVALID")
    try:
        numeric = float(value)
        encoded = struct.pack(">d", numeric)
    except (OverflowError, struct.error, TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError("TRAINING_SAMPLE_AFTER_COST_LABEL_INVALID") from exc
    if not math.isfinite(numeric):
        _fail("TRAINING_SAMPLE_AFTER_COST_LABEL_INVALID")
    return hashlib.sha256(
        b"checkpoint_training_after_cost_label_float64_v1\0" + encoded
    ).hexdigest()


def _exact_timeframe_finality_evidence(
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Authenticate every configured candle close against its exact receipt."""

    lineage_raw = envelope.get("source_lineage_material")
    lineage = dict(lineage_raw) if isinstance(lineage_raw, Mapping) else {}
    finality_raw = lineage.get("timeframe_finality")
    if not isinstance(finality_raw, Mapping):
        _fail("TRAINING_SAMPLE_TIMEFRAME_FINALITY_INVALID:LINEAGE_MISSING")
    finality_by_timeframe = dict(finality_raw)
    reasons: list[str] = []
    if set(finality_by_timeframe) != set(DEFAULT_TIMEFRAMES):
        reasons.append("TIMEFRAME_FINALITY_LINEAGE_SET_MISMATCH")
    mtf_snapshot_id = lineage.get("mtf_snapshot_id")
    if type(mtf_snapshot_id) is not str or not mtf_snapshot_id:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    receipts_raw = envelope.get("source_read_receipts")
    receipts = receipts_raw if isinstance(receipts_raw, list) else []
    receipts_by_sha = {
        str(receipt.get("receipt_sha256")): dict(receipt)
        for receipt in receipts
        if isinstance(receipt, Mapping) and _valid_sha256(receipt.get("receipt_sha256")) is not None
    }
    decision_time = _strict_utc(envelope.get("tensor_decision_time"))
    global_cutoff = _strict_utc(envelope.get("feature_cutoff"))
    used_receipts: list[str] = []
    exact_entries: dict[str, Any] = {}
    for timeframe in DEFAULT_TIMEFRAMES:
        raw_entry = finality_by_timeframe.get(timeframe)
        if not isinstance(raw_entry, Mapping):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_MISSING")
            continue
        entry = dict(raw_entry)
        if entry.get("timeframe") != timeframe:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_IDENTITY_MISMATCH")
        if entry.get("candle_closed_confirmed") is not True:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_NOT_CLOSED")
        receipt_sha256 = _valid_sha256(entry.get("source_read_receipt_sha256"))
        receipt = receipts_by_sha.get(str(receipt_sha256)) if receipt_sha256 else None
        if receipt is None:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_RECEIPT_MISSING")
            continue
        used_receipts.append(str(receipt_sha256))
        receipt_finality_raw = receipt.get("finality_evidence")
        receipt_finality = (
            dict(receipt_finality_raw) if isinstance(receipt_finality_raw, Mapping) else {}
        )
        comparisons = {
            "source_label": receipt.get("source_label"),
            "event_time": receipt.get("event_time"),
            "available_at": receipt.get("available_at"),
            "consumer_observed_at": receipt.get("consumer_observed_at"),
            "feature_cutoff": receipt.get("feature_cutoff"),
            "finality_cutoff": receipt_finality.get("finality_cutoff"),
            "finality_verified_at": receipt_finality.get("finality_verified_at"),
        }
        if any(entry.get(field) != expected for field, expected in comparisons.items()):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_RECEIPT_MISMATCH")
        if receipt_finality.get("finality_type") != "CLOSED_INTERVAL":
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_TYPE_INVALID")
        if receipt_finality.get("event_final") is not True:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_EVENT_NOT_FINAL")
        clocks = {
            "open": _strict_utc(entry.get("candle_open_time")),
            "close": _strict_utc(entry.get("candle_close_time")),
            "event": _strict_utc(entry.get("event_time")),
            "available": _strict_utc(entry.get("available_at")),
            "observed": _strict_utc(entry.get("consumer_observed_at")),
            "receipt_cutoff": _strict_utc(entry.get("feature_cutoff")),
            "finality_cutoff": _strict_utc(entry.get("finality_cutoff")),
            "finality_verified": _strict_utc(entry.get("finality_verified_at")),
        }
        if (
            decision_time is None
            or global_cutoff is None
            or any(clock is None for clock in clocks.values())
        ):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CLOCK_INVALID")
            continue
        open_time = clocks["open"]
        close_time = clocks["close"]
        event_time = clocks["event"]
        available_at = clocks["available"]
        observed_at = clocks["observed"]
        receipt_cutoff = clocks["receipt_cutoff"]
        finality_cutoff = clocks["finality_cutoff"]
        finality_verified = clocks["finality_verified"]
        assert all(
            clock is not None
            for clock in (
                open_time,
                close_time,
                event_time,
                available_at,
                observed_at,
                receipt_cutoff,
                finality_cutoff,
                finality_verified,
            )
        )
        assert open_time is not None
        assert close_time is not None
        assert event_time is not None
        assert available_at is not None
        assert observed_at is not None
        assert receipt_cutoff is not None
        assert finality_cutoff is not None
        assert finality_verified is not None
        if close_time - open_time != timedelta(
            seconds=timeframe_seconds(timeframe),
            milliseconds=-1,
        ):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_INTERVAL_INVALID")
        if event_time != close_time:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_EVENT_CLOSE_MISMATCH")
        if not (close_time <= finality_cutoff <= finality_verified <= observed_at <= decision_time):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_ORDER_INVALID")
        if available_at > observed_at or receipt_cutoff > global_cutoff:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CUTOFF_INVALID")
        if type(entry.get("candle_id")) is not str or not entry.get("candle_id"):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CANDLE_ID_MISSING")
        exact_entries[timeframe] = entry
    if len(used_receipts) != len(set(used_receipts)):
        reasons.append("TIMEFRAME_FINALITY_RECEIPTS_NOT_DISTINCT")
    if reasons:
        _fail("TRAINING_SAMPLE_TIMEFRAME_FINALITY_INVALID:" + ",".join(sorted(set(reasons))))
    proof = {
        "schema_version": "exact_per_timeframe_finality_lineage_v1",
        "mtf_snapshot_id": mtf_snapshot_id,
        "required_timeframes": list(DEFAULT_TIMEFRAMES),
        "timeframe_finality": exact_entries,
    }
    return {**proof, "timeframe_finality_sha256": stable_json_sha256(proof)}


def _feature_snapshot_for_label_rebuild(
    item: FixedCutoffFeatureSnapshot,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild the immutable snapshot view used by the trusted-replay labeler."""

    record = item.record
    envelope_raw = record.get("frozen_envelope")
    if not isinstance(envelope_raw, Mapping):
        _fail("DURABLE_FEATURE_ENVELOPE_MISSING")
    envelope = dict(envelope_raw)
    names_raw = envelope.get("ordered_feature_names")
    values_raw = envelope.get("feature_values")
    missing_raw = envelope.get("missing_mask")
    stale_raw = envelope.get("stale_mask")
    availability_raw = envelope.get("source_availability_mask")
    if (
        type(names_raw) is not list
        or not names_raw
        or any(type(name) is not str or not name for name in names_raw)
        or len(set(names_raw)) != len(names_raw)
    ):
        _fail("TRAINING_SAMPLE_DURABLE_FEATURE_NAMES_INVALID")
    names = list(names_raw)
    vectors = (values_raw, missing_raw, stale_raw, availability_raw)
    if any(type(vector) is not list or len(vector) != len(names) for vector in vectors):
        _fail("TRAINING_SAMPLE_DURABLE_FEATURE_VECTOR_DIMENSION_MISMATCH")
    assert isinstance(values_raw, list)
    assert isinstance(missing_raw, list)
    assert isinstance(stale_raw, list)
    assert isinstance(availability_raw, list)
    try:
        values = [float(value) for value in values_raw]
    except (OverflowError, TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError("TRAINING_SAMPLE_DURABLE_FEATURE_VALUE_INVALID") from exc
    if any(not math.isfinite(value) for value in values):
        _fail("TRAINING_SAMPLE_DURABLE_FEATURE_VALUE_INVALID")
    if any(
        type(flag) is not int or flag not in (0, 1)
        for vector in (missing_raw, stale_raw, availability_raw)
        for flag in vector
    ):
        _fail("TRAINING_SAMPLE_DURABLE_FEATURE_MASK_INVALID")
    finality_evidence = _exact_timeframe_finality_evidence(envelope)
    mtf_snapshot_id = finality_evidence["mtf_snapshot_id"]
    features = dict(zip(names, values, strict=True))
    snapshot: dict[str, Any] = {
        "snapshot_id": record.get("durable_snapshot_id"),
        "feature_snapshot_id": envelope.get("feature_snapshot_id"),
        "symbol": envelope.get("symbol"),
        "timeframe": envelope.get("timeframe"),
        "features": features,
        "missing_mask": dict(zip(names, (bool(flag) for flag in missing_raw), strict=True)),
        "stale_mask": dict(zip(names, (bool(flag) for flag in stale_raw), strict=True)),
        "source_availability": dict(
            zip(names, (bool(flag) for flag in availability_raw), strict=True)
        ),
        "ordered_feature_names": names,
        "feature_abi": envelope.get("feature_abi"),
        "feature_source_receipt_sha256s": envelope.get("feature_source_receipt_sha256s"),
        "feature_cutoff": envelope.get("feature_cutoff"),
        "masa_feature_cutoff": envelope.get("masa_feature_cutoff"),
        "ppo_feature_cutoff": envelope.get("ppo_feature_cutoff"),
        "tensor_decision_time": envelope.get("tensor_decision_time"),
        "ppo_decision_time": envelope.get("ppo_decision_time"),
        "decision_time": envelope.get("ppo_decision_time"),
        "generated_at": envelope.get("generated_at"),
        "available_at": envelope.get("generated_at"),
        "mtf_snapshot_id": mtf_snapshot_id,
        "candle_closed_confirmed": True,
        "source_hashes": {
            "durable_record_sha256": record.get("record_sha256"),
            "frozen_envelope_sha256": record.get("frozen_envelope_sha256"),
            "source_lineage_sha256": envelope.get("source_lineage_sha256"),
            "timeframe_finality_sha256": finality_evidence["timeframe_finality_sha256"],
            "append_receipt_sha256": item.append_receipt_sha256,
            "postcommit_receipt_sha256": item.postcommit_receipt_sha256,
        },
        "durable_feature_snapshot_ledger": True,
        "append_transaction_id": item.append_transaction_id,
        "append_receipt_sha256": item.append_receipt_sha256,
        "postcommit_receipt_sha256": item.postcommit_receipt_sha256,
        "postcommit_readback_at": item.postcommit_readback_at,
        "timeframe_finality_lineage": finality_evidence,
    }
    snapshot["content_sha256"] = durable_snapshot_content_sha256(snapshot)
    return snapshot, envelope


def _positive_feature_receipt_evidence(
    *,
    envelope: Mapping[str, Any],
    feature_name: str,
    decision_time: datetime,
) -> dict[str, Any]:
    """Bind one present feature to a positive, finalized durable read receipt."""

    names = list(envelope.get("ordered_feature_names") or ())
    try:
        index = names.index(feature_name)
    except ValueError:
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_FEATURE_MISSING:{feature_name}")
    vectors = {
        "missing": list(envelope.get("missing_mask") or ()),
        "stale": list(envelope.get("stale_mask") or ()),
        "availability": list(envelope.get("source_availability_mask") or ()),
        "source_label": list(envelope.get("ordered_feature_source_labels") or ()),
        "receipt": list(envelope.get("feature_source_receipt_sha256s") or ()),
        "value": list(envelope.get("feature_values") or ()),
    }
    if any(index >= len(vector) for vector in vectors.values()):
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_VECTOR_MISMATCH:{feature_name}")
    if (
        vectors["missing"][index] != 0
        or vectors["stale"][index] != 0
        or vectors["availability"][index] != 1
    ):
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_NOT_POSITIVE:{feature_name}")
    receipt_sha256 = vectors["receipt"][index]
    if _valid_sha256(receipt_sha256) is None:
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_INVALID:{feature_name}")
    receipts_raw = envelope.get("source_read_receipts")
    receipts = receipts_raw if isinstance(receipts_raw, list) else []
    matches = [
        receipt
        for receipt in receipts
        if isinstance(receipt, Mapping) and receipt.get("receipt_sha256") == receipt_sha256
    ]
    if len(matches) != 1:
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_NOT_EXACT:{feature_name}")
    receipt = dict(matches[0])
    source_label = vectors["source_label"][index]
    if receipt.get("source_label") != source_label:
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_SOURCE_MISMATCH:{feature_name}")
    read_evidence_raw = receipt.get("read_evidence")
    finality_raw = receipt.get("finality_evidence")
    if not isinstance(read_evidence_raw, Mapping) or not isinstance(
        finality_raw,
        Mapping,
    ):
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_EVIDENCE_MISSING:{feature_name}")
    read_evidence = dict(read_evidence_raw)
    finality = dict(finality_raw)
    payload_bytes = read_evidence.get("payload_byte_count")
    if (
        type(payload_bytes) is not int
        or payload_bytes <= 0
        or finality.get("event_final") is not True
    ):
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_NOT_POSITIVE:{feature_name}")
    receipt_clocks: dict[str, datetime] = {}
    for field in ("available_at", "consumer_observed_at", "feature_cutoff"):
        parsed = _strict_utc(receipt.get(field))
        if parsed is None or parsed > decision_time:
            _fail(f"TRAINING_SAMPLE_LABEL_INPUT_RECEIPT_CLOCK_INVALID:{feature_name}")
        receipt_clocks[field] = parsed
    finality_verified = _strict_utc(finality.get("finality_verified_at"))
    if finality_verified is None or finality_verified > decision_time:
        _fail(f"TRAINING_SAMPLE_LABEL_INPUT_FINALITY_CLOCK_INVALID:{feature_name}")
    return {
        "feature_name": feature_name,
        "feature_value_float64_sha256": _label_float64_sha256(vectors["value"][index]),
        "source_label": source_label,
        "source_receipt_sha256": receipt_sha256,
        "source_payload_sha256": receipt.get("payload_sha256"),
        "source_payload_byte_count": payload_bytes,
        "source_read_evidence_sha256": receipt.get("read_evidence_sha256"),
        "source_finality_evidence_sha256": receipt.get("finality_evidence_sha256"),
        "source_read_locator_sha256": receipt.get("read_locator_sha256"),
        "source_available_at": receipt.get("available_at"),
        "source_consumer_observed_at": receipt.get("consumer_observed_at"),
        "source_feature_cutoff": receipt.get("feature_cutoff"),
        "source_finality_verified_at": finality.get("finality_verified_at"),
        "event_final": True,
        "positive_payload_verified": True,
    }


def _strict_material_equal(observed: Any, expected: Any) -> bool:
    try:
        return _strict_json_material_sha256(
            observed,
            reason="TRAINING_SAMPLE_TRUST_FIELD_NOT_STRICT_JSON",
        ) == _strict_json_material_sha256(
            expected,
            reason="TRAINING_SAMPLE_REBUILT_TRUST_FIELD_NOT_STRICT_JSON",
        )
    except TrainingSampleIdentityError:
        return False


def _authenticated_trust_evidence(
    *,
    trust_row: Mapping[str, Any],
    rebuilt_row: Mapping[str, Any],
    causal_label_path_sha256: str,
) -> dict[str, Any]:
    if trust_row.get("row_source") != SUPPORTED_DURABLE_LABEL_ROW_SOURCE:
        _fail("TRAINING_SAMPLE_LABEL_LANE_UNSUPPORTED")
    if (
        trust_row.get("trusted_replay_row") is not True
        or trust_row.get("historical_replay_row") is not True
    ):
        _fail("TRAINING_SAMPLE_DURABLE_REPLAY_TRUST_MARKERS_MISSING")
    authoritative_fields = (
        "target_action",
        "target_action_index",
        "future_return_after_cost_bps",
        "label_available_at",
        "outcome_available_at",
        "feature_cutoff",
        "decision_time",
        "trusted_replay_label_candle_source_key",
        "trusted_replay_label_candle_evidence_sha256",
        "trusted_replay_label_path_candle_count",
        "trusted_replay_label_path_contiguous_verified",
        "trusted_replay_label_future_available_candle_used",
        "trusted_replay_label_horizon_candle_ids",
        "cost_evidence_schema_version",
        "cost_evidence_hash",
        "cost_evidence_components",
        "round_trip_cost_bps",
        "action_dead_zone_bps",
    )
    authenticated: dict[str, Any] = {}
    for field in authoritative_fields:
        if field not in trust_row:
            _fail(f"TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISSING:{field}")
        expected = rebuilt_row.get(field)
        observed = trust_row.get(field)
        if not _strict_material_equal(observed, expected):
            _fail(f"TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISMATCH:{field}")
        authenticated[field] = expected
    lineage_raw = trust_row.get("source_lineage")
    if not isinstance(lineage_raw, Mapping):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_SOURCE_LINEAGE_MISSING")
    lineage = dict(lineage_raw)
    reported_label_path_sha256 = _valid_sha256(
        lineage.get("durable_canonical_5m_label_path_sha256")
    )
    source_key = trust_row.get("trusted_replay_label_candle_source_key")
    if (
        lineage.get("durable_canonical_5m_label_archive") is not True
        or reported_label_path_sha256 is None
        or type(source_key) is not str
        or not source_key.endswith(f":{reported_label_path_sha256}")
    ):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_SOURCE_LINEAGE_MISMATCH")
    material = {
        "schema_version": "checkpoint_authenticated_trust_fields_v1",
        "row_source": SUPPORTED_DURABLE_LABEL_ROW_SOURCE,
        "trusted_replay_row": True,
        "historical_replay_row": True,
        "authoritative_fields": authenticated,
        "reported_durable_canonical_5m_label_path_sha256": (
            reported_label_path_sha256
        ),
        "causal_label_path_sha256": causal_label_path_sha256,
    }
    return {**material, "authenticated_trust_sha256": stable_json_sha256(material)}


def _causal_label_path_evidence(
    *,
    rows: Sequence[Mapping[str, Any]],
    path_proof: Mapping[str, Any],
    observation_cutoff: datetime,
) -> dict[str, Any]:
    """Bind only the label-path prefix observable at the cycle cutoff.

    The archive's full head is intentionally excluded: later valid appends do
    not change the causal rows or receipts available to this training cycle.
    """

    range_raw = path_proof.get("range_proof")
    if not isinstance(range_raw, Mapping):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_RANGE_PROOF_MISSING")
    range_proof = dict(range_raw)
    append_receipts = range_proof.get("append_receipt_sha256")
    postcommit_receipts = range_proof.get(
        "postcommit_readback_receipt_sha256"
    )
    if (
        type(append_receipts) is not list
        or type(postcommit_receipts) is not list
        or any(_valid_sha256(value) is None for value in append_receipts)
        or any(_valid_sha256(value) is None for value in postcommit_receipts)
    ):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_PATH_RECEIPTS_INVALID")
    try:
        ordered_row_sha256s = [
            _strict_json_material_sha256(
                dict(row),
                reason="TRAINING_SAMPLE_DURABLE_LABEL_ROW_INVALID",
            )
            for row in rows
        ]
    except (TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError(
            "TRAINING_SAMPLE_DURABLE_LABEL_ROW_INVALID"
        ) from exc
    material = {
        "schema_version": "checkpoint_causal_5m_label_path_v1",
        "archive_path": path_proof.get("archive_path"),
        "symbol": path_proof.get("symbol"),
        "decision_time_epoch_us": path_proof.get("decision_time_epoch_us"),
        "training_observed_at": observation_cutoff.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "horizon_seconds": path_proof.get("horizon_seconds"),
        "start_close_time_ms": range_proof.get("start_close_time_ms"),
        "end_close_time_ms": range_proof.get("end_close_time_ms"),
        "ordered_label_row_sha256s": ordered_row_sha256s,
        "append_receipt_sha256s": sorted(str(value) for value in append_receipts),
        "postcommit_receipt_sha256s": sorted(
            str(value) for value in postcommit_receipts
        ),
        "receipt_commit_cutoff_required": range_proof.get(
            "receipt_commit_cutoff_required"
        ),
        "pit_available_at_verified": range_proof.get(
            "pit_available_at_verified"
        ),
        "contiguous_path_verified": range_proof.get(
            "contiguous_path_verified"
        ),
    }
    return {**material, "causal_label_path_sha256": stable_json_sha256(material)}


def _durable_label_binding(
    *,
    example: TrainingExample,
    item: FixedCutoffFeatureSnapshot,
    archive: DurableCanonical5mLabelArchive,
    archive_integrity: Mapping[str, Any],
    archive_high_water: Mapping[str, Any],
    observation_cutoff: datetime,
) -> dict[str, Any]:
    trust_row = example.trust_row
    if not isinstance(trust_row, Mapping):
        _fail("TRAINING_SAMPLE_TRUST_LINEAGE_MISSING")
    if trust_row.get("row_source") != SUPPORTED_DURABLE_LABEL_ROW_SOURCE:
        _fail("TRAINING_SAMPLE_LABEL_LANE_UNSUPPORTED:" f"{trust_row.get('row_source')}")
    snapshot, envelope = _feature_snapshot_for_label_rebuild(item)
    decision_time = _strict_utc(snapshot.get("decision_time"))
    if decision_time is None:
        _fail("TRAINING_SAMPLE_DECISION_TIME_INVALID")
    features = snapshot["features"]
    assert isinstance(features, Mapping)
    entry_field = next(
        (
            field
            for field in ENTRY_PRICE_FIELD_ALIASES
            if field in features
            and not isinstance(features.get(field), bool)
            and isinstance(features.get(field), int | float)
            and math.isfinite(float(features[field]))
            and float(features[field]) > 0.0
        ),
        None,
    )
    if entry_field is None:
        _fail("TRAINING_SAMPLE_DURABLE_ENTRY_PRICE_MISSING")
    entry_receipt = _positive_feature_receipt_evidence(
        envelope=envelope,
        feature_name=entry_field,
        decision_time=decision_time,
    )
    strict_prior_observation = _strict_prior_observation(
        observation_cutoff,
        reason="TRAINING_SAMPLE_OBSERVATION_CUTOFF_INVALID",
    )
    try:
        rows, path_proof = archive.verified_label_path(
            symbol=str(example.symbol).upper(),
            decision_time=example.decision_time or "",
            training_observed_at=strict_prior_observation,
            horizon_seconds=HORIZON_SECONDS["4h"],
            # A full-tail proof becomes stale on every valid producer append.
            # The range reader instead verifies SQLite health, canonical rows,
            # row chains, and both receipt classes in one read transaction.
            archive_integrity_proof=None,
            require_receipt_committed_by_observation=True,
        )
    except (Canonical5mArchiveError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError(
            f"TRAINING_SAMPLE_DURABLE_LABEL_PATH_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if rows is None:
        reasons = ",".join(str(reason) for reason in path_proof.get("rejection_reasons") or ())
        _fail(f"TRAINING_SAMPLE_DURABLE_LABEL_PATH_UNVERIFIED:{reasons}")
    range_raw = path_proof.get("range_proof")
    if not isinstance(range_raw, Mapping):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_RANGE_PROOF_MISSING")
    range_proof = dict(range_raw)
    required_path_evidence = (
        path_proof.get("status") == "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
        and path_proof.get("pit_available_at_verified") is True
        and path_proof.get("strictly_after_decision_verified") is True
        and path_proof.get("horizon_endpoint_verified") is True
        and range_proof.get("archive_integrity_proof_reused") is False
        and range_proof.get("archive_integrity_proof_current") is None
        and range_proof.get("sqlite_quick_check_verified") is True
        and range_proof.get("archive_schema_and_retention_verified") is True
        and range_proof.get("append_transaction_precommit_receipts_verified") is True
        and range_proof.get("postcommit_readback_receipts_verified") is True
        and range_proof.get("receipt_commit_cutoff_required") is True
        and range_proof.get("pit_available_at_verified") is True
        and range_proof.get("contiguous_path_verified") is True
    )
    label_path_sha256 = _valid_sha256(path_proof.get("label_path_sha256"))
    range_sha256 = _valid_sha256(range_proof.get("range_sha256"))
    if not required_path_evidence or label_path_sha256 is None or range_sha256 is None:
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_PATH_EVIDENCE_INVALID")
    causal_label_path = _causal_label_path_evidence(
        rows=rows,
        path_proof=path_proof,
        observation_cutoff=observation_cutoff,
    )
    source_key = trust_row.get("trusted_replay_label_candle_source_key")
    if type(source_key) is not str or not source_key:
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_SOURCE_KEY_INVALID")
    source_lineage_raw = trust_row.get("source_lineage")
    source_lineage = (
        dict(source_lineage_raw)
        if isinstance(source_lineage_raw, Mapping)
        else {}
    )
    reported_path_sha256 = _valid_sha256(
        source_lineage.get("durable_canonical_5m_label_path_sha256")
    )
    source_prefix = "durable_canonical_5m_label_archive:"
    source_locator, separator, source_path_sha256 = source_key.rpartition(":")
    if (
        not source_locator.startswith(source_prefix)
        or not source_locator.removeprefix(source_prefix)
        or separator != ":"
        or _valid_sha256(source_path_sha256) is None
    ):
        _fail(
            "TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISMATCH:"
            "trusted_replay_label_candle_source_key"
        )
    if (
        reported_path_sha256 is None
        or source_path_sha256 != reported_path_sha256
    ):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_SOURCE_LINEAGE_MISMATCH")
    rebuilt_row, rebuild_reasons = build_trusted_replay_row(
        snapshot,
        candles=rows,
        training_observed_at=observation_cutoff,
        label_candle_source_key=source_key,
    )
    if rebuilt_row is None:
        _fail(
            "TRAINING_SAMPLE_DURABLE_LABEL_REBUILD_INVALID:"
            + ",".join(str(reason) for reason in rebuild_reasons)
        )
    rebuilt_action = target_action_index(rebuilt_row.get("target_action"))
    if rebuilt_action is None or example.label_action_index != rebuilt_action:
        _fail("TRAINING_SAMPLE_ACTION_LABEL_MISMATCH")
    if _label_float64_sha256(example.label_expected_move_after_cost_bps) != (
        _label_float64_sha256(rebuilt_row.get("future_return_after_cost_bps"))
    ):
        _fail("TRAINING_SAMPLE_AFTER_COST_LABEL_MISMATCH")
    rebuilt_available_at = _canonical_utc(
        rebuilt_row.get("label_available_at"),
        reason="TRAINING_SAMPLE_REBUILT_LABEL_AVAILABLE_AT_INVALID",
    )
    if example.label_available_at != rebuilt_available_at:
        _fail("TRAINING_SAMPLE_LABEL_AVAILABLE_AT_MISMATCH")
    if example.label_timing_valid is not True:
        _fail("TRAINING_SAMPLE_LABEL_TIMING_INVALID")
    cost_components = rebuilt_row.get("cost_evidence_components")
    if not isinstance(cost_components, Mapping):
        _fail("TRAINING_SAMPLE_REBUILT_COST_EVIDENCE_MISSING")
    cost_receipts: dict[str, Any] = {}
    for component, aliases in COST_COMPONENT_FIELD_ALIASES.items():
        component_evidence = cost_components.get(component)
        if not isinstance(component_evidence, Mapping):
            _fail(f"TRAINING_SAMPLE_REBUILT_COST_COMPONENT_MISSING:{component}")
        selected_field = component_evidence.get("field")
        if selected_field not in aliases:
            _fail(f"TRAINING_SAMPLE_REBUILT_COST_FIELD_INVALID:{component}")
        cost_receipts[component] = _positive_feature_receipt_evidence(
            envelope=envelope,
            feature_name=str(selected_field),
            decision_time=decision_time,
        )
    trust_evidence = _authenticated_trust_evidence(
        trust_row=trust_row,
        rebuilt_row=rebuilt_row,
        causal_label_path_sha256=str(
            causal_label_path["causal_label_path_sha256"]
        ),
    )
    integrity_checkpoint = dict(archive_high_water)
    material = {
        "schema_version": LABEL_BINDING_SCHEMA_VERSION,
        "archive_path": str(archive.path),
        "archive_integrity_checkpoint": integrity_checkpoint,
        "archive_integrity_checkpoint_sha256": stable_json_sha256(integrity_checkpoint),
        "training_observed_at": observation_cutoff.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "receipt_visibility_semantics": "STRICTLY_BEFORE_TRAINING_OBSERVED_AT",
        "receipt_observation_strict_upper_bound": (
            strict_prior_observation.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            )
        ),
        "decision_time": example.decision_time,
        "label_available_at": rebuilt_available_at,
        "timeframe_finality_sha256": dict(snapshot.get("source_hashes") or {}).get(
            "timeframe_finality_sha256"
        ),
        "horizon_seconds": HORIZON_SECONDS["4h"],
        "causal_label_path": causal_label_path,
        "causal_label_path_sha256": causal_label_path[
            "causal_label_path_sha256"
        ],
        "label_range_start_close_time_ms": range_proof.get("start_close_time_ms"),
        "label_range_end_close_time_ms": range_proof.get("end_close_time_ms"),
        "label_path_candle_count": len(rows),
        "label_append_receipt_sha256s": range_proof.get("append_receipt_sha256"),
        "label_postcommit_receipt_sha256s": range_proof.get("postcommit_readback_receipt_sha256"),
        "label_receipts_committed_by_observation": True,
        "trusted_replay_label_candle_evidence_sha256": rebuilt_row.get(
            "trusted_replay_label_candle_evidence_sha256"
        ),
        "entry_feature_receipt": entry_receipt,
        "cost_feature_receipts": cost_receipts,
        "cost_evidence_hash": rebuilt_row.get("cost_evidence_hash"),
        "authenticated_trust_evidence": trust_evidence,
    }
    return {**material, "durable_label_binding_sha256": stable_json_sha256(material)}


def labeled_training_sample_identity(
    example: TrainingExample,
    item: FixedCutoffFeatureSnapshot,
    *,
    durable_label_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    """Bind one optimizer row to exact feature, target, and label lineage."""

    _feature_identity, feature_identity_sha256 = feature_sample_identity(item)
    if type(example.label_action_index) is not int or example.label_action_index < 0:
        _fail("TRAINING_SAMPLE_ACTION_LABEL_INVALID")
    payload_keys = list(example.payload_keys)
    if any(type(value) is not str or not value for value in payload_keys):
        _fail("TRAINING_SAMPLE_PAYLOAD_KEY_INVALID")
    if type(example.row_classification) is not str or not example.row_classification:
        _fail("TRAINING_SAMPLE_ROW_CLASSIFICATION_INVALID")
    if durable_label_binding.get("schema_version") != LABEL_BINDING_SCHEMA_VERSION:
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_BINDING_INVALID")
    durable_label_binding_sha256 = durable_label_binding.get("durable_label_binding_sha256")
    unsigned_label_binding = {
        str(key): value
        for key, value in durable_label_binding.items()
        if str(key) != "durable_label_binding_sha256"
    }
    if (
        _valid_sha256(durable_label_binding_sha256) is None
        or stable_json_sha256(unsigned_label_binding) != durable_label_binding_sha256
    ):
        _fail("TRAINING_SAMPLE_DURABLE_LABEL_BINDING_DIGEST_MISMATCH")
    identity = {
        "schema_version": SAMPLE_IDENTITY_DOMAIN,
        "feature_sample_identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
        "feature_sample_identity_sha256": feature_identity_sha256,
        "label_binding_schema_version": LABEL_BINDING_SCHEMA_VERSION,
        "durable_label_binding": dict(durable_label_binding),
        "durable_label_binding_sha256": durable_label_binding_sha256,
        "label_action_index": example.label_action_index,
        "label_expected_move_after_cost_bps_float64_sha256": (
            _label_float64_sha256(example.label_expected_move_after_cost_bps)
        ),
        "decision_time": example.decision_time,
        "label_available_at": example.label_available_at,
        "label_timing_source": example.label_timing_source,
        "label_timing_valid": example.label_timing_valid,
        "payload_keys": payload_keys,
        "row_classification": example.row_classification,
        "behavior_action_index": example.behavior_action_index,
        "behavior_action": example.behavior_action,
        "authenticated_trust_sha256": dict(
            durable_label_binding.get("authenticated_trust_evidence") or {}
        ).get("authenticated_trust_sha256"),
    }
    identity_sha256 = stable_json_sha256(identity)
    return identity, identity_sha256, feature_identity_sha256


def _float32_bytes(values: Sequence[Any]) -> bytes:
    encoded = bytearray()
    try:
        for value in values:
            numeric = float(value)
            if not math.isfinite(numeric):
                _fail("TRAINING_SAMPLE_NONFINITE_FEATURE_VALUE")
            encoded.extend(struct.pack(">f", numeric))
    except (OverflowError, struct.error, TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError("TRAINING_SAMPLE_FEATURE_VALUE_NOT_FLOAT32") from exc
    return bytes(encoded)


def _integrity_material(report: FeatureSnapshotIntegrityReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "verified_records": report.verified_records,
        "verified_append_receipts": report.verified_append_receipts,
        "verified_postcommit_receipts": report.verified_postcommit_receipts,
        "verified_projection_outbox_rows": report.verified_projection_outbox_rows,
        "total_record_bytes": report.total_record_bytes,
        "archive_chain_sha256": report.archive_chain_sha256,
        "integrity_verified": report.integrity_verified,
    }


def feature_ledger_fixed_observation_high_water(
    *,
    ledger: DurableFeatureSnapshotLedger,
    report: FeatureSnapshotIntegrityReport,
    observation_cutoff: datetime,
    scan_limit: int,
) -> dict[str, Any]:
    """Reproduce the verified immutable ledger prefix strictly before cutoff.

    ``report`` authenticates a physical head frontier captured by a completed
    streaming integrity pass.  The read below is bounded by that frontier, so a
    valid suffix committed between integrity verification and this transaction
    cannot enter the prefix, even when its clock equals the cycle clock.
    """

    if report.integrity_verified is not True:
        _fail("FEATURE_LEDGER_INTEGRITY_UNVERIFIED")
    if type(scan_limit) is not int or scan_limit <= 0:
        _fail("FEATURE_LEDGER_HIGH_WATER_SCAN_LIMIT_INVALID")
    strict_prior = _strict_prior_observation(
        observation_cutoff,
        reason="FEATURE_LEDGER_HIGH_WATER_OBSERVATION_INVALID",
    )
    strict_prior_us = _epoch_microseconds(strict_prior)
    transactions: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    try:
        connection = sqlite3.connect(
            ledger.path.as_uri() + "?mode=ro",
            uri=True,
            timeout=60.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            receipt_rows = list(
                connection.execute(
                    """
                    SELECT head.head_sequence, head.total_unique_rows,
                           head.archive_chain_sha256, head.head_sha256,
                           receipt.transaction_id,
                           receipt.receipt_sha256,
                           receipt.commit_prepared_at,
                           post.readback_receipt_sha256,
                           post.postcommit_readback_at
                    FROM feature_snapshot_ledger_heads AS head
                    JOIN feature_snapshot_append_receipts AS receipt
                      ON receipt.transaction_id = head.transaction_id
                    JOIN feature_snapshot_postcommit_receipts AS post
                      ON post.transaction_id = head.transaction_id
                    WHERE head.head_sequence <= ?
                      AND post.postcommit_readback_at_us <= ?
                    ORDER BY head.head_sequence ASC
                    LIMIT ?
                    """,
                    (
                        report.verified_append_receipts,
                        strict_prior_us,
                        scan_limit + 1,
                    ),
                )
            )
            if len(receipt_rows) > scan_limit:
                _fail("FEATURE_LEDGER_HIGH_WATER_SCAN_TRUNCATED")
            for expected_head_sequence, row in enumerate(receipt_rows, start=1):
                prepared = _strict_utc(row["commit_prepared_at"])
                postcommit = _strict_utc(row["postcommit_readback_at"])
                if (
                    int(row["head_sequence"]) != expected_head_sequence
                    or prepared is None
                    or postcommit is None
                    or postcommit < prepared
                    or postcommit > strict_prior
                    or _valid_sha256(row["receipt_sha256"]) is None
                    or _valid_sha256(row["readback_receipt_sha256"]) is None
                    or _valid_sha256(row["archive_chain_sha256"]) is None
                    or _valid_sha256(row["head_sha256"]) is None
                ):
                    _fail("FEATURE_LEDGER_HIGH_WATER_RECEIPT_INVALID")
                transactions.append(
                    {
                        "head_sequence": int(row["head_sequence"]),
                        "total_unique_rows": int(row["total_unique_rows"]),
                        "archive_chain_sha256": str(row["archive_chain_sha256"]),
                        "head_sha256": str(row["head_sha256"]),
                        "transaction_id": str(row["transaction_id"]),
                        "append_receipt_sha256": str(row["receipt_sha256"]),
                        "commit_prepared_at": str(row["commit_prepared_at"]),
                        "postcommit_receipt_sha256": str(
                            row["readback_receipt_sha256"]
                        ),
                        "postcommit_readback_at": str(
                            row["postcommit_readback_at"]
                        ),
                    }
                )
            prefix_records = (
                int(transactions[-1]["total_unique_rows"])
                if transactions
                else 0
            )
            if prefix_records > scan_limit:
                _fail("FEATURE_LEDGER_HIGH_WATER_SCAN_TRUNCATED")
            projection_rows = list(
                connection.execute(
                    """
                    SELECT record.sequence, length(record.record_json) AS record_bytes,
                           projection.projection_sha256,
                           receipt.receipt_sha256,
                           post.readback_receipt_sha256,
                           post.postcommit_readback_at
                    FROM feature_snapshot_records AS record
                    JOIN feature_snapshot_projection_outbox AS projection
                      ON projection.durable_snapshot_id = record.durable_snapshot_id
                    JOIN feature_snapshot_append_receipts AS receipt
                      ON receipt.transaction_id = record.append_transaction_id
                    JOIN feature_snapshot_postcommit_receipts AS post
                      ON post.transaction_id = record.append_transaction_id
                    WHERE record.sequence <= ?
                    ORDER BY record.sequence ASC
                    LIMIT ?
                    """,
                    (prefix_records, scan_limit + 1),
                )
            )
            if len(projection_rows) != prefix_records:
                _fail("FEATURE_LEDGER_HIGH_WATER_PROJECTION_COUNT_MISMATCH")
            for expected_sequence, row in enumerate(projection_rows, start=1):
                postcommit = _strict_utc(row["postcommit_readback_at"])
                if (
                    int(row["sequence"]) != expected_sequence
                    or postcommit is None
                    or postcommit > strict_prior
                    or _valid_sha256(row["projection_sha256"]) is None
                    or _valid_sha256(row["receipt_sha256"]) is None
                    or _valid_sha256(row["readback_receipt_sha256"]) is None
                ):
                    _fail("FEATURE_LEDGER_HIGH_WATER_PROJECTION_INVALID")
                projections.append(
                    {
                        "sequence": expected_sequence,
                        "record_bytes": int(row["record_bytes"]),
                        "projection_sha256": str(row["projection_sha256"]),
                        "append_receipt_sha256": str(row["receipt_sha256"]),
                        "postcommit_receipt_sha256": str(
                            row["readback_receipt_sha256"]
                        ),
                        "postcommit_readback_at": str(
                            row["postcommit_readback_at"]
                        ),
                    }
                )
            connection.rollback()
        finally:
            connection.close()
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(
            f"FEATURE_LEDGER_HIGH_WATER_READ_FAILED:{type(exc).__name__}"
        ) from exc
    clocks = [_strict_utc(row["postcommit_readback_at"]) for row in transactions]
    prefix_records = len(projections)
    selected_full_integrity_frontier = (
        len(transactions) == report.verified_append_receipts
        and prefix_records == report.verified_records
    )
    if selected_full_integrity_frontier and (
        len(transactions) != report.verified_postcommit_receipts
        or prefix_records != report.verified_projection_outbox_rows
        or sum(row["record_bytes"] for row in projections)
        != report.total_record_bytes
        or (
            transactions[-1]["archive_chain_sha256"]
            if transactions
            else FEATURE_LEDGER_GENESIS_SHA256
        )
        != report.archive_chain_sha256
    ):
        _fail("FEATURE_LEDGER_HIGH_WATER_INTEGRITY_FRONTIER_MISMATCH")
    material = {
        "schema_version": FEATURE_HIGH_WATER_SCHEMA_VERSION,
        "ledger_path": str(ledger.path),
        "training_observed_at": observation_cutoff.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "receipt_visibility_semantics": "STRICTLY_BEFORE_TRAINING_OBSERVED_AT",
        "strict_prior_observation": strict_prior.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "authenticated_prefix_head_sequence": len(transactions),
        "integrity_schema_version": report.schema_version,
        "verified_records": prefix_records,
        "verified_append_receipts": len(transactions),
        "verified_postcommit_receipts": len(transactions),
        "verified_projection_outbox_rows": prefix_records,
        "total_record_bytes": sum(row["record_bytes"] for row in projections),
        "archive_chain_sha256": (
            transactions[-1]["archive_chain_sha256"]
            if transactions
            else FEATURE_LEDGER_GENESIS_SHA256
        ),
        "ordered_transaction_receipts_sha256": stable_json_sha256(
            transactions
        ),
        "ordered_projection_receipts_sha256": stable_json_sha256(projections),
        "max_postcommit_readback_at": (
            max(clock for clock in clocks if clock is not None).isoformat() if clocks else None
        ),
        "fixed_observation_prefix_only": True,
        "later_valid_append_suffix_ignored": True,
        "full_ledger_integrity_verified_at_reproduction": True,
        "receipt_backed": True,
        "postcommit_readback_verified": True,
    }
    return {**material, "high_water_sha256": stable_json_sha256(material)}


def label_archive_fixed_observation_high_water(
    *,
    archive: DurableCanonical5mLabelArchive,
    integrity: Mapping[str, Any],
    observation_cutoff: datetime,
    scan_limit: int,
) -> dict[str, Any]:
    """Reproduce the verified immutable label prefix strictly before cutoff.

    Receipt order is the archive integrity verifier's authenticated, strictly
    increasing commit clock, never SQLite ``rowid``.  The integrity report's
    exact terminal clocks and receipt count bind the physical frontier, so a
    later valid suffix cannot reorder an older prefix or make a bounded cutoff
    permanently unverifiable.
    """

    raw_receipts = integrity.get("verified_append_receipts")
    raw_rows = integrity.get("verified_rows")
    if (
        integrity.get("archive_integrity_verified") is not True
        or type(raw_receipts) is not int
        or raw_receipts < 0
        or type(raw_rows) is not int
        or raw_rows < 0
        or integrity.get("verified_postcommit_readback_receipts")
        != raw_receipts
        or integrity.get("append_receipt_ordering_verified") is not True
        or integrity.get("append_receipt_order")
        != "COMMIT_PREPARED_AT_ASC_STRICT_UNIQUE"
        or integrity.get("append_receipt_cumulative_state_verified") is not True
        or integrity.get("postcommit_clock_causality_verified") is not True
    ):
        _fail("LABEL_ARCHIVE_HIGH_WATER_INTEGRITY_UNVERIFIED")
    if type(scan_limit) is not int or scan_limit <= 0:
        _fail("LABEL_ARCHIVE_HIGH_WATER_SCAN_LIMIT_INVALID")
    strict_prior = _strict_prior_observation(
        observation_cutoff,
        reason="LABEL_ARCHIVE_HIGH_WATER_OBSERVATION_INVALID",
    )
    # Archive receipt clocks are canonical millisecond strings.  Flooring the
    # one-microsecond predecessor implements receipt_time < observation for
    # both exact-millisecond and sub-millisecond observation clocks.
    strict_prior_text = strict_prior.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    rows: list[dict[str, Any]] = []
    try:
        connection = sqlite3.connect(
            archive.path.as_uri() + "?mode=ro",
            uri=True,
            timeout=60.0,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            if raw_receipts:
                frontier = connection.execute(
                    """
                    SELECT receipt.commit_prepared_at,
                           post.postcommit_readback_at
                    FROM canonical_5m_append_receipts AS receipt
                    JOIN canonical_5m_postcommit_readback_receipts AS post
                      ON post.transaction_id = receipt.transaction_id
                    ORDER BY receipt.commit_prepared_at ASC
                    LIMIT 1 OFFSET ?
                    """,
                    (raw_receipts - 1,),
                ).fetchone()
                if (
                    frontier is None
                    or str(frontier["commit_prepared_at"])
                    != integrity.get("verified_last_commit_prepared_at")
                    or str(frontier["postcommit_readback_at"])
                    != integrity.get("verified_last_postcommit_readback_at")
                ):
                    _fail("LABEL_ARCHIVE_HIGH_WATER_INTEGRITY_FRONTIER_MISMATCH")
            elif (
                integrity.get("verified_last_commit_prepared_at") is not None
                or integrity.get("verified_last_postcommit_readback_at")
                is not None
            ):
                _fail("LABEL_ARCHIVE_HIGH_WATER_INTEGRITY_FRONTIER_MISMATCH")
            cursor = connection.execute(
                """
                WITH authenticated_receipt_frontier AS (
                    SELECT ROW_NUMBER() OVER (
                               ORDER BY commit_prepared_at ASC
                           ) AS receipt_ordinal,
                           transaction_id, receipt_sha256,
                           commit_prepared_at, total_unique_rows,
                           archive_chain_sha256
                    FROM canonical_5m_append_receipts
                    ORDER BY commit_prepared_at ASC
                    LIMIT ?
                )
                SELECT receipt.receipt_ordinal,
                       receipt.transaction_id, receipt.receipt_sha256,
                       receipt.commit_prepared_at,
                       receipt.total_unique_rows,
                       receipt.archive_chain_sha256,
                       post.readback_receipt_sha256,
                       post.postcommit_readback_at
                FROM authenticated_receipt_frontier AS receipt
                JOIN canonical_5m_postcommit_readback_receipts AS post
                  ON post.transaction_id = receipt.transaction_id
                WHERE post.postcommit_readback_at <= ?
                ORDER BY receipt.receipt_ordinal ASC
                LIMIT ?
                """,
                (raw_receipts, strict_prior_text, scan_limit + 1),
            )
            scanned_receipts = 0
            for row in cursor:
                scanned_receipts += 1
                prepared = _strict_utc(row["commit_prepared_at"])
                postcommit = _strict_utc(row["postcommit_readback_at"])
                if (
                    prepared is None
                    or postcommit is None
                    or postcommit < prepared
                    or _valid_sha256(row["receipt_sha256"]) is None
                    or _valid_sha256(row["readback_receipt_sha256"]) is None
                    or _valid_sha256(row["archive_chain_sha256"]) is None
                    or int(row["receipt_ordinal"]) != scanned_receipts
                    or int(row["total_unique_rows"]) > raw_rows
                    or postcommit > strict_prior
                ):
                    _fail("LABEL_ARCHIVE_HIGH_WATER_RECEIPT_INVALID")
                rows.append(
                    {
                        "receipt_ordinal": scanned_receipts,
                        "transaction_id": str(row["transaction_id"]),
                        "append_receipt_sha256": str(row["receipt_sha256"]),
                        "commit_prepared_at": str(row["commit_prepared_at"]),
                        "total_unique_rows": int(row["total_unique_rows"]),
                        "archive_chain_sha256": str(
                            row["archive_chain_sha256"]
                        ),
                        "postcommit_receipt_sha256": str(row["readback_receipt_sha256"]),
                        "postcommit_readback_at": str(row["postcommit_readback_at"]),
                    }
                )
            connection.rollback()
        finally:
            connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise TrainingSampleIdentityError(
            f"LABEL_ARCHIVE_HIGH_WATER_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if len(rows) > scan_limit:
        _fail("LABEL_ARCHIVE_HIGH_WATER_SCAN_TRUNCATED")
    clocks: list[datetime] = []
    for row in rows:
        prepared = _strict_utc(row["commit_prepared_at"])
        postcommit = _strict_utc(row["postcommit_readback_at"])
        if prepared is None or postcommit is None or postcommit < prepared:
            _fail("LABEL_ARCHIVE_HIGH_WATER_RECEIPT_CLOCK_INVALID")
        clocks.append(postcommit)
    prefix_records = max(
        (int(row["total_unique_rows"]) for row in rows),
        default=0,
    )
    if prefix_records > scan_limit:
        _fail("LABEL_ARCHIVE_HIGH_WATER_SCAN_TRUNCATED")
    prefix_chain_candidates = {
        str(row["archive_chain_sha256"])
        for row in rows
        if int(row["total_unique_rows"]) == prefix_records
    }
    if rows and len(prefix_chain_candidates) != 1:
        _fail("LABEL_ARCHIVE_HIGH_WATER_CHAIN_FRONTIER_AMBIGUOUS")
    prefix_chain = (
        next(iter(prefix_chain_candidates))
        if prefix_chain_candidates
        else LABEL_ARCHIVE_GENESIS_SHA256
    )
    material = {
        "schema_version": LABEL_HIGH_WATER_SCHEMA_VERSION,
        "archive_path": str(archive.path),
        "training_observed_at": observation_cutoff.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "receipt_visibility_semantics": "STRICTLY_BEFORE_TRAINING_OBSERVED_AT",
        "strict_prior_observation": strict_prior.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "receipt_order": "COMMIT_PREPARED_AT_ASC_STRICT_UNIQUE",
        "archive_schema_version": integrity.get("schema_version"),
        "verified_rows": prefix_records,
        "verified_max_sequence": prefix_records,
        "verified_append_receipts": len(rows),
        "verified_postcommit_readback_receipts": len(rows),
        "archive_chain_sha256": prefix_chain,
        "ordered_transaction_receipts_sha256": stable_json_sha256(rows),
        "max_postcommit_readback_at": max(clocks).isoformat() if clocks else None,
        "fixed_observation_prefix_only": True,
        "later_valid_append_suffix_ignored": True,
        "full_archive_integrity_verified_at_reproduction": True,
        "receipt_backed": True,
        "postcommit_readback_verified": True,
    }
    return {**material, "high_water_sha256": stable_json_sha256(material)}


def _scan_fixed_cutoff(
    *,
    ledger: DurableFeatureSnapshotLedger,
    observation_cutoff: str,
    scan_limit: int,
) -> tuple[list[FixedCutoffFeatureSnapshot], FeatureSnapshotIntegrityReport]:
    if type(scan_limit) is not int or not 0 < scan_limit <= MAX_SAMPLE_IDENTITIES:
        _fail("FEATURE_LEDGER_SCAN_LIMIT_INVALID")
    before = ledger.verify_integrity_streaming()
    if before.integrity_verified is not True:
        _fail("FEATURE_LEDGER_INTEGRITY_UNVERIFIED")
    parsed_observation = _strict_utc(observation_cutoff)
    if parsed_observation is None:
        _fail("FEATURE_LEDGER_OBSERVATION_CUTOFF_INVALID")
    try:
        before_high_water = feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=before,
            observation_cutoff=parsed_observation,
            scan_limit=scan_limit,
        )
    except TrainingSampleIdentityError as exc:
        if str(exc) == "FEATURE_LEDGER_HIGH_WATER_SCAN_TRUNCATED":
            _fail("FEATURE_LEDGER_SCAN_TRUNCATED_NO_PREFIX_ADMISSION")
        raise
    if int(before_high_water["verified_records"]) > scan_limit:
        _fail("FEATURE_LEDGER_SCAN_TRUNCATED_NO_PREFIX_ADMISSION")
    strict_prior = _strict_prior_observation(
        parsed_observation,
        reason="FEATURE_LEDGER_OBSERVATION_CUTOFF_INVALID",
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    rows: list[FixedCutoffFeatureSnapshot] = []
    after_sequence = 0
    while len(rows) <= scan_limit:
        page = ledger.query_fixed_cutoff(
            decision_time_cutoff=strict_prior,
            training_observed_at=strict_prior,
            limit=min(
                FEATURE_LEDGER_SAFE_QUERY_PAGE_ROWS,
                scan_limit + 1 - len(rows),
            ),
            after_sequence=after_sequence,
        )
        if not page:
            break
        rows.extend(page)
        after_sequence = page[-1].sequence
        if len(rows) > scan_limit:
            _fail("FEATURE_LEDGER_SCAN_TRUNCATED_NO_PREFIX_ADMISSION")
    after = ledger.verify_integrity_streaming()
    after_high_water = feature_ledger_fixed_observation_high_water(
        ledger=ledger,
        report=after,
        observation_cutoff=parsed_observation,
        scan_limit=scan_limit,
    )
    if before_high_water != after_high_water:
        _fail("FEATURE_LEDGER_CHANGED_DURING_SAMPLE_INVENTORY")
    return rows, after


def _example_binding_reasons(
    example: TrainingExample,
    item: FixedCutoffFeatureSnapshot,
    *,
    observation_cutoff: datetime,
) -> list[str]:
    record = item.record
    envelope_raw = record.get("frozen_envelope")
    if not isinstance(envelope_raw, Mapping):
        return ["DURABLE_FEATURE_ENVELOPE_MISSING"]
    envelope = dict(envelope_raw)
    tensor = example.tensor
    reasons: list[str] = []
    if envelope.get("provenance_classification") != PROVENANCE_CANONICAL_V3:
        reasons.append("LEGACY_FEATURE_SAMPLE_FORBIDDEN")
    if envelope.get("strict_training_eligible") is not True:
        reasons.append("DURABLE_FEATURE_SAMPLE_NOT_STRICT_TRAINING_ELIGIBLE")
    exact_pairs = (
        ("SYMBOL", str(example.symbol).upper(), envelope.get("symbol")),
        ("TIMEFRAME", example.timeframe, envelope.get("timeframe")),
        ("TENSOR_SYMBOL", str(tensor.symbol).upper(), envelope.get("symbol")),
        ("TENSOR_TIMEFRAME", tensor.timeframe, envelope.get("timeframe")),
        (
            "FEATURE_SNAPSHOT_ID",
            tensor.feature_snapshot_id,
            envelope.get("feature_snapshot_id"),
        ),
        ("TENSOR_ID", tensor.tensor_id, envelope.get("original_tensor_id")),
        (
            "TENSOR_DECISION_TIME",
            tensor.decision_time,
            envelope.get("tensor_decision_time"),
        ),
        (
            "PPO_DECISION_TIME",
            example.decision_time,
            envelope.get("ppo_decision_time"),
        ),
    )
    for label, observed, expected in exact_pairs:
        if observed != expected:
            reasons.append(f"TRAINING_SAMPLE_{label}_MISMATCH")
    vector_pairs = (
        ("FEATURE_NAMES", tensor.feature_names, envelope.get("ordered_feature_names")),
        ("MISSING_MASK", tensor.missing_mask, envelope.get("missing_mask")),
        ("STALE_MASK", tensor.stale_mask, envelope.get("stale_mask")),
        (
            "SOURCE_AVAILABILITY",
            tensor.source_availability,
            envelope.get("source_availability_mask"),
        ),
        (
            "SOURCE_LABELS",
            tensor.source_labels,
            envelope.get("ordered_feature_source_labels"),
        ),
        (
            "TEMPORAL_REJECTION_REASONS",
            tensor.temporal_rejection_reasons,
            envelope.get("temporal_rejection_reasons"),
        ),
    )
    for label, observed, expected in vector_pairs:
        if list(observed) != list(expected or ()):
            reasons.append(f"TRAINING_SAMPLE_{label}_MISMATCH")
    if tuple(tensor.source_availability) != tuple(tensor.source_availability_vector):
        reasons.append("TRAINING_SAMPLE_SOURCE_AVAILABILITY_VECTOR_MISMATCH")
    try:
        if _float32_bytes(tensor.values) != _float32_bytes(
            list(envelope.get("feature_values") or ())
        ):
            reasons.append("TRAINING_SAMPLE_FEATURE_VALUES_MISMATCH")
    except TrainingSampleIdentityError as exc:
        reasons.append(str(exc))
    expected_missing_names = [
        str(name)
        for name, flag in zip(
            envelope.get("ordered_feature_names") or (),
            envelope.get("missing_mask") or (),
            strict=False,
        )
        if int(flag) == 1
    ]
    expected_stale_names = [
        str(name)
        for name, flag in zip(
            envelope.get("ordered_feature_names") or (),
            envelope.get("stale_mask") or (),
            strict=False,
        )
        if int(flag) == 1
    ]
    if list(tensor.missing_feature_names) != expected_missing_names:
        reasons.append("TRAINING_SAMPLE_MISSING_FEATURE_NAMES_MISMATCH")
    if list(tensor.stale_feature_names) != expected_stale_names:
        reasons.append("TRAINING_SAMPLE_STALE_FEATURE_NAMES_MISMATCH")
    decision = _strict_utc(example.decision_time)
    label_available = _strict_utc(example.label_available_at)
    if decision is None:
        reasons.append("TRAINING_SAMPLE_DECISION_TIME_INVALID")
    if example.label_timing_valid is not True or label_available is None:
        reasons.append("TRAINING_SAMPLE_LABEL_AVAILABILITY_UNVERIFIED")
    elif label_available >= observation_cutoff:
        reasons.append("TRAINING_SAMPLE_LABEL_AVAILABLE_AFTER_OBSERVATION")
    elif decision is not None and label_available < decision:
        reasons.append("TRAINING_SAMPLE_LABEL_AVAILABLE_BEFORE_DECISION")
    trust_row = example.trust_row if isinstance(example.trust_row, Mapping) else {}
    optional_bindings = {
        "durable_snapshot_id": record.get("durable_snapshot_id"),
        "feature_snapshot_record_sha256": record.get("record_sha256"),
        "feature_snapshot_append_receipt_sha256": item.append_receipt_sha256,
        "feature_snapshot_postcommit_receipt_sha256": (item.postcommit_receipt_sha256),
    }
    for field, expected in optional_bindings.items():
        observed = trust_row.get(field)
        if observed not in (None, "") and observed != expected:
            reasons.append(f"TRAINING_SAMPLE_{field.upper()}_CONFLICT")
    return sorted(set(reasons))


def _inventory_for_examples(
    examples: Sequence[TrainingExample],
    *,
    by_tensor_id: Mapping[str, FixedCutoffFeatureSnapshot],
    label_archive: DurableCanonical5mLabelArchive,
    label_archive_integrity: Mapping[str, Any],
    label_archive_high_water: Mapping[str, Any],
    observation_cutoff: datetime,
    lane: str,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    identities: list[str] = []
    feature_identities: list[str] = []
    bindings: list[dict[str, Any]] = []
    for ordinal, example in enumerate(examples):
        if type(example) is not TrainingExample:
            _fail(f"{lane}_TRAINING_EXAMPLE_TYPE_INVALID:{ordinal}")
        item = by_tensor_id.get(str(example.tensor.tensor_id))
        if item is None:
            _fail(f"{lane}_TRAINING_SAMPLE_NOT_IN_DURABLE_V3_LEDGER:{ordinal}")
        reasons = _example_binding_reasons(
            example,
            item,
            observation_cutoff=observation_cutoff,
        )
        if reasons:
            _fail(f"{lane}_TRAINING_SAMPLE_BINDING_INVALID:" + ",".join(reasons))
        durable_label_binding = _durable_label_binding(
            example=example,
            item=item,
            archive=label_archive,
            archive_integrity=label_archive_integrity,
            archive_high_water=label_archive_high_water,
            observation_cutoff=observation_cutoff,
        )
        identity, identity_sha256, feature_identity_sha256 = labeled_training_sample_identity(
            example,
            item,
            durable_label_binding=durable_label_binding,
        )
        identities.append(identity_sha256)
        feature_identities.append(feature_identity_sha256)
        bindings.append(
            {
                "sample_identity_sha256": identity_sha256,
                "sample_identity": identity,
                "feature_sample_identity_sha256": feature_identity_sha256,
                "sequence": item.sequence,
                "append_transaction_id": item.append_transaction_id,
                "append_receipt_sha256": item.append_receipt_sha256,
                "postcommit_receipt_sha256": item.postcommit_receipt_sha256,
                "postcommit_readback_at": item.postcommit_readback_at,
                "frozen_envelope_sha256": item.record.get("frozen_envelope_sha256"),
                "model_vector_sha256": dict(item.record.get("frozen_envelope") or {}).get(
                    "model_vector_sha256"
                ),
            }
        )
    if len(identities) != len(set(identities)):
        _fail(f"{lane}_TRAINING_SAMPLE_IDENTITY_DUPLICATE")
    if len(feature_identities) != len(set(feature_identities)):
        _fail(f"{lane}_FEATURE_SAMPLE_IDENTITY_DUPLICATE")
    bindings.sort(key=lambda row: str(row["sample_identity_sha256"]))
    return sorted(identities), sorted(feature_identities), bindings


def build_checkpoint_sample_inventory(
    *,
    training_examples: Sequence[TrainingExample],
    validation_examples: Sequence[TrainingExample] = (),
    repo_root: Path,
    training_observed_at: str,
    scan_limit: int = MAX_SAMPLE_IDENTITIES,
) -> dict[str, Any]:
    """Authenticate the exact planned/actual train and validation examples."""

    observation_text = _canonical_utc(
        training_observed_at,
        reason="TRAINING_OBSERVATION_CUTOFF_INVALID",
    )
    observation = _strict_utc(observation_text)
    assert observation is not None
    if len(training_examples) + len(validation_examples) > MAX_SAMPLE_IDENTITIES:
        _fail("CHECKPOINT_SAMPLE_INVENTORY_EXCEEDS_BOUND")
    if not training_examples and not validation_examples:
        empty_set = sample_identity_set_sha256([])
        empty_feature_set = feature_identity_set_sha256([])
        return {
            "training_sample_identity_sha256s": [],
            "training_sample_identity_inventory_complete": True,
            "training_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
            "training_sample_identity_set_sha256": empty_set,
            "training_sample_count": 0,
            "training_sample_provenance_bindings_sha256": stable_json_sha256([]),
            "training_feature_identity_sha256s": [],
            "training_feature_identity_inventory_complete": True,
            "training_feature_identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
            "training_feature_identity_set_sha256": empty_feature_set,
            "training_feature_identity_count": 0,
            "validation_sample_identity_sha256s": [],
            "validation_sample_identity_inventory_complete": True,
            "validation_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
            "validation_sample_identity_set_sha256": empty_set,
            "validation_sample_count": 0,
            "validation_sample_provenance_bindings_sha256": stable_json_sha256([]),
            "validation_feature_identity_sha256s": [],
            "validation_feature_identity_inventory_complete": True,
            "validation_feature_identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
            "validation_feature_identity_set_sha256": empty_feature_set,
            "validation_feature_identity_count": 0,
            "sample_inventory_training_observed_at": observation_text,
            "sample_inventory_durable_v3_only": True,
            "sample_inventory_mutable_redis_used": False,
            "optional_missing_evidence_semantics": (OPTIONAL_MISSING_EVIDENCE_SEMANTICS),
            "optional_missing_typed_negative_receipts_verified": False,
            "optional_missing_observed_zero_claimed": False,
        }
    root = Path(repo_root).resolve()
    ledger_path = default_feature_snapshot_ledger_path(root)
    label_archive_path = default_canonical_5m_label_archive_path(root)
    if not ledger_path.is_file():
        _fail("DURABLE_FEATURE_SNAPSHOT_LEDGER_REQUIRED")
    if not label_archive_path.is_file():
        _fail("DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED")
    ledger = DurableFeatureSnapshotLedger(ledger_path)
    label_archive = DurableCanonical5mLabelArchive(label_archive_path)
    try:
        items, report = _scan_fixed_cutoff(
            ledger=ledger,
            observation_cutoff=observation_text,
            scan_limit=scan_limit,
        )
        label_integrity = label_archive.verify_integrity()
    except (
        Canonical5mArchiveError,
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(
            f"DURABLE_FEATURE_LEDGER_INVENTORY_FAILED:{type(exc).__name__}"
        ) from exc
    if label_integrity.get("archive_integrity_verified") is not True:
        _fail("LABEL_ARCHIVE_INTEGRITY_UNVERIFIED")
    label_high_water = label_archive_fixed_observation_high_water(
        archive=label_archive,
        integrity=label_integrity,
        observation_cutoff=observation,
        scan_limit=scan_limit,
    )
    by_tensor_id: dict[str, FixedCutoffFeatureSnapshot] = {}
    for item in items:
        envelope = item.record.get("frozen_envelope")
        tensor_id = (
            str(envelope.get("original_tensor_id") or "") if isinstance(envelope, Mapping) else ""
        )
        if not tensor_id or tensor_id in by_tensor_id:
            _fail("DURABLE_FEATURE_LEDGER_TENSOR_IDENTITY_DUPLICATE")
        by_tensor_id[tensor_id] = item
    train_ids, train_feature_ids, train_bindings = _inventory_for_examples(
        training_examples,
        by_tensor_id=by_tensor_id,
        label_archive=label_archive,
        label_archive_integrity=label_integrity,
        label_archive_high_water=label_high_water,
        observation_cutoff=observation,
        lane="OPTIMIZER",
    )
    validation_ids, validation_feature_ids, validation_bindings = _inventory_for_examples(
        validation_examples,
        by_tensor_id=by_tensor_id,
        label_archive=label_archive,
        label_archive_integrity=label_integrity,
        label_archive_high_water=label_high_water,
        observation_cutoff=observation,
        lane="VALIDATION",
    )
    if set(train_ids) & set(validation_ids):
        _fail("TRAINING_VALIDATION_SAMPLE_IDENTITY_OVERLAP")
    if set(train_feature_ids) & set(validation_feature_ids):
        _fail("TRAINING_VALIDATION_FEATURE_IDENTITY_OVERLAP")
    feature_high_water = feature_ledger_fixed_observation_high_water(
        ledger=ledger,
        report=report,
        observation_cutoff=observation,
        scan_limit=scan_limit,
    )
    try:
        completion = ledger.verify_integrity_streaming()
        completion_label_integrity = label_archive.verify_integrity()
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(
            f"FEATURE_LEDGER_COMPLETION_PROOF_FAILED:{type(exc).__name__}"
        ) from exc
    completion_feature_high_water = feature_ledger_fixed_observation_high_water(
        ledger=ledger,
        report=completion,
        observation_cutoff=observation,
        scan_limit=scan_limit,
    )
    completion_label_high_water = label_archive_fixed_observation_high_water(
        archive=label_archive,
        integrity=completion_label_integrity,
        observation_cutoff=observation,
        scan_limit=scan_limit,
    )
    if completion_feature_high_water != feature_high_water:
        _fail("FEATURE_LEDGER_CHANGED_DURING_SAMPLE_INVENTORY")
    if completion_label_high_water != label_high_water:
        _fail("LABEL_ARCHIVE_CHANGED_DURING_SAMPLE_INVENTORY")
    return {
        "training_sample_identity_sha256s": train_ids,
        "training_sample_identity_inventory_complete": True,
        "training_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
        "training_sample_identity_set_sha256": sample_identity_set_sha256(train_ids),
        "training_sample_count": len(train_ids),
        "training_sample_provenance_bindings_sha256": stable_json_sha256(train_bindings),
        "training_feature_identity_sha256s": train_feature_ids,
        "training_feature_identity_inventory_complete": True,
        "training_feature_identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
        "training_feature_identity_set_sha256": feature_identity_set_sha256(train_feature_ids),
        "training_feature_identity_count": len(train_feature_ids),
        "validation_sample_identity_sha256s": validation_ids,
        "validation_sample_identity_inventory_complete": True,
        "validation_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
        "validation_sample_identity_set_sha256": sample_identity_set_sha256(validation_ids),
        "validation_sample_count": len(validation_ids),
        "validation_sample_provenance_bindings_sha256": stable_json_sha256(validation_bindings),
        "validation_feature_identity_sha256s": validation_feature_ids,
        "validation_feature_identity_inventory_complete": True,
        "validation_feature_identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
        "validation_feature_identity_set_sha256": feature_identity_set_sha256(
            validation_feature_ids
        ),
        "validation_feature_identity_count": len(validation_feature_ids),
        "sample_inventory_training_observed_at": observation_text,
        "sample_inventory_feature_ledger_high_water": feature_high_water,
        "sample_inventory_feature_ledger_integrity": _integrity_material(report),
        "sample_inventory_label_archive_high_water": label_high_water,
        "sample_inventory_label_archive_integrity": dict(label_integrity),
        "sample_inventory_label_archive_verified_once": True,
        "sample_inventory_durable_v3_only": True,
        "sample_inventory_mutable_redis_used": False,
        "optional_missing_evidence_semantics": (OPTIONAL_MISSING_EVIDENCE_SEMANTICS),
        "optional_missing_typed_negative_receipts_verified": False,
        "optional_missing_observed_zero_claimed": False,
        "_authenticated_items": items,
        "_training_bindings": train_bindings,
        "_validation_bindings": validation_bindings,
    }


def checkpoint_inventory_evidence(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Return only strict-JSON checkpoint evidence, excluding working objects."""

    return {str(key): value for key, value in inventory.items() if not str(key).startswith("_")}


def _window(rows: Sequence[tuple[datetime, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "start_decision_time": (
            rows[0][0].isoformat(timespec="microseconds").replace("+00:00", "Z") if rows else None
        ),
        "end_decision_time": (
            rows[-1][0].isoformat(timespec="microseconds").replace("+00:00", "Z") if rows else None
        ),
    }


def prepare_checkpoint_partition_manifest(
    *,
    inventory: Mapping[str, Any],
    training_partition_digest: str,
    repo_root: Path,
    generated_utc: str,
    scan_limit: int = MAX_SAMPLE_IDENTITIES,
) -> dict[str, Any]:
    """Prepare a v2 manifest whose holdout starts after actual validation."""

    if _valid_sha256(training_partition_digest) is None:
        _fail("TRAINING_PARTITION_DIGEST_INVALID")
    generated_text = _canonical_utc(
        generated_utc,
        reason="MANIFEST_GENERATED_UTC_INVALID",
    )
    generated = _strict_utc(generated_text)
    assert generated is not None
    root = Path(repo_root).resolve()
    ledger_path = default_feature_snapshot_ledger_path(root)
    label_path = default_canonical_5m_label_archive_path(root)
    if not ledger_path.is_file():
        _fail("DURABLE_FEATURE_SNAPSHOT_LEDGER_REQUIRED")
    if not label_path.is_file():
        _fail("DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED")
    ledger = DurableFeatureSnapshotLedger(ledger_path)
    label_archive = DurableCanonical5mLabelArchive(label_path)
    try:
        items, feature_report = _scan_fixed_cutoff(
            ledger=ledger,
            observation_cutoff=generated_text,
            scan_limit=scan_limit,
        )
        label_integrity = label_archive.verify_integrity()
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(
            f"CHECKPOINT_PARTITION_SOURCE_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if label_integrity.get("archive_integrity_verified") is not True:
        _fail("LABEL_ARCHIVE_INTEGRITY_UNVERIFIED")
    feature_high_water = feature_ledger_fixed_observation_high_water(
        ledger=ledger,
        report=feature_report,
        observation_cutoff=generated,
        scan_limit=scan_limit,
    )
    label_high_water = label_archive_fixed_observation_high_water(
        archive=label_archive,
        integrity=label_integrity,
        observation_cutoff=generated,
        scan_limit=scan_limit,
    )
    rows: list[tuple[datetime, str]] = []
    identity_by_sha: dict[str, tuple[datetime, str]] = {}
    for item in items:
        identity, identity_sha = feature_sample_identity(item)
        decision = _strict_utc(identity.get("ppo_decision_time"))
        if decision is None:
            _fail("FEATURE_LEDGER_PPO_DECISION_TIME_INVALID")
        if identity_sha in identity_by_sha:
            _fail("FEATURE_LEDGER_SAMPLE_IDENTITY_DUPLICATE")
        row = (decision, identity_sha)
        rows.append(row)
        identity_by_sha[identity_sha] = row
    rows.sort(key=lambda row: (row[0], row[1]))
    training_ids = [str(value) for value in inventory.get("training_sample_identity_sha256s") or ()]
    validation_ids = [
        str(value) for value in inventory.get("validation_sample_identity_sha256s") or ()
    ]
    training_feature_ids = [
        str(value) for value in inventory.get("training_feature_identity_sha256s") or ()
    ]
    validation_feature_ids = [
        str(value) for value in inventory.get("validation_feature_identity_sha256s") or ()
    ]
    if not training_ids:
        _fail("CHECKPOINT_TRAINING_SAMPLE_INVENTORY_EMPTY")
    if len(training_feature_ids) != len(training_ids):
        _fail("CHECKPOINT_TRAINING_FEATURE_IDENTITY_COUNT_MISMATCH")
    if len(validation_feature_ids) != len(validation_ids):
        _fail("CHECKPOINT_VALIDATION_FEATURE_IDENTITY_COUNT_MISMATCH")
    if any(identity not in identity_by_sha for identity in training_feature_ids):
        _fail("CHECKPOINT_TRAINING_SAMPLE_NOT_IN_MANIFEST_LEDGER")
    if any(identity not in identity_by_sha for identity in validation_feature_ids):
        _fail("CHECKPOINT_VALIDATION_SAMPLE_NOT_IN_MANIFEST_LEDGER")
    training_end = max(identity_by_sha[identity][0] for identity in training_feature_ids)
    if validation_feature_ids:
        validation_start = min(identity_by_sha[identity][0] for identity in validation_feature_ids)
        validation_end = max(identity_by_sha[identity][0] for identity in validation_feature_ids)
        if training_end >= validation_start:
            _fail("TRAINING_VALIDATION_TEMPORAL_OVERLAP")
    else:
        validation_start = None
        validation_end = None
    boundary = validation_end or training_end
    training_rows = [row for row in rows if row[0] <= training_end]
    validation_rows = (
        [row for row in rows if training_end < row[0] <= validation_end]
        if validation_end is not None
        else []
    )
    holdout_rows = [row for row in rows if row[0] > boundary]
    if not holdout_rows:
        _fail("AUTHENTICATED_HOLDOUT_PARTITION_EMPTY")
    holdout_ids = [row[1] for row in holdout_rows]
    if set(training_feature_ids) & set(holdout_ids):
        _fail("CHECKPOINT_TRAINING_HOLDOUT_SAMPLE_OVERLAP")
    if set(validation_feature_ids) & set(holdout_ids):
        _fail("CHECKPOINT_VALIDATION_HOLDOUT_SAMPLE_OVERLAP")
    if generated <= holdout_rows[-1][0]:
        _fail("MANIFEST_GENERATED_UTC_NOT_AFTER_HOLDOUT_END")
    partition = {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "identity_domain": FEATURE_SAMPLE_IDENTITY_DOMAIN,
        "training_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
        "validation_sample_identity_domain": SAMPLE_IDENTITY_DOMAIN,
        "training_partition_digest": training_partition_digest,
        "training_sample_count": len(training_ids),
        "training_sample_identity_set_sha256": sample_identity_set_sha256(training_ids),
        "validation_sample_count": len(validation_ids),
        "validation_sample_identity_set_sha256": sample_identity_set_sha256(validation_ids),
        "training_feature_identity_count": len(training_feature_ids),
        "training_feature_identity_set_sha256": feature_identity_set_sha256(training_feature_ids),
        "validation_feature_identity_count": len(validation_feature_ids),
        "validation_feature_identity_set_sha256": feature_identity_set_sha256(
            validation_feature_ids
        ),
        "holdout_sample_count": len(holdout_ids),
        "holdout_sample_identity_set_sha256": feature_identity_set_sha256(holdout_ids),
        "training_validation_disjoint": True,
        "training_holdout_disjoint": True,
        "validation_holdout_disjoint": True,
        "optional_missing_evidence_semantics": (OPTIONAL_MISSING_EVIDENCE_SEMANTICS),
        "optional_missing_typed_negative_receipts_verified": False,
        "optional_missing_observed_zero_claimed": False,
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_utc": generated_text,
        "split_method": MANIFEST_SPLIT_METHOD,
        "training_window": _window(training_rows),
        "validation_window": _window(validation_rows),
        "holdout_window": _window(holdout_rows),
        "temporal_overlap": False,
        "feature_ledger_high_water": feature_high_water,
        "label_archive_high_water": label_high_water,
        "partition_evidence": partition,
        "checkpoint_sample_inventory_sha256": stable_json_sha256(
            checkpoint_inventory_evidence(inventory)
        ),
        "mutable_redis_used": False,
    }
    manifest["manifest_payload_sha256"] = stable_json_sha256(manifest)
    try:
        completion_feature = ledger.verify_integrity_streaming()
        completion_label = label_archive.verify_integrity()
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrainingSampleIdentityError(
            f"MANIFEST_COMPLETION_PROOF_FAILED:{type(exc).__name__}"
        ) from exc
    completion_feature_high_water = feature_ledger_fixed_observation_high_water(
        ledger=ledger,
        report=completion_feature,
        observation_cutoff=generated,
        scan_limit=scan_limit,
    )
    completion_label_high_water = label_archive_fixed_observation_high_water(
        archive=label_archive,
        integrity=completion_label,
        observation_cutoff=generated,
        scan_limit=scan_limit,
    )
    if completion_feature_high_water != feature_high_water:
        _fail("FEATURE_LEDGER_CHANGED_DURING_MANIFEST_PREPARATION")
    if completion_label_high_water != label_high_water:
        _fail("LABEL_ARCHIVE_CHANGED_DURING_MANIFEST_PREPARATION")
    return manifest


def manifest_paths(repo_root: Path) -> tuple[Path, Path, Path]:
    root = Path(repo_root).resolve()
    return (
        root / "v2/frontend/public/operator_runtime/v2_native_trainer/latest" / MANIFEST_FILENAME,
        root / "claude_worklog/final_readiness" / GOAL_ID / "latest" / MANIFEST_FILENAME,
        root / "goal_state" / GOAL_ID / MANIFEST_FILENAME,
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = (
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(raw) <= 0 or len(raw) > MAX_MANIFEST_BYTES:
        _fail("HOLDOUT_MANIFEST_BYTES_OUT_OF_BOUNDS")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _strict_manifest_json(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> Never:
        _fail(f"HOLDOUT_MANIFEST_NONFINITE_CONSTANT:{value}")

    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                _fail("HOLDOUT_MANIFEST_DUPLICATE_JSON_KEY")
            payload[key] = value
        return payload

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise TrainingSampleIdentityError("HOLDOUT_MANIFEST_STRICT_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        _fail("HOLDOUT_MANIFEST_ROOT_NOT_OBJECT")
    return payload


def _verify_manifest_payload(
    payload: Mapping[str, Any],
    *,
    require_checkpoint_binding: bool,
) -> dict[str, Any]:
    copied = dict(payload)
    if copied.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        _fail("HOLDOUT_MANIFEST_SCHEMA_INVALID")
    supplied_digest = copied.get("manifest_payload_sha256")
    unsigned = {
        str(key): value for key, value in copied.items() if str(key) != "manifest_payload_sha256"
    }
    if _valid_sha256(supplied_digest) is None or supplied_digest != stable_json_sha256(unsigned):
        _fail("HOLDOUT_MANIFEST_PAYLOAD_DIGEST_MISMATCH")
    if require_checkpoint_binding:
        binding = copied.get("checkpoint_binding")
        if not isinstance(binding, Mapping):
            _fail("HOLDOUT_MANIFEST_CHECKPOINT_BINDING_MISSING")
        checkpoint_id = binding.get("checkpoint_id")
        if (
            type(checkpoint_id) is not str
            or not checkpoint_id
            or Path(checkpoint_id).name != checkpoint_id
        ):
            _fail("HOLDOUT_MANIFEST_CHECKPOINT_ID_INVALID")
        for field_name in (
            "checkpoint_evidence_digest",
            "training_partition_digest",
            "training_sample_identity_set_sha256",
            "validation_sample_identity_set_sha256",
            "training_feature_identity_set_sha256",
            "validation_feature_identity_set_sha256",
        ):
            if _valid_sha256(binding.get(field_name)) is None:
                _fail("HOLDOUT_MANIFEST_CHECKPOINT_BINDING_" f"{field_name.upper()}_INVALID")
    return copied


def _read_manifest_path(
    path: Path,
    *,
    require_checkpoint_binding: bool,
) -> tuple[dict[str, Any], bytes]:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                _fail("HOLDOUT_MANIFEST_NOT_REGULAR_FILE")
            if metadata.st_size <= 0 or metadata.st_size > MAX_MANIFEST_BYTES:
                _fail("HOLDOUT_MANIFEST_BYTES_OUT_OF_BOUNDS")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) != metadata.st_size:
                _fail("HOLDOUT_MANIFEST_CHANGED_WHILE_READING")
        finally:
            os.close(descriptor)
    except TrainingSampleIdentityError:
        raise
    except OSError as exc:
        raise TrainingSampleIdentityError(
            f"HOLDOUT_MANIFEST_READ_FAILED:{type(exc).__name__}"
        ) from exc
    payload = _strict_manifest_json(raw)
    return (
        _verify_manifest_payload(
            payload,
            require_checkpoint_binding=require_checkpoint_binding,
        ),
        raw,
    )


def read_published_checkpoint_partition_manifest(
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Read only the goal-state primary, the sole activation authority."""

    primary_path = manifest_paths(repo_root)[-1]
    payload, _raw = _read_manifest_path(
        primary_path,
        require_checkpoint_binding=True,
    )
    return payload


def checkpoint_partition_manifest_projection_status(
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Audit secondary projections without granting them activation authority."""

    public_path, worklog_path, primary_path = manifest_paths(repo_root)
    primary_payload, primary_raw = _read_manifest_path(
        primary_path,
        require_checkpoint_binding=True,
    )
    projections: list[dict[str, Any]] = []
    for role, path in (("public", public_path), ("worklog", worklog_path)):
        try:
            payload, raw = _read_manifest_path(
                path,
                require_checkpoint_binding=True,
            )
        except TrainingSampleIdentityError as exc:
            projections.append(
                {
                    "role": role,
                    "path": str(path),
                    "readable_and_verified": False,
                    "matches_primary_payload": False,
                    "matches_primary_bytes": False,
                    "mismatch_reason": str(exc),
                }
            )
            continue
        payload_matches = payload == primary_payload
        bytes_match = raw == primary_raw
        projections.append(
            {
                "role": role,
                "path": str(path),
                "readable_and_verified": True,
                "matches_primary_payload": payload_matches,
                "matches_primary_bytes": bytes_match,
                "mismatch_reason": (
                    None
                    if payload_matches and bytes_match
                    else "HOLDOUT_MANIFEST_PROJECTION_READBACK_MISMATCH"
                ),
            }
        )
    all_match = all(
        projection["readable_and_verified"] is True
        and projection["matches_primary_payload"] is True
        and projection["matches_primary_bytes"] is True
        for projection in projections
    )
    return {
        "schema_version": PROJECTION_AUDIT_SCHEMA_VERSION,
        "primary_path": str(primary_path),
        "primary_manifest_payload_sha256": primary_payload.get("manifest_payload_sha256"),
        "primary_is_sole_activation_authority": True,
        "secondary_projections": projections,
        "all_secondary_projections_match_primary": all_match,
    }


def publish_checkpoint_partition_manifest(
    *,
    manifest: Mapping[str, Any],
    repo_root: Path,
) -> tuple[str, ...]:
    """Publish secondary projections first and consumer-priority primary last."""

    verified_manifest = _verify_manifest_payload(
        manifest,
        require_checkpoint_binding=True,
    )
    public_path, worklog_path, primary_path = manifest_paths(repo_root)
    lock_path = primary_path.with_name(".trusted_replay_manifest_publication.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TrainingSampleIdentityError(
                "HOLDOUT_MANIFEST_PUBLICATION_LOCK_CONTENDED"
            ) from exc
        for path in (public_path, worklog_path, primary_path):
            _atomic_write_json(path, verified_manifest)
            readback, _raw = _read_manifest_path(
                path,
                require_checkpoint_binding=True,
            )
            if readback != verified_manifest:
                _fail("HOLDOUT_MANIFEST_POSTCOMMIT_READBACK_MISMATCH")
        activated = read_published_checkpoint_partition_manifest(repo_root=repo_root)
        if activated != verified_manifest:
            _fail("HOLDOUT_MANIFEST_PRIMARY_ACTIVATION_READBACK_MISMATCH")
        projection_status = checkpoint_partition_manifest_projection_status(repo_root=repo_root)
        if projection_status["all_secondary_projections_match_primary"] is not True:
            _fail("HOLDOUT_MANIFEST_PROJECTION_READBACK_MISMATCH")
    finally:
        os.close(descriptor)
    return tuple(str(path) for path in (public_path, worklog_path, primary_path))


__all__ = [
    "FEATURE_HIGH_WATER_SCHEMA_VERSION",
    "FEATURE_SAMPLE_IDENTITY_DOMAIN",
    "GOAL_ID",
    "LABEL_HIGH_WATER_SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "MAX_SAMPLE_IDENTITIES",
    "PARTITION_SCHEMA_VERSION",
    "LABEL_BINDING_SCHEMA_VERSION",
    "OPTIONAL_MISSING_EVIDENCE_SEMANTICS",
    "SAMPLE_IDENTITY_DOMAIN",
    "TrainingSampleIdentityError",
    "build_checkpoint_sample_inventory",
    "checkpoint_partition_manifest_projection_status",
    "checkpoint_inventory_evidence",
    "feature_identity_set_sha256",
    "feature_ledger_fixed_observation_high_water",
    "feature_sample_identity",
    "label_archive_fixed_observation_high_water",
    "labeled_training_sample_identity",
    "manifest_paths",
    "prepare_checkpoint_partition_manifest",
    "publish_checkpoint_partition_manifest",
    "read_published_checkpoint_partition_manifest",
    "sample_identity_set_sha256",
    "stable_json_sha256",
]
