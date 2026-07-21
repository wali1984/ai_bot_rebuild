"""Durable coordinator record for exact on-policy paper entries.

The behavior-receipt archive is filesystem durable while the paper book is
published to Redis and JSON state.  Those stores cannot share one transaction.
This SQLite outbox seals an admitted fill and a revision-bound canonical paper
state transition before ``ENTRY_ACCEPTED`` is appended.  It then authenticates
the exact lifecycle event and read-after-write commit evidence as idempotent
state transitions.  A subsequent paper cycle can inspect a row left between
those transitions without inventing or re-running an old market decision.

SQLite durability does *not* make the receipt archive, Redis, JSON ledgers, or
margin state economically atomic.  The integration contract remains: the
paper state owner must apply ``exact_on_policy_paper_state_transition`` with a
compare-and-swap against its sealed prior revision/hash, write every economic
effect represented by the canonical delta, verify the resulting revision/hash
by readback, and only then call :meth:`mark_committed`.  A fill without that
complete deterministic command fails at :meth:`prepare`; this module must not
be treated as proof that an external state write happened.

Nothing in this module routes to live execution.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OUTBOX_SCHEMA_VERSION = "v2_exact_on_policy_entry_outbox_v2"
OUTBOX_RECORD_SCHEMA_VERSION = "v2_exact_on_policy_entry_outbox_record_v2"
PAPER_STATE_TRANSITION_SCHEMA_VERSION = (
    "v2_exact_on_policy_paper_state_transition_v1"
)
COMMIT_BINDING_SCHEMA_VERSION = "v2_exact_on_policy_entry_commit_binding_v1"
LIFECYCLE_EVENT_SCHEMA_VERSION = "v2_behavior_receipt_lifecycle_event_v1"
ENTRY_EVENT_TYPE = "ENTRY_ACCEPTED"
STATE_TRANSITION_FIELD = "exact_on_policy_paper_state_transition"
STATE_TRANSITION_KIND = "EXACT_ON_POLICY_FLAT_TO_OPEN"
STATE_PREPARED = "PREPARED"
STATE_ENTRY_EVENT_APPENDED = "ENTRY_EVENT_APPENDED"
STATE_COMMITTED = "COMMITTED"
OUTBOX_STATES = (
    STATE_PREPARED,
    STATE_ENTRY_EVENT_APPENDED,
    STATE_COMMITTED,
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_OUTBOX_RELATIVE_PATH = Path(
    ".local_data/v2_paper_trade_management/exact_on_policy_entry_outbox.sqlite3"
)


class ExactOnPolicyEntryOutboxError(ValueError):
    """Raised when an outbox record is incomplete, corrupt, or conflicting."""


@dataclass(frozen=True)
class ExactOnPolicyEntryOutboxRecord:
    record_id: str
    receipt_hash: str
    paper_fill_id: str
    state: str
    sealed_fill_sha256: str
    sealed_fill: dict[str, Any]
    prepared_at: str
    entry_event_hash: str | None
    entry_event_binding: dict[str, Any] | None
    entry_event_recorded_at: str | None
    commit_evidence_sha256: str | None
    commit_evidence: dict[str, Any] | None
    committed_at: str | None

    def materialized_fill(self) -> dict[str, Any]:
        """Return the sealed fill with only proven lifecycle state overlaid."""

        fill = deepcopy(self.sealed_fill)
        if self.state in {STATE_ENTRY_EVENT_APPENDED, STATE_COMMITTED}:
            fill.update(
                {
                    "behavior_policy_receipt_archive_verified_at_entry": True,
                    "behavior_policy_receipt_archive_entry_event_hash": (
                        self.entry_event_hash
                    ),
                    "behavior_policy_receipt_archive_retention_required": True,
                    "behavior_policy_receipt_entry_event_pending": False,
                    "on_policy_action_receipt_valid": True,
                    "on_policy_action_receipt_prevalidated": True,
                    "exact_on_policy_entry_outbox_record_id": self.record_id,
                    "exact_on_policy_entry_outbox_state": self.state,
                    "exact_on_policy_sealed_fill_sha256": (
                        self.sealed_fill_sha256
                    ),
                }
            )
        return fill


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def default_outbox_path(repo_root: Path | None = None) -> Path:
    return (repo_root or _repo_root()) / DEFAULT_OUTBOX_RELATIVE_PATH


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_NON_CANONICAL_JSON_PAYLOAD"
        ) from exc
    return encoded.encode("utf-8")


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _strict_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _paper_fill_id(fill: Mapping[str, Any]) -> str:
    for field in (
        "fill_id",
        "paper_intent_id",
        "intent_id",
        "ledger_row_id",
    ):
        value = fill.get(field)
        if value not in (None, ""):
            return str(value)
    raise ExactOnPolicyEntryOutboxError("OUTBOX_PAPER_FILL_ID_MISSING")


def _strict_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _same_strict_utc(left: Any, right: Any) -> bool:
    left_time = _strict_utc(left)
    right_time = _strict_utc(right)
    return left_time is not None and left_time == right_time


def _validated_behavior_receipt_hash(
    fill: Mapping[str, Any],
) -> str:
    receipt = fill.get("behavior_policy_receipt")
    fill_receipt_hash = str(fill.get("behavior_policy_receipt_hash") or "")
    if not isinstance(receipt, Mapping):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_BEHAVIOR_RECEIPT_MISSING"
        )
    receipt_material = dict(receipt)
    embedded_receipt_hash = str(receipt_material.pop("receipt_hash", ""))
    if not SHA256_RE.fullmatch(embedded_receipt_hash):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_BEHAVIOR_RECEIPT_HASH_INVALID"
        )
    if _canonical_sha256(receipt_material) != embedded_receipt_hash:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_BEHAVIOR_RECEIPT_CONTENT_HASH_MISMATCH"
        )
    if fill_receipt_hash != embedded_receipt_hash:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_BEHAVIOR_RECEIPT_HASH_BINDING_MISMATCH"
        )
    return embedded_receipt_hash


def _validated_state_transition(
    fill: Mapping[str, Any],
    *,
    receipt_hash: str,
    paper_fill_id: str,
) -> tuple[dict[str, Any], str]:
    contract = fill.get(STATE_TRANSITION_FIELD)
    if not isinstance(contract, Mapping):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ECONOMIC_STATE_TRANSITION_MISSING"
        )
    row = dict(contract)
    supplied_hash = str(row.pop("contract_sha256", ""))
    if not SHA256_RE.fullmatch(supplied_hash):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ECONOMIC_STATE_TRANSITION_HASH_INVALID"
        )
    if _canonical_sha256(row) != supplied_hash:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ECONOMIC_STATE_TRANSITION_CONTENT_HASH_MISMATCH"
        )
    reasons: list[str] = []
    if row.get("schema_version") != PAPER_STATE_TRANSITION_SCHEMA_VERSION:
        reasons.append("SCHEMA_VERSION_INVALID")
    if row.get("transition_kind") != STATE_TRANSITION_KIND:
        reasons.append("TRANSITION_KIND_INVALID")
    if str(row.get("paper_fill_id") or "") != paper_fill_id:
        reasons.append("PAPER_FILL_ID_MISMATCH")
    if str(row.get("behavior_policy_receipt_hash") or "") != receipt_hash:
        reasons.append("RECEIPT_HASH_MISMATCH")
    if not str(row.get("canonical_state_owner") or "").strip():
        reasons.append("CANONICAL_STATE_OWNER_MISSING")
    if not str(row.get("canonical_state_key") or "").strip():
        reasons.append("CANONICAL_STATE_KEY_MISSING")
    prior_revision = _strict_int(row.get("prior_state_revision"))
    next_revision = _strict_int(row.get("next_state_revision"))
    if prior_revision is None or prior_revision < 0:
        reasons.append("PRIOR_STATE_REVISION_INVALID")
    if (
        next_revision is None
        or prior_revision is None
        or next_revision != prior_revision + 1
    ):
        reasons.append("NEXT_STATE_REVISION_INVALID")
    prior_hash = str(row.get("prior_state_sha256") or "")
    next_hash = str(row.get("next_state_sha256") or "")
    if not SHA256_RE.fullmatch(prior_hash):
        reasons.append("PRIOR_STATE_HASH_INVALID")
    if not SHA256_RE.fullmatch(next_hash):
        reasons.append("NEXT_STATE_HASH_INVALID")
    if prior_hash == next_hash:
        reasons.append("STATE_HASH_DID_NOT_CHANGE")
    if row.get("canonical_state_delta_complete") is not True:
        reasons.append("CANONICAL_STATE_DELTA_NOT_DECLARED_COMPLETE")
    delta = row.get("canonical_state_delta")
    delta_hash = str(row.get("canonical_state_delta_sha256") or "")
    if not isinstance(delta, Mapping) or not delta:
        reasons.append("CANONICAL_STATE_DELTA_MISSING")
    elif not SHA256_RE.fullmatch(delta_hash):
        reasons.append("CANONICAL_STATE_DELTA_HASH_INVALID")
    elif _canonical_sha256(delta) != delta_hash:
        reasons.append("CANONICAL_STATE_DELTA_HASH_MISMATCH")
    else:
        for field, expected in (
            ("transition_kind", STATE_TRANSITION_KIND),
            ("paper_fill_id", paper_fill_id),
            ("behavior_policy_receipt_hash", receipt_hash),
            ("symbol", fill.get("symbol")),
            ("side", fill.get("side")),
            ("quantity", fill.get("quantity")),
            ("fill_price", fill.get("fill_price")),
        ):
            if delta.get(field) != expected:
                reasons.append(
                    "CANONICAL_STATE_DELTA_" + field.upper() + "_MISMATCH"
                )
        mutations = delta.get("state_mutations")
        if not isinstance(mutations, list) or not mutations:
            reasons.append("CANONICAL_STATE_MUTATIONS_MISSING")
        elif any(not isinstance(item, Mapping) for item in mutations):
            reasons.append("CANONICAL_STATE_MUTATION_INVALID")
        else:
            mutation_identities: list[tuple[str, str]] = []
            for mutation in mutations:
                component = str(mutation.get("state_component") or "").strip()
                state_key = str(mutation.get("state_key") or "").strip()
                operation = str(mutation.get("operation") or "").strip()
                mutation_delta = mutation.get("canonical_delta")
                mutation_delta_hash = str(
                    mutation.get("canonical_delta_sha256") or ""
                )
                if not component:
                    reasons.append("CANONICAL_STATE_COMPONENT_MISSING")
                if not state_key:
                    reasons.append("CANONICAL_STATE_MUTATION_KEY_MISSING")
                if not operation:
                    reasons.append("CANONICAL_STATE_MUTATION_OPERATION_MISSING")
                if not isinstance(mutation_delta, Mapping) or not mutation_delta:
                    reasons.append("CANONICAL_STATE_MUTATION_DELTA_MISSING")
                elif not SHA256_RE.fullmatch(mutation_delta_hash):
                    reasons.append("CANONICAL_STATE_MUTATION_HASH_INVALID")
                elif _canonical_sha256(mutation_delta) != mutation_delta_hash:
                    reasons.append("CANONICAL_STATE_MUTATION_HASH_MISMATCH")
                mutation_identities.append((component, state_key))
            if len(mutation_identities) != len(set(mutation_identities)):
                reasons.append("CANONICAL_STATE_MUTATION_IDENTITY_DUPLICATE")
    if row.get("paper_only") is not True:
        reasons.append("PAPER_ONLY_NOT_TRUE")
    if row.get("routes_to_live") is not False:
        reasons.append("ROUTES_TO_LIVE_NOT_FALSE")
    if row.get("places_real_order") is not False:
        reasons.append("PLACES_REAL_ORDER_NOT_FALSE")
    if reasons:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ECONOMIC_STATE_TRANSITION_INVALID:"
            + ",".join(sorted(set(reasons)))
        )
    return dict(contract), supplied_hash


def _validate_sealed_fill(fill: Mapping[str, Any], *, prepared_at: str) -> None:
    reasons: list[str] = []
    if fill.get("paper_only") is not True:
        reasons.append("PAPER_ONLY_NOT_TRUE")
    for field in (
        "routes_to_live",
        "places_real_order",
        "live_order",
        "test_order",
        "order_submitted",
        "test_order_submitted",
        "leverage_mutated",
        "margin_mutated",
    ):
        if fill.get(field) is True:
            reasons.append(f"{field.upper()}_TRUE")
    if fill.get("ppo_on_policy_entry_fields_present") is not True:
        reasons.append("PPO_ON_POLICY_ENTRY_FIELDS_NOT_PRESENT")
    if fill.get("on_policy_action_receipt_prevalidated") is not True:
        reasons.append("ON_POLICY_RECEIPT_NOT_PREVALIDATED")
    if fill.get("behavior_policy_receipt_entry_event_pending") is not True:
        reasons.append("ENTRY_EVENT_NOT_PENDING")
    if fill.get("on_policy_action_receipt_valid") is True:
        reasons.append("ENTRY_RECEIPT_PREMATURELY_MARKED_VALID")
    receipt_hash = _validated_behavior_receipt_hash(fill)
    receipt = fill["behavior_policy_receipt"]
    assert isinstance(receipt, Mapping)
    paper_fill_id = _paper_fill_id(fill)
    _validated_state_transition(
        fill,
        receipt_hash=receipt_hash,
        paper_fill_id=paper_fill_id,
    )
    receipt_cutoff = _strict_utc(receipt.get("feature_cutoff"))
    receipt_available = _strict_utc(receipt.get("available_at"))
    receipt_candle_close = _strict_utc(receipt.get("candle_close_time"))
    receipt_decision = _strict_utc(receipt.get("decision_time"))
    decision_time = _strict_utc(fill.get("decision_time"))
    final_admission_time = _strict_utc(
        fill.get("paper_final_admission_decision_time")
    )
    fill_price_observed_at = _strict_utc(fill.get("fill_price_observed_at"))
    entry_time = _strict_utc(fill.get("entry_time"))
    execution_time = _strict_utc(fill.get("execution_time"))
    materialized_time = _strict_utc(fill.get("paper_fill_materialized_at"))
    prepared_time = _strict_utc(prepared_at)
    for field, parsed in (
        ("RECEIPT_FEATURE_CUTOFF", receipt_cutoff),
        ("RECEIPT_AVAILABLE_AT", receipt_available),
        ("RECEIPT_CANDLE_CLOSE_TIME", receipt_candle_close),
        ("RECEIPT_DECISION_TIME", receipt_decision),
        ("DECISION_TIME", decision_time),
        ("PAPER_FINAL_ADMISSION_DECISION_TIME", final_admission_time),
        ("FILL_PRICE_OBSERVED_AT", fill_price_observed_at),
        ("ENTRY_TIME", entry_time),
        ("EXECUTION_TIME", execution_time),
        ("PAPER_FILL_MATERIALIZED_AT", materialized_time),
        ("PREPARED_AT", prepared_time),
    ):
        if parsed is None:
            reasons.append(f"{field}_MISSING_OR_NOT_STRICT_AWARE_UTC")
    if None not in (
        receipt_candle_close,
        receipt_cutoff,
        receipt_available,
        receipt_decision,
    ):
        assert receipt_candle_close is not None
        assert receipt_cutoff is not None
        assert receipt_available is not None
        assert receipt_decision is not None
        if receipt_candle_close > receipt_cutoff:
            reasons.append("RECEIPT_CANDLE_CLOSE_AFTER_FEATURE_CUTOFF")
        if receipt_cutoff > receipt_available:
            reasons.append("RECEIPT_FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
        if receipt_available >= receipt_decision:
            reasons.append("RECEIPT_AVAILABLE_AT_NOT_BEFORE_DECISION_TIME")
    if receipt_decision is not None and decision_time is not None:
        if receipt_decision != decision_time:
            reasons.append("RECEIPT_DECISION_TIME_BINDING_MISMATCH")
    for field in ("prediction_id", "symbol", "timeframe"):
        if str(receipt.get(field) or "") != str(fill.get(field) or ""):
            reasons.append(f"RECEIPT_{field.upper()}_BINDING_MISMATCH")
    if None not in (entry_time, execution_time, materialized_time):
        if not entry_time == execution_time == materialized_time:
            reasons.append("ENTRY_EXECUTION_MATERIALIZATION_TIME_MISMATCH")
    if decision_time is not None and final_admission_time is not None:
        if decision_time > final_admission_time:
            reasons.append("DECISION_TIME_AFTER_FINAL_ADMISSION_TIME")
    if decision_time is not None and fill_price_observed_at is not None:
        if decision_time > fill_price_observed_at:
            reasons.append("DECISION_TIME_AFTER_FILL_PRICE_OBSERVATION")
    if entry_time is not None:
        if final_admission_time is not None and final_admission_time > entry_time:
            reasons.append("FINAL_ADMISSION_TIME_AFTER_ENTRY_TIME")
        if (
            fill_price_observed_at is not None
            and fill_price_observed_at > entry_time
        ):
            reasons.append("FILL_PRICE_OBSERVATION_AFTER_ENTRY_TIME")
        if prepared_time is not None and entry_time > prepared_time:
            reasons.append("ENTRY_TIME_AFTER_OUTBOX_PREPARED_AT")
    if reasons:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_SEALED_FILL_INVALID:" + ",".join(sorted(set(reasons)))
        )
    _canonical_json_bytes(fill)


def _record_id_for(
    *,
    receipt_hash: str,
    paper_fill_id: str,
    sealed_fill_sha256: str,
    prepared_at: str,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": OUTBOX_RECORD_SCHEMA_VERSION,
            "receipt_hash": receipt_hash,
            "paper_fill_id": paper_fill_id,
            "sealed_fill_sha256": sealed_fill_sha256,
            "prepared_at": prepared_at,
        }
    )


def _entry_event_material(
    *,
    receipt_hash: str,
    binding: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": LIFECYCLE_EVENT_SCHEMA_VERSION,
        "receipt_hash": receipt_hash,
        "event_type": ENTRY_EVENT_TYPE,
        "recorded_at": recorded_at,
        "binding": dict(binding),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _commit_binding_sha256(
    evidence: Mapping[str, Any],
    *,
    committed_at: str,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": COMMIT_BINDING_SCHEMA_VERSION,
            "committed_at": committed_at,
            "commit_evidence": dict(evidence),
        }
    )


def _validate_entry_event_values(
    record: ExactOnPolicyEntryOutboxRecord,
    *,
    event_hash: Any,
    binding: Any,
    recorded_at: Any,
) -> None:
    if not SHA256_RE.fullmatch(str(event_hash or "")):
        raise ExactOnPolicyEntryOutboxError("OUTBOX_ENTRY_EVENT_HASH_INVALID")
    if not isinstance(binding, Mapping):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_BINDING_INVALID"
        )
    event_time = _strict_utc(recorded_at)
    prepared_time = _strict_utc(record.prepared_at)
    if event_time is None:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_RECORDED_AT_INVALID"
        )
    if prepared_time is None or event_time < prepared_time:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_BEFORE_PREPARED_AT"
        )
    fill = record.sealed_fill
    receipt_hash = _validated_behavior_receipt_hash(fill)
    _, transition_hash = _validated_state_transition(
        fill,
        receipt_hash=receipt_hash,
        paper_fill_id=record.paper_fill_id,
    )
    expected_exact = {
        "paper_fill_id": record.paper_fill_id,
        "prediction_id": fill.get("prediction_id"),
        "symbol": fill.get("symbol"),
        "timeframe": fill.get("timeframe"),
        "decision_time": fill.get("decision_time"),
        "entry_time": fill.get("entry_time"),
        "execution_time": fill.get("execution_time"),
        "paper_fill_materialized_at": fill.get("paper_fill_materialized_at"),
        "behavior_policy_receipt_hash": record.receipt_hash,
        "exact_on_policy_entry_outbox_record_id": record.record_id,
        "sealed_fill_sha256": record.sealed_fill_sha256,
        "paper_state_transition_contract_sha256": transition_hash,
    }
    mismatches = [
        field
        for field, expected in expected_exact.items()
        if binding.get(field) != expected
    ]
    if mismatches:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_BINDING_MISMATCH:"
            + ",".join(sorted(mismatches))
        )
    if not SHA256_RE.fullmatch(
        str(binding.get("entry_fee_schedule_evidence_sha256") or "")
    ):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_FEE_SCHEDULE_HASH_INVALID"
        )
    expected_event_hash = _canonical_sha256(
        _entry_event_material(
            receipt_hash=record.receipt_hash,
            binding=binding,
            recorded_at=str(recorded_at),
        )
    )
    if str(event_hash) != expected_event_hash:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_CONTENT_HASH_MISMATCH"
        )


def _validate_commit_values(
    record: ExactOnPolicyEntryOutboxRecord,
    *,
    evidence_sha256: Any,
    evidence: Any,
    committed_at: Any,
) -> None:
    if not isinstance(evidence, Mapping):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_COMMIT_EVIDENCE_INVALID"
        )
    committed_time = _strict_utc(committed_at)
    event_time = _strict_utc(record.entry_event_recorded_at)
    if committed_time is None:
        raise ExactOnPolicyEntryOutboxError("OUTBOX_COMMITTED_AT_INVALID")
    if event_time is None or committed_time < event_time:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_COMMIT_BEFORE_ENTRY_EVENT"
        )
    receipt_hash = _validated_behavior_receipt_hash(record.sealed_fill)
    transition, transition_hash = _validated_state_transition(
        record.sealed_fill,
        receipt_hash=receipt_hash,
        paper_fill_id=record.paper_fill_id,
    )
    delta_hash = str(transition.get("canonical_state_delta_sha256") or "")
    expected_exact = {
        "record_id": record.record_id,
        "paper_fill_id": record.paper_fill_id,
        "behavior_policy_receipt_hash": record.receipt_hash,
        "sealed_fill_sha256": record.sealed_fill_sha256,
        "entry_event_hash": record.entry_event_hash,
        "paper_state_transition_contract_sha256": transition_hash,
        "canonical_state_delta_sha256": delta_hash,
        "applied_prior_state_revision": transition.get(
            "prior_state_revision"
        ),
        "applied_prior_state_sha256": transition.get("prior_state_sha256"),
        "committed_state_revision": transition.get("next_state_revision"),
        "committed_state_sha256": transition.get("next_state_sha256"),
        "materialized_outbox_state": STATE_ENTRY_EVENT_APPENDED,
    }
    mismatches = [
        field
        for field, expected in expected_exact.items()
        if evidence.get(field) != expected
    ]
    if mismatches:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_COMMIT_BINDING_MISMATCH:"
            + ",".join(sorted(mismatches))
        )
    for field in (
        "state_materialized",
        "state_readback_verified",
        "accepted_state_written",
        "open_or_terminal_state_written",
    ):
        if evidence.get(field) is not True:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_COMMIT_" + field.upper() + "_NOT_TRUE"
            )
    state_materialized_time = _strict_utc(evidence.get("state_materialized_at"))
    if state_materialized_time is None:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_COMMIT_STATE_MATERIALIZED_AT_INVALID"
        )
    if event_time > state_materialized_time:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_STATE_MATERIALIZED_BEFORE_ENTRY_EVENT"
        )
    if state_materialized_time > committed_time:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_STATE_MATERIALIZED_AFTER_COMMIT"
        )
    expected_hash = _commit_binding_sha256(
        evidence,
        committed_at=str(committed_at),
    )
    if str(evidence_sha256 or "") != expected_hash:
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_COMMIT_EVIDENCE_HASH_MISMATCH"
        )


def _validate_record_state(record: ExactOnPolicyEntryOutboxRecord) -> None:
    entry_values = (
        record.entry_event_hash,
        record.entry_event_binding,
        record.entry_event_recorded_at,
    )
    commit_values = (
        record.commit_evidence_sha256,
        record.commit_evidence,
        record.committed_at,
    )
    if record.state == STATE_PREPARED:
        if any(value is not None for value in entry_values + commit_values):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_PREPARED_STATE_HAS_LATER_TRANSITION_DATA"
            )
        return
    if any(value is None for value in entry_values):
        raise ExactOnPolicyEntryOutboxError(
            "OUTBOX_ENTRY_EVENT_STATE_INCOMPLETE"
        )
    _validate_entry_event_values(
        record,
        event_hash=record.entry_event_hash,
        binding=record.entry_event_binding,
        recorded_at=record.entry_event_recorded_at,
    )
    if record.state == STATE_ENTRY_EVENT_APPENDED:
        if any(value is not None for value in commit_values):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_ENTRY_EVENT_STATE_HAS_COMMIT_DATA"
            )
        return
    if any(value is None for value in commit_values):
        raise ExactOnPolicyEntryOutboxError("OUTBOX_COMMITTED_STATE_INCOMPLETE")
    _validate_commit_values(
        record,
        evidence_sha256=record.commit_evidence_sha256,
        evidence=record.commit_evidence,
        committed_at=record.committed_at,
    )


class ExactOnPolicyEntryOutbox:
    """SQLite-backed idempotent outbox for paper entry lifecycle commits."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_outbox_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS exact_entry_outbox (
                    record_id TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    paper_fill_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL CHECK (
                        state IN ('PREPARED','ENTRY_EVENT_APPENDED','COMMITTED')
                    ),
                    sealed_fill_sha256 TEXT NOT NULL,
                    sealed_fill_json TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    entry_event_hash TEXT,
                    entry_event_binding_json TEXT,
                    entry_event_recorded_at TEXT,
                    commit_evidence_sha256 TEXT,
                    commit_evidence_json TEXT,
                    committed_at TEXT
                )
                """
            )
            try:
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    exact_entry_outbox_paper_fill_id_uq
                    ON exact_entry_outbox (paper_fill_id)
                    """
                )
            except sqlite3.IntegrityError as exc:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_EXISTING_PAPER_FILL_ID_DUPLICATE"
                ) from exc
            index_rows = connection.execute(
                "PRAGMA index_list('exact_entry_outbox')"
            ).fetchall()
            matching_indexes = [
                row
                for row in index_rows
                if str(row["name"])
                == "exact_entry_outbox_paper_fill_id_uq"
            ]
            if (
                len(matching_indexes) != 1
                or int(matching_indexes[0]["unique"]) != 1
            ):
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_PAPER_FILL_ID_UNIQUE_INDEX_INVALID"
                )
            index_columns = connection.execute(
                "PRAGMA index_info('exact_entry_outbox_paper_fill_id_uq')"
            ).fetchall()
            if [str(row["name"]) for row in index_columns] != [
                "paper_fill_id"
            ]:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_PAPER_FILL_ID_UNIQUE_INDEX_INVALID"
                )
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_SQLITE_INTEGRITY_CHECK_FAILED"
                )
        try:
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_PERMISSION_HARDENING_FAILED"
            ) from exc

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ExactOnPolicyEntryOutboxRecord:
        try:
            sealed_fill = json.loads(row["sealed_fill_json"])
            entry_binding = (
                json.loads(row["entry_event_binding_json"])
                if row["entry_event_binding_json"] is not None
                else None
            )
            commit_evidence = (
                json.loads(row["commit_evidence_json"])
                if row["commit_evidence_json"] is not None
                else None
            )
        except (TypeError, json.JSONDecodeError) as exc:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_STORED_JSON_UNREADABLE"
            ) from exc
        if not isinstance(sealed_fill, dict):
            raise ExactOnPolicyEntryOutboxError("OUTBOX_SEALED_FILL_NOT_MAPPING")
        sealed_fill_sha256 = str(row["sealed_fill_sha256"] or "")
        if (
            not SHA256_RE.fullmatch(sealed_fill_sha256)
            or _canonical_sha256(sealed_fill) != sealed_fill_sha256
        ):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_SEALED_FILL_HASH_MISMATCH"
            )
        state = str(row["state"] or "")
        if state not in OUTBOX_STATES:
            raise ExactOnPolicyEntryOutboxError("OUTBOX_STATE_INVALID")
        record_id = str(row["record_id"] or "")
        receipt_hash = str(row["receipt_hash"] or "")
        paper_fill_id = str(row["paper_fill_id"] or "")
        prepared_at = str(row["prepared_at"] or "")
        if not SHA256_RE.fullmatch(record_id):
            raise ExactOnPolicyEntryOutboxError("OUTBOX_RECORD_ID_INVALID")
        if not SHA256_RE.fullmatch(receipt_hash):
            raise ExactOnPolicyEntryOutboxError("OUTBOX_RECEIPT_HASH_INVALID")
        _validate_sealed_fill(sealed_fill, prepared_at=prepared_at)
        derived_receipt_hash = _validated_behavior_receipt_hash(sealed_fill)
        derived_paper_fill_id = _paper_fill_id(sealed_fill)
        if receipt_hash != derived_receipt_hash:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_DATABASE_RECEIPT_HASH_BINDING_MISMATCH"
            )
        if paper_fill_id != derived_paper_fill_id:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_DATABASE_PAPER_FILL_ID_BINDING_MISMATCH"
            )
        expected_record_id = _record_id_for(
            receipt_hash=receipt_hash,
            paper_fill_id=paper_fill_id,
            sealed_fill_sha256=sealed_fill_sha256,
            prepared_at=prepared_at,
        )
        if record_id != expected_record_id:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_RECORD_ID_CONTENT_MISMATCH"
            )
        if entry_binding is not None and not isinstance(entry_binding, Mapping):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_ENTRY_EVENT_BINDING_INVALID"
            )
        if commit_evidence is not None and not isinstance(
            commit_evidence, Mapping
        ):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_COMMIT_EVIDENCE_INVALID"
            )
        record = ExactOnPolicyEntryOutboxRecord(
            record_id=record_id,
            receipt_hash=receipt_hash,
            paper_fill_id=paper_fill_id,
            state=state,
            sealed_fill_sha256=sealed_fill_sha256,
            sealed_fill=sealed_fill,
            prepared_at=prepared_at,
            entry_event_hash=(
                str(row["entry_event_hash"])
                if row["entry_event_hash"] is not None
                else None
            ),
            entry_event_binding=(
                dict(entry_binding) if isinstance(entry_binding, Mapping) else None
            ),
            entry_event_recorded_at=(
                str(row["entry_event_recorded_at"])
                if row["entry_event_recorded_at"] is not None
                else None
            ),
            commit_evidence_sha256=(
                str(row["commit_evidence_sha256"])
                if row["commit_evidence_sha256"] is not None
                else None
            ),
            commit_evidence=(
                dict(commit_evidence)
                if isinstance(commit_evidence, Mapping)
                else None
            ),
            committed_at=(
                str(row["committed_at"])
                if row["committed_at"] is not None
                else None
            ),
        )
        _validate_record_state(record)
        return record

    def get(self, record_id: str) -> ExactOnPolicyEntryOutboxRecord:
        if not SHA256_RE.fullmatch(str(record_id or "")):
            raise ExactOnPolicyEntryOutboxError("OUTBOX_RECORD_ID_INVALID")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM exact_entry_outbox WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            raise ExactOnPolicyEntryOutboxError("OUTBOX_RECORD_NOT_FOUND")
        return self._record_from_row(row)

    def prepare(
        self,
        fill: Mapping[str, Any],
        *,
        prepared_at: str | None = None,
    ) -> ExactOnPolicyEntryOutboxRecord:
        timestamp = prepared_at or _utc_now()
        _validate_sealed_fill(fill, prepared_at=timestamp)
        sealed_fill = deepcopy(dict(fill))
        sealed_fill_sha256 = _canonical_sha256(sealed_fill)
        receipt_hash = _validated_behavior_receipt_hash(sealed_fill)
        paper_fill_id = _paper_fill_id(sealed_fill)
        encoded_fill = _canonical_json_bytes(sealed_fill).decode("utf-8")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_rows = connection.execute(
                """
                SELECT * FROM exact_entry_outbox
                WHERE receipt_hash = ? OR paper_fill_id = ?
                """,
                (receipt_hash, paper_fill_id),
            ).fetchall()
            if len(existing_rows) > 1:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_IDENTITY_SPLIT_BRAIN"
                )
            if existing_rows:
                record = self._record_from_row(existing_rows[0])
                if (
                    record.paper_fill_id == paper_fill_id
                    and record.receipt_hash != receipt_hash
                ):
                    raise ExactOnPolicyEntryOutboxError(
                        "OUTBOX_PAPER_FILL_ID_IMMUTABLE_CONFLICT"
                    )
                if (
                    record.receipt_hash != receipt_hash
                    or record.paper_fill_id != paper_fill_id
                    or record.sealed_fill_sha256 != sealed_fill_sha256
                    or record.sealed_fill != sealed_fill
                ):
                    raise ExactOnPolicyEntryOutboxError(
                        "OUTBOX_IMMUTABLE_PREPARE_CONFLICT"
                    )
                connection.commit()
                return record
            record_id = _record_id_for(
                receipt_hash=receipt_hash,
                paper_fill_id=paper_fill_id,
                sealed_fill_sha256=sealed_fill_sha256,
                prepared_at=timestamp,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO exact_entry_outbox (
                        record_id, receipt_hash, paper_fill_id, state,
                        sealed_fill_sha256, sealed_fill_json, prepared_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        receipt_hash,
                        paper_fill_id,
                        STATE_PREPARED,
                        sealed_fill_sha256,
                        encoded_fill,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_UNIQUE_IDENTITY_CONFLICT"
                ) from exc
            connection.commit()
        return self.get(record_id)

    def pending(self, *, limit: int = 1000) -> list[ExactOnPolicyEntryOutboxRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ExactOnPolicyEntryOutboxError("OUTBOX_PENDING_LIMIT_INVALID")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM exact_entry_outbox
                WHERE state != ?
                ORDER BY prepared_at ASC, record_id ASC
                LIMIT ?
                """,
                (STATE_COMMITTED, limit + 1),
            ).fetchall()
        if len(rows) > limit:
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_PENDING_RESOURCE_BOUND_EXCEEDED"
            )
        return [self._record_from_row(row) for row in rows]

    def mark_entry_event_appended(
        self,
        record_id: str,
        *,
        event_hash: str,
        binding: Mapping[str, Any],
        recorded_at: str | None = None,
    ) -> ExactOnPolicyEntryOutboxRecord:
        timestamp = recorded_at or _utc_now()
        if not isinstance(binding, Mapping):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_ENTRY_EVENT_BINDING_INVALID"
            )
        encoded_binding = _canonical_json_bytes(binding).decode("utf-8")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM exact_entry_outbox WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise ExactOnPolicyEntryOutboxError("OUTBOX_RECORD_NOT_FOUND")
            record = self._record_from_row(row)
            _validate_entry_event_values(
                record,
                event_hash=event_hash,
                binding=binding,
                recorded_at=timestamp,
            )
            if record.state in {STATE_ENTRY_EVENT_APPENDED, STATE_COMMITTED}:
                if (
                    record.entry_event_hash != event_hash
                    or record.entry_event_binding != dict(binding)
                    or record.entry_event_recorded_at != timestamp
                ):
                    raise ExactOnPolicyEntryOutboxError(
                        "OUTBOX_ENTRY_EVENT_IMMUTABLE_CONFLICT"
                    )
                connection.commit()
                return record
            cursor = connection.execute(
                """
                UPDATE exact_entry_outbox
                SET state = ?, entry_event_hash = ?,
                    entry_event_binding_json = ?, entry_event_recorded_at = ?
                WHERE record_id = ? AND state = ?
                """,
                (
                    STATE_ENTRY_EVENT_APPENDED,
                    event_hash,
                    encoded_binding,
                    timestamp,
                    record_id,
                    STATE_PREPARED,
                ),
            )
            if cursor.rowcount != 1:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_ENTRY_EVENT_STATE_TRANSITION_LOST"
                )
            connection.commit()
        return self.get(record_id)

    def mark_committed(
        self,
        record_id: str,
        *,
        commit_evidence: Mapping[str, Any],
        committed_at: str | None = None,
    ) -> ExactOnPolicyEntryOutboxRecord:
        timestamp = committed_at or _utc_now()
        if _strict_utc(timestamp) is None:
            raise ExactOnPolicyEntryOutboxError("OUTBOX_COMMITTED_AT_INVALID")
        if not isinstance(commit_evidence, Mapping):
            raise ExactOnPolicyEntryOutboxError(
                "OUTBOX_COMMIT_EVIDENCE_INVALID"
            )
        evidence = dict(commit_evidence)
        encoded_evidence = _canonical_json_bytes(evidence).decode("utf-8")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM exact_entry_outbox WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise ExactOnPolicyEntryOutboxError("OUTBOX_RECORD_NOT_FOUND")
            record = self._record_from_row(row)
            if record.state == STATE_PREPARED:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_ENTRY_EVENT_REQUIRED_BEFORE_COMMIT"
                )
            if record.state == STATE_COMMITTED:
                if record.commit_evidence != evidence:
                    raise ExactOnPolicyEntryOutboxError(
                        "OUTBOX_COMMIT_IMMUTABLE_CONFLICT"
                    )
                connection.commit()
                return record
            evidence_sha256 = _commit_binding_sha256(
                evidence,
                committed_at=timestamp,
            )
            _validate_commit_values(
                record,
                evidence_sha256=evidence_sha256,
                evidence=evidence,
                committed_at=timestamp,
            )
            cursor = connection.execute(
                """
                UPDATE exact_entry_outbox
                SET state = ?, commit_evidence_sha256 = ?,
                    commit_evidence_json = ?, committed_at = ?
                WHERE record_id = ? AND state = ?
                """,
                (
                    STATE_COMMITTED,
                    evidence_sha256,
                    encoded_evidence,
                    timestamp,
                    record_id,
                    STATE_ENTRY_EVENT_APPENDED,
                ),
            )
            if cursor.rowcount != 1:
                raise ExactOnPolicyEntryOutboxError(
                    "OUTBOX_COMMIT_STATE_TRANSITION_LOST"
                )
            connection.commit()
        return self.get(record_id)
