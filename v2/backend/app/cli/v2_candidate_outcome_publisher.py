"""Publish every finalized paper candidate to the authenticated outcome archive.

This runtime has evidence authority only.  It reads one atomic Redis projection
of the finalized paper cycle, dereferences each immutable feature snapshot with
verification enabled, builds revision-one ``CandidateDecisionOutcomeV2``
records, and appends the complete cycle under one signed archive transaction.
It has no exchange credentials and cannot authorize or submit an order.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import signal
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION,
    ActualPaperExecutionOutcomeV2,
    CandidateDecisionOutcomeV2,
    CandidateOutcomeContractError,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    CandidateOutcomeMaturationError,
    CandidateOutcomeMaturationPending,
    mature_candidate,
    required_label_range,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_publisher_v2 import (
    PublisherCycleV2,
    build_publisher_cycle,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)

RUNTIME_SCHEMA_VERSION = "candidate_outcome_publisher_runtime_v2"
CYCLE_RECEIPT_SCHEMA_VERSION = "candidate_outcome_publisher_cycle_receipt_v2"
TERMINAL_RECEIPT_SCHEMA_VERSION = "candidate_outcome_publisher_terminal_receipt_v2"
MATURATION_STATUS_SCHEMA_VERSION = "candidate_outcome_maturation_runtime_v2"
WRITER_ID = "candidate-outcome-writer-v2"
SIGNING_CREDENTIAL_NAME = "candidate_outcome_ed25519_seed"
PAPER_STATUS_KEY = "v2:paper:trade_management:status"
PAPER_INTENTS_KEY = "v2:paper:intents"
PAPER_REGISTRY_KEY = "v2:model_registry:paper:active"
PAPER_CLOSED_TRADES_KEY = "v2:paper:closed_trades"
RUNTIME_STATUS_KEY = "v2:adaptive_system:candidate_outcomes:status"
SAFE_RESUME_COMMAND = (
    ".venv/bin/python -P -B -m "
    "v2.backend.app.cli.v2_candidate_outcome_publisher --loop"
)
ACTUAL_CLOSE_REQUIRED_DISPOSITIONS = frozenset(
    {"SELECTED_TRADE", "SELECTED_RISK_REDUCED", "SELECTED_HEDGED"}
)


class CandidateOutcomeRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1_000)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomeRuntimeError("payload_not_strict_json") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _strict_json_object(raw: object, field: str) -> dict[str, Any]:
    if type(raw) is not str or not raw:
        raise CandidateOutcomeRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not dict:
        raise CandidateOutcomeRuntimeError(f"{field}:object_required")
    return value


def _strict_json_array(raw: object, field: str) -> list[dict[str, Any]]:
    if type(raw) is not str or not raw:
        raise CandidateOutcomeRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise CandidateOutcomeRuntimeError(f"{field}:object_array_required")
    return value


def _read_cycle_projection(
    client: Any,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    raw_status, raw_intents, raw_registry, raw_closed = client.mget(
        (
            PAPER_STATUS_KEY,
            PAPER_INTENTS_KEY,
            PAPER_REGISTRY_KEY,
            PAPER_CLOSED_TRADES_KEY,
        )
    )
    return (
        _strict_json_object(raw_status, PAPER_STATUS_KEY),
        _strict_json_array(raw_intents, PAPER_INTENTS_KEY),
        _strict_json_object(raw_registry, PAPER_REGISTRY_KEY),
        _strict_json_array(raw_closed, PAPER_CLOSED_TRADES_KEY),
    )


def _parse_aware_utc_ms(value: object, field: str) -> int:
    if type(value) is not str or not value:
        raise CandidateOutcomeRuntimeError(f"{field}:aware_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateOutcomeRuntimeError(
            f"{field}:aware_timestamp_required"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateOutcomeRuntimeError(f"{field}:aware_timestamp_required")
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


def _required_identifier(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise CandidateOutcomeRuntimeError(f"{field}:identifier_required")
    return value


def _required_sha256(value: object, field: str) -> str:
    result = _required_identifier(value, field)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise CandidateOutcomeRuntimeError(f"{field}:sha256_required")
    return result


def _required_positive_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CandidateOutcomeRuntimeError(f"{field}:positive_float_required")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise CandidateOutcomeRuntimeError(f"{field}:positive_float_required")
    return result


def _required_zero_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CandidateOutcomeRuntimeError(f"{field}:exact_zero_required")
    result = float(value)
    if not math.isfinite(result) or result != 0.0:
        raise CandidateOutcomeRuntimeError(f"{field}:exact_zero_required")
    return result


def _required_nonnegative_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CandidateOutcomeRuntimeError(f"{field}:nonnegative_float_required")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CandidateOutcomeRuntimeError(f"{field}:nonnegative_float_required")
    return result


def _candidate_id_from_close(close: Mapping[str, Any]) -> str:
    generation = close.get("checkpoint_generation")
    if type(generation) is not int or generation < 1:
        raise CandidateOutcomeRuntimeError(
            "close.checkpoint_generation:positive_int_required"
        )
    identity_material = {
        "prediction_id": _required_identifier(
            close.get("entry_prediction_id") or close.get("prediction_id"),
            "close.prediction_id",
        ),
        "preemptive_decision_id": _required_identifier(
            close.get("preemptive_decision_id"),
            "close.preemptive_decision_id",
        ),
        "policy_id": _required_identifier(
            close.get("policy_id") or close.get("candidate_id"),
            "close.policy_id",
        ),
        "policy_sha256": _required_sha256(
            close.get("policy_fingerprint"),
            "close.policy_fingerprint",
        ),
        "checkpoint_generation": generation,
        "checkpoint_id": _required_identifier(
            close.get("checkpoint_id"), "close.checkpoint_id"
        ),
    }
    return f"cdo2_{_sha256(identity_material)}"


def _authenticated_actual_close_sources(
    *,
    paper_status: Mapping[str, Any],
    closed_trades: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Index final typed-policy closes without granting execution authority."""

    current_session = paper_status.get("paper_session_id")
    current_epoch = paper_status.get("paper_account_epoch")
    sources: dict[str, dict[str, Any]] = {}
    duplicate_candidate_ids: set[str] = set()
    rejection_counts: dict[str, int] = {}
    eligible_rows = 0

    def reject(reason: str) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    for raw in closed_trades:
        if raw.get("adaptive_policy_authoritative") is not True:
            continue
        if raw.get("close_position") is not True:
            continue
        if raw.get("paper_session_id") != current_session or raw.get(
            "paper_account_epoch"
        ) != current_epoch:
            continue
        eligible_rows += 1
        try:
            if (
                raw.get("paper_only") is not True
                or raw.get("routes_to_live") is not False
                or raw.get("places_real_order") is not False
                or raw.get("exchange_action_taken") is not False
            ):
                raise CandidateOutcomeRuntimeError("close:unsafe_authority_flags")
            mode = raw.get("adaptive_policy_action_policy_mode")
            if mode not in {
                "champion_exploitation",
                "bounded_information_seeking_exploration",
                "bootstrap_information_acquisition",
            }:
                raise CandidateOutcomeRuntimeError("close:typed_policy_mode_required")
            expected_exploration = mode in {
                "bounded_information_seeking_exploration",
                "bootstrap_information_acquisition",
            }
            if (
                raw.get("exploration_provenance") is not expected_exploration
                or raw.get("counts_as_training_feedback") is not True
                or raw.get("counts_as_live_profit") is not False
            ):
                raise CandidateOutcomeRuntimeError(
                    "close:typed_training_provenance_invalid"
                )
            if mode == "bootstrap_information_acquisition" and (
                raw.get("counts_as_natural_paper_execution") is not True
                or raw.get("counts_as_counterfactual") is not False
                or raw.get("counts_as_champion_profitability_evidence") is not False
            ):
                raise CandidateOutcomeRuntimeError(
                    "close:typed_training_provenance_invalid"
                )
            candidate_id = _candidate_id_from_close(raw)
            if candidate_id in sources or candidate_id in duplicate_candidate_ids:
                sources.pop(candidate_id, None)
                duplicate_candidate_ids.add(candidate_id)
                raise CandidateOutcomeRuntimeError(
                    "close:duplicate_final_close_for_candidate"
                )
            sources[candidate_id] = dict(raw)
        except CandidateOutcomeRuntimeError as exc:
            reject(str(exc))
    return sources, {
        "eligible_typed_final_close_count": eligible_rows,
        "authenticated_actual_close_source_count": len(sources),
        "actual_close_source_rejection_counts": dict(sorted(rejection_counts.items())),
    }


def _actual_paper_outcome_from_close(
    *,
    record: CandidateDecisionOutcomeV2,
    close: Mapping[str, Any],
    paper_status: Mapping[str, Any],
    observed_at_ms: int,
) -> ActualPaperExecutionOutcomeV2:
    if _candidate_id_from_close(close) != record.decision.candidate_id:
        raise CandidateOutcomeRuntimeError("actual_close:candidate_identity_mismatch")
    try:
        selected = json.loads(record.decision.selected_action.payload_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - contract defensive
        raise CandidateOutcomeRuntimeError("selected_action:invalid_json") from exc
    for field in (
        "adaptive_policy_action_id",
        "adaptive_policy_action_sha256",
        "adaptive_policy_action_policy_mode",
        "adaptive_paper_policy_authorization_sha256",
        "adaptive_policy_paper_cycle_receipt_id",
        "adaptive_policy_paper_cycle_receipt_sha256",
    ):
        if close.get(field) != selected.get(field):
            raise CandidateOutcomeRuntimeError(
                f"actual_close:selected_action_binding_mismatch:{field}"
            )
    if (
        close.get("exploration_provenance")
        is not selected.get("exploration_provenance")
        or close.get("counts_as_training_feedback") is not True
        or close.get("counts_as_live_profit") is not False
    ):
        raise CandidateOutcomeRuntimeError(
            "actual_close:selected_action_provenance_mismatch"
        )

    margin = paper_status.get("paper_account_margin_status")
    reconciliation = paper_status.get("paper_position_fill_reconciliation_status")
    if not isinstance(margin, Mapping) or (
        margin.get("status") != "PASS"
        or margin.get("accounting_complete") is not True
        or margin.get("invariant_holds") is not True
    ):
        raise CandidateOutcomeRuntimeError(
            "actual_close:flat_accounting_reconciliation_required"
        )
    # Continuous paper learning: other positions may legitimately be OPEN
    # while an earlier close matures, so global used/newly-reserved margin is
    # finite-nonnegative rather than exactly zero.  Conservation authority is
    # unchanged and still mandatory: margin status PASS with
    # accounting_complete and invariant_holds (used margin == sum of open
    # position margins), reconciliation PASS with zero unresolved/phantom
    # positions, exact-zero unexplained wallet mutation below, and the
    # close's own contract (reduce_only, fully_closed, released margin)
    # enforced in ActualPaperExecutionOutcomeV2.
    _required_nonnegative_float(
        margin.get("used_margin_usd"), "paper_status.used_margin_usd"
    )
    _required_nonnegative_float(
        margin.get("newly_reserved_margin_usd"),
        "paper_status.newly_reserved_margin_usd",
    )
    if not isinstance(reconciliation, Mapping) or (
        reconciliation.get("status") != "PASS"
        or reconciliation.get("unresolved_position_count") != 0
        or reconciliation.get("phantom_position_count") != 0
    ):
        raise CandidateOutcomeRuntimeError(
            "actual_close:position_fill_reconciliation_required"
        )
    _required_zero_float(
        reconciliation.get("wallet_balance_mutation_usd"),
        "paper_status.wallet_balance_mutation_usd",
    )

    quantity = _required_positive_float(close.get("closed_quantity"), "close.closed_quantity")
    entry_price = _required_positive_float(close.get("entry_price"), "close.entry_price")
    gross_notional = quantity * entry_price
    declared_notional = _required_positive_float(
        close.get("gross_notional_usd"), "close.gross_notional_usd"
    )
    if not math.isclose(
        gross_notional, declared_notional, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise CandidateOutcomeRuntimeError("actual_close:gross_notional_mismatch")
    leverage = _required_positive_float(
        close.get("effective_leverage"), "close.effective_leverage"
    )
    allocated_margin = _required_positive_float(
        close.get("allocated_margin_usd"), "close.allocated_margin_usd"
    )
    if not math.isclose(
        allocated_margin,
        gross_notional / leverage,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise CandidateOutcomeRuntimeError("actual_close:allocated_margin_mismatch")
    realized_pnl_usd_raw = close.get("realized_net_pnl_usd")
    if isinstance(realized_pnl_usd_raw, bool) or not isinstance(
        realized_pnl_usd_raw, int | float
    ):
        raise CandidateOutcomeRuntimeError("actual_close:realized_net_pnl_required")
    realized_pnl_usd = float(realized_pnl_usd_raw)
    if not math.isfinite(realized_pnl_usd):
        raise CandidateOutcomeRuntimeError("actual_close:realized_net_pnl_required")
    # The execution instant is the authenticated FINAL-ADMISSION decision
    # time (when the fill was actually admitted), not the entry price
    # snapshot instant, which legitimately precedes the typed action's
    # decision it fed.  Legacy rows without the receipt keep the entry
    # generation time.
    fill_execution_ms = _parse_aware_utc_ms(
        close.get("paper_final_admission_decision_time")
        or close.get("entry_generation_time_utc"),
        "close.paper_final_admission_decision_time",
    )
    close_execution_ms = _parse_aware_utc_ms(
        close.get("close_event_time") or close.get("exit_time"),
        "close.close_event_time",
    )
    if observed_at_ms < close_execution_ms:
        raise CandidateOutcomeRuntimeError("actual_close:observed_before_close")
    if close.get("reduce_only") is not True or close.get(
        "remaining_quantity_after_close"
    ) != 0.0:
        raise CandidateOutcomeRuntimeError("actual_close:final_reduce_only_flat_required")

    return ActualPaperExecutionOutcomeV2(
        schema_version=ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION,
        candidate_id=record.decision.candidate_id,
        selected_action_sha256=record.decision.selected_action.content_sha256(),
        signal_id=_required_identifier(
            close.get("entry_signal_id") or close.get("signal_id"),
            "close.signal_id",
        ),
        intent_id=_required_identifier(
            close.get("intent_id") or close.get("source_intent_id"),
            "close.intent_id",
        ),
        fill_id=_required_identifier(close.get("entry_fill_id"), "close.entry_fill_id"),
        position_id=_required_identifier(close.get("position_id"), "close.position_id"),
        closed_trade_id=_required_identifier(close.get("close_id"), "close.close_id"),
        fill_receipt_sha256=_required_sha256(
            close.get("paper_final_admission_receipt_hash"),
            "close.paper_final_admission_receipt_hash",
        ),
        close_receipt_sha256=_sha256(close),
        accounting_receipt_sha256=_sha256(
            {
                "paper_account_margin_status": dict(margin),
                "paper_position_fill_reconciliation_status": dict(reconciliation),
            }
        ),
        fill_execution_time_ms=fill_execution_ms,
        fill_record_available_at_ms=fill_execution_ms,
        close_execution_time_ms=close_execution_ms,
        close_record_available_at_ms=observed_at_ms,
        accounting_record_available_at_ms=observed_at_ms,
        executed_quantity=quantity,
        execution_price=entry_price,
        gross_notional_usd=gross_notional,
        effective_leverage=leverage,
        allocated_margin_usd=allocated_margin,
        realized_pnl_usd=realized_pnl_usd,
        realized_pnl_bps=realized_pnl_usd / gross_notional * 10_000.0,
        open_quantity_after_close=0.0,
        used_margin_after_close_usd=0.0,
        reserved_margin_after_close_usd=0.0,
        reduce_only_close=True,
        fully_closed=True,
        paper_only=True,
        places_real_order=False,
        exchange_action_taken=False,
    )


def _paper_status_marker(client: Any) -> str:
    return _sha256(_strict_json_object(client.get(PAPER_STATUS_KEY), PAPER_STATUS_KEY))


def _snapshot_id(intent: Mapping[str, Any]) -> str:
    prediction = intent.get("entry_prediction_snapshot")
    prediction = prediction if isinstance(prediction, Mapping) else {}
    value = (
        intent.get("entry_feature_snapshot_id")
        or intent.get("feature_snapshot_id")
        or prediction.get("feature_snapshot_id")
    )
    if type(value) is not str or not value or value.strip() != value:
        raise CandidateOutcomeRuntimeError("intent:feature_snapshot_id_required")
    return value


def _load_feature_snapshots(
    intents: list[dict[str, Any]], archive_root: Path
) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for snapshot_id in sorted({_snapshot_id(intent) for intent in intents}):
        snapshot = load_snapshot(snapshot_id, root=archive_root, verify=True)
        if snapshot is None:
            raise CandidateOutcomeRuntimeError(
                f"feature_snapshot:{snapshot_id}:missing_from_verified_archive"
            )
        snapshots[snapshot_id] = snapshot
    return snapshots


def _cycle_id(cycle: PublisherCycleV2) -> str:
    material = {
        "schema_version": CYCLE_RECEIPT_SCHEMA_VERSION,
        "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
        "matrix_generated_at_ms": cycle.matrix_generated_at_ms,
        "source_candidate_count": cycle.source_candidate_count,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "record_content_sha256s": [
            record.content_sha256() for record in cycle.decision_records
        ],
    }
    return f"candidate_cycle_{_sha256(material)}"


def _existing_cycle_receipt(path: Path, cycle: PublisherCycleV2, cycle_id: str) -> bool:
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        raise CandidateOutcomeRuntimeError("cycle_receipt:regular_file_required")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateOutcomeRuntimeError("cycle_receipt:invalid") from exc
    expected = {
        "cycle_id": cycle_id,
        "source_candidate_count": cycle.source_candidate_count,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "record_content_sha256s": [
            record.content_sha256() for record in cycle.decision_records
        ],
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise CandidateOutcomeRuntimeError(f"cycle_receipt:{field}:mismatch")
    if receipt.get("completed") is not True:
        raise CandidateOutcomeRuntimeError("cycle_receipt:completion_unproven")
    return True


def process_maturation(
    *,
    archive: CandidateOutcomeArchiveV2,
    label_archive: DurableCanonical5mLabelArchive,
    signed_at_ms: int,
    max_candidates: int,
    paper_status: Mapping[str, Any] | None = None,
    closed_trades: list[dict[str, Any]] | None = None,
    integrity_proof_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mature one bounded oldest-first batch under the publisher's writer key."""

    if type(max_candidates) is not int or max_candidates < 1:
        raise CandidateOutcomeRuntimeError("max_candidates:positive_int_required")
    actual_close_sources, actual_close_source_status = (
        _authenticated_actual_close_sources(
            paper_status=paper_status,
            closed_trades=closed_trades or [],
        )
        if paper_status is not None
        else (
            {},
            {
                "eligible_typed_final_close_count": 0,
                "authenticated_actual_close_source_count": 0,
                "actual_close_source_rejection_counts": {},
            },
        )
    )
    verification_before, selection = (
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=signed_at_ms,
            max_candidates=max_candidates,
            actual_close_required_dispositions=(
                ACTUAL_CLOSE_REQUIRED_DISPOSITIONS
            ),
            actual_close_candidate_ids=frozenset(actual_close_sources),
        )
    )
    batch = list(selection.records)
    pending_reason_counts: dict[str, int] = {}

    def count_pending(reason: str, amount: int = 1) -> None:
        pending_reason_counts[reason] = pending_reason_counts.get(reason, 0) + amount

    if selection.selected_actual_pending_count:
        count_pending(
            "RECONCILED_ACTUAL_PAPER_CLOSE_REQUIRED",
            selection.selected_actual_pending_count,
        )
    if selection.label_candidate_count > len(batch):
        count_pending(
            "MATURATION_BATCH_LIMIT",
            selection.label_candidate_count - len(batch),
        )

    integrity: Mapping[str, Any] | None = None
    integrity_rejection_reasons: list[str] = []
    candidates_to_append = []
    source_eligible_ids: list[str] = []
    transaction_cache: set[tuple[str, str, str, str, int, str]] = set()
    if batch:
        if (
            integrity_proof_cache
            and integrity_proof_cache.get("archive_integrity_verified") is True
        ):
            integrity = label_archive.extend_integrity_proof(
                integrity_proof_cache
            )
        else:
            integrity = label_archive.verify_integrity()
        if integrity.get("archive_integrity_verified") is not True:
            integrity_rejection_reasons = [
                str(reason)
                for reason in integrity.get("rejection_reasons") or [integrity.get("status")]
            ]
            count_pending(
                "CANONICAL_LABEL_ARCHIVE_INTEGRITY_UNPROVEN",
                len(batch),
            )
        else:
            if integrity_proof_cache is not None:
                integrity_proof_cache.clear()
                integrity_proof_cache.update(integrity)
            for record in batch:
                start_ms, end_ms, expected_rows = required_label_range(record)
                rows, proof = label_archive.verified_range(
                    symbol=record.decision.symbol,
                    start_close_time_ms=start_ms,
                    end_close_time_ms=end_ms,
                    training_observed_at=signed_at_ms,
                    limit=expected_rows,
                    archive_integrity_proof=integrity,
                    _verified_transaction_cache=transaction_cache,
                )
                if rows is None:
                    reasons = proof.get("rejection_reasons") or [proof.get("status")]
                    for reason in sorted({str(item) for item in reasons}):
                        count_pending(reason)
                    continue
                try:
                    actual_paper_outcome = None
                    if record.decision.decision_disposition in (
                        ACTUAL_CLOSE_REQUIRED_DISPOSITIONS
                    ):
                        source_close = actual_close_sources.get(
                            record.decision.candidate_id
                        )
                        if source_close is None or paper_status is None:
                            count_pending("RECONCILED_ACTUAL_PAPER_CLOSE_REQUIRED")
                            continue
                        actual_paper_outcome = _actual_paper_outcome_from_close(
                            record=record,
                            close=source_close,
                            paper_status=paper_status,
                            observed_at_ms=signed_at_ms,
                        )
                    matured = mature_candidate(
                        record,
                        rows=rows,
                        proof=proof,
                        label_generated_at_ms=signed_at_ms,
                        actual_paper_outcome=actual_paper_outcome,
                    )
                except CandidateOutcomeRuntimeError as exc:
                    count_pending(f"INVALID_ACTUAL_PAPER_OUTCOME:{exc}")
                    continue
                except CandidateOutcomeMaturationPending as exc:
                    count_pending(str(exc))
                    continue
                except CandidateOutcomeMaturationError as exc:
                    count_pending(f"INVALID_LABEL_INPUT:{exc}")
                    continue
                except CandidateOutcomeContractError as exc:
                    # One candidate's contract failure is an alert, never a
                    # stall: the learning loop must keep maturing every other
                    # candidate while this one surfaces in the pending
                    # decomposition for repair.
                    count_pending(f"INVALID_MATURED_CONTRACT:{exc}")
                    continue
                candidates_to_append.append(matured)
                source_eligible_ids.append(record.decision.candidate_id)

    verification_after = verification_before
    if candidates_to_append:
        append_receipts, verification_after = archive.append_many_with_verification(
            tuple(candidates_to_append),
            signed_at_ms=signed_at_ms,
        )
    else:
        append_receipts = ()
    total_matured = verification_after.matured_revision_count
    decision_revision_count = verification_before.decision_revision_count
    proven_eligible_total = (
        verification_before.matured_revision_count
        + len(set(source_eligible_ids))
    )
    unexplained_drops = max(0, proven_eligible_total - total_matured)
    status_name = (
        "BLOCKED"
        if integrity_rejection_reasons
        or any(reason.startswith("INVALID_LABEL_INPUT:") for reason in pending_reason_counts)
        or any(
            reason.startswith("INVALID_ACTUAL_PAPER_OUTCOME:")
            for reason in pending_reason_counts
        )
        or bool(actual_close_source_status["actual_close_source_rejection_counts"])
        or unexplained_drops
        else "PASS"
    )
    return {
        "schema_version": MATURATION_STATUS_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": status_name,
        "decision_revision_count": decision_revision_count,
        "matured_revision_count": total_matured,
        "unmatured_candidate_count": (
            decision_revision_count - total_matured
        ),
        "horizon_due_candidate_count": selection.horizon_due_candidate_count,
        "selected_candidate_awaiting_actual_close_count": (
            selection.selected_actual_pending_count
        ),
        "label_candidate_count": selection.label_candidate_count,
        "batch_candidate_count": len(batch),
        "source_eligible_candidate_count": len(source_eligible_ids),
        "newly_matured_candidate_count": len(append_receipts),
        "idempotent_matured_append_count": sum(
            receipt.idempotent_replay for receipt in append_receipts
        ),
        "proven_eligible_matured_candidate_count": proven_eligible_total,
        "eligible_matured_label_coverage": (
            total_matured / proven_eligible_total if proven_eligible_total else 1.0
        ),
        "eligible_matured_label_coverage_100_percent": unexplained_drops == 0,
        "unexplained_maturation_drops": unexplained_drops,
        "pending_reason_counts": dict(sorted(pending_reason_counts.items())),
        "actual_close_sources": actual_close_source_status,
        "actual_paper_outcome_candidate_count": len(actual_close_sources),
        "newly_matured_actual_paper_outcome_count": sum(
            candidate.matured_labels is not None
            and candidate.matured_labels.actual_paper_outcome is not None
            for candidate in candidates_to_append
        ),
        "newly_matured_exploration_outcome_count": sum(
            candidate.matured_labels is not None
            and candidate.matured_labels.actual_paper_outcome is not None
            and actual_close_sources.get(candidate.decision.candidate_id, {}).get(
                "exploration_provenance"
            )
            is True
            for candidate in candidates_to_append
        ),
        "canonical_label_archive_integrity_verified": (
            integrity.get("archive_integrity_verified") is True if integrity is not None else None
        ),
        "canonical_label_archive_chain_sha256": (
            integrity.get("archive_chain_sha256") if integrity is not None else None
        ),
        "canonical_label_archive_verification_mode": (
            integrity.get("verification_mode", "FULL_ARCHIVE_VERIFICATION")
            if integrity is not None
            else None
        ),
        "canonical_label_archive_rejection_reasons": integrity_rejection_reasons,
        "transaction_identity_cache_entry_count": len(transaction_cache),
        "archive_verification": asdict(verification_after),
        "counterfactual_counts_as_paper_profit": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def process_cycle(
    *,
    client: Any,
    archive: CandidateOutcomeArchiveV2,
    state_root: Path,
    feature_archive_root: Path,
    signed_at_ms: int,
    label_archive: DurableCanonical5mLabelArchive | None = None,
    max_maturation_candidates: int = 256,
    label_integrity_proof_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paper_status, intents, registry, closed_trades = _read_cycle_projection(client)
    snapshots = _load_feature_snapshots(intents, feature_archive_root)
    cycle = build_publisher_cycle(
        paper_status=paper_status,
        intents=intents,
        registry_payload=registry,
        feature_snapshots_by_id=snapshots,
    )
    cycle_id = _cycle_id(cycle)
    receipt_path = state_root / "cycle_receipts" / f"{cycle_id}.json"
    already_complete = _existing_cycle_receipt(receipt_path, cycle, cycle_id)

    verification_after_decisions = None
    if already_complete:
        append_receipts = ()
    else:
        if cycle.decision_records:
            (
                append_receipts,
                verification_after_decisions,
            ) = archive.append_many_with_verification(
                cycle.decision_records,
                signed_at_ms=signed_at_ms,
            )
        else:
            append_receipts = ()
            verification_after_decisions = archive.verify()
        cycle_receipt = {
            "schema_version": CYCLE_RECEIPT_SCHEMA_VERSION,
            "cycle_id": cycle_id,
            "generated_at": _utc_now(),
            "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
            "matrix_generated_at_ms": cycle.matrix_generated_at_ms,
            "source_candidate_count": cycle.source_candidate_count,
            "recorded_candidate_count": len(cycle.decision_records),
            "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
            "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
            "record_content_sha256s": [
                record.content_sha256() for record in cycle.decision_records
            ],
            "archive_receipt_ids": [receipt.receipt_id for receipt in append_receipts],
            "archive_terminal_chain_sha256": (
                verification_after_decisions.terminal_chain_sha256
            ),
            "candidate_recording_coverage": cycle.candidate_recording_coverage,
            "unexplained_candidate_drops": cycle.unexplained_candidate_drops,
            "completed": True,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_json_atomic(receipt_path, cycle_receipt)

    maturation = (
        process_maturation(
            archive=archive,
            label_archive=label_archive,
            signed_at_ms=signed_at_ms,
            max_candidates=max_maturation_candidates,
            paper_status=paper_status,
            closed_trades=closed_trades,
            integrity_proof_cache=label_integrity_proof_cache,
        )
        if label_archive is not None
        else {
            "schema_version": MATURATION_STATUS_SCHEMA_VERSION,
            "status": "NOT_CONFIGURED",
            "runtime_integrated": False,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
    )
    if maturation.get("archive_verification") is not None:
        archive_verification = maturation["archive_verification"]
    elif verification_after_decisions is not None:
        archive_verification = asdict(verification_after_decisions)
    else:
        archive_verification = asdict(archive.verify())
    status = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "PASS",
        "scope": "paper_loop_finalized_candidate_universe",
        "cycle_id": cycle_id,
        "source_paper_status_sha256": _sha256(paper_status),
        "cycle_generated_at_ms": cycle.cycle_generated_at_ms,
        "source_candidate_count": cycle.source_candidate_count,
        "recorded_candidate_count": len(cycle.decision_records),
        "candidate_recording_coverage": cycle.candidate_recording_coverage,
        "candidate_recording_coverage_100_percent": (
            cycle.candidate_recording_coverage == 1.0
        ),
        "unexplained_candidate_drops": cycle.unexplained_candidate_drops,
        "source_candidate_ids_sha256": cycle.source_candidate_ids_sha256,
        "recorded_candidate_ids_sha256": cycle.recorded_candidate_ids_sha256,
        "cycle_idempotent_replay": already_complete,
        "archive_batch_append_count": len(append_receipts),
        "archive_idempotent_append_count": sum(
            receipt.idempotent_replay for receipt in append_receipts
        ),
        "archive": archive_verification,
        "maturation": maturation,
        "candidate_outcome_maturer_runtime_integrated": label_archive is not None,
        "feature_snapshot_archive_root": str(feature_archive_root),
        "writer_id": archive.writer_id,
        "writer_public_key_hex": archive.writer_public_key_hex,
        "signing_private_key_exported": False,
        "single_policy_writer_claimed": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "status.json", status)
    client.set(RUNTIME_STATUS_KEY, _canonical_json(status))
    return status


def _load_signing_key() -> tuple[Ed25519PrivateKey, str]:
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not credentials_directory:
        raise CandidateOutcomeRuntimeError("CREDENTIALS_DIRECTORY:missing")
    path = Path(credentials_directory) / SIGNING_CREDENTIAL_NAME
    if path.is_symlink() or not path.is_file():
        raise CandidateOutcomeRuntimeError("signing_credential:regular_file_required")
    seed = path.read_bytes()
    if len(seed) != 32:
        raise CandidateOutcomeRuntimeError("signing_credential:exactly_32_bytes_required")
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return private_key, public_key_hex


def _acquire_single_writer_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _terminal_receipt(
    state_root: Path,
    *,
    reason: str,
    signal_number: int | None,
    exception: BaseException | None,
) -> None:
    payload = {
        "schema_version": TERMINAL_RECEIPT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "exit_reason": reason,
        "signal_number": signal_number,
        "exception_type": type(exception).__name__ if exception else None,
        "exception_message": str(exception)[:2_048] if exception else None,
        "safe_resume_command": SAFE_RESUME_COMMAND,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "terminal_receipt.json", payload)


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[4]
    local_data_root = Path(
        os.environ.get("AI_BOT_LOCAL_DATA_ROOT", str(Path.home() / "ai_bot_local_data"))
    )
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument(
        "--state-root",
        type=Path,
        default=local_data_root / "candidate_outcomes_v2",
    )
    parser.add_argument(
        "--feature-archive-root",
        type=Path,
        default=repo_root / ".local_data/v2_native_trainer/durable_feature_snapshot_archive",
    )
    parser.add_argument(
        "--label-archive-path",
        type=Path,
        default=(
            local_data_root
            / "v2_native_trainer/canonical_finalized_5m_label_archive.sqlite3"
        ),
    )
    parser.add_argument("--max-maturation-candidates", type=int, default=256)
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(
            os.environ.get(
                "V2_CANDIDATE_OUTCOME_PUBLISHER_LOCK_PATH",
                f"/run/user/{os.getuid()}/ai-bot-v2-candidate-outcome-publisher/writer.lock",
            )
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    if args.max_maturation_candidates < 1:
        raise SystemExit("--max-maturation-candidates must be positive")
    args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_descriptor = _acquire_single_writer_lock(args.lock_path)
    private_key, public_key_hex = _load_signing_key()
    archive = CandidateOutcomeArchiveV2(
        archive_path=args.state_root / "candidate_decision_outcomes_v2.jsonl",
        writer_id=WRITER_ID,
        writer_public_key_hex=public_key_hex,
        signer=private_key.sign,
    )
    label_archive = DurableCanonical5mLabelArchive(args.label_archive_path)
    client = redis.Redis.from_url(
        args.redis_url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )
    stopping = False
    received_signal: int | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stopping, received_signal
        stopping = True
        received_signal = signum

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    failure: BaseException | None = None
    last_status_marker: str | None = None
    label_integrity_proof_cache: dict[str, Any] = {}
    try:
        while not stopping:
            current_marker = _paper_status_marker(client)
            if current_marker != last_status_marker:
                status = process_cycle(
                    client=client,
                    archive=archive,
                    state_root=args.state_root,
                    feature_archive_root=args.feature_archive_root,
                    signed_at_ms=_now_ms(),
                    label_archive=label_archive,
                    max_maturation_candidates=args.max_maturation_candidates,
                    label_integrity_proof_cache=label_integrity_proof_cache,
                )
                last_status_marker = status["source_paper_status_sha256"]
            if args.once:
                break
            deadline = time.monotonic() + args.interval_seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    except BaseException as exc:
        failure = exc
        _terminal_receipt(
            args.state_root,
            reason="EXCEPTION",
            signal_number=received_signal,
            exception=exc,
        )
        print(f"candidate outcome publisher failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock_descriptor)

    _terminal_receipt(
        args.state_root,
        reason="SIGNAL" if received_signal is not None else "ONCE_COMPLETE",
        signal_number=received_signal,
        exception=failure,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
