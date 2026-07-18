"""Runtime orchestration for the V2 hybrid CUDA trainer."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.current_cycle_evidence import (
    CURRENT_RESOURCE_EVIDENCE_SCHEMA,
    build_current_cycle_parity_attestation,
    build_current_cycle_prediction_publication_evidence,
    canonical_sha256,
    capture_cycle_identity,
    current_process_service_evidence,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_OUTCOME_FINALIZED,
    EVENT_TRAINER_CONSUMED,
    BehaviorReceiptArchiveError,
    lifecycle_events,
    load_behavior_receipt,
    receipt_lifecycle_status,
    verify_archived_behavior_receipt,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    append_lifecycle_event as append_behavior_receipt_lifecycle_event,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    default_archive_root as default_behavior_receipt_archive_root,
)
from v2.backend.app.services.native_trainer.learning_readiness import (
    CURRENT_CYCLE_ENVELOPE_SCHEMA,
    build_learning_readiness,
)

from .checkpoint import CheckpointManifest, V2HybridCheckpointManager
from .checkpoint_lifecycle import (
    NON_SERVING_CANDIDATE_LINEAGE,
    REJECTED_ATTEMPT_LINEAGE,
    VERIFIED_SERVING_LINEAGE,
    checkpoint_evidence,
    checkpoint_stores,
    reconcile_checkpoint_consumption,
    serving_promotion_decision,
    verified_candidate_checkpoint_evidence,
)
from .confidence import CONFIDENCE_LABEL_SEMANTICS
from .config import (
    ACTION_LABELS,
    CHECKPOINT_SOURCE,
    LEGACY_BEHAVIOR_REFERENCES,
    LEGACY_HYBRID_PARITY_BASELINE,
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE,
    PREDICTION_KEY_TEMPLATE,
    TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
    TRAINER_SOURCE,
    HybridTrainerConfig,
)
from .data_loader import V2HybridTrainerDataLoader
from .environment import V2PaperShadowHybridEnv
from .model import V2HybridPolicyModel
from .on_policy_behavior import (
    adaptive_on_policy_lane_plan,
    build_exact_cost_provenance,
    model_parameter_fingerprint,
    ppo_consumption_update_key_from_row,
)
from .parallel_env import run_parallel_env_rollout_proof
from .policy_backtest import BACKTEST_SCHEMA_VERSION, run_policy_archive_backtest
from .ppo_trainer import V2HybridPPOTrainer
from .publisher import (
    V2HybridPredictionPublisher,
    build_operator_dashboard_payload,
    build_prediction_payload,
    dumps_pretty,
    trainer_status_publication_timing,
)
from .rewards import reward_stack_status
from .safety import V2OnlyJsonIO, safety_scoreboard
from .tensor_builder import FEATURE_SPEC
from .training_state import (
    candidate_progress_decision,
    confidence_promotion_decision,
    ppo_consumption_update_key,
    training_partition_digest,
)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_iso_microseconds() -> str:
    """Capture a causal observation clock without sub-second truncation."""

    return datetime.now(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _causal_decision_time_after_cost_observation(
    cost_evidence: Mapping[str, Any],
) -> str:
    """Return an aware decision clock strictly after exact cost observation."""
    now = datetime.now(UTC)
    provenance = cost_evidence.get("exact_cost_provenance")
    observed = (
        _strict_utc(provenance.get("consumer_observed_at"))
        if isinstance(provenance, Mapping)
        else None
    )
    if observed is not None and now <= observed:
        now = observed + timedelta(microseconds=1)
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _provider_feature_names() -> list[str]:
    names: list[str] = []
    for name, source in FEATURE_SPEC:
        text = f"{name}:{source}".lower()
        if any(token in text for token in ("altdata", "moralis", "coinglass")):
            names.append(name)
    return names


@dataclass(frozen=True)
class HybridRuntimePaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path


@dataclass(frozen=True)
class HybridRuntimeResult:
    go_no_go: str
    status: dict[str, Any]
    metrics: dict[str, Any]
    predictions: list[dict[str, Any]]
    lineages: list[dict[str, Any]]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


def default_paths(repo_root: Path) -> HybridRuntimePaths:
    rel = Path("v2_native_rl_masa_ppo_cuda_trainer_implementation/latest")
    return HybridRuntimePaths(
        repo_root=repo_root,
        worklog_dir=repo_root / "claude_worklog/final_readiness" / rel,
        public_dir=repo_root / "v2/frontend/public" / rel,
    )


def _select_training_examples_for_cycle(
    *,
    fresh_examples: list[Any],
    replay_buffer: Any | None,
    max_training_rows_per_cycle: int,
) -> list[Any]:
    if replay_buffer is not None:
        replay_buffer.extend(fresh_examples)
        rows = list(replay_buffer) if replay_buffer else list(fresh_examples)
    else:
        rows = list(fresh_examples)
    limit = max(0, int(max_training_rows_per_cycle or 0))
    if limit and len(rows) > limit:
        return rows[-limit:]
    return rows


def _trusted_replay_load_limit_for_cycle(
    *,
    max_training_rows_per_cycle: int,
    replay_buffer: Any | None,
) -> int:
    limit = max(0, int(max_training_rows_per_cycle or 0))
    buffer_maxlen = getattr(replay_buffer, "maxlen", None) if replay_buffer is not None else None
    if buffer_maxlen:
        return min(limit or int(buffer_maxlen), int(buffer_maxlen))
    return limit


def _trusted_replay_backfill_limit_for_cycle(
    *,
    max_training_rows_per_cycle: int,
    replay_buffer: Any | None,
    frontier_rows: int,
) -> int:
    """Bound cold/prefetched backfill by both cycle and buffer capacity."""

    cycle_limit = max(0, int(max_training_rows_per_cycle or 0))
    if cycle_limit == 0:
        return 0
    frontier_count = max(0, int(frontier_rows or 0))
    remaining_cycle_rows = max(0, cycle_limit - frontier_count)
    buffer_maxlen = (
        getattr(replay_buffer, "maxlen", None)
        if replay_buffer is not None
        else None
    )
    if not buffer_maxlen:
        return 0
    occupancy = len(replay_buffer) + frontier_count
    remaining_buffer_rows = max(0, int(buffer_maxlen) - occupancy)
    return min(remaining_cycle_rows, remaining_buffer_rows)


def _sha256_file(path: str | None) -> str | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists() or not source.is_file():
        return None
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _strict_nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric != float(parsed) or parsed < 0:
        return None
    return parsed


def _sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _optimizer_parameter_fingerprints_bound(
    *,
    parameter_hash_before: Any,
    parameter_hash_after: Any,
    training_parent_policy_fingerprint: Any,
    candidate_policy_fingerprint: Any,
) -> bool:
    """Bind optimizer receipts to the actual parent and child model states."""

    before = str(parameter_hash_before or "")
    after = str(parameter_hash_after or "")
    parent = str(training_parent_policy_fingerprint or "")
    candidate = str(candidate_policy_fingerprint or "")
    return bool(
        _sha256_hex(before)
        and _sha256_hex(after)
        and _sha256_hex(parent)
        and _sha256_hex(candidate)
        and before == parent
        and after == candidate
    )


def _exact_ppo_optimizer_contract_valid(
    *,
    metrics: Mapping[str, Any],
    optimizer_attempts: list[Mapping[str, Any]],
    ordered_update_keys: list[str],
) -> bool:
    metrics_update_keys = [
        str(value) for value in (metrics.get("ppo_consumed_update_keys") or ())
    ]
    attempt_count = len(optimizer_attempts)
    return bool(
        metrics_update_keys == ordered_update_keys
        and metrics.get("ppo_consumed_update_keys_complete") is True
        and metrics.get("ppo_consumed_update_keys_ordered") is True
        and metrics.get("ppo_consumed_update_keys_unique") is True
        and metrics.get("ppo_objective_used") is True
        and int(metrics.get("ppo_rows_consumed") or 0) == attempt_count
        and int(metrics.get("ppo_clipped_surrogate_rows") or 0) == attempt_count
        and int(metrics.get("ppo_rows_available_but_optimizer_unavailable") or 0)
        == 0
    )


def _verified_durable_receipt_archive_sync_status(
    *,
    ledger: Any,
    archive_root: Path,
) -> dict[str, Any]:
    """Re-read every watermark-bound archive event before reporting readiness."""

    status = dict(ledger.archive_sync_status())
    reasons = list(status.get("archive_sync_rejection_reasons") or ())
    metadata_valid = status.get("archive_sync_integrity_verified") is True
    bindings: list[Mapping[str, Any]] = []
    if metadata_valid:
        try:
            bindings = list(ledger.archive_sync_bindings())
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BINDING_LEDGER_UNREADABLE")
    checked = 0
    for row in bindings:
        sequence = int(row.get("sequence") or -1)
        receipt_hash = str(row.get("receipt_hash") or "")
        expected_event_hash = str(
            row.get("trainer_consumed_event_hash") or ""
        )
        try:
            receipt = load_behavior_receipt(receipt_hash, root=archive_root)
            verify_archived_behavior_receipt(receipt, root=archive_root)
            events = lifecycle_events(receipt_hash, root=archive_root)
        except (BehaviorReceiptArchiveError, OSError, TypeError, ValueError):
            reasons.append(
                "PPO_RECEIPT_ARCHIVE_SYNC_BOUND_EVENT_UNREADABLE:"
                + str(sequence)
            )
            continue
        event = next(
            (
                candidate
                for candidate in events
                if candidate.get("event_type") == EVENT_TRAINER_CONSUMED
                and candidate.get("event_hash") == expected_event_hash
            ),
            None,
        )
        legacy_binding = {
            "ppo_consumption_update_key": row.get("update_key"),
            "ledger_sequence": sequence,
            "ledger_chain_hash": row.get("ledger_chain_hash"),
            "ledger_disposition": row.get("disposition"),
            "checkpoint_id": row.get("checkpoint_id"),
            "child_policy_fingerprint": row.get("child_policy_fingerprint"),
            "finalized_outcome_digest": row.get("finalized_outcome_digest"),
        }
        exact_binding = {
            **legacy_binding,
            "ledger_recorded_utc": row.get("recorded_utc"),
        }
        event_binding = event.get("binding") if isinstance(event, Mapping) else None
        if (
            not isinstance(event, Mapping)
            or event.get("receipt_hash") != receipt_hash
            or event.get("recorded_at") != row.get("recorded_utc")
            or not isinstance(event_binding, Mapping)
            or dict(event_binding) not in (exact_binding, legacy_binding)
        ):
            reasons.append(
                "PPO_RECEIPT_ARCHIVE_SYNC_BOUND_EVENT_MISMATCH:"
                + str(sequence)
            )
            continue
        checked += 1
    if checked != len(bindings):
        reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BOUND_EVENT_COUNT_MISMATCH")
    reasons = list(dict.fromkeys(reasons))
    status.update(
        {
            "archive_sync_metadata_integrity_verified": metadata_valid,
            "archive_event_bindings_checked": checked,
            "archive_event_bindings_verified": not reasons,
            "archive_sync_integrity_verified": not reasons,
            "archive_sync_rejection_reasons": reasons,
            "archive_root": str(archive_root),
        }
    )
    return status


def _sync_durable_receipt_consumption(
    *,
    ledger: Any,
    archive_root: Path | None = None,
    update_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Mirror terminal PPO ledger rows into immutable receipt lifecycles.

    The SQLite ledger is the optimizer replay authority.  This journal mirror is
    written only after a terminal ledger disposition exists, and is safe to
    retry after a crash because lifecycle writes are create-or-identical.
    """

    root = Path(archive_root) if archive_root is not None else (
        default_behavior_receipt_archive_root()
    )
    sync_before = _verified_durable_receipt_archive_sync_status(
        ledger=ledger,
        archive_root=root,
    )
    if sync_before.get("archive_sync_integrity_verified") is not True:
        raise RuntimeError("durable_receipt_consumption_watermark_invalid")
    expected_keys = None if update_keys is None else set(update_keys)
    requested_rows = [] if update_keys is None else ledger.attempt_rows(update_keys)
    requested_observed = {
        str(row.get("update_key") or "") for row in requested_rows
    }
    if expected_keys is not None and requested_observed != expected_keys:
        raise RuntimeError("durable_receipt_consumption_ledger_rows_missing")
    attempts = ledger.unsynced_attempt_rows()

    appended = 0
    already_present = 0
    event_hashes: list[str] = []
    for attempt in attempts:
        update_key = str(attempt.get("update_key") or "")
        receipt_hash = str(attempt.get("receipt_hash") or "")
        outcome_digest = str(
            attempt.get("finalized_outcome_digest") or ""
        )
        parent_fingerprint = str(
            attempt.get("parent_policy_fingerprint") or ""
        )
        if (
            not _sha256_hex(update_key)
            or not _sha256_hex(receipt_hash)
            or not _sha256_hex(outcome_digest)
            or not _sha256_hex(parent_fingerprint)
            or ppo_consumption_update_key(
                receipt_hash=receipt_hash,
                finalized_outcome_digest=outcome_digest,
                parent_policy_fingerprint=parent_fingerprint,
            )
            != update_key
        ):
            raise RuntimeError("durable_receipt_consumption_ledger_binding_invalid")
        try:
            receipt = load_behavior_receipt(receipt_hash, root=root)
            verify_archived_behavior_receipt(receipt, root=root)
            status = receipt_lifecycle_status(receipt_hash, root=root)
            receipt_events = lifecycle_events(receipt_hash, root=root)
        except (BehaviorReceiptArchiveError, OSError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "durable_receipt_consumption_archive_invalid"
            ) from exc
        finalized_binding = (
            status.get("event_bindings", {}).get(EVENT_OUTCOME_FINALIZED)
            if isinstance(status.get("event_bindings"), Mapping)
            else None
        )
        if (
            status.get("outcome_finalized_durable") is not True
            or not isinstance(finalized_binding, Mapping)
            or finalized_binding.get("finalized_outcome_digest")
            != outcome_digest
            or finalized_binding.get("ppo_consumption_update_key")
            != update_key
        ):
            raise RuntimeError(
                "durable_receipt_consumption_finalized_binding_invalid"
            )
        legacy_binding = {
            "ppo_consumption_update_key": update_key,
            "ledger_sequence": int(attempt["sequence"]),
            "ledger_chain_hash": str(attempt.get("chain_hash") or ""),
            "ledger_disposition": str(attempt.get("disposition") or ""),
            "checkpoint_id": attempt.get("checkpoint_id"),
            "child_policy_fingerprint": str(
                attempt.get("child_policy_fingerprint") or ""
            ),
            "finalized_outcome_digest": outcome_digest,
        }
        binding = {
            **legacy_binding,
            "ledger_recorded_utc": str(attempt.get("recorded_utc") or ""),
        }
        if (
            not _sha256_hex(binding["ledger_chain_hash"])
            or not binding["ledger_disposition"]
            or not _sha256_hex(binding["child_policy_fingerprint"])
        ):
            raise RuntimeError(
                "durable_receipt_consumption_terminal_binding_invalid"
            )
        existing_binding = (
            status.get("event_bindings", {}).get(EVENT_TRAINER_CONSUMED)
            if isinstance(status.get("event_bindings"), Mapping)
            else None
        )
        if status.get("trainer_consumed_durable") is True:
            consumed_event = next(
                (
                    event
                    for event in receipt_events
                    if event.get("event_type") == EVENT_TRAINER_CONSUMED
                ),
                None,
            )
            existing_matches = bool(
                isinstance(existing_binding, Mapping)
                and isinstance(consumed_event, Mapping)
                and consumed_event.get("recorded_at")
                == binding["ledger_recorded_utc"]
                and (
                    dict(existing_binding) == binding
                    # Events written by the immediately preceding archive
                    # schema did not duplicate the ledger clock in the
                    # binding; their immutable event recorded_at was still the
                    # hash-chained ledger recorded_utc.  Accept only that exact
                    # legacy field set so upgrade/restart remains idempotent.
                    or dict(existing_binding) == legacy_binding
                )
            )
            if not existing_matches:
                raise RuntimeError(
                    "durable_receipt_consumption_existing_binding_conflict"
                )
            consumed_event_hash = str(consumed_event.get("event_hash") or "")
        if status.get("trainer_consumed_durable") is True:
            already_present += 1
        else:
            try:
                write = append_behavior_receipt_lifecycle_event(
                    receipt_hash=receipt_hash,
                    event_type=EVENT_TRAINER_CONSUMED,
                    binding=binding,
                    root=root,
                    recorded_at=str(attempt.get("recorded_utc") or ""),
                )
            except (
                BehaviorReceiptArchiveError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                raise RuntimeError("durable_receipt_consumption_write_failed") from exc
            consumed_event_hash = write.event_hash
            event_hashes.append(write.event_hash)
            if write.already_present:
                already_present += 1
            else:
                appended += 1
        try:
            ledger.mark_archive_synced(
                sequence=int(attempt["sequence"]),
                chain_hash=str(attempt.get("chain_hash") or ""),
                receipt_hash=receipt_hash,
                trainer_consumed_event_hash=consumed_event_hash,
            )
        except (RuntimeError, TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(
                "durable_receipt_consumption_watermark_advance_failed"
            ) from exc
    sync_after = _verified_durable_receipt_archive_sync_status(
        ledger=ledger,
        archive_root=root,
    )
    if sync_after.get("archive_sync_integrity_verified") is not True:
        raise RuntimeError("durable_receipt_consumption_watermark_post_sync_invalid")
    return {
        "schema_version": "v2_trainer_durable_receipt_consumption_sync_v1",
        "ledger_attempts_checked": len(attempts),
        "trainer_consumed_events_appended": appended,
        "trainer_consumed_events_already_present": already_present,
        "trainer_consumed_event_hashes": event_hashes,
        "archive_sync_before": sync_before,
        "archive_sync_after": sync_after,
        "legacy_terminal_attempts_not_archive_bound": int(
            sync_after.get("legacy_terminal_attempts_not_archive_bound") or 0
        ),
        "unsynced_terminal_attempts": int(
            sync_after.get("unsynced_terminal_attempts") or 0
        ),
        "archive_root": str(root),
        "sync_complete": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _strict_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _verified_serving_checkpoint_evidence(
    checkpoint_reload: Mapping[str, Any],
    *,
    expected_checkpoint_id: str,
) -> tuple[bool, tuple[str, ...]]:
    """Verify that a loaded artifact is a promoted serving policy.

    A digest-valid candidate is intentionally insufficient. Exact sampling can
    issue a behavior receipt only from a content-addressed weight blob whose
    optimizer, PIT validation, confidence, promotion, ledger, and lineage proof
    is complete and bound to the artifact that was actually restored.
    """

    load = dict(checkpoint_reload)
    reasons: list[str] = []
    required_load_truths = (
        "latest_checkpoint_loadable",
        "model_state_restored",
        "weight_file_sha256_verified",
        "model_parameter_fingerprint_verified",
        "checkpoint_evidence_verified",
        "checkpoint_identity_verified",
    )
    for field_name in required_load_truths:
        if load.get(field_name) is not True:
            reasons.append(f"serving_checkpoint_{field_name}_false")
    if load.get("checkpoint_id") != expected_checkpoint_id:
        reasons.append("serving_checkpoint_identity_not_bound_to_selected_manifest")
    if not _sha256_hex(load.get("weight_file_sha256")):
        reasons.append("serving_checkpoint_weight_sha256_invalid")
    if not _sha256_hex(load.get("model_parameter_fingerprint")):
        reasons.append("serving_checkpoint_parameter_fingerprint_invalid")

    evidence = load.get("checkpoint_evidence")
    evidence_digest = str(load.get("checkpoint_evidence_digest") or "")
    if not isinstance(evidence, Mapping):
        reasons.append("serving_checkpoint_evidence_missing")
        evidence = {}
    if not _sha256_hex(evidence_digest):
        reasons.append("serving_checkpoint_evidence_digest_invalid")
    else:
        try:
            observed_digest = hashlib.sha256(
                json.dumps(
                    dict(evidence),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError):
            reasons.append("serving_checkpoint_evidence_not_canonical")
        else:
            if observed_digest != evidence_digest:
                reasons.append("serving_checkpoint_evidence_digest_mismatch")

    evidence_map = dict(evidence)
    if evidence_map.get("checkpoint_role") != "VERIFIED_SERVING_POLICY":
        reasons.append("serving_checkpoint_role_not_verified_serving_policy")
    if evidence_map.get("ledger_disposition") != "SERVING_PROMOTED":
        reasons.append("serving_checkpoint_ledger_disposition_not_promoted")
    if load.get("lineage_kind") != "VERIFIED_SERVING_POLICY" or evidence_map.get(
        "lineage_kind"
    ) != "VERIFIED_SERVING_POLICY":
        reasons.append("serving_checkpoint_lineage_kind_invalid")

    serving_evidence_raw = evidence_map.get("serving_promotion_decision")
    comparison_status = (
        serving_evidence_raw.get("same_partition_incumbent_comparison_status")
        if isinstance(serving_evidence_raw, Mapping)
        else None
    )
    bootstrap_without_incumbent = bool(
        isinstance(serving_evidence_raw, Mapping)
        and comparison_status
        == "BOOTSTRAP_NO_INCUMBENT_SAME_PARTITION_NOT_APPLICABLE"
        and serving_evidence_raw.get("prior_verified_serving_exists") is False
        and serving_evidence_raw.get(
            "training_parent_is_non_serving_candidate"
        )
        is False
    )
    no_incumbent_candidate_parent = bool(
        isinstance(serving_evidence_raw, Mapping)
        and comparison_status
        == "NO_INCUMBENT_VERIFIED_NON_SERVING_CANDIDATE_PARENT"
        and serving_evidence_raw.get("prior_verified_serving_exists") is False
        and serving_evidence_raw.get(
            "training_parent_is_non_serving_candidate"
        )
        is True
    )
    parent_checkpoint_id = load.get("parent_checkpoint_id")
    parent_fingerprint = str(load.get("parent_policy_fingerprint") or "")
    if not bootstrap_without_incumbent and not str(parent_checkpoint_id or ""):
        reasons.append("serving_checkpoint_parent_checkpoint_id_missing")
    if bootstrap_without_incumbent and parent_checkpoint_id not in (None, ""):
        reasons.append("serving_checkpoint_bootstrap_parent_checkpoint_unexpected")
    if no_incumbent_candidate_parent and not str(parent_checkpoint_id or ""):
        reasons.append("serving_checkpoint_candidate_parent_checkpoint_missing")
    if not _sha256_hex(parent_fingerprint):
        reasons.append("serving_checkpoint_parent_fingerprint_invalid")
    for field_name, expected in (
        ("parent_checkpoint_id", parent_checkpoint_id),
        ("parent_policy_fingerprint", parent_fingerprint),
        ("training_partition_digest", load.get("training_partition_digest")),
    ):
        if evidence_map.get(field_name) != expected:
            reasons.append(f"serving_checkpoint_{field_name}_evidence_mismatch")

    update_keys_raw = load.get("consumed_ppo_update_keys")
    update_keys = (
        [str(value) for value in update_keys_raw]
        if isinstance(update_keys_raw, list | tuple)
        else []
    )
    if not isinstance(update_keys_raw, list | tuple):
        reasons.append("serving_checkpoint_consumed_update_keys_missing")
    if any(not _sha256_hex(value) for value in update_keys):
        reasons.append("serving_checkpoint_consumed_update_key_invalid")
    if len(update_keys) != len(set(update_keys)):
        reasons.append("serving_checkpoint_consumed_update_keys_not_unique")
    if evidence_map.get("consumed_ppo_update_keys") != update_keys:
        reasons.append("serving_checkpoint_consumed_update_keys_evidence_mismatch")
    try:
        from .training_state import training_partition_digest

        expected_partition_digest = training_partition_digest(update_keys)
    except (TypeError, ValueError):
        expected_partition_digest = None
        reasons.append("serving_checkpoint_training_partition_invalid")
    if (
        expected_partition_digest is None
        or load.get("training_partition_digest") != expected_partition_digest
    ):
        reasons.append("serving_checkpoint_training_partition_digest_mismatch")

    candidate = evidence_map.get("candidate_progress_decision")
    if not isinstance(candidate, Mapping) or candidate.get(
        "candidate_progress_allowed"
    ) is not True:
        reasons.append("serving_checkpoint_candidate_progress_not_allowed")

    confidence = evidence_map.get("confidence_promotion_decision")
    if not isinstance(confidence, Mapping):
        reasons.append("serving_checkpoint_confidence_promotion_missing")
        confidence = {}
    if confidence.get("confidence_promotion_gate_passed") is not True:
        reasons.append("serving_checkpoint_confidence_promotion_not_passed")
    fit_digest = confidence.get("fit_row_digest")
    validation_digest = confidence.get("validation_row_digest")
    if not _sha256_hex(fit_digest) or not _sha256_hex(validation_digest):
        reasons.append("serving_checkpoint_confidence_partition_digest_invalid")
    elif fit_digest == validation_digest:
        reasons.append("serving_checkpoint_confidence_partition_digest_collision")

    serving = serving_evidence_raw
    if not isinstance(serving, Mapping):
        reasons.append("serving_checkpoint_promotion_decision_missing")
        serving = {}
    if serving.get("checkpoint_promotion_allowed") is not True:
        reasons.append("serving_checkpoint_promotion_not_allowed")
    if serving.get("mandatory_pit_edge_gate_passed") is not True:
        reasons.append("serving_checkpoint_pit_edge_gate_not_passed")
    if serving.get("same_partition_incumbent_comparison_proven") is not True:
        reasons.append("serving_checkpoint_same_partition_comparison_not_proven")
    if serving.get("same_partition_incumbent_comparison_status") not in {
        "PASS_SAME_UNTOUCHED_FORWARD_PARTITION",
        "BOOTSTRAP_NO_INCUMBENT_SAME_PARTITION_NOT_APPLICABLE",
        "NO_INCUMBENT_VERIFIED_NON_SERVING_CANDIDATE_PARENT",
    }:
        reasons.append("serving_checkpoint_same_partition_comparison_status_invalid")

    optimizer = evidence_map.get("optimizer_evidence")
    if not isinstance(optimizer, Mapping):
        reasons.append("serving_checkpoint_optimizer_evidence_missing")
        optimizer = {}
    optimizer_steps = _strict_nonnegative_int(
        optimizer.get("optimizer_steps_this_cycle")
    )
    if optimizer_steps is None or optimizer_steps <= 0:
        reasons.append("serving_checkpoint_optimizer_steps_missing")
    parameter_before = optimizer.get("parameter_hash_before")
    parameter_after = optimizer.get("parameter_hash_after")
    if not _sha256_hex(parameter_before) or not _sha256_hex(parameter_after):
        reasons.append("serving_checkpoint_optimizer_parameter_hash_invalid")
    elif parameter_before == parameter_after:
        reasons.append("serving_checkpoint_optimizer_parameters_unchanged")
    loaded_parent_fingerprint = str(load.get("parent_policy_fingerprint") or "")
    loaded_candidate_fingerprint = str(
        load.get("model_parameter_fingerprint") or ""
    )
    if parameter_before != loaded_parent_fingerprint:
        reasons.append("serving_checkpoint_optimizer_parent_fingerprint_mismatch")
    if parameter_after != loaded_candidate_fingerprint:
        reasons.append("serving_checkpoint_optimizer_artifact_fingerprint_mismatch")
    if optimizer.get("actual_training_parent_policy_fingerprint") != (
        loaded_parent_fingerprint
    ):
        reasons.append("serving_checkpoint_actual_parent_fingerprint_mismatch")
    if optimizer.get("actual_candidate_policy_fingerprint") != (
        loaded_candidate_fingerprint
    ):
        reasons.append("serving_checkpoint_actual_artifact_fingerprint_mismatch")
    if optimizer.get("optimizer_parameter_fingerprints_bound") is not True:
        reasons.append("serving_checkpoint_optimizer_fingerprint_binding_not_proven")
    if optimizer.get("ppo_consumed_update_keys") != update_keys:
        reasons.append("serving_checkpoint_optimizer_update_keys_mismatch")
    if update_keys:
        for field_name in (
            "ppo_consumed_update_keys_complete",
            "ppo_consumed_update_keys_ordered",
            "ppo_consumed_update_keys_unique",
        ):
            if optimizer.get(field_name) is not True:
                reasons.append(f"serving_checkpoint_{field_name}_false")
        ppo_epochs = _strict_nonnegative_int(
            optimizer.get(
                "ppo_configured_optimizer_epochs_per_consumption_claim"
            )
        )
        if ppo_epochs is None or ppo_epochs <= 0:
            reasons.append("serving_checkpoint_optimizer_epoch_declaration_invalid")
        if not isinstance(
            optimizer.get(
                "ppo_rows_reused_across_optimizer_steps_within_train_call"
            ),
            bool,
        ):
            reasons.append(
                "serving_checkpoint_optimizer_row_reuse_declaration_missing"
            )
    elif (
        optimizer.get("outcome_supervised_bootstrap") is not True
        or optimizer.get("optimizer_input_lane") != "outcome_supervised"
    ):
        reasons.append("serving_checkpoint_bootstrap_lane_declaration_invalid")

    validation = evidence_map.get("validation_evidence")
    if not isinstance(validation, Mapping):
        reasons.append("serving_checkpoint_validation_evidence_missing")
        validation = {}
    if validation.get("validation_split_pit_safe") is not True:
        reasons.append("serving_checkpoint_validation_split_not_pit_safe")
    if validation.get("validation_split_temporal_overlap") is not False:
        reasons.append("serving_checkpoint_validation_temporal_overlap_not_false")
    if validation.get("validation_split_label_overlap") is not False:
        reasons.append("serving_checkpoint_validation_label_overlap_not_false")
    train_rows = _strict_nonnegative_int(
        validation.get("validation_split_actual_training_rows")
    )
    validation_rows = _strict_nonnegative_int(
        validation.get("validation_split_actual_validation_rows")
    )
    edge_rows = _strict_nonnegative_int(
        validation.get("validation_policy_edge_rows_evaluated")
    )
    if (
        train_rows is None
        or validation_rows is None
        or train_rows <= 0
        or validation_rows <= 0
        or edge_rows != validation_rows
    ):
        reasons.append("serving_checkpoint_validation_row_count_invalid")
    train_end = _strict_utc(
        validation.get("validation_split_training_end_decision_time")
    )
    train_label_max = _strict_utc(
        validation.get("validation_split_training_label_available_at_max")
    )
    validation_start = _strict_utc(
        validation.get("validation_split_validation_start_decision_time")
    )
    if None in (train_end, train_label_max, validation_start):
        reasons.append("serving_checkpoint_validation_frontier_missing")
    else:
        assert train_end is not None and train_label_max is not None
        assert validation_start is not None
        if not train_end < validation_start or train_label_max > validation_start:
            reasons.append("serving_checkpoint_validation_frontier_order_invalid")
    edge_mean = _finite_float(
        validation.get("validation_policy_edge_after_cost_bps")
    )
    edge_se = _finite_float(
        validation.get("validation_policy_edge_standard_error_bps")
    )
    edge_lcb = _finite_float(
        validation.get("validation_policy_edge_lower_confidence_bound_bps")
    )
    if (
        edge_mean is None
        or edge_se is None
        or edge_lcb is None
        or edge_se < 0.0
        or edge_lcb <= 0.0
    ):
        reasons.append("serving_checkpoint_validation_edge_proof_invalid")
    serving_lcb = _finite_float(
        serving.get("validation_policy_edge_lower_confidence_bound_bps")
    )
    if edge_lcb is None or serving_lcb is None or not math.isclose(
        edge_lcb, serving_lcb, rel_tol=1e-12, abs_tol=1e-12
    ):
        reasons.append("serving_checkpoint_validation_edge_promotion_mismatch")
    if validation.get("validation_confidence_eligible_row_digest") != validation_digest:
        reasons.append("serving_checkpoint_confidence_validation_digest_mismatch")
    for scope in ("", "long_", "short_"):
        for calibration in ("raw", "calibrated"):
            for metric in ("brier", "ece"):
                field_name = f"validation_confidence_{scope}{calibration}_{metric}"
                value = _finite_float(validation.get(field_name))
                if value is None or not 0.0 <= value <= 1.0:
                    reasons.append(f"serving_checkpoint_{field_name}_invalid")

    # A hash proves immutability, not semantic truth. Recompute every canonical
    # decision from its bound raw evidence and require byte-equivalent JSON data.
    decision_metrics = {**dict(validation), **dict(optimizer)}
    try:
        recomputed_candidate = candidate_progress_decision(decision_metrics)
    except Exception as exc:  # noqa: BLE001 - malformed evidence fails closed
        recomputed_candidate = {}
        reasons.append(
            "serving_checkpoint_candidate_decision_recompute_failed:"
            + type(exc).__name__
        )
    if not isinstance(candidate, Mapping) or dict(candidate) != recomputed_candidate:
        reasons.append("serving_checkpoint_candidate_decision_not_rederived")

    calibration_state = load.get("confidence_calibration_state")
    try:
        recomputed_confidence = confidence_promotion_decision(
            training_metrics=decision_metrics,
            calibration_state=(
                calibration_state
                if isinstance(calibration_state, Mapping)
                else None
            ),
            candidate_policy_fingerprint=str(
                load.get("model_parameter_fingerprint") or ""
            ),
        )
    except Exception as exc:  # noqa: BLE001 - malformed evidence fails closed
        recomputed_confidence = {}
        reasons.append(
            "serving_checkpoint_confidence_decision_recompute_failed:"
            + type(exc).__name__
        )
    if dict(confidence) != recomputed_confidence:
        reasons.append("serving_checkpoint_confidence_decision_not_rederived")

    try:
        recomputed_serving = serving_promotion_decision(
            training_metrics=decision_metrics,
            candidate_decision=recomputed_candidate,
            confidence_decision=recomputed_confidence,
            prior_verified_serving_exists=(
                serving.get("prior_verified_serving_exists") is True
            ),
            training_parent_is_verified_serving=(
                serving.get("training_parent_is_verified_serving") is True
            ),
            training_parent_is_non_serving_candidate=(
                serving.get("training_parent_is_non_serving_candidate") is True
            ),
        )
    except Exception as exc:  # noqa: BLE001 - malformed evidence fails closed
        recomputed_serving = {}
        reasons.append(
            "serving_checkpoint_promotion_decision_recompute_failed:"
            + type(exc).__name__
        )
    if any(
        key not in serving or serving.get(key) != value
        for key, value in recomputed_serving.items()
    ):
        reasons.append("serving_checkpoint_promotion_decision_not_rederived")

    return not reasons, tuple(sorted(set(reasons)))


def _normalized_verified_serving_evidence(
    *,
    checkpoint: CheckpointManifest,
    checkpoint_reload: Mapping[str, Any],
    semantic_verification_complete: bool,
) -> dict[str, Any]:
    """Normalize manager evidence without promoting a weaker hash-only claim."""

    reload = dict(checkpoint_reload)
    checkpoint_evidence_map = reload.get("checkpoint_evidence")
    checkpoint_evidence_payload = (
        dict(checkpoint_evidence_map)
        if isinstance(checkpoint_evidence_map, Mapping)
        else {}
    )
    optimizer_map = checkpoint_evidence_payload.get("optimizer_evidence")
    optimizer = dict(optimizer_map) if isinstance(optimizer_map, Mapping) else {}
    generation = _strict_nonnegative_int(reload.get("checkpoint_generation"))
    causal_order_verified = bool(
        semantic_verification_complete
        and generation is not None
        and _sha256_hex(reload.get("checkpoint_semantic_digest"))
        and _sha256_hex(reload.get("checkpoint_causal_record_digest"))
    )
    ledger_disposition = checkpoint_evidence_payload.get("ledger_disposition")
    return {
        "checkpoint_artifact_verified": semantic_verification_complete,
        "causal_order_verified": causal_order_verified,
        "lineage_kind": reload.get("lineage_kind"),
        "checkpoint_id": reload.get("checkpoint_id"),
        "parent_checkpoint_id": reload.get("parent_checkpoint_id"),
        "model_parameter_fingerprint": reload.get(
            "model_parameter_fingerprint"
        ),
        "parent_policy_fingerprint": reload.get("parent_policy_fingerprint"),
        "weight_file_sha256": reload.get("weight_file_sha256"),
        "exact_optimizer_contract_durable": bool(
            semantic_verification_complete
            and optimizer.get("exact_optimizer_contract_valid") is True
            and optimizer.get("optimizer_parameter_fingerprints_bound") is True
            and ledger_disposition == "SERVING_PROMOTED"
        ),
        "ledger_disposition": ledger_disposition,
        "generated_utc": checkpoint.generated_utc,
        "manager_semantic_verification_recomputed_this_cycle": True,
    }


def _lineage_identity_complete(
    *,
    lineages: list[Mapping[str, Any]],
    cycle_id: str,
    process_instance_id: str,
    checkpoint_id: str,
    candidate_policy_fingerprint: str,
) -> bool:
    required = {
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "checkpoint_id": checkpoint_id,
        "candidate_policy_fingerprint": candidate_policy_fingerprint,
    }
    if not lineages:
        return False
    for lineage in lineages:
        if any(lineage.get(key) != value for key, value in required.items()):
            return False
        for field_name in (
            "trainer_prediction_record",
            "orchestrator_decision_record",
            "risk_decision_record",
            "paper_execution_ledger_entry",
            "paper_signal_lineage",
        ):
            record = lineage.get(field_name)
            if not isinstance(record, Mapping) or any(
                record.get(key) != value
                for key, value in required.items()
                if key != "checkpoint_id"
                or field_name != "trainer_prediction_record"
            ):
                return False
            if record.get("checkpoint_id") != checkpoint_id:
                return False
        receipt = lineage.get("publication_receipt")
        component_receipts = (
            list(receipt.get("component_receipts") or ())
            if isinstance(receipt, Mapping)
            else []
        )
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("publication_complete") is not True
            or receipt.get("publication_scope")
            != "TRAINER_NONAUTHORITATIVE_PROPOSALS_ONLY"
            or receipt.get("counts_as_end_to_end_authoritative_lineage")
            is not False
            or len(component_receipts) != 9
            or not all(isinstance(component, Mapping) for component in component_receipts)
            or any(
                component.get("publication_complete") is not True
                or component.get("acknowledged") is not True
                or component.get("readback_verified") is not True
                for component in component_receipts
                if isinstance(component, Mapping)
            )
        ):
            return False
    return True


def _current_cycle_grid_readback_evidence(
    *,
    io: V2OnlyJsonIO,
    predictions: list[Mapping[str, Any]],
    lineages: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Re-read every durable per-scope key after the whole grid is published."""

    lineage_by_prediction_id = {
        str(lineage.get("trainer_prediction_record", {}).get("prediction_id")): lineage
        for lineage in lineages
        if isinstance(lineage.get("trainer_prediction_record"), Mapping)
    }
    receipts: list[dict[str, Any]] = []
    for prediction in predictions:
        symbol = str(prediction.get("symbol") or "")
        timeframe = str(prediction.get("timeframe") or "")
        prediction_id = str(prediction.get("prediction_id") or "")
        lineage = lineage_by_prediction_id.get(prediction_id)
        signal = (
            lineage.get("paper_signal_lineage")
            if isinstance(lineage, Mapping)
            else None
        )
        targets = (
            (
                PREDICTION_KEY_TEMPLATE.format(
                    symbol=symbol,
                    timeframe=timeframe,
                ),
                prediction,
                "prediction",
            ),
            (
                PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE.format(
                    symbol=symbol,
                    timeframe=timeframe,
                ),
                signal,
                "paper_signal_timeframe",
            ),
        )
        for key, expected, record_kind in targets:
            actual = io.get_json(key)
            try:
                exact = bool(
                    isinstance(expected, Mapping)
                    and isinstance(actual, Mapping)
                    and canonical_sha256(dict(actual))
                    == canonical_sha256(dict(expected))
                )
            except (TypeError, ValueError):
                exact = False
            receipts.append(
                {
                    "key": key,
                    "record_kind": record_kind,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "prediction_id": prediction_id,
                    "readback_verified": exact,
                }
            )
    expected_receipt_count = len(predictions) * 2
    complete = bool(
        predictions
        and len(lineages) == len(predictions)
        and len(receipts) == expected_receipt_count
        and all(receipt["readback_verified"] is True for receipt in receipts)
    )
    return {
        "schema_version": "v2_trainer_current_cycle_grid_readback_v1",
        "publication_complete": complete,
        "expected_receipt_count": expected_receipt_count,
        "verified_receipt_count": sum(
            1 for receipt in receipts if receipt["readback_verified"] is True
        ),
        "component_receipts": receipts,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


# Symbol-adaptive round-trip cost keys published by
# services/paper_trade_management/adaptive_cost_model.py (via the
# all-timeframe signal publisher). The trainer consumes them read-only with a
# flat-config fallback so a cost-model outage can never block prediction
# publishing.
_ADAPTIVE_COST_KEY_TEMPLATE = "v2:costs:round_trip_bps:{symbol}"
_ADAPTIVE_ON_POLICY_LANE_STATE: dict[str, float | int] = {
    "carry": 0.0,
    "single_candidate_ordinary_credit": 0,
}


def _effective_paper_entry_gate_from_heartbeat(
    heartbeat: Any,
) -> dict[str, Any] | None:
    """Extract the paper loop's composed, fail-closed entry-gate truth."""
    if not isinstance(heartbeat, dict):
        return None
    for field_name in ("paper_effective_entry_gate_status", "paper_entry_freeze"):
        candidate = heartbeat.get(field_name)
        if (
            isinstance(candidate, dict)
            and candidate.get("schema_version")
            == "paper_effective_entry_gate_status_v1"
            and candidate.get("paper_only") is True
            and candidate.get("routes_to_live") is False
            and candidate.get("places_real_order") is False
        ):
            return dict(candidate)
    return None


def _paper_margin_status_from_heartbeat(
    heartbeat: Any,
) -> dict[str, Any] | None:
    """Extract canonical margin truth from the same TTL-bound paper cycle."""
    if not isinstance(heartbeat, dict):
        return None
    margin = heartbeat.get("paper_account_margin_status")
    if (
        isinstance(margin, dict)
        and margin.get("schema_version") == "paper_account_margin_v1"
        and margin.get("paper_only") is True
        and margin.get("routes_to_live") is False
        and margin.get("places_real_order") is False
    ):
        return dict(margin)
    return None


def _adaptive_round_trip_cost_evidence(
    symbol: str,
    *,
    safe_io: V2OnlyJsonIO,
    flat_round_trip_bps: float,
    fee_floor_bps: float,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return ordinary cost plus exact sampling provenance when available.

    Ordinary deterministic predictions retain the conservative fallback. Exact
    sampling accepts only the estimator's fresh, non-floor source contract and
    does not add a second static consumer-age threshold.
    """
    symbol_norm = str(symbol or "").strip().upper()
    if symbol_norm in cache:
        return cache[symbol_norm]
    source_key = _ADAPTIVE_COST_KEY_TEMPLATE.format(symbol=symbol_norm)
    resolved = max(float(flat_round_trip_bps), float(fee_floor_bps))
    exact_provenance: dict[str, Any] | None = None
    rejection_reason = "ADAPTIVE_COST_PAYLOAD_MISSING"
    try:
        payload = safe_io.get_json(source_key)
        if isinstance(payload, dict):
            value = _finite_float(payload.get("round_trip_cost_bps"))
            if value is not None and value > 0.0:
                resolved = max(value, float(fee_floor_bps))
            try:
                exact_provenance = build_exact_cost_provenance(
                    source_key=source_key,
                    source_payload=payload,
                    consumer_observed_at=_utc_iso_microseconds(),
                )
                resolved = float(exact_provenance["round_trip_cost_bps"])
                rejection_reason = ""
            except (TypeError, ValueError) as exc:
                rejection_reason = str(exc)
    except Exception:  # noqa: BLE001 - cost lookup must never break the trainer
        resolved = float(flat_round_trip_bps)
        rejection_reason = "ADAPTIVE_COST_LOOKUP_FAILED"
    result = {
        "round_trip_cost_bps": resolved,
        "exact_cost_provenance": exact_provenance,
        "exact_cost_provenance_valid": exact_provenance is not None,
        "exact_cost_payload_hash": (
            exact_provenance.get("source_payload_sha256")
            if exact_provenance is not None
            else None
        ),
        "exact_cost_rejection_reason": rejection_reason or None,
        "ordinary_cost_fallback_allowed": exact_provenance is None,
        "source_key": source_key,
    }
    cache[symbol_norm] = result
    return result


def _checkpoint_promotion_status_fields(
    checkpoint_promotion: dict[str, Any],
) -> dict[str, Any]:
    return {
        "pit_edge_promotion_gate_active": checkpoint_promotion.get(
            "pit_edge_promotion_gate_active"
        ),
        "mandatory_pit_edge_gate_passed": checkpoint_promotion.get(
            "mandatory_pit_edge_gate_passed"
        ),
        "checkpoint_promotion_guard_active": checkpoint_promotion.get(
            "checkpoint_promotion_guard_active"
        ),
        "checkpoint_promotion_allowed": checkpoint_promotion.get(
            "checkpoint_promotion_allowed"
        ),
        "checkpoint_promotion_rejected": checkpoint_promotion.get(
            "checkpoint_promotion_rejected"
        ),
        "checkpoint_promotion_reason": checkpoint_promotion.get(
            "checkpoint_promotion_reason"
        ),
        "overfit_gap_warning_advisory": checkpoint_promotion.get(
            "overfit_gap_warning_advisory"
        ),
        "prior_promotion_rejection_streak": checkpoint_promotion.get(
            "prior_promotion_rejection_streak"
        ),
        "promotion_rejection_streak_after": checkpoint_promotion.get(
            "promotion_rejection_streak_after"
        ),
        "max_promotion_rejection_streak": checkpoint_promotion.get(
            "max_promotion_rejection_streak"
        ),
        "forced_promote_after_rejection_streak": checkpoint_promotion.get(
            "forced_promote_after_rejection_streak"
        ),
        "forced_promote_after_rejection_streak_blocked": checkpoint_promotion.get(
            "forced_promote_after_rejection_streak_blocked"
        ),
        "forced_promote_block_reason": checkpoint_promotion.get(
            "forced_promote_block_reason"
        ),
        "hard_promotion_rejection_reason": checkpoint_promotion.get(
            "hard_promotion_rejection_reason"
        ),
        "pit_edge_hard_rejection_reason": checkpoint_promotion.get(
            "pit_edge_hard_rejection_reason"
        ),
        "force_promote_after_rejection_streak_enabled": checkpoint_promotion.get(
            "force_promote_after_rejection_streak_enabled"
        ),
        "validation_split_pit_safe": checkpoint_promotion.get(
            "validation_split_pit_safe"
        ),
        "validation_split_reason": checkpoint_promotion.get(
            "validation_split_reason"
        ),
        "validation_policy_edge_status": checkpoint_promotion.get(
            "validation_policy_edge_status"
        ),
        "validation_policy_edge_after_cost_bps": checkpoint_promotion.get(
            "validation_policy_edge_after_cost_bps"
        ),
        "validation_policy_edge_lower_confidence_bound_bps": checkpoint_promotion.get(
            "validation_policy_edge_lower_confidence_bound_bps"
        ),
        "validation_policy_edge_rows_evaluated": checkpoint_promotion.get(
            "validation_policy_edge_rows_evaluated"
        ),
        "model_serving_allowed": checkpoint_promotion.get("model_serving_allowed"),
        "model_serving_source": checkpoint_promotion.get("model_serving_source"),
        "rejected_candidate_serving_suppressed": checkpoint_promotion.get(
            "rejected_candidate_serving_suppressed"
        ),
        "model_serving_suppression_reason": checkpoint_promotion.get(
            "model_serving_suppression_reason"
        ),
    }


def _increment_rejection_reason(counts: dict[str, int], reason: Any) -> None:
    text = str(reason or "").strip()
    if not text or text.upper() == "NONE":
        return
    counts[text] = counts.get(text, 0) + 1


def _feedback_quarantine_rejection_counts(io: V2OnlyJsonIO) -> dict[str, int]:
    rows = io.get_json("v2:trainer:feedback:outcomes:quarantine")
    if rows is None:
        return {}
    if not isinstance(rows, list):
        return {"quarantine_not_list": 1}
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            _increment_rejection_reason(counts, "invalid_quarantine_row")
            continue
        emitted = False
        for field_name in (
            "trust_envelope_rejection_reasons",
            "trust_reconstruction_rejection_reasons",
            "audit_quality_rejection_reasons",
            "missing_feedback_classifications",
            "missing_feedback_fields",
        ):
            values = row.get(field_name)
            if isinstance(values, list):
                for value in values:
                    _increment_rejection_reason(counts, value)
                    emitted = True
            elif values not in (None, "", [], {}):
                _increment_rejection_reason(counts, values)
                emitted = True
        if not emitted:
            for reason in str(row.get("quarantine_reason") or "quarantined_without_reason").split(","):
                _increment_rejection_reason(counts, reason)
    return counts


def _without_consumed_exact_examples(
    examples: list[Any],
    *,
    consumed_update_keys: set[str],
) -> tuple[list[Any], int]:
    """Remove consumed exact rows entirely so they cannot change training lane."""
    retained: list[Any] = []
    removed = 0
    for example in examples:
        row = dict(getattr(example, "trust_row", None) or {})
        keys: set[str] = set()
        observed = str(row.get("ppo_consumption_update_key") or "")
        if len(observed) == 64:
            keys.add(observed)
        try:
            keys.add(ppo_consumption_update_key_from_row(row))
        except (TypeError, ValueError):
            pass
        if keys & consumed_update_keys:
            removed += 1
            continue
        retained.append(example)
    return retained, removed


def _claim_exact_optimizer_plan(
    *,
    trainer: V2HybridPPOTrainer,
    examples: list[Any],
    ledger: Any,
    batch_size: int,
    validation_fraction: float,
) -> tuple[list[Any], dict[str, Any], str, dict[str, Any]]:
    """Reach a stable planner/claim fixed point before optimizer entry."""
    working = list(examples)
    owner_id = ledger.process_owner_id()
    held_keys: set[str] = set()
    last_plan: dict[str, Any] = {}
    for _iteration in range(len(working) + 2):
        plan = trainer.plan_exact_ppo_optimizer_attempts(
            working,
            batch_size=batch_size,
            validation_fraction=validation_fraction,
        )
        descriptors = list(plan.get("optimizer_attempt_descriptors") or ())
        eligible_examples = list(plan.get("eligible_examples") or ())
        ordered_keys = [str(row.get("update_key") or "") for row in descriptors]
        if (
            plan.get("ordered_update_keys_complete") is not True
            or plan.get("ordered_update_keys_unique") is not True
            or len(descriptors) != len(eligible_examples)
            or any(len(key) != 64 for key in ordered_keys)
        ):
            raise RuntimeError("exact_ppo_optimizer_plan_incomplete_or_ambiguous")
        if not descriptors:
            ledger.release_claims(
                owner_id=owner_id,
                update_keys=sorted(held_keys),
            )
            return working, plan, owner_id, {
                "claimed_update_keys": [],
                "unavailable_update_keys": [],
                "planner_fixed_point": True,
            }
        claim = ledger.claim_attempts(
            attempts=descriptors,
            owner_id=owner_id,
        )
        claimed = {str(value) for value in claim["claimed_update_keys"]}
        unavailable = {str(value) for value in claim["unavailable_update_keys"]}
        held_keys.update(claimed)
        if unavailable:
            blocked_example_ids = {
                id(example)
                for descriptor, example in zip(
                    descriptors,
                    eligible_examples,
                    strict=True,
                )
                if str(descriptor["update_key"]) in unavailable
            }
            if not blocked_example_ids:
                raise RuntimeError("exact_ppo_unavailable_claim_not_bound_to_example")
            working = [
                example for example in working if id(example) not in blocked_example_ids
            ]
            last_plan = plan
            continue
        final_keys = set(ordered_keys)
        extra_keys = held_keys - final_keys
        released = ledger.release_claims(
            owner_id=owner_id,
            update_keys=sorted(extra_keys),
        )
        if released != len(extra_keys):
            raise RuntimeError("exact_ppo_nonfinal_claim_release_failed")
        return working, plan, owner_id, {
            "claimed_update_keys": ordered_keys,
            "unavailable_update_keys": [],
            "planner_fixed_point": True,
        }
    ledger.release_claims(owner_id=owner_id, update_keys=sorted(held_keys))
    raise RuntimeError(
        "exact_ppo_optimizer_claim_plan_did_not_converge:"
        + str(len(last_plan.get("optimizer_attempt_descriptors") or ()))
    )


def _manifest_for_loaded_checkpoint(
    manager: V2HybridCheckpointManager,
    checkpoint_load: Mapping[str, Any],
    *,
    lineage_kind: str,
) -> CheckpointManifest | None:
    checkpoint_id = str(checkpoint_load.get("checkpoint_id") or "")
    if not checkpoint_id:
        return None
    for manifest in manager.manifests(
        allowed_lineage_kinds=frozenset({lineage_kind}),
        require_weight_blob=True,
    ):
        if manifest.checkpoint_id == checkpoint_id:
            return manifest
    return None


def _basic_checkpoint_load_verified(checkpoint_load: Mapping[str, Any]) -> bool:
    return all(
        checkpoint_load.get(field_name) is True
        for field_name in (
            "latest_checkpoint_loadable",
            "model_state_restored",
            "weight_file_sha256_verified",
            "model_parameter_fingerprint_verified",
            "checkpoint_evidence_verified",
            "checkpoint_identity_verified",
        )
    )


def run_hybrid_trainer_cycle(
    *,
    config: HybridTrainerConfig,
    io: V2OnlyJsonIO | None = None,
    publish: bool = True,
    replay_buffer: Any | None = None,
    trusted_replay_archive_root: Path | None = None,
    behavior_receipt_archive_root: Path | None = None,
    prefetched_backfill_examples: list[Any] | None = None,
) -> HybridRuntimeResult:
    config.validate_safety()
    cycle_identity = capture_cycle_identity()
    cycle_id = str(cycle_identity["cycle_id"])
    process_instance_id = str(cycle_identity["process_instance_id"])
    # Use one causal consumer clock for every label admitted in this cycle.
    # Reading the wall clock per row would make availability depend on row
    # iteration order instead of the trainer's actual observation boundary.
    training_observed_at = str(cycle_identity["cycle_started_utc"])
    # Crash recovery is independent of current market-data availability and
    # must happen before any loader or empty-grid early exit.  Otherwise an
    # outage can strand write-ahead-fenced claims indefinitely.
    stores = checkpoint_stores(config.model_dir)
    checkpoint_manager = stores.serving
    ledger_reconciliation = reconcile_checkpoint_consumption(
        stores,
        serving_evidence_verifier=lambda load, checkpoint_id: (
            _verified_serving_checkpoint_evidence(
                load,
                expected_checkpoint_id=checkpoint_id,
            )
        ),
    )
    durable_receipt_startup_sync = _sync_durable_receipt_consumption(
        ledger=stores.ledger,
        archive_root=behavior_receipt_archive_root,
    )
    consumed_update_keys = stores.ledger.consumed_update_keys()
    safe_io = io or V2OnlyJsonIO(client=None)
    loader = V2HybridTrainerDataLoader(io=safe_io, trusted_replay_archive_root=trusted_replay_archive_root)
    data_loader_started = time.perf_counter()
    _stage_started = time.perf_counter()
    prediction_examples = loader.load_prediction_grid_examples(
        symbols=config.symbols,
        timeframes=config.timeframes,
        limit=config.max_training_rows_per_cycle,
        snapshot_fast_path=True,
        max_workers=min(max(1, int(config.parallel_env_workers)), 16),
    )
    prediction_load_ms = round((time.perf_counter() - _stage_started) * 1000.0, 3)
    _stage_started = time.perf_counter()
    fresh_examples = loader.load_training_examples(
        symbols=config.symbols,
        timeframes=config.timeframes,
        limit=config.max_training_rows_per_cycle,
        trusted_only=True,
        closed_trade_only=True,
        training_observed_at=training_observed_at,
    )
    fresh_load_ms = round((time.perf_counter() - _stage_started) * 1000.0, 3)
    _stage_started = time.perf_counter()
    trusted_replay_examples = loader.load_trusted_replay_examples(
        limit=_trusted_replay_load_limit_for_cycle(
            max_training_rows_per_cycle=config.max_training_rows_per_cycle,
            replay_buffer=replay_buffer,
        ),
        training_observed_at=training_observed_at,
    )
    frontier_load_ms = round((time.perf_counter() - _stage_started) * 1000.0, 3)
    _stage_started = time.perf_counter()
    # Historical backfill lane: when the in-memory buffer is under half full
    # (e.g. after a restart) the frontier lane alone refills it only at live
    # production rate while ~1.7M labelable archive rows sit behind the
    # frontier cursor. Top up from history with a separate cursor that never
    # touches the frontier cursor.
    backfill_examples: list[Any] = []
    buffer_maxlen = getattr(replay_buffer, "maxlen", None) if replay_buffer is not None else None
    backfill_limit = _trusted_replay_backfill_limit_for_cycle(
        max_training_rows_per_cycle=config.max_training_rows_per_cycle,
        replay_buffer=replay_buffer,
        frontier_rows=len(trusted_replay_examples),
    )
    if prefetched_backfill_examples:
        # Resident pipeline mode: a background prefetcher built these rows
        # WHILE the previous cycle trained on GPU, so the cycle no longer pays
        # the archive tensor-build cost synchronously.
        backfill_examples = list(prefetched_backfill_examples[:backfill_limit])
    elif buffer_maxlen:
        # Cold start (empty prefetch queue) or non-resident mode: fall back to
        # the synchronous backfill so the buffer never starves.
        occupancy = len(replay_buffer) + len(trusted_replay_examples)
        if occupancy < int(buffer_maxlen) // 2 and backfill_limit > 0:
            backfill_examples = loader.load_trusted_replay_examples(
                limit=backfill_limit,
                backfill=True,
                training_observed_at=training_observed_at,
            )
    backfill_load_ms = round((time.perf_counter() - _stage_started) * 1000.0, 3)
    data_loader_elapsed_ms = round((time.perf_counter() - data_loader_started) * 1000.0, 3)
    data_loader_stage_ms = {
        "prediction_load_ms": prediction_load_ms,
        "fresh_load_ms": fresh_load_ms,
        "frontier_load_ms": frontier_load_ms,
        "backfill_load_ms": backfill_load_ms,
        "prefetched_backfill_rows": len(prefetched_backfill_examples or []),
        "prefetched_backfill_rows_consumed": len(backfill_examples),
        "prefetched_backfill_rows_retained": max(
            0,
            len(prefetched_backfill_examples or []) - len(backfill_examples),
        ),
        "trusted_replay_backfill_cycle_limit": backfill_limit,
        "closed_trade_load": dict(
            getattr(loader, "last_closed_trade_load", {}) or {}
        ),
        "prediction_grid_load": dict(getattr(loader, "last_prediction_grid_load", {}) or {}),
    }
    # Feed loader-approved trusted rows into the replay buffer, but keep each
    # resident cycle bounded so current prediction publication stays fresh.
    # Prediction publication stays on the fresh current grid, not replayed rows.
    training_examples = _select_training_examples_for_cycle(
        fresh_examples=[*backfill_examples, *trusted_replay_examples, *fresh_examples],
        replay_buffer=replay_buffer,
        max_training_rows_per_cycle=config.max_training_rows_per_cycle,
    )
    if not prediction_examples:
        raise RuntimeError("no prediction examples built")
    input_dim_source = training_examples[0] if training_examples else prediction_examples[0]
    input_dim = len(input_dim_source.tensor.model_vector)
    training_examples, consumed_exact_examples_removed = (
        _without_consumed_exact_examples(
            list(training_examples),
            consumed_update_keys=consumed_update_keys,
        )
    )

    serving_model = V2HybridPolicyModel(input_dim=input_dim)
    checkpoint_load = stores.serving.load_latest_weights(
        serving_model,
        allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
    )
    prior_serving_manifest = _manifest_for_loaded_checkpoint(
        stores.serving,
        checkpoint_load,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
    )
    prior_serving_contract_complete = False
    prior_serving_contract_reasons: tuple[str, ...] = ()
    if prior_serving_manifest is not None and _basic_checkpoint_load_verified(
        checkpoint_load
    ):
        (
            prior_serving_contract_complete,
            prior_serving_contract_reasons,
        ) = _verified_serving_checkpoint_evidence(
            checkpoint_load,
            expected_checkpoint_id=prior_serving_manifest.checkpoint_id,
        )

    candidate_model = V2HybridPolicyModel(input_dim=input_dim)
    candidate_load = stores.candidate.load_latest_weights(
        candidate_model,
        allowed_lineage_kinds=frozenset({NON_SERVING_CANDIDATE_LINEAGE}),
    )
    candidate_manifest = _manifest_for_loaded_checkpoint(
        stores.candidate,
        candidate_load,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
    )
    candidate_contract_complete = False
    candidate_contract_reasons: tuple[str, ...] = ()
    if candidate_manifest is not None:
        candidate_contract_complete, candidate_contract_reasons = (
            verified_candidate_checkpoint_evidence(candidate_load)
        )
    candidate_available = bool(
        candidate_manifest is not None and candidate_contract_complete
    )

    training_parent_load: dict[str, Any] = {}
    training_parent_manifest: CheckpointManifest | None = None
    training_parent_is_verified_serving = False
    # A verified serving policy is the only promotable incumbent head.  A
    # persisted candidate remains a recovery head only while no serving policy
    # exists; otherwise training from it creates a branch that cannot prove a
    # same-partition comparison against the incumbent.
    if prior_serving_contract_complete:
        training_model = V2HybridPolicyModel(input_dim=input_dim)
        training_parent_load = stores.serving.load_latest_weights(
            training_model,
            allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
        )
        if not _basic_checkpoint_load_verified(training_parent_load):
            raise RuntimeError("verified_serving_training_parent_reload_failed")
        training_parent_manifest = prior_serving_manifest
        training_parent_is_verified_serving = True
        training_parent_source = "VERIFIED_SERVING_POLICY"
    elif candidate_available:
        training_model = candidate_model
        training_parent_load = candidate_load
        training_parent_manifest = candidate_manifest
        training_parent_source = "NON_SERVING_TRAINING_CANDIDATE"
    else:
        training_model = V2HybridPolicyModel(input_dim=input_dim)
        training_parent_source = "FRESH_UNSERVED_POLICY"

    training_parent_fingerprint = model_parameter_fingerprint(training_model)
    trainer = V2HybridPPOTrainer(
        model=training_model,
        clip_epsilon=config.ppo_clip_epsilon,
        behavior_receipt_archive_root=behavior_receipt_archive_root,
        training_observed_at=training_observed_at,
    )
    (
        optimizer_examples,
        optimizer_plan,
        optimizer_owner_id,
        optimizer_claim_status,
    ) = _claim_exact_optimizer_plan(
        trainer=trainer,
        examples=list(training_examples),
        ledger=stores.ledger,
        batch_size=config.batch_size,
        validation_fraction=config.validation_fraction,
    )
    optimizer_attempts = list(
        optimizer_plan.get("optimizer_attempt_descriptors") or ()
    )
    ordered_update_keys = [
        str(attempt["update_key"]) for attempt in optimizer_attempts
    ]
    optimizer_partition_digest = training_partition_digest(ordered_update_keys)
    if any(
        attempt.get("parent_policy_fingerprint")
        != training_parent_fingerprint
        for attempt in optimizer_attempts
    ):
        raise RuntimeError("exact_ppo_claim_parent_policy_mismatch")
    optimizer_fence: dict[str, Any] = {
        "optimizer_write_ahead_fence_durable": False,
        "ordered_update_keys": [],
        "training_partition_digest": optimizer_partition_digest,
    }
    if ordered_update_keys:
        optimizer_fence = stores.ledger.mark_optimizer_started(
            owner_id=optimizer_owner_id,
            update_keys=ordered_update_keys,
            partition_digest=optimizer_partition_digest,
        )

    training = trainer.train(
        optimizer_examples,
        steps=config.train_steps if optimizer_examples else 0,
        batch_size=config.batch_size,
        validation_fraction=config.validation_fraction,
    )
    cycle_training_metrics = dict(training.metrics)
    optimizer_steps = int(
        cycle_training_metrics.get("optimizer_steps_this_cycle") or 0
    )
    parameter_before = str(
        cycle_training_metrics.get("parameter_hash_before") or ""
    )
    parameter_after = str(
        cycle_training_metrics.get("parameter_hash_after") or ""
    )
    candidate_fingerprint = model_parameter_fingerprint(training_model)
    optimizer_parameter_fingerprints_bound = (
        _optimizer_parameter_fingerprints_bound(
            parameter_hash_before=parameter_before,
            parameter_hash_after=parameter_after,
            training_parent_policy_fingerprint=training_parent_fingerprint,
            candidate_policy_fingerprint=candidate_fingerprint,
        )
    )
    fingerprint_binding_metrics = {
        "actual_training_parent_policy_fingerprint": (
            training_parent_fingerprint
        ),
        "actual_candidate_policy_fingerprint": candidate_fingerprint,
        "optimizer_parameter_fingerprints_bound": (
            optimizer_parameter_fingerprints_bound
        ),
    }
    cycle_training_metrics.update(fingerprint_binding_metrics)
    training.metrics.update(fingerprint_binding_metrics)
    weight_delta_norm = _finite_float(
        cycle_training_metrics.get("weight_delta_norm")
    )
    optimizer_mutated = bool(
        optimizer_steps > 0
        and optimizer_parameter_fingerprints_bound
        and training_parent_fingerprint != candidate_fingerprint
        and weight_delta_norm is not None
        and weight_delta_norm > 0.0
    )
    exact_optimizer_contract_valid = _exact_ppo_optimizer_contract_valid(
        metrics=cycle_training_metrics,
        optimizer_attempts=optimizer_attempts,
        ordered_update_keys=ordered_update_keys,
    )
    if ordered_update_keys and not optimizer_mutated:
        zero_step_no_mutation_proven = bool(
            optimizer_steps == 0
            and optimizer_parameter_fingerprints_bound
            and training_parent_fingerprint == candidate_fingerprint
            and weight_delta_norm == 0.0
        )
        if zero_step_no_mutation_proven:
            released = stores.ledger.release_optimizer_fence_without_step(
                owner_id=optimizer_owner_id,
                update_keys=ordered_update_keys,
                partition_digest=optimizer_partition_digest,
            )
            if released != len(ordered_update_keys):
                raise RuntimeError("exact_ppo_zero_step_claim_release_failed")
            optimizer_claim_status["zero_step_claims_released"] = released
            optimizer_attempts = []
            ordered_update_keys = []
            optimizer_partition_digest = training_partition_digest([])
        else:
            exact_optimizer_contract_valid = False

    exact_optimizer_contract_metrics = {
        "exact_optimizer_contract_valid": exact_optimizer_contract_valid,
    }
    cycle_training_metrics.update(exact_optimizer_contract_metrics)
    training.metrics.update(exact_optimizer_contract_metrics)

    candidate_decision = candidate_progress_decision(cycle_training_metrics)
    if not optimizer_parameter_fingerprints_bound:
        candidate_decision = {
            **candidate_decision,
            "candidate_progress_allowed": False,
            "candidate_progress_rejected": True,
            "candidate_progress_reason": (
                "OPTIMIZER_PARAMETER_FINGERPRINT_BINDING_INVALID"
            ),
            "candidate_progress_rejection_reasons": list(
                dict.fromkeys(
                    [
                        *candidate_decision.get(
                            "candidate_progress_rejection_reasons", []
                        ),
                        "OPTIMIZER_PARAMETER_FINGERPRINT_BINDING_INVALID",
                    ]
                )
            ),
        }
    if optimizer_attempts and not exact_optimizer_contract_valid:
        candidate_decision = {
            **candidate_decision,
            "candidate_progress_allowed": False,
            "candidate_progress_rejected": True,
            "candidate_progress_reason": "EXACT_PPO_OPTIMIZER_CONTRACT_INVALID",
            "candidate_progress_rejection_reasons": [
                *candidate_decision.get(
                    "candidate_progress_rejection_reasons", []
                ),
                "EXACT_PPO_OPTIMIZER_CONTRACT_INVALID",
            ],
        }
    confidence_decision = confidence_promotion_decision(
        training_metrics=cycle_training_metrics,
        calibration_state=training_model.confidence_calibration_state,
        candidate_policy_fingerprint=candidate_fingerprint,
    )
    checkpoint_promotion = serving_promotion_decision(
        training_metrics=cycle_training_metrics,
        candidate_decision=candidate_decision,
        confidence_decision=confidence_decision,
        prior_verified_serving_exists=prior_serving_contract_complete,
        training_parent_is_verified_serving=(
            training_parent_is_verified_serving
        ),
        training_parent_is_non_serving_candidate=(
            training_parent_source == NON_SERVING_CANDIDATE_LINEAGE
        ),
    )
    checkpoint_promotion.update(
        {
            "checkpoint_promotion_guard_active": True,
            "prior_checkpoint_loadable": prior_serving_contract_complete,
            "static_validation_thresholds_used": False,
            "training_parent_source": training_parent_source,
        }
    )
    if not config.allow_weight_artifact_write and checkpoint_promotion.get(
        "checkpoint_promotion_allowed"
    ):
        checkpoint_promotion.update(
            {
                "checkpoint_promotion_allowed": False,
                "checkpoint_promotion_rejected": True,
                "checkpoint_promotion_reason": "DURABLE_WEIGHT_ARTIFACT_WRITE_DISABLED",
            }
        )

    parent_checkpoint_id = (
        training_parent_manifest.checkpoint_id
        if training_parent_manifest is not None
        else None
    )
    candidate_artifact: CheckpointManifest | None = None
    candidate_artifact_verification: dict[str, Any] = {}
    serving_artifact: CheckpointManifest | None = None
    serving_artifact_load: dict[str, Any] = {}
    rejected_artifact: CheckpointManifest | None = None
    rejected_artifact_verification: dict[str, Any] = {}
    ledger_artifact: CheckpointManifest | None = None
    ledger_artifact_verification: dict[str, Any] = {}
    ledger_disposition: str | None = None
    checkpoint_weight_blob_written_this_cycle = False

    if optimizer_mutated and config.allow_weight_artifact_write:
        candidate_evidence = checkpoint_evidence(
            checkpoint_role=NON_SERVING_CANDIDATE_LINEAGE,
            ledger_disposition="NON_SERVING_CANDIDATE_PERSISTED",
            candidate_decision=candidate_decision,
            confidence_decision=confidence_decision,
            serving_decision=checkpoint_promotion,
            training_metrics=cycle_training_metrics,
            ordered_update_keys=ordered_update_keys,
        )
        if candidate_decision.get("candidate_progress_allowed") is True:
            candidate_artifact = stores.candidate.write_checkpoint(
                model=training_model,
                input_dim=input_dim,
                device=training_model.device,
                cuda_active=training_model.cuda_active,
                lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=training_parent_fingerprint,
                consumed_ppo_update_keys=tuple(ordered_update_keys),
                training_partition_digest=optimizer_partition_digest,
                checkpoint_evidence=candidate_evidence,
            )
            candidate_artifact_verification = (
                stores.candidate.verify_manifest_artifact(candidate_artifact)
            )
            if candidate_artifact_verification.get(
                "checkpoint_artifact_verified"
            ) is not True:
                raise RuntimeError("candidate_checkpoint_reload_verification_failed")
            ledger_artifact = candidate_artifact
            ledger_artifact_verification = candidate_artifact_verification
            ledger_disposition = "NON_SERVING_CANDIDATE_PERSISTED"

        if checkpoint_promotion.get("checkpoint_promotion_allowed") is True:
            if candidate_artifact is None:
                raise RuntimeError("serving_promotion_without_verified_candidate")
            serving_evidence = checkpoint_evidence(
                checkpoint_role=VERIFIED_SERVING_LINEAGE,
                ledger_disposition="SERVING_PROMOTED",
                candidate_decision=candidate_decision,
                confidence_decision=confidence_decision,
                serving_decision=checkpoint_promotion,
                training_metrics=cycle_training_metrics,
                ordered_update_keys=ordered_update_keys,
            )
            serving_artifact = stores.serving.write_checkpoint(
                model=training_model,
                input_dim=input_dim,
                device=training_model.device,
                cuda_active=training_model.cuda_active,
                lineage_kind=VERIFIED_SERVING_LINEAGE,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=training_parent_fingerprint,
                consumed_ppo_update_keys=tuple(ordered_update_keys),
                training_partition_digest=optimizer_partition_digest,
                checkpoint_evidence=serving_evidence,
            )
            promoted_serving_model = V2HybridPolicyModel(input_dim=input_dim)
            serving_artifact_load = stores.serving.load_latest_weights(
                promoted_serving_model,
                allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
            )
            promoted_complete, promoted_reasons = (
                _verified_serving_checkpoint_evidence(
                    serving_artifact_load,
                    expected_checkpoint_id=serving_artifact.checkpoint_id,
                )
            )
            if not promoted_complete:
                raise RuntimeError(
                    "serving_checkpoint_reload_verification_failed:"
                    + ",".join(promoted_reasons)
                )
            serving_model = promoted_serving_model
            ledger_artifact = serving_artifact
            ledger_artifact_verification = stores.serving.verify_manifest_artifact(
                serving_artifact
            )
            ledger_disposition = "SERVING_PROMOTED"
            checkpoint_weight_blob_written_this_cycle = True
        elif optimizer_attempts and candidate_artifact is None:
            rejected_evidence = checkpoint_evidence(
                checkpoint_role=REJECTED_ATTEMPT_LINEAGE,
                ledger_disposition="REJECTED_TRAINING_ATTEMPT_PERSISTED",
                candidate_decision=candidate_decision,
                confidence_decision=confidence_decision,
                serving_decision=checkpoint_promotion,
                training_metrics=cycle_training_metrics,
                ordered_update_keys=ordered_update_keys,
            )
            rejected_artifact = stores.rejected_attempt.write_checkpoint(
                model=training_model,
                input_dim=input_dim,
                device=training_model.device,
                cuda_active=training_model.cuda_active,
                lineage_kind=REJECTED_ATTEMPT_LINEAGE,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=training_parent_fingerprint,
                consumed_ppo_update_keys=tuple(ordered_update_keys),
                training_partition_digest=optimizer_partition_digest,
                checkpoint_evidence=rejected_evidence,
            )
            rejected_artifact_verification = (
                stores.rejected_attempt.verify_manifest_artifact(
                    rejected_artifact
                )
            )
            if rejected_artifact_verification.get(
                "checkpoint_artifact_verified"
            ) is not True:
                raise RuntimeError("rejected_attempt_artifact_verification_failed")
            ledger_artifact = rejected_artifact
            ledger_artifact_verification = rejected_artifact_verification
            ledger_disposition = "REJECTED_TRAINING_ATTEMPT_PERSISTED"

    durable_receipt_post_ledger_sync: dict[str, Any] = {
        "schema_version": "v2_trainer_durable_receipt_consumption_sync_v1",
        "ledger_attempts_checked": 0,
        "trainer_consumed_events_appended": 0,
        "trainer_consumed_events_already_present": 0,
        "trainer_consumed_event_hashes": [],
        "sync_complete": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if optimizer_attempts:
        if not config.allow_weight_artifact_write:
            raise RuntimeError(
                "exact_ppo_optimizer_ran_with_durable_artifact_write_disabled"
            )
        if (
            ledger_artifact is None
            or ledger_disposition is None
            or ledger_artifact_verification.get(
                "checkpoint_artifact_verified"
            )
            is not True
        ):
            raise RuntimeError("exact_ppo_optimizer_attempt_artifact_missing")
        stores.ledger.record_attempts(
            attempts=optimizer_attempts,
            child_policy_fingerprint=candidate_fingerprint,
            disposition=ledger_disposition,
            checkpoint_id=ledger_artifact.checkpoint_id,
            checkpoint_path=ledger_artifact.weight_file_path,
            checkpoint_sha256=ledger_artifact.weight_file_sha256,
            partition_digest=optimizer_partition_digest,
            owner_id=optimizer_owner_id,
        )
        durable_receipt_post_ledger_sync = _sync_durable_receipt_consumption(
            ledger=stores.ledger,
            archive_root=behavior_receipt_archive_root,
            update_keys=ordered_update_keys,
        )

    training.metrics.update(
        {
            "trainer_checkpoint_lifecycle_schema_version": (
                "v2_candidate_serving_exact_ppo_lifecycle_v1"
            ),
            "checkpoint_ledger_reconciliation": ledger_reconciliation,
            "durable_receipt_startup_consumption_sync": (
                durable_receipt_startup_sync
            ),
            "durable_receipt_post_ledger_consumption_sync": (
                durable_receipt_post_ledger_sync
            ),
            "consumed_exact_examples_removed_before_planning": (
                consumed_exact_examples_removed
            ),
            "optimizer_claim_status": optimizer_claim_status,
            "optimizer_write_ahead_fence": optimizer_fence,
            "optimizer_training_partition_digest": (
                optimizer_partition_digest
            ),
            "candidate_progress_decision": candidate_decision,
            "confidence_promotion_decision": confidence_decision,
            "serving_promotion_decision": checkpoint_promotion,
            "candidate_checkpoint_artifact": candidate_artifact_verification,
            "rejected_attempt_checkpoint_artifact": (
                rejected_artifact_verification
            ),
            "training_parent_source": training_parent_source,
            "training_parent_checkpoint_id": parent_checkpoint_id,
            "training_parent_policy_fingerprint": (
                training_parent_fingerprint
            ),
            "candidate_policy_fingerprint": candidate_fingerprint,
            "prior_serving_contract_complete": (
                prior_serving_contract_complete
            ),
            "prior_serving_contract_rejection_reasons": list(
                prior_serving_contract_reasons
            ),
            "candidate_contract_complete": candidate_contract_complete,
            "candidate_contract_rejection_reasons": list(
                candidate_contract_reasons
            ),
        }
    )

    if serving_artifact is not None:
        checkpoint = serving_artifact
        checkpoint_reload = serving_artifact_load
        model = serving_model
        model_serving_allowed = True
        checkpoint_promotion["model_serving_source"] = (
            "VERIFIED_PROMOTED_SERVING_CHECKPOINT"
        )
    elif prior_serving_contract_complete and prior_serving_manifest is not None:
        checkpoint = prior_serving_manifest
        checkpoint_reload = checkpoint_load
        model = serving_model
        model_serving_allowed = True
        checkpoint_promotion["model_serving_source"] = (
            "VERIFIED_PRIOR_SERVING_CHECKPOINT_RESTORED"
        )
    else:
        model = training_model
        model_serving_allowed = False
        checkpoint = (
            candidate_artifact
            or rejected_artifact
            or CheckpointManifest(
                checkpoint_id=f"v2_hybrid_unserved_{training_model.model_id[-24:]}",
                checkpoint_source=CHECKPOINT_SOURCE,
                path="",
                generated_utc=_utc_iso_microseconds(),
                model_id=training_model.model_id,
                input_dim=input_dim,
                device=training_model.device,
                cuda_active=training_model.cuda_active,
                weight_blob_written=False,
            )
        )
        checkpoint_reload = (
            candidate_artifact_verification
            or rejected_artifact_verification
            or {}
        )
        checkpoint_promotion["model_serving_source"] = (
            "NONE_NO_VERIFIED_SERVING_CHECKPOINT"
        )
    checkpoint_promotion.update(
        {
            "model_serving_allowed": model_serving_allowed,
            "rejected_candidate_serving_suppressed": not model_serving_allowed,
            "model_serving_suppression_reason": (
                None
                if model_serving_allowed
                else "NO_FULLY_VERIFIED_SERVING_POLICY"
            ),
            "checkpoint_restore_after_rejection_status": checkpoint_load.get(
                "load_status"
            ),
            "checkpoint_restore_after_rejection_verified": (
                prior_serving_contract_complete
            ),
        }
    )
    checkpoint_hash = _sha256_file(checkpoint.weight_file_path)
    checkpoint_reload_verified = bool(
        model_serving_allowed
        and _basic_checkpoint_load_verified(checkpoint_reload)
    )
    checkpoint_evidence_digest = str(
        checkpoint_reload.get("checkpoint_evidence_digest") or ""
    )
    checkpoint_reload_identity_bound = (
        checkpoint_reload.get("checkpoint_id") == checkpoint.checkpoint_id
    )
    checkpoint_identity_verified = bool(
        checkpoint_reload_identity_bound
        and checkpoint_reload.get("checkpoint_identity_verified") is True
        and checkpoint_reload.get("latest_checkpoint_loadable") is True
        and checkpoint_reload.get("model_state_restored") is True
    )
    (
        checkpoint_serving_evidence_complete,
        checkpoint_serving_evidence_rejection_reasons,
    ) = _verified_serving_checkpoint_evidence(
        checkpoint_reload,
        expected_checkpoint_id=checkpoint.checkpoint_id,
    )
    # The receipt field deliberately means the *complete serving contract*, not
    # merely that the manager could hash the candidate's evidence mapping.
    checkpoint_evidence_verified = checkpoint_serving_evidence_complete
    served_policy_fingerprint: str | None = None
    served_policy_fingerprint_error: str | None = None
    if model_serving_allowed and checkpoint_serving_evidence_complete:
        try:
            served_policy_fingerprint = model_parameter_fingerprint(model)
        except (TypeError, ValueError, RuntimeError) as exc:
            served_policy_fingerprint_error = f"{type(exc).__name__}:{exc}"
    model_serving_allowed = bool(
        model_serving_allowed and checkpoint_serving_evidence_complete
    )
    prediction_suppressed_count = 0 if model_serving_allowed else len(
        prediction_examples
    )
    # GPU-fast policy backtest: one batched eval pass of the CURRENT policy
    # over the labeled replay rows already in memory. Readiness evidence only;
    # never A+ evidence (see policy_backtest module contract). A rejected model
    # is not the current policy unless a prior checkpoint restore was verified.
    if model_serving_allowed:
        policy_backtest_report = run_policy_archive_backtest(
            model=model,
            examples=list(optimizer_plan.get("validation_rows") or ()),
            excluded_training_examples=list(
                optimizer_plan.get("train_rows") or ()
            ),
            untouched_forward_partition_proven=(
                training.metrics.get("validation_split_pit_safe") is True
                and training.metrics.get("validation_split_temporal_overlap")
                is False
                and training.metrics.get("validation_split_label_overlap")
                is False
            ),
        )
    else:
        policy_backtest_report = {
            "schema_version": BACKTEST_SCHEMA_VERSION,
            "status": "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE",
            "suppression_reason": checkpoint_promotion.get(
                "model_serving_suppression_reason"
            ),
            "rows_evaluated": 0,
            "backtest_rows_per_second": None,
            "counts_as_A_plus": False,
            "counts_as_live_ready": False,
            "evidence_class": "NO_EVIDENCE_REJECTED_CANDIDATE_SUPPRESSED",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    if safe_io is not None:
        try:
            safe_io.set_json(
                "v2:trainer:hybrid_cuda:policy_backtest_report", policy_backtest_report
            )
        except Exception:
            pass
    env_examples = training_examples if training_examples else prediction_examples
    env = V2PaperShadowHybridEnv(env_examples[: min(8, len(env_examples))])
    env_obs, env_info = env.reset()
    step_obs, step_reward, terminated, truncated, step_info = env.step(0)
    del env_obs, step_obs
    configured_n_envs = min(
        max(1, int(config.rollout_max_envs)),
        max(1, len(config.symbols) * len(config.timeframes)),
    )
    parallel_rollout = run_parallel_env_rollout_proof(
        env_examples,
        configured_n_envs=configured_n_envs,
        rollout_n_steps=config.rollout_n_steps,
        max_workers=config.parallel_env_workers,
    )
    publisher = V2HybridPredictionPublisher(
        io=safe_io,
        behavior_receipt_archive_root=behavior_receipt_archive_root,
        current_cycle_publication_ttl_seconds=(
            config.expected_cycle_cadence_seconds * 3
        ),
    )
    predictions: list[dict[str, Any]] = []
    lineages: list[dict[str, Any]] = []
    published_prediction_count = 0
    prediction_failure_rows: list[dict[str, Any]] = []
    prediction_started = time.perf_counter()
    flat_round_trip_cost_bps = 2.0 * (config.fee_bps_per_side + config.slippage_bps_per_side)
    adaptive_cost_cache: dict[str, dict[str, Any]] = {}
    forward_candidates: list[dict[str, Any]] = []
    for example in prediction_examples if model_serving_allowed else ():
        try:
            forward = model.forward(example.tensor)
            cost_evidence = _adaptive_round_trip_cost_evidence(
                example.symbol,
                safe_io=safe_io,
                flat_round_trip_bps=flat_round_trip_cost_bps,
                fee_floor_bps=2.0 * config.fee_bps_per_side,
                cache=adaptive_cost_cache,
            )
            round_trip_cost_bps = float(cost_evidence["round_trip_cost_bps"])
            # The exact-cost observation is captured inside the helper first;
            # decision_time must retain microseconds and be causally later.
            decision_time = _causal_decision_time_after_cost_observation(
                cost_evidence
            )
            trust_row = dict(example.trust_row or {})
            calibration = (
                dict(forward.calibration)
                if isinstance(forward.calibration, dict)
                else {}
            )
            positive_edge_action = (
                "long"
                if float(forward.expected_move_bps) - round_trip_cost_bps > 0.0
                else "short"
                if -float(forward.expected_move_bps) - round_trip_cost_bps > 0.0
                else None
            )
            calibration_by_direction = calibration.get(
                "confidence_calibration_by_direction"
            )
            positive_edge_calibration = (
                calibration_by_direction.get(positive_edge_action)
                if positive_edge_action is not None
                and isinstance(calibration_by_direction, dict)
                else None
            )
            confidence = (
                _finite_float(
                    positive_edge_calibration.get("confidence_calibrated")
                )
                if isinstance(positive_edge_calibration, dict)
                else None
            )
            forward_candidates.append(
                {
                    "example": example,
                    "forward": forward,
                    "round_trip_cost_bps": round_trip_cost_bps,
                    "cost_evidence": cost_evidence,
                    "decision_time": decision_time,
                    "lane_candidate": {
                        "symbol": example.symbol,
                        "timeframe": example.timeframe,
                        "feature_tensor_id": example.tensor.tensor_id,
                        "feature_cutoff": trust_row.get("feature_cutoff")
                        or trust_row.get("decision_cutoff"),
                        "available_at": trust_row.get("available_at")
                        or trust_row.get("source_available_time"),
                        "candle_close_time": trust_row.get("candle_close_time"),
                        "candle_closed_confirmed": trust_row.get(
                            "candle_closed_confirmed"
                        ),
                        "decision_time": decision_time,
                        "row_classification": example.row_classification,
                        "raw_action_logits": list(forward.action_logits),
                        "confidence_calibrated": confidence,
                        "confidence_calibration_fitted": bool(
                            isinstance(positive_edge_calibration, dict)
                            and positive_edge_calibration.get(
                                "calibration_fitted"
                            )
                            is True
                            and positive_edge_calibration.get(
                                "probability_semantics_valid"
                            )
                            is True
                            and positive_edge_calibration.get("label_semantics")
                            == CONFIDENCE_LABEL_SEMANTICS
                        ),
                        "confidence_candidate_action": positive_edge_action,
                        "expected_move_bps": forward.expected_move_bps,
                        "round_trip_cost_bps": round_trip_cost_bps,
                        "exact_cost_provenance_valid": cost_evidence[
                            "exact_cost_provenance_valid"
                        ],
                        "exact_cost_payload_hash": cost_evidence[
                            "exact_cost_payload_hash"
                        ],
                        "served_policy_fingerprint_available": (
                            served_policy_fingerprint is not None
                        ),
                        "served_policy_fingerprint": served_policy_fingerprint,
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "checkpoint_weight_sha256": checkpoint_hash,
                        "checkpoint_evidence_digest": (
                            checkpoint_evidence_digest
                        ),
                        "checkpoint_evidence_verified": (
                            checkpoint_evidence_verified
                        ),
                        "checkpoint_identity_verified": (
                            checkpoint_identity_verified
                        ),
                        "checkpoint_serving_evidence_complete": (
                            checkpoint_serving_evidence_complete
                        ),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            prediction_failure_rows.append(
                {
                    "symbol": example.symbol,
                    "timeframe": example.timeframe,
                    "feature_snapshot_id": example.tensor.feature_snapshot_id,
                    "feature_tensor_id": example.tensor.tensor_id,
                    "row_classification": example.row_classification,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:240],
                }
            )
            continue
    try:
        paper_runtime_heartbeat = safe_io.get_json("v2:paper:heartbeat")
    except Exception:  # noqa: BLE001
        paper_runtime_heartbeat = None
    paper_margin_status = _paper_margin_status_from_heartbeat(
        paper_runtime_heartbeat
    )
    paper_entry_freeze = _effective_paper_entry_gate_from_heartbeat(
        paper_runtime_heartbeat
    )
    on_policy_lane_plan = adaptive_on_policy_lane_plan(
        [candidate["lane_candidate"] for candidate in forward_candidates],
        paper_margin_status=(
            paper_margin_status if isinstance(paper_margin_status, dict) else None
        ),
        paper_entry_freeze=(
            paper_entry_freeze if isinstance(paper_entry_freeze, dict) else None
        ),
        carry_in=_ADAPTIVE_ON_POLICY_LANE_STATE["carry"],
        single_candidate_ordinary_credit_in=_ADAPTIVE_ON_POLICY_LANE_STATE[
            "single_candidate_ordinary_credit"
        ],
    )
    _ADAPTIVE_ON_POLICY_LANE_STATE["carry"] = float(
        on_policy_lane_plan["carry_out"]
    )
    _ADAPTIVE_ON_POLICY_LANE_STATE["single_candidate_ordinary_credit"] = int(
        on_policy_lane_plan["single_candidate_ordinary_credit_out"]
    )
    selected_on_policy_indices = set(on_policy_lane_plan["selected_indices"])
    for candidate_index, candidate in enumerate(forward_candidates):
        example = candidate["example"]
        try:
            payload = build_prediction_payload(
                example=example,
                model_output=candidate["forward"],
                checkpoint=checkpoint,
                round_trip_cost_bps=float(candidate["round_trip_cost_bps"]),
                min_data_coverage_percent=config.min_data_coverage_percent,
                min_confidence_calibrated=config.min_confidence_calibrated,
                min_edge_after_cost_bps=config.min_edge_after_cost_bps,
                served_policy_fingerprint=served_policy_fingerprint,
                checkpoint_weight_sha256=checkpoint_hash,
                checkpoint_evidence_digest=checkpoint_evidence_digest,
                checkpoint_evidence_verified=checkpoint_evidence_verified,
                checkpoint_identity_verified=checkpoint_identity_verified,
                cost_provenance=candidate["cost_evidence"].get(
                    "exact_cost_provenance"
                ),
                on_policy_sampling_selected=(
                    candidate_index in selected_on_policy_indices
                ),
                on_policy_sampling_plan=on_policy_lane_plan,
                decision_time_utc=str(candidate["decision_time"]),
                cycle_id=cycle_id,
                process_instance_id=process_instance_id,
                candidate_policy_fingerprint=served_policy_fingerprint,
            )
        except Exception as exc:  # noqa: BLE001
            prediction_failure_rows.append(
                {
                    "symbol": example.symbol,
                    "timeframe": example.timeframe,
                    "feature_snapshot_id": example.tensor.feature_snapshot_id,
                    "feature_tensor_id": example.tensor.tensor_id,
                    "row_classification": example.row_classification,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:240],
                }
            )
            continue
        predictions.append(payload)
        if publish:
            try:
                if not publisher.publish_prediction(payload):
                    raise RuntimeError(
                        "prediction publication failed; lineage/risk publication suppressed"
                    )
                published_prediction_count += 1
                lineages.append(
                    publisher.publish_lineage(
                        prediction_payload=payload,
                        min_confidence_calibrated=config.min_confidence_calibrated,
                        min_data_coverage_percent=config.min_data_coverage_percent,
                        risk_caps_configured=config.risk_caps_configured,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                prediction_failure_rows.append(
                    {
                        "symbol": example.symbol,
                        "timeframe": example.timeframe,
                        "prediction_id": payload.get("prediction_id"),
                        "feature_snapshot_id": example.tensor.feature_snapshot_id,
                        "feature_tensor_id": example.tensor.tensor_id,
                        "row_classification": example.row_classification,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:240],
                    }
                )
    grid_readback_evidence: dict[str, Any] = {
        "schema_version": "v2_trainer_current_cycle_grid_readback_v1",
        "publication_complete": False,
        "expected_receipt_count": len(predictions) * 2,
        "verified_receipt_count": 0,
        "component_receipts": [],
        "rejection_reason": (
            "PUBLICATION_DISABLED" if not publish else "NO_COMPLETE_GRID"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if publish and predictions:
        try:
            grid_readback_evidence = _current_cycle_grid_readback_evidence(
                io=safe_io,
                predictions=predictions,
                lineages=lineages,
            )
        except Exception as exc:  # noqa: BLE001 - evidence must fail closed
            grid_readback_evidence["rejection_reason"] = (
                "CURRENT_CYCLE_GRID_READBACK_FAILED:" + type(exc).__name__
            )
    prediction_elapsed = max(1e-6, time.perf_counter() - prediction_started)
    training_metrics = dict(training.metrics)
    optimizer_steps_this_cycle = int(training_metrics.get("optimizer_steps_this_cycle") or 0)
    parameter_hash_before = training_metrics.get("parameter_hash_before")
    parameter_hash_after = training_metrics.get("parameter_hash_after")
    weight_mutated = bool(
        optimizer_steps_this_cycle > 0
        and parameter_hash_before
        and parameter_hash_after
        and parameter_hash_before != parameter_hash_after
        and float(training_metrics.get("weight_delta_norm") or 0.0) > 0.0
    )
    checkpoint_promoted_this_cycle = bool(
        weight_mutated
        and checkpoint_promotion.get("checkpoint_promotion_allowed") is True
        and checkpoint.weight_blob_written
        and checkpoint_reload_verified
    )
    generated_weight_update_at = checkpoint.generated_utc if checkpoint_promoted_this_cycle else None
    rows_rejected_by_reason = dict(training_metrics.get("training_rejection_reason_counts") or {})
    if not rows_rejected_by_reason and int(training_metrics.get("trusted_rows_loaded") or 0) <= 0:
        rows_rejected_by_reason.update(_feedback_quarantine_rejection_counts(safe_io))
    training_metrics.update(
        {
            "trusted_rows_loaded": int(
                training_metrics.get("trusted_rows_loaded")
                if training_metrics.get("trusted_rows_loaded") is not None
                else training_metrics.get("training_trusted_rows") or 0
            ),
            "trusted_replay_rows_loaded": int(
                training_metrics.get("trusted_replay_rows_loaded") or len(trusted_replay_examples)
            ),
            "feedback_rows_entered_batch": int(
                training_metrics.get("feedback_rows_entered_batch") or len(fresh_examples)
            ),
            "rows_rejected_by_reason": rows_rejected_by_reason,
            "optimizer_steps_total": optimizer_steps_this_cycle,
            "optimizer_steps_last_hour": optimizer_steps_this_cycle,
            "checkpoint_weight_blob_written": checkpoint_weight_blob_written_this_cycle,
            "checkpoint_candidate_weight_mutated": weight_mutated,
            "checkpoint_promoted_this_cycle": checkpoint_promoted_this_cycle,
            "checkpoint_path": checkpoint.weight_file_path,
            "checkpoint_hash": checkpoint_hash,
            "checkpoint_reload_verified": checkpoint_reload_verified,
            "model_serving_allowed": model_serving_allowed,
            "model_serving_source": checkpoint_promotion.get("model_serving_source"),
            "rejected_candidate_serving_suppressed": checkpoint_promotion.get(
                "rejected_candidate_serving_suppressed"
            ),
            "model_serving_suppression_reason": checkpoint_promotion.get(
                "model_serving_suppression_reason"
            ),
            "prediction_suppressed_count": prediction_suppressed_count,
            "served_policy_fingerprint": served_policy_fingerprint,
            "served_policy_fingerprint_error": served_policy_fingerprint_error,
            "adaptive_on_policy_lane_plan": on_policy_lane_plan,
            "adaptive_on_policy_lane_plan_hash": on_policy_lane_plan.get(
                "plan_hash"
            ),
            "adaptive_on_policy_lane_input_hash": on_policy_lane_plan.get(
                "input_hash"
            ),
            "adaptive_on_policy_selected_count": int(
                on_policy_lane_plan.get("selected_sample_count") or 0
            ),
            "adaptive_on_policy_ordinary_reserved_count": int(
                on_policy_lane_plan.get("ordinary_lane_reserved_count") or 0
            ),
            "on_policy_categorical_prediction_count": sum(
                1
                for prediction in predictions
                if prediction.get("on_policy_action_receipt_valid") is True
            ),
            "on_policy_directional_candidate_count": sum(
                1
                for prediction in predictions
                if prediction.get("behavior_policy_receipt_write_success") is True
            ),
            "last_successful_weight_update_at": generated_weight_update_at,
            "data_loader_time_ms": data_loader_elapsed_ms,
            "data_loader_stage_ms": data_loader_stage_ms,
            "trusted_replay_frontier_scan": dict(getattr(loader, "last_trusted_replay_scan", {}) or {}),
            "trusted_replay_backfill_scan": dict(
                getattr(loader, "last_trusted_replay_backfill_scan", {}) or {}
            ),
        }
    )
    readiness = build_learning_readiness(
        training={"metrics": training_metrics},
        prediction_rows=len(predictions),
    )
    training_metrics.update(
        {
            key: readiness.get(key)
            for key in (
                "trainer_learning_ready",
                "offline_replay_learning_status",
                "online_paper_learning_status",
                "online_learning_status",
                "effective_trainer_mode",
                "readiness_blocking_reasons",
                "requirement_checks",
            )
        }
    )
    training_metrics["available_examples"] = int(training_metrics.get("available_examples", len(training_examples)))
    training_metrics["selected_examples"] = int(
        training_metrics.get("selected_examples", training.train_rows + training.validation_rows)
    )
    training_metrics["batch_covers_available_examples"] = (
        training_metrics["selected_examples"] >= training_metrics["available_examples"]
    )
    training_payload = asdict(training)
    training_payload["metrics"] = dict(training_metrics)
    resource_utilization = {
        "cuda_available": bool(training.cuda_active),
        "gpu_name": training.gpu_name,
        "current_gpu_utilization": None,
        "current_vram_used_mb": training.vram_allocated_mb,
        "target_batch_size": training_metrics.get("target_batch_size", config.batch_size),
        "actual_batch_size": training_metrics.get("actual_batch_size", training.batch_size),
        "dataloader_workers": training_metrics.get("dataloader_workers", 0),
        "pinned_memory": training_metrics.get("pinned_memory", False),
        "prefetch_factor": training_metrics.get("prefetch_factor"),
        "persistent_workers": training_metrics.get("persistent_workers", False),
        "mixed_precision_enabled": training_metrics.get("uses_amp", False),
        "gradient_accumulation_steps": training_metrics.get("gradient_accumulation_steps", 1),
        "throughput_predictions_per_second": round(len(predictions) / prediction_elapsed, 6),
        "training_steps_per_minute": training_metrics.get("training_steps_per_minute"),
        "tensor_rows_per_second": training_metrics.get("tensor_rows_per_second"),
        "data_loader_time_ms": training_metrics.get("data_loader_time_ms"),
        "gpu_train_time_ms": training_metrics.get("gpu_train_time_ms"),
        "cpu_train_time_ms": training_metrics.get("cpu_train_time_ms"),
        "backtest_rows_per_second": policy_backtest_report.get("backtest_rows_per_second"),
        "policy_backtest": {
            "status": policy_backtest_report.get("status"),
            "rows_evaluated": policy_backtest_report.get("rows_evaluated"),
            "win_rate": policy_backtest_report.get("win_rate"),
            "expectancy_after_cost_bps": policy_backtest_report.get("expectancy_after_cost_bps"),
            "profit_factor_proxy": policy_backtest_report.get("profit_factor_proxy"),
            "a_plus_readiness_signal": policy_backtest_report.get("a_plus_readiness_signal"),
            "evidence_class": policy_backtest_report.get("evidence_class"),
        },
        "oom_count": training_metrics.get("oom_count", 0),
        "vram_target_mb": training_metrics.get("vram_target_mb"),
        "vram_reserved_mb": training_metrics.get("vram_reserved_mb"),
    }
    if not model_serving_allowed:
        prediction_publication_status = (
            "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
        )
    elif not publish:
        prediction_publication_status = "DISABLED"
    elif not predictions:
        prediction_publication_status = "NO_PREDICTIONS_PUBLISHED"
    elif (
        published_prediction_count == len(predictions)
        and len(lineages) == published_prediction_count
        and grid_readback_evidence["publication_complete"] is True
    ):
        prediction_publication_status = "ACTIVE"
    elif published_prediction_count <= 0:
        prediction_publication_status = "FAILED"
    else:
        prediction_publication_status = "PARTIAL"
    checkpoint_promotion_status = _checkpoint_promotion_status_fields(checkpoint_promotion)
    status = {
        "schema_version": "v2_native_rl_masa_ppo_cuda_trainer_status_v1",
        "generated_utc": _utc_iso(),
        "trainer_source": TRAINER_SOURCE,
        "model_source": MODEL_SOURCE,
        "checkpoint_source": CHECKPOINT_SOURCE,
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_load_status": checkpoint_load,
        "symbols_count": len(config.symbols),
        "timeframes": list(config.timeframes),
        "examples_built": len(training_examples),
        "fresh_examples_built": len(fresh_examples),
        "trusted_replay_examples_built": len(trusted_replay_examples),
        "trusted_replay_scan": dict(getattr(loader, "last_trusted_replay_scan", {}) or {}),
        "trusted_replay_backfill_examples_built": len(backfill_examples),
        "trusted_replay_backfill_scan": dict(
            getattr(loader, "last_trusted_replay_backfill_scan", {}) or {}
        ),
        "prediction_examples_built": len(prediction_examples),
        "prediction_suppressed_count": prediction_suppressed_count,
        "prediction_failure_count": len(prediction_failure_rows),
        "prediction_failure_rows_sample": prediction_failure_rows[:10],
        "replay_buffer_enabled": replay_buffer is not None,
        "replay_buffer_size": len(replay_buffer) if replay_buffer is not None else 0,
        "replay_buffer_limit": getattr(replay_buffer, "maxlen", None) if replay_buffer is not None else None,
        "feature_dim": len(FEATURE_SPEC),
        "input_dim": input_dim,
        "expected_input_dim": len(FEATURE_SPEC) * 4,
        "feature_schema_status": (
            "ALIGNED"
            if input_dim == len(FEATURE_SPEC) * 4
            else "INPUT_DIM_MISMATCH"
        ),
        "checkpoint_guard_active": True,
        "stale_checkpoints_rejected": True,
        "checkpoint_shape_guard": "latest_manifest(input_dim=runtime_input_dim)",
        **checkpoint_promotion_status,
        "checkpoint_candidate_weight_mutated": training_metrics.get(
            "checkpoint_candidate_weight_mutated"
        ),
        "checkpoint_promoted_this_cycle": training_metrics.get(
            "checkpoint_promoted_this_cycle"
        ),
        "ppo_provider_feature_mask_count": len(_provider_feature_names()),
        "masa_provider_feature_mask_count": len(_provider_feature_names()),
        "provider_feature_names": _provider_feature_names(),
        "cuda_active": model.cuda_active,
        "model_device": model.device,
        "model_tensors_device_verified": model.model_tensors_device_verified(),
        "served_policy_fingerprint": served_policy_fingerprint,
        "served_policy_fingerprint_error": served_policy_fingerprint_error,
        "paper_shadow_only": True,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "trainer_process_status": "ACTIVE_CURRENT_CYCLE",
        "cuda_inference_status": (
            "ACTIVE"
            if model_serving_allowed
            else "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
        ),
        "prediction_publication_status": prediction_publication_status,
        "prediction_payloads_built": len(predictions),
        "predictions_published": published_prediction_count,
        "lineages_published": len(lineages),
        "lineages_published_semantics": (
            "TRAINER_NONAUTHORITATIVE_PROPOSAL_PUBLICATION_RECEIPTS"
        ),
        "authoritative_consumer_lineages_attested": 0,
        "authoritative_end_to_end_consumption_complete": False,
        "online_learning_status": training_metrics["online_learning_status"],
        "effective_trainer_mode": training_metrics["effective_trainer_mode"],
        "last_successful_weight_update_at": training_metrics["last_successful_weight_update_at"],
        "learning_metrics": {
            "training_steps": training.training_steps,
            "optimizer_steps_this_cycle": training_metrics.get(
                "optimizer_steps_this_cycle"
            ),
            "loss_before": training.loss_before,
            "loss_after": training.loss_after,
            "weight_delta_norm": training_metrics.get("weight_delta_norm"),
            "parameter_hash_before": training_metrics.get("parameter_hash_before"),
            "parameter_hash_after": training_metrics.get("parameter_hash_after"),
            "learning_update_lane": training_metrics.get("learning_update_lane"),
            "ppo_objective_used": training_metrics.get("ppo_objective_used"),
            "ppo_policy_loss": training_metrics.get("ppo_policy_loss"),
            "ppo_value_loss": training_metrics.get("ppo_value_loss"),
            "ppo_entropy": training_metrics.get("ppo_entropy"),
            "masa_loss": training_metrics.get("masa_loss"),
            "expected_move_loss": training_metrics.get("expected_move_loss"),
            "confidence_loss": training_metrics.get("confidence_loss"),
            # Out-of-sample generalization signal + tunable regularization knobs
            # (edge-recovery repair: the held-out split is now actually evaluated).
            "validation_supervised_loss": training_metrics.get("validation_supervised_loss"),
            "validation_supervised_loss_before": training_metrics.get(
                "validation_supervised_loss_before"
            ),
            "validation_supervised_loss_after": training_metrics.get(
                "validation_supervised_loss_after"
            ),
            "validation_loss_delta": training_metrics.get("validation_loss_delta"),
            "validation_improved": training_metrics.get("validation_improved"),
            "validation_rows_evaluated": training_metrics.get("validation_rows_evaluated"),
            "train_val_generalization_gap": training_metrics.get("train_val_generalization_gap"),
            "overfit_gap_warning": training_metrics.get("overfit_gap_warning"),
            **checkpoint_promotion_status,
            "checkpoint_candidate_weight_mutated": training_metrics.get(
                "checkpoint_candidate_weight_mutated"
            ),
            "checkpoint_promoted_this_cycle": training_metrics.get(
                "checkpoint_promoted_this_cycle"
            ),
            "checkpoint_restore_after_rejection_status": checkpoint_promotion.get(
                "checkpoint_restore_after_rejection_status"
            ),
            "checkpoint_restore_after_rejection_verified": checkpoint_promotion.get(
                "checkpoint_restore_after_rejection_verified"
            ),
            "entropy_coefficient": training_metrics.get("entropy_coefficient"),
            "supervised_entropy_bonus": training_metrics.get("supervised_entropy_bonus"),
            "weight_decay": training_metrics.get("weight_decay"),
            "model_dropout": training_metrics.get("model_dropout"),
        },
        "risk_caps_configured": config.risk_caps_configured,
        "legacy_behavior_references": LEGACY_BEHAVIOR_REFERENCES,
        "legacy_hybrid_parity_claim": "V2_FULL_FUNCTION_PARITY_BY_NATIVE_TRAINER_AND_V2_RUNTIME_OWNERSHIP",
        "legacy_hybrid_parity_baseline": LEGACY_HYBRID_PARITY_BASELINE,
        "legacy_capabilities_ported_or_improved": [
            "dynamic_symbol_refresh_for_loaded_training_batch",
            "full_loaded_batch_training_by_default",
            "v2_safe_parallel_symbol_timeframe_env_rollout_proof",
            "cuda_residual_shared_encoder_with_ppo_value_expected_move_confidence_masa_heads",
            "ppo_clipped_surrogate_loss",
            "masa_auxiliary_signal_head_and_adapter_blend",
            "trainer_to_orchestrator_to_risk_to_paper_lineage",
            "v2_only_redis_publication",
        ],
        "legacy_capabilities_rebuilt_or_reassigned": [
            "raw_stable_baselines3_subproc_vec_env_replaced_by_v2_safe_parallel_rollout_proof",
            "legacy_masa_agent_rebuilt_as_native_masa_adapter_and_cuda_auxiliary_head",
            "continuous_train_predict_thread_model_replaced_by_systemd_guard_and_native_training_loop",
            "legacy_signal_coordinator_profit_taking_liquidation_prevention_reassigned_to_v2_risk_orchestrator_trade_management",
            "legacy_live_signal_streams_reassigned_to_live_gate_trader_transport_fail_closed_boundary",
        ],
        "training_batch_policy": {
            "max_training_rows_per_cycle": config.max_training_rows_per_cycle,
            "batch_size": config.batch_size,
            "target_batch_size": resource_utilization["target_batch_size"],
            "actual_batch_size": resource_utilization["actual_batch_size"],
            "batch_covers_available_examples": training.metrics.get("batch_covers_available_examples", False),
            "available_examples": training.metrics.get("available_examples", len(training_examples)),
            "selected_examples": training.metrics.get("selected_examples", training.train_rows + training.validation_rows),
            "data_loader_time_ms": data_loader_elapsed_ms,
            "gpu_train_time_ms": training_metrics.get("gpu_train_time_ms"),
            "cpu_prep_bottleneck": bool(
                data_loader_elapsed_ms
                > float(training_metrics.get("train_elapsed_ms") or 0.0)
                and training_metrics.get("gpu_train_time_ms") is not None
            ),
        },
        "cuda_cpu_resource_utilization": resource_utilization,
        "model_architecture": model.architecture_status(),
        "environment_reset_step_loop": {
            "reset_info": env_info,
            "step_reward": step_reward,
            "terminated": terminated,
            "truncated": truncated,
            "step_info": step_info,
        },
        "parallel_environment_rollout": parallel_rollout.to_jsonable(),
        "safety_scoreboard": safety_scoreboard(),
    }
    metrics = {
        "training": training_payload,
        "parallel_environment_rollout": parallel_rollout.to_jsonable(),
        "reward_stack": reward_stack_status(),
        "checkpoint": checkpoint_manager.status(checkpoint),
        "checkpoint_load": checkpoint_load,
        "checkpoint_reload": checkpoint_reload,
        "checkpoint_promotion": checkpoint_promotion,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_reload_verified": checkpoint_reload_verified,
        "data_coverage_min": min((p["data_coverage_percent"] for p in predictions), default=0.0),
        "data_coverage_avg": sum(p["data_coverage_percent"] for p in predictions) / max(1, len(predictions)),
        "missing_feature_count_total": sum(p["missing_feature_count"] for p in predictions),
        "stale_feature_count_total": sum(p["stale_feature_count"] for p in predictions),
        "prediction_count": len(predictions),
        "prediction_payloads_built": len(predictions),
        "predictions_published": published_prediction_count,
        "on_policy_categorical_prediction_count": sum(
            1
            for prediction in predictions
            if prediction.get("on_policy_action_receipt_valid") is True
        ),
        "on_policy_directional_candidate_count": sum(
            1
            for prediction in predictions
            if prediction.get("behavior_policy_receipt_write_success") is True
        ),
        "lineage_count": len(lineages),
        "lineage_count_semantics": (
            "TRAINER_NONAUTHORITATIVE_PROPOSAL_PUBLICATION_RECEIPTS"
        ),
        "authoritative_consumer_lineage_count": 0,
        "prediction_suppressed_count": prediction_suppressed_count,
        "model_serving_allowed": model_serving_allowed,
        "model_serving_suppression_reason": checkpoint_promotion.get(
            "model_serving_suppression_reason"
        ),
        "prediction_failure_count": len(prediction_failure_rows),
        "prediction_failure_rows_sample": prediction_failure_rows[:10],
        "cuda_cpu_resource_utilization": resource_utilization,
        "v2_io_audit": asdict(safe_io.audit),
    }
    archive_sync_status = _verified_durable_receipt_archive_sync_status(
        ledger=stores.ledger,
        archive_root=(
            Path(behavior_receipt_archive_root)
            if behavior_receipt_archive_root is not None
            else default_behavior_receipt_archive_root()
        ),
    )
    ledger_integrity = stores.ledger.verify_integrity()
    publication_timing = trainer_status_publication_timing(
        expected_cycle_cadence_seconds=config.expected_cycle_cadence_seconds
    )
    evidence_generated_utc = str(publication_timing["generated_utc"])
    expected_prediction_count = len(config.symbols) * len(config.timeframes)
    lineage_identity_complete = _lineage_identity_complete(
        lineages=lineages,
        cycle_id=cycle_id,
        process_instance_id=process_instance_id,
        checkpoint_id=checkpoint.checkpoint_id,
        candidate_policy_fingerprint=str(served_policy_fingerprint or ""),
    )
    prediction_publication_evidence = (
        build_current_cycle_prediction_publication_evidence(
            rows=predictions,
            expected_prediction_count=expected_prediction_count,
            lineages_published=(
                len(lineages) if lineage_identity_complete else 0
            ),
            cycle_id=cycle_id,
            process_instance_id=process_instance_id,
            checkpoint_id=checkpoint.checkpoint_id,
            candidate_policy_fingerprint=str(served_policy_fingerprint or ""),
            generated_utc=evidence_generated_utc,
            publication_attempted=bool(
                publish
                and published_prediction_count == len(predictions)
                and lineage_identity_complete
                and grid_readback_evidence["publication_complete"] is True
            ),
        )
    )
    prediction_publication_evidence["lineage_identity_complete"] = (
        lineage_identity_complete
    )
    prediction_publication_evidence.update(
        {
            "lineages_published_semantics": (
                "ACK_AND_EXACT_READBACK_COMPLETE_TRAINER_"
                "NONAUTHORITATIVE_PROPOSAL_BUNDLES"
            ),
            "nonauthoritative_proposal_lineages_published": (
                len(lineages) if lineage_identity_complete else 0
            ),
            "authoritative_consumer_lineages_attested": 0,
            "authoritative_end_to_end_consumption_complete": False,
            "counts_as_authoritative_orchestrator_risk_paper_consumption": False,
            "final_grid_readback_evidence": grid_readback_evidence,
        }
    )
    if grid_readback_evidence["publication_complete"] is not True:
        prediction_publication_evidence["publication_complete"] = False
        prediction_publication_evidence[
            "publication_rejection_reasons"
        ] = list(
            dict.fromkeys(
                [
                    *prediction_publication_evidence.get(
                        "publication_rejection_reasons", []
                    ),
                    "CURRENT_CYCLE_GRID_EXACT_READBACK_INCOMPLETE",
                ]
            )
        )
    if not lineage_identity_complete:
        prediction_publication_evidence["publication_complete"] = False
        prediction_publication_evidence[
            "publication_rejection_reasons"
        ] = list(
            dict.fromkeys(
                [
                    *prediction_publication_evidence.get(
                        "publication_rejection_reasons", []
                    ),
                    "PREDICTION_LINEAGE_IDENTITY_MIXED_OR_LEGACY",
                ]
            )
        )
    current_cycle_resource_evidence = {
        "schema_version": CURRENT_RESOURCE_EVIDENCE_SCHEMA,
        "generated_utc": evidence_generated_utc,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "cuda_available": bool(
            training.cuda_active
            and model.cuda_active
            and training.cuda_claim_verified
        ),
        "cuda_active": bool(
            training.cuda_active
            and model.cuda_active
            and training.cuda_claim_verified
            and model.model_tensors_device_verified()
        ),
        "model_device": model.device,
        "model_tensors_device_verified": model.model_tensors_device_verified(),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    parity_evidence = build_current_cycle_parity_attestation(
        repo_root=Path(__file__).resolve().parents[6],
        cycle_id=cycle_id,
        process_instance_id=process_instance_id,
        generated_utc=evidence_generated_utc,
    )
    manager_serving_evidence = _normalized_verified_serving_evidence(
        checkpoint=checkpoint,
        checkpoint_reload=checkpoint_reload,
        semantic_verification_complete=(
            checkpoint_serving_evidence_complete
        ),
    )
    immutable_checkpoint_evidence_raw = checkpoint_reload.get(
        "checkpoint_evidence"
    )
    immutable_checkpoint_evidence = (
        dict(immutable_checkpoint_evidence_raw)
        if isinstance(immutable_checkpoint_evidence_raw, Mapping)
        else {}
    )
    optimizer_evidence_raw = immutable_checkpoint_evidence.get(
        "optimizer_evidence"
    )
    optimizer_evidence = (
        dict(optimizer_evidence_raw)
        if isinstance(optimizer_evidence_raw, Mapping)
        else {}
    )
    ledger_disposition = immutable_checkpoint_evidence.get(
        "ledger_disposition"
    )
    process_evidence = current_process_service_evidence(
        expected_process_instance_id=process_instance_id
    )
    status_publication_claim = {
        "schema_version": "v2_trainer_expiring_status_publication_v1",
        "publication_complete": bool(publish),
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "ttl_seconds": publication_timing["ttl_seconds"],
        "expires_at": publication_timing["expires_at"],
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    promoted_current_cycle = bool(
        checkpoint_promoted_this_cycle
        and serving_artifact is not None
        and checkpoint_weight_blob_written_this_cycle
        and ledger_disposition == "SERVING_PROMOTED"
    )
    envelope = {
        "schema_version": CURRENT_CYCLE_ENVELOPE_SCHEMA,
        "generated_utc": evidence_generated_utc,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "expected_cycle_cadence_seconds": (
            config.expected_cycle_cadence_seconds
        ),
        "trusted_rows_loaded": training_metrics.get("trusted_rows_loaded"),
        "trusted_replay_rows_loaded": training_metrics.get(
            "trusted_replay_rows_loaded"
        ),
        "feedback_rows_entered_batch": training_metrics.get(
            "feedback_rows_entered_batch"
        ),
        "optimizer_steps_this_cycle": optimizer_evidence.get(
            "optimizer_steps_this_cycle"
        ),
        "optimizer_steps_total": optimizer_evidence.get(
            "optimizer_steps_this_cycle"
        ),
        "optimizer_steps_last_hour": optimizer_evidence.get(
            "optimizer_steps_this_cycle"
        ),
        "parameter_hash_before": optimizer_evidence.get(
            "parameter_hash_before"
        ),
        "parameter_hash_after": optimizer_evidence.get(
            "parameter_hash_after"
        ),
        "weight_delta_norm": optimizer_evidence.get("weight_delta_norm"),
        "parent_policy_fingerprint": checkpoint_reload.get(
            "parent_policy_fingerprint"
        ),
        "candidate_policy_fingerprint": checkpoint_reload.get(
            "model_parameter_fingerprint"
        ),
        "checkpoint_id": checkpoint.checkpoint_id,
        "parent_checkpoint_id": checkpoint_reload.get("parent_checkpoint_id"),
        "checkpoint_hash": checkpoint_reload.get("weight_file_sha256"),
        "checkpoint_path": checkpoint.weight_file_path,
        "checkpoint_generated_utc": checkpoint.generated_utc,
        "checkpoint_weight_blob_written": bool(
            checkpoint_weight_blob_written_this_cycle
        ),
        "checkpoint_reload_verified": bool(
            checkpoint_reload_verified
            and checkpoint_serving_evidence_complete
        ),
        "verified_serving": bool(
            promoted_current_cycle and checkpoint_serving_evidence_complete
        ),
        "exact_optimizer_contract": {
            "valid": optimizer_evidence.get("exact_optimizer_contract_valid")
            is True,
            "ppo_objective_used": optimizer_evidence.get(
                "ppo_objective_used"
            )
            is True,
            "optimizer_parameter_fingerprints_bound": optimizer_evidence.get(
                "optimizer_parameter_fingerprints_bound"
            )
            is True,
            "ledger_disposition": ledger_disposition,
            "checkpoint_id": checkpoint.checkpoint_id,
        },
        "ppo_ledger_integrity": ledger_integrity,
        "receipt_archive_sync_status": archive_sync_status,
        "status_publication": status_publication_claim,
        "trainer_process_status": "ACTIVE_CURRENT_CYCLE",
        "cuda_inference_status": (
            "ACTIVE"
            if current_cycle_resource_evidence["cuda_active"]
            else "BLOCKED_NO_CURRENT_CYCLE_CUDA"
        ),
        "prediction_publication_status": (
            "ACTIVE"
            if prediction_publication_evidence["publication_complete"]
            else "BLOCKED_INCOMPLETE_CURRENT_CYCLE_GRID"
        ),
        "online_learning_status": (
            "WEIGHTS_UPDATING"
            if promoted_current_cycle
            else "BLOCKED_NO_CURRENT_CYCLE_SERVING_PROMOTION"
        ),
        "runtime_readiness_status": "READY",
        "last_successful_weight_update_at": (
            checkpoint.generated_utc if promoted_current_cycle else None
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    heartbeat_evidence = {
        "generated_utc": evidence_generated_utc,
        "expires_at": publication_timing["expires_at"],
        "expected_cycle_cadence_seconds": (
            config.expected_cycle_cadence_seconds
        ),
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
    }
    status.update(
        {
            "generated_utc": evidence_generated_utc,
            "cycle_id": cycle_id,
            "process_instance_id": process_instance_id,
            "candidate_policy_fingerprint": checkpoint_reload.get(
                "model_parameter_fingerprint"
            ),
            "expected_cycle_cadence_seconds": (
                config.expected_cycle_cadence_seconds
            ),
            "status_payload_expires_at": publication_timing["expires_at"],
            "status_payload_ttl_seconds": publication_timing["ttl_seconds"],
            "status_publication_status": "ACTIVE" if publish else "DISABLED",
            "runtime_readiness_status": "READY",
            "trainer_learning_ready": True,
            "current_cycle_learning_envelope": envelope,
            "current_cycle_prediction_publication_evidence": (
                prediction_publication_evidence
            ),
            "current_cycle_resource_evidence": (
                current_cycle_resource_evidence
            ),
            "current_cycle_parity_evidence": parity_evidence,
            "current_cycle_verified_serving_checkpoint_evidence": (
                manager_serving_evidence
            ),
            "ppo_ledger_integrity": ledger_integrity,
            "receipt_archive_sync_status": archive_sync_status,
            "status_publication": status_publication_claim,
        }
    )
    readiness = build_learning_readiness(
        trainer_process_active=bool(process_evidence),
        trainer_process_evidence=process_evidence,
        cuda_inference_active=current_cycle_resource_evidence["cuda_active"],
        current_cycle_learning_envelope=envelope,
        runtime_status_evidence=status,
        heartbeat_evidence=heartbeat_evidence,
        verified_serving_checkpoint=manager_serving_evidence,
        prediction_publication_evidence=prediction_publication_evidence,
        resource_evidence=current_cycle_resource_evidence,
        parity_evidence=parity_evidence,
    )
    if readiness.get("trainer_learning_ready") is not True:
        envelope.update(
            {
                "runtime_readiness_status": "BLOCKED",
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
            }
        )
        status.update(
            {
                "runtime_readiness_status": "BLOCKED",
                "trainer_learning_ready": False,
            }
        )
        readiness = build_learning_readiness(
            trainer_process_active=bool(process_evidence),
            trainer_process_evidence=process_evidence,
            cuda_inference_active=current_cycle_resource_evidence["cuda_active"],
            current_cycle_learning_envelope=envelope,
            runtime_status_evidence=status,
            heartbeat_evidence=heartbeat_evidence,
            verified_serving_checkpoint=manager_serving_evidence,
            prediction_publication_evidence=prediction_publication_evidence,
            resource_evidence=current_cycle_resource_evidence,
            parity_evidence=parity_evidence,
        )
    runtime_readiness_blockers = list(
        readiness.get("readiness_blocking_reasons") or ()
    )
    status.update(
        {
            "runtime_readiness_status": readiness.get(
                "canonical_readiness_status"
            ),
            "runtime_readiness_blockers": runtime_readiness_blockers,
            "trainer_learning_ready": readiness.get("trainer_learning_ready"),
            "online_learning_status": readiness.get("online_learning_status"),
            "effective_trainer_mode": readiness.get("effective_trainer_mode"),
        }
    )
    training_metrics.update(
        {
            key: readiness.get(key)
            for key in (
                "trainer_learning_ready",
                "offline_replay_learning_status",
                "online_paper_learning_status",
                "online_learning_status",
                "effective_trainer_mode",
                "readiness_blocking_reasons",
                "requirement_checks",
            )
        }
    )
    training_payload["metrics"] = dict(training_metrics)
    metrics.update(
        {
            "training": training_payload,
            "current_cycle_learning_envelope": envelope,
            "current_cycle_prediction_publication_evidence": (
                prediction_publication_evidence
            ),
            "current_cycle_resource_evidence": current_cycle_resource_evidence,
            "current_cycle_parity_evidence": parity_evidence,
            "current_cycle_verified_serving_checkpoint_evidence": (
                manager_serving_evidence
            ),
        }
    )
    status_publication: dict[str, Any] = status_publication_claim
    if publish:
        status_publication = publisher.publish_status(
            status=status,
            metrics=metrics,
            expected_cycle_cadence_seconds=(
                config.expected_cycle_cadence_seconds
            ),
            publication_timing=publication_timing,
        )
    if status_publication.get("publication_complete") is not True:
        envelope.update(
            {
                "status_publication": {
                    **status_publication_claim,
                    "publication_complete": False,
                },
                "runtime_readiness_status": "BLOCKED",
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
            }
        )
        status.update(
            {
                "current_cycle_learning_envelope": envelope,
                "runtime_readiness_status": "BLOCKED",
                "trainer_learning_ready": False,
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
            }
        )
        runtime_readiness_blockers = list(
            dict.fromkeys(
                [*runtime_readiness_blockers, "STATUS_PUBLICATION_FAILED"]
            )
        )
        status["runtime_readiness_blockers"] = runtime_readiness_blockers
        training_metrics.update(
            {
                "trainer_learning_ready": False,
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
                "effective_trainer_mode": "INFERENCE_ONLY",
                "readiness_blocking_reasons": runtime_readiness_blockers,
            }
        )
        training_payload["metrics"] = dict(training_metrics)
        metrics["training"] = training_payload
    runtime_ready = bool(
        status_publication.get("publication_complete") is True
        and status.get("trainer_learning_ready") is True
        and status.get("runtime_readiness_status") == "READY"
    )
    status["status_publication"] = status_publication
    metrics["runtime_readiness"] = {
        "ready": runtime_ready,
        "blockers": runtime_readiness_blockers,
        "prediction_publication_status": prediction_publication_status,
        "status_publication": status_publication,
    }
    go_no_go = (
        TRAINER_CORE_PAPER_SHADOW_GO_NO_GO
        if runtime_ready
        else "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_BLOCKED"
    )
    return HybridRuntimeResult(
        go_no_go=go_no_go,
        status=status,
        metrics=metrics,
        predictions=predictions,
        lineages=lineages,
    )


def write_runtime_artifacts(
    *,
    paths: HybridRuntimePaths,
    result: HybridRuntimeResult,
) -> HybridRuntimeResult:
    payload = build_operator_dashboard_payload(
        predictions=result.predictions,
        lineages=result.lineages,
        status=result.status,
        metrics=result.metrics,
    )
    report = build_report(result)
    go_no_go = result.go_no_go + "\n"
    status_payloads = build_status_payloads(result, operator_dashboard=payload)
    written: list[str] = []
    for base in (paths.worklog_dir, paths.public_dir):
        base.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {
            "GO_NO_GO.md": go_no_go,
            "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_IMPLEMENTATION_REPORT.md": report,
            "operator_dashboard_payload.json": dumps_pretty(payload),
        }
        for name, obj in status_payloads.items():
            files[name] = dumps_pretty(obj)
        for name, text in files.items():
            path = base / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            written.append(str(path))
    return HybridRuntimeResult(
        go_no_go=result.go_no_go,
        status=result.status,
        metrics=result.metrics,
        predictions=result.predictions,
        lineages=result.lineages,
        paths_written=tuple(written),
    )


def build_status_payloads(result: HybridRuntimeResult, *, operator_dashboard: dict[str, Any]) -> dict[str, Any]:
    status = result.status
    metrics = result.metrics
    runtime_ready = status.get("runtime_readiness_status") == "READY"
    lineage_active = bool(
        status.get("prediction_publication_status") == "ACTIVE"
        and len(result.lineages) == len(result.predictions)
        and len(result.lineages) > 0
    )
    return {
        "v2_native_rl_masa_ppo_port_status.json": {
            "status": (
                "FULL_FUNCTION_PARITY_RUNTIME_READY"
                if runtime_ready
                else "IMPLEMENTED_RUNTIME_BLOCKED"
            ),
            "runtime_readiness_blockers": status.get(
                "runtime_readiness_blockers"
            )
            or [],
            "trainer_source": TRAINER_SOURCE,
            "raw_legacy_trainer_imported": False,
            "legacy_behavior_references": LEGACY_BEHAVIOR_REFERENCES,
            "legacy_hybrid_parity_baseline": LEGACY_HYBRID_PARITY_BASELINE,
            "legacy_hybrid_parity_claim": status["legacy_hybrid_parity_claim"],
            "ported_or_improved": status["legacy_capabilities_ported_or_improved"],
            "rebuilt_or_reassigned": status["legacy_capabilities_rebuilt_or_reassigned"],
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
        "v2_native_rl_tensor_builder_status.json": {
            "status": status.get("feature_schema_status") or "UNKNOWN",
            "values_masked": True,
            "missing_mask_present": True,
            "stale_mask_present": True,
            "source_availability_present": True,
            "data_coverage_avg": metrics["data_coverage_avg"],
        },
        "v2_native_rl_environment_status.json": {
            "status": (
                "READY"
                if metrics["parallel_environment_rollout"].get(
                    "covers_all_loaded_examples"
                )
                is True
                else "BLOCKED"
            ),
            "reset_step_loop_present": True,
            "parallel_rollout_present": True,
            "parallel_rollout": metrics["parallel_environment_rollout"],
            "action_contract": list(ACTION_LABELS),
            "exchange_mutation": False,
        },
        "v2_native_rl_reward_stack_status.json": metrics["reward_stack"],
        "v2_native_rl_masa_ppo_model_status.json": {
            "status": (
                "VERIFIED_SERVING_READY"
                if status.get("model_serving_allowed") is True
                else "BLOCKED_NO_VERIFIED_SERVING_MODEL"
            ),
            **status["model_architecture"],
            "action_probability_output": True,
            "calibration_output": True,
            "model_source": MODEL_SOURCE,
        },
        "v2_native_rl_cuda_runtime_status.json": {
            "status": "CUDA_ACTIVE" if status["cuda_active"] else "CPU_FALLBACK_OR_CUDA_UNAVAILABLE",
            "cuda_active": status["cuda_active"],
            "model_tensors_device_verified": status["model_tensors_device_verified"],
            "training": metrics["training"],
            "cuda_cpu_resource_utilization": metrics["cuda_cpu_resource_utilization"],
        },
        "v2_native_rl_training_loop_status.json": {
            "status": (
                "LEARNING_READY"
                if status.get("trainer_learning_ready") is True
                else "BLOCKED_NOT_LEARNING"
            ),
            "heartbeat_key": "v2:trainer:hybrid_cuda:heartbeat",
            "status_key": "v2:trainer:hybrid_cuda:status",
            "metrics_key": "v2:trainer:hybrid_cuda:metrics",
            "training": metrics["training"],
            "training_batch_policy": status["training_batch_policy"],
            "parallel_environment_rollout": metrics["parallel_environment_rollout"],
        },
        "v2_native_rl_prediction_publisher_status.json": {
            "status": status.get("prediction_publication_status") or "UNKNOWN",
            "prediction_count": len(result.predictions),
            "trainer_source": TRAINER_SOURCE,
            "writes_only_v2_prediction_keys": True,
        },
        "v2_risk_gateway_native_rl_integration_status.json": {
            "status": "ACTIVE" if lineage_active else "BLOCKED_NO_LINEAGE",
            "lineage_count": len(result.lineages),
            "risk_caps_configured": status["risk_caps_configured"],
            "fail_closed_when_caps_unset": True,
        },
        "v2_orchestrator_native_rl_signal_status.json": {
            "status": "ACTIVE" if lineage_active else "BLOCKED_NO_LINEAGE",
            "trainer_risk_orchestrator_chain_present": True,
            "lineage_count": len(result.lineages),
        },
        "v2_paper_trader_native_rl_signal_consumption_status.json": {
            "status": "ACTIVE" if lineage_active else "BLOCKED_NO_PAPER_SIGNAL",
            "paper_signal_lineage_present": True,
            "paper_entries": len(result.lineages),
        },
        "v2_website_native_rl_live_control_status.json": {
            "status": "LIVE_CONTROL_DISABLED_HUMAN_ONLY",
            "trainer_brain_payload_path": "operator_dashboard_payload.json",
            "live_switch_visible": True,
            "live_switch_enabled": False,
            "disabled_reason": operator_dashboard["live_switch"]["disabled_reason"],
        },
    }


def build_report(result: HybridRuntimeResult) -> str:
    return "\n".join(
        [
            "# V2 Native RL/MASA/PPO CUDA Trainer Implementation Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Trainer source: `{TRAINER_SOURCE}`",
            f"Model source: `{MODEL_SOURCE}`",
            f"Predictions emitted: `{len(result.predictions)}`",
            f"Lineage chains emitted: `{len(result.lineages)}`",
            f"Train rows: `{result.metrics['training']['train_rows']}`",
            f"Validation rows: `{result.metrics['training']['validation_rows']}`",
            f"Batch covers available examples: `{result.status['training_batch_policy']['batch_covers_available_examples']}`",
            f"Parallel env rollout: `{result.metrics['parallel_environment_rollout']['status']}` across `{result.metrics['parallel_environment_rollout']['envs_instantiated']}` envs",
            "",
            "Legacy parity statement: all 324 `HybridTrainer` methods are covered by native trainer implementation, explicit V2 runtime ownership, or a fail-closed trainer boundary. The legacy class is not imported as a wrapper; unsafe exchange/account behavior stays outside the trainer.",
            "",
            "Safety: paper/shadow only, `LIVE_GATE=blocked_human_only`, `live_symbols=[]`, no exchange mutation, no old Redis writes.",
            "",
            "CUDA is reported active only when Torch is available, CUDA is available, and model parameters are verified on the CUDA device.",
        ]
    ) + "\n"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
