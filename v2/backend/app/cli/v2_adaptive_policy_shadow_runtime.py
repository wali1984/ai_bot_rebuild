"""Persist production/adaptive paper decisions with independent objective parity."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import sqlite3
import stat
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis

from v2.backend.app.domain.adaptive_policy_action_v2 import ACTION_REMAIN_FLAT
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    AdaptivePolicyShadowCandidateV2,
    build_adaptive_policy_shadow_candidate,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)

SCHEMA_VERSION = "adaptive_policy_shadow_runtime_v2"
ARCHIVE_SCHEMA_VERSION = "adaptive_policy_shadow_archive_v2"
ARCHIVE_RECORD_SCHEMA_VERSION = "adaptive_policy_shadow_archive_record_v2"
STATUS_KEY = "v2:adaptive_system:policy_shadow:status"
LATEST_KEY = "v2:adaptive_system:policy_shadow:latest"
INTENTS_KEY = "v2:paper:intents"
PAPER_STATUS_KEY = "v2:paper:trade_management:status"
CALIBRATION_KEY = "v2:adaptive_system:candidate_calibration:v2"
REGISTRY_KEY = "v2:model_registry:paper:active"
GENESIS_CHAIN_SHA256 = "0" * 64


class AdaptivePolicyShadowRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1_000)


def _iso8601_epoch_ms(value: object, field: str) -> int:
    if type(value) is not str or not value.endswith("Z"):
        raise AdaptivePolicyShadowRuntimeError(f"{field}:utc_z_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise AdaptivePolicyShadowRuntimeError(f"{field}:utc_required")
    return int(parsed.timestamp() * 1_000)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_strict_json_default,
    )


def _strict_json_default(value: object) -> str:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("nonfinite Decimal is not strict JSON")
        return format(value, "f")
    raise TypeError(f"{type(value).__name__} is not strict JSON serializable")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _strict_object(raw: object, field: str) -> dict[str, Any]:
    if type(raw) is not str or not raw:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not dict:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:object_required")
    return value


def _strict_array(raw: object, field: str) -> list[dict[str, Any]]:
    if type(raw) is not str or not raw:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:missing")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdaptivePolicyShadowRuntimeError(f"{field}:invalid_json") from exc
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise AdaptivePolicyShadowRuntimeError(f"{field}:object_array_required")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                allow_nan=False,
                default=_strict_json_default,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class AdaptivePolicyShadowArchiveV2:
    """Transactional, hash-chained compact shadow-decision archive."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
            raise AdaptivePolicyShadowRuntimeError("archive_path:absolute_without_parent_required")
        if path.is_symlink():
            raise AdaptivePolicyShadowRuntimeError("archive_path:symlink_forbidden")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_records (
                    row_index INTEGER PRIMARY KEY,
                    record_key TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL,
                    calibration_sha256 TEXT NOT NULL,
                    source_intent_sha256 TEXT NOT NULL,
                    generated_at_ms INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL,
                    previous_chain_sha256 TEXT NOT NULL,
                    chain_sha256 TEXT NOT NULL UNIQUE
                ) STRICT
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_metadata (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) STRICT
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO archive_metadata(name,value) VALUES('schema_version',?)",
                (ARCHIVE_SCHEMA_VERSION,),
            )
            mode = stat.S_IMODE(self.path.stat().st_mode)
            if mode & 0o077:
                os.chmod(self.path, 0o600)

    def verify(self) -> dict[str, Any]:
        previous = GENESIS_CHAIN_SHA256
        count = 0
        with self._connect() as connection:
            schema = connection.execute(
                "SELECT value FROM archive_metadata WHERE name='schema_version'"
            ).fetchone()
            if schema is None or schema["value"] != ARCHIVE_SCHEMA_VERSION:
                raise AdaptivePolicyShadowRuntimeError("archive:schema_version_invalid")
            for row in connection.execute("SELECT * FROM shadow_records ORDER BY row_index"):
                count += 1
                if row["row_index"] != count:
                    raise AdaptivePolicyShadowRuntimeError("archive:row_index_not_contiguous")
                try:
                    record = json.loads(row["record_json"])
                except json.JSONDecodeError as exc:
                    raise AdaptivePolicyShadowRuntimeError("archive:record_json_invalid") from exc
                if _canonical_json(record) != row["record_json"]:
                    raise AdaptivePolicyShadowRuntimeError("archive:record_json_not_canonical")
                column_bindings = {
                    "record_key": row["record_key"],
                    "candidate_id": row["candidate_id"],
                    "calibration_sha256": row["calibration_sha256"],
                    "source_intent_sha256": row["source_intent_sha256"],
                    "generated_at_ms": row["generated_at_ms"],
                }
                for field, column_value in column_bindings.items():
                    if record.get(field) != column_value:
                        raise AdaptivePolicyShadowRuntimeError(
                            f"archive:{field}_column_binding_mismatch"
                        )
                if (
                    record.get("production_reference_parity", {}).get("status") != "PASS"
                    or record.get("production_reference_parity", {}).get(
                        "disagreement_count"
                    )
                    != 0
                ):
                    raise AdaptivePolicyShadowRuntimeError("archive:reference_parity_invalid")
                if (
                    record.get("adaptive_policy_authoritative") is not False
                    or record.get("execution_authority") is not False
                    or record.get("paper_only") is not True
                    or record.get("live_gate") != "blocked_human_only"
                    or record.get("routes_to_live") is not False
                    or record.get("places_real_order") is not False
                    or record.get("exchange_action_taken") is not False
                ):
                    raise AdaptivePolicyShadowRuntimeError("archive:shadow_safety_invalid")
                record_sha = _sha256(record)
                if record_sha != row["record_sha256"]:
                    raise AdaptivePolicyShadowRuntimeError("archive:record_sha256_mismatch")
                if row["previous_chain_sha256"] != previous:
                    raise AdaptivePolicyShadowRuntimeError("archive:previous_chain_mismatch")
                expected_chain = _sha256(
                    {
                        "row_index": count,
                        "record_key": row["record_key"],
                        "record_sha256": record_sha,
                        "previous_chain_sha256": previous,
                    }
                )
                if row["chain_sha256"] != expected_chain:
                    raise AdaptivePolicyShadowRuntimeError("archive:chain_sha256_mismatch")
                previous = expected_chain
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "row_count": count,
            "terminal_chain_sha256": previous,
            "verified": True,
        }

    def append_many(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        inserted = duplicates = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            tail = connection.execute(
                "SELECT row_index,chain_sha256 FROM shadow_records ORDER BY row_index DESC LIMIT 1"
            ).fetchone()
            row_index = int(tail["row_index"]) if tail else 0
            previous = str(tail["chain_sha256"]) if tail else GENESIS_CHAIN_SHA256
            for record in records:
                record_key = str(record["record_key"])
                existing = connection.execute(
                    "SELECT record_sha256 FROM shadow_records WHERE record_key=?",
                    (record_key,),
                ).fetchone()
                record_json = _canonical_json(record)
                record_sha = _sha256(record)
                if existing is not None:
                    if existing["record_sha256"] != record_sha:
                        raise AdaptivePolicyShadowRuntimeError(
                            "archive:conflicting_duplicate_record_key"
                        )
                    duplicates += 1
                    continue
                row_index += 1
                chain = _sha256(
                    {
                        "row_index": row_index,
                        "record_key": record_key,
                        "record_sha256": record_sha,
                        "previous_chain_sha256": previous,
                    }
                )
                connection.execute(
                    """
                    INSERT INTO shadow_records(
                        row_index,record_key,candidate_id,calibration_sha256,
                        source_intent_sha256,generated_at_ms,record_json,record_sha256,
                        previous_chain_sha256,chain_sha256
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_index,
                        record_key,
                        record["candidate_id"],
                        record["calibration_sha256"],
                        record["source_intent_sha256"],
                        record["generated_at_ms"],
                        record_json,
                        record_sha,
                        previous,
                        chain,
                    ),
                )
                inserted += 1
                previous = chain
            connection.commit()
        verification = self.verify()
        return {**verification, "inserted": inserted, "duplicates": duplicates}


def _component_projection(result: AdaptivePolicyShadowCandidateV2) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for bundle in result.component_estimates:
        groups: dict[str, Any] = {}
        for group in bundle.component_groups:
            scalars = {
                item.name: item.value
                for item in group.scalar_estimates
                if item.availability == "AVAILABLE"
            }
            distributions = {
                item.name: {
                    str(quantile.probability): quantile.value for quantile in item.quantiles
                }
                for item in group.distribution_estimates
                if item.availability == "AVAILABLE"
            }
            groups[group.component_name] = {
                "scalars": scalars,
                "distributions": distributions,
                "source_diagnostic_action": group.source_diagnostic_action,
                "diagnostic_only": group.diagnostic_only,
            }
        output.append(
            {
                "bundle_id": bundle.bundle_id,
                "content_sha256": bundle.content_sha256,
                "side": bundle.side,
                "action_under_evaluation_sha256": bundle.action_under_evaluation_sha256,
                "groups": groups,
                "paper_only": bundle.paper_only,
                "routes_to_live": bundle.routes_to_live,
                "places_real_order": bundle.places_real_order,
                "exchange_action_taken": bundle.exchange_action_taken,
            }
        )
    return output


def _compact_record(
    result: AdaptivePolicyShadowCandidateV2,
    *,
    calibration_sha256: str,
    generated_at_ms: int,
) -> dict[str, Any]:
    selected_id = result.selected_adaptive_action.decision_id
    if (
        result.selected_adaptive_action.policy_mode
        == "bootstrap_information_acquisition"
    ):
        # Bootstrap information acquisition binds to its exact venue-minimum
        # exploration input by identity; the champion/exploration slots stay
        # reserved for positive-utility selections.
        bootstrap_side = result.selected_adaptive_action.primary_side.lower()
        bootstrap_side_suffixes = (
            f":bounded_information_seeking_exploration:{bootstrap_side}",
            f":{bootstrap_side}:venue_minimum",
        )
        selected_input = next(
            item
            for item in result.objective_inputs
            if item.policy_mode == "bounded_information_seeking_exploration"
            and item.selected_action != ACTION_REMAIN_FLAT
            and item.action_id.endswith(bootstrap_side_suffixes)
            and item.hard_constraints_satisfied is True
        )
    else:
        selected_input_id = (
            result.objective_evaluation.exploration_action_id
            if result.selected_adaptive_action.policy_mode
            == "bounded_information_seeking_exploration"
            else result.objective_evaluation.champion_action_id
        )
        if selected_input_id is None:
            if result.selected_adaptive_action.selected_action != ACTION_REMAIN_FLAT:
                raise AdaptivePolicyShadowRuntimeError(
                    "selected_objective_input:missing_for_nonflat_action"
                )
            selected_input = next(
                item
                for item in result.objective_inputs
                if item.selected_action == ACTION_REMAIN_FLAT
            )
        else:
            selected_input = next(
                item
                for item in result.objective_inputs
                if item.action_id == selected_input_id
            )
    selected_venue = next(
        (
            item
            for item in result.venue_attestations
            if item.request.policy_action_sha256 == selected_input.action_sha256
        ),
        None,
    )
    record_key = _sha256(
        {
            "candidate_id": result.candidate_id,
            "calibration_sha256": calibration_sha256,
            "source_intent_sha256": result.source_intent_sha256,
            "generated_at_ms": generated_at_ms,
        }
    )
    return {
        "schema_version": ARCHIVE_RECORD_SCHEMA_VERSION,
        "record_key": record_key,
        "candidate_id": result.candidate_id,
        "source_intent_sha256": result.source_intent_sha256,
        "calibration_sha256": calibration_sha256,
        "generated_at_ms": generated_at_ms,
        "production_decision": result.production_decision,
        "action_dispositions": [
            {"action_id": action_id, "blocking_reasons": list(reasons)}
            for action_id, reasons in result.action_dispositions
        ],
        "component_estimates": _component_projection(result),
        "objective_evaluation": {
            "evaluation_id": result.objective_evaluation.evaluation_id,
            "champion_action_id": result.objective_evaluation.champion_action_id,
            "exploration_action_id": result.objective_evaluation.exploration_action_id,
            "failure_signals": list(result.objective_evaluation.failure_signals),
            "scores": [
                {
                    "action_id": score.action_id,
                    "action_sha256": score.action_sha256,
                    "selected_action": score.selected_action,
                    "policy_mode": score.policy_mode,
                    "eligible": score.eligible,
                    "utility": score.utility,
                    "return_contribution": score.return_contribution,
                    "total_penalty": score.total_penalty,
                    "information_gain_contribution": score.information_gain_contribution,
                    "score_fingerprint": score.score_fingerprint,
                }
                for score in result.objective_evaluation.scores
            ],
        },
        "reference_utilities": [list(item) for item in result.reference_utilities],
        "venue_minimum_objective_comparisons": [
            {
                **asdict(item),
                "content_sha256": item.content_sha256,
            }
            for item in result.venue_minimum_objective_comparisons
        ],
        "production_reference_parity": {
            "status": result.parity_status,
            "disagreement_count": result.parity_disagreement_count,
        },
        "selected_objective_input": asdict(selected_input),
        "selected_venue_attestation": (
            asdict(selected_venue) if selected_venue is not None else None
        ),
        "selected_adaptive_action": result.selected_adaptive_action.to_payload(),
        "selected_adaptive_action_content_sha256": result.selected_adaptive_action.content_sha256,
        "selected_adaptive_action_id": selected_id,
        "full_shadow_result_sha256": result.content_sha256,
        "adaptive_policy_authoritative": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _snapshot_id(intent: Mapping[str, Any]) -> str:
    prediction = intent.get("entry_prediction_snapshot")
    if not isinstance(prediction, Mapping):
        raise AdaptivePolicyShadowRuntimeError("intent:entry_prediction_snapshot_missing")
    value = prediction.get("feature_snapshot_id")
    if type(value) is not str or not value:
        raise AdaptivePolicyShadowRuntimeError("intent:feature_snapshot_id_missing")
    return value


def process_once(
    *,
    client: Any,
    archive: AdaptivePolicyShadowArchiveV2,
    state_root: Path,
    feature_archive_root: Path,
    validator_seed: bytes,
    generated_at_ms: int,
    snapshot_loader: Callable[[str, Path], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    raw_intents, raw_status, raw_calibration, raw_registry = client.mget(
        (INTENTS_KEY, PAPER_STATUS_KEY, CALIBRATION_KEY, REGISTRY_KEY)
    )
    intents = _strict_array(raw_intents, INTENTS_KEY)
    paper_status = _strict_object(raw_status, PAPER_STATUS_KEY)
    calibration = _strict_object(raw_calibration, CALIBRATION_KEY)
    registry = _strict_object(raw_registry, REGISTRY_KEY)
    if not intents:
        raise AdaptivePolicyShadowRuntimeError("intents:nonempty_current_cycle_required")
    if paper_status.get("paper_only") is not True:
        raise AdaptivePolicyShadowRuntimeError("paper_status:paper_only_required")
    if registry.get("paper_only") is not True or registry.get("live_eligible") is not False:
        raise AdaptivePolicyShadowRuntimeError("registry:paper_only_nonlive_required")
    source_cycle_generated_at_ms = _iso8601_epoch_ms(
        paper_status.get("generated_utc"), "paper_status.generated_utc"
    )
    if source_cycle_generated_at_ms > generated_at_ms:
        raise AdaptivePolicyShadowRuntimeError("paper_status.generated_utc:future_time_forbidden")
    loader = snapshot_loader or (
        lambda snapshot_id, root: load_snapshot(snapshot_id, root=root, verify=True)
    )
    results: list[AdaptivePolicyShadowCandidateV2] = []
    records: list[dict[str, Any]] = []
    calibration_sha = str(calibration.get("calibration_sha256"))
    for intent in intents:
        snapshot_id = _snapshot_id(intent)
        snapshot = loader(snapshot_id, feature_archive_root)
        if not isinstance(snapshot, Mapping):
            raise AdaptivePolicyShadowRuntimeError(
                f"feature_snapshot:{snapshot_id}:missing_or_unverified"
            )
        result = build_adaptive_policy_shadow_candidate(
            intent=intent,
            feature_snapshot=snapshot,
            paper_status=paper_status,
            calibration=calibration,
            registry=registry,
            validator_seed=validator_seed,
            generated_at_ms=generated_at_ms,
            require_complete_terminal_state=False,
        )
        results.append(result)
        records.append(
            _compact_record(
                result,
                calibration_sha256=calibration_sha,
                generated_at_ms=generated_at_ms,
            )
        )
    candidate_ids = [item.candidate_id for item in results]
    if len(set(candidate_ids)) != len(intents):
        raise AdaptivePolicyShadowRuntimeError("candidate_ids:unique_coverage_required")
    disagreement_count = sum(item.parity_disagreement_count for item in results)
    if disagreement_count != 0:
        raise AdaptivePolicyShadowRuntimeError(
            f"production_reference_parity:disagreement_count={disagreement_count}"
        )
    archive_result = archive.append_many(records)
    selected_actions = [item.selected_adaptive_action for item in results]
    side_counts = Counter(item.primary_side for item in selected_actions)
    mode_counts = Counter(item.policy_mode for item in selected_actions)
    directional = sum(item.selected_action == "directional_trade" for item in selected_actions)
    static_comparator_blocks = sum(
        item.production_decision.get("paper_fill_allowed") is not True for item in results
    )
    adaptive_over_static = sum(
        item.production_decision.get("paper_fill_allowed") is not True
        and item.selected_adaptive_action.selected_action == "directional_trade"
        for item in results
    )
    directional_action_disposition_count = sum(
        item.objective_inputs[index].selected_action == "directional_trade"
        for item in results
        for index in range(len(item.objective_inputs))
    )
    hard_blocked_directional_action_count = sum(
        bool(reasons)
        for item in results
        for action_id, reasons in item.action_dispositions
        if next(
            objective.selected_action
            for objective in item.objective_inputs
            if objective.action_id == action_id
        )
        == "directional_trade"
    )
    physical_plan_unavailable_count = sum(
        any(reason.startswith("PHYSICAL_PLAN_UNAVAILABLE:") for reason in reasons)
        for item in results
        for _action_id, reasons in item.action_dispositions
    )
    hard_blocked_typed_flat_count = sum(
        item.selected_adaptive_action.selected_action == ACTION_REMAIN_FLAT
        and "HARD_CONSTRAINT_BLOCKED_NONEXECUTING"
        in item.selected_adaptive_action.decision_rationale_codes
        for item in results
    )
    venue_minimum_comparisons = [
        comparison
        for item in results
        for comparison in item.venue_minimum_objective_comparisons
    ]
    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generated_at_ms": generated_at_ms,
        "source_cycle_generated_at_ms": source_cycle_generated_at_ms,
        "status": "PASS_SHADOW",
        "source_candidate_count": len(intents),
        "source_candidate_ids_sha256": _sha256(sorted(candidate_ids)),
        "source_intents_sha256": _sha256(intents),
        "persisted_record_keys_sha256": _sha256(
            sorted(record["record_key"] for record in records)
        ),
        "production_decisions_persisted": len(results),
        "adaptive_shadow_decisions_persisted": len(results),
        "candidate_coverage": 1.0,
        "unexplained_candidate_drop_count": 0,
        "directional_action_disposition_count": directional_action_disposition_count,
        "hard_blocked_directional_action_count": hard_blocked_directional_action_count,
        "physical_plan_unavailable_count": physical_plan_unavailable_count,
        "sub_minimum_exploration_candidates": len(venue_minimum_comparisons),
        "venue_minimum_candidates_evaluated": sum(
            item.venue_min_candidate_evaluated
            for item in venue_minimum_comparisons
        ),
        "venue_minimum_positive_utility_authorizations": sum(
            item.venue_min_candidate_selected
            and item.venue_min_candidate_hard_risk_pass
            and item.venue_min_candidate_utility is not None
            and item.venue_min_candidate_utility > 0.0
            for item in venue_minimum_comparisons
        ),
        "venue_minimum_hard_risk_pass_count": sum(
            item.venue_min_candidate_hard_risk_pass
            for item in venue_minimum_comparisons
        ),
        "venue_minimum_bootstrap_information_acquisition_selected": sum(
            item.selection_reason
            == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
            for item in venue_minimum_comparisons
        ),
        "venue_minimum_comparison_reference_disagreements": sum(
            item.production_reference_disagreement_count
            for item in venue_minimum_comparisons
        ),
        "venue_minimum_effective_sample_sizes": sorted(
            {item.effective_sample_size for item in venue_minimum_comparisons}
        ),
        "venue_minimum_posterior_alpha_beta": sorted(
            {
                (
                    item.bucket_identity,
                    item.posterior_alpha,
                    item.posterior_beta,
                )
                for item in venue_minimum_comparisons
            }
        ),
        "venue_minimum_expected_information_gain_nats": sorted(
            {
                item.venue_min_candidate_expected_information_gain_nats
                for item in venue_minimum_comparisons
            }
        ),
        "venue_minimum_rejection_decomposition": dict(
            sorted(Counter(item.selection_reason for item in venue_minimum_comparisons).items())
        ),
        "hard_blocked_typed_flat_count": hard_blocked_typed_flat_count,
        "production_reference_parity_status": "PASS",
        "production_reference_disagreement_count": 0,
        "selected_directional_action_count": directional,
        "selected_side_counts": dict(sorted(side_counts.items())),
        "selected_policy_mode_counts": dict(sorted(mode_counts.items())),
        "static_comparator_block_count": static_comparator_blocks,
        "adaptive_directional_where_static_blocked_count": adaptive_over_static,
        "calibration_sha256": calibration_sha,
        "checkpoint_generation": registry.get("registry_generation"),
        "checkpoint_id": registry.get("checkpoint_id"),
        "archive": archive_result,
        "adaptive_policy_authoritative": False,
        "static_category_e_authority_removed": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    latest = {
        "schema_version": "adaptive_policy_shadow_latest_v2",
        "generated_at_ms": generated_at_ms,
        "source_cycle_generated_at_ms": source_cycle_generated_at_ms,
        "calibration_sha256": calibration_sha,
        "candidate_count": len(results),
        "actions": [
            {
                "candidate_id": item.candidate_id,
                "decision_id": item.selected_adaptive_action.decision_id,
                "action_content_sha256": item.selected_adaptive_action.content_sha256,
                "symbol": item.selected_adaptive_action.primary_symbol,
                "timeframe": item.selected_adaptive_action.primary_timeframe,
                "selected_action": item.selected_adaptive_action.selected_action,
                "side": item.selected_adaptive_action.primary_side,
                "policy_mode": item.selected_adaptive_action.policy_mode,
                "target_notional_usd": item.selected_adaptive_action.target_notional_usd,
                "leverage": item.selected_adaptive_action.leverage,
                "margin_allocation_usd": item.selected_adaptive_action.margin_allocation_usd,
                "stop_price": item.selected_adaptive_action.stop_price,
                "venue_minimum_objective_comparisons": [
                    {
                        **asdict(comparison),
                        "content_sha256": comparison.content_sha256,
                    }
                    for comparison in item.venue_minimum_objective_comparisons
                ],
                "execution_authority": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            }
            for item in results
        ],
        "adaptive_policy_authoritative": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_json_atomic(state_root / "status.json", status)
    _write_json_atomic(state_root / "latest.json", latest)
    pipeline = client.pipeline(transaction=True)
    pipeline.set(
        STATUS_KEY,
        json.dumps(
            status,
            sort_keys=True,
            allow_nan=False,
            default=_strict_json_default,
        ),
    )
    pipeline.set(
        LATEST_KEY,
        json.dumps(
            latest,
            sort_keys=True,
            allow_nan=False,
            default=_strict_json_default,
        ),
    )
    pipeline.execute()
    return status


def _load_validator_seed(path: Path) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise AdaptivePolicyShadowRuntimeError("validator_seed:regular_absolute_file_required")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise AdaptivePolicyShadowRuntimeError("validator_seed:group_or_world_access_forbidden")
    seed = path.read_bytes()
    if len(seed) != 32:
        raise AdaptivePolicyShadowRuntimeError("validator_seed:exactly_32_bytes_required")
    return seed


def _is_pending_feature_snapshot(exc: BaseException) -> bool:
    """True for the durable-archive-not-yet-written race only.

    ``process_once`` raises ``AdaptivePolicyShadowRuntimeError(f"feature_snapshot:
    {snapshot_id}:missing_or_unverified")`` when ``load_snapshot`` returns ``None``
    because the feature-snapshot archiver has not yet durably indexed a snapshot
    that a just-published paper intent already references. That is an ordering
    race between two independent producers (intent publisher vs. archive
    writer), not a safety or integrity failure — the archiver reliably catches
    up within the next tick or two. It is intentionally distinct from
    ``SnapshotArchiveError`` (raised by ``load_snapshot`` itself for a missing
    blob or a failed content/clock verification), which stays fail-closed.
    """
    message = str(exc)
    return (
        isinstance(exc, AdaptivePolicyShadowRuntimeError)
        and message.startswith("feature_snapshot:")
        and message.endswith(":missing_or_unverified")
    )


def _pending_feature_evidence_status(exc: BaseException) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "PENDING_FEATURE_EVIDENCE",
        "exact_blocker": str(exc),
        "adaptive_policy_authoritative": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _acquire_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise AdaptivePolicyShadowRuntimeError("single_writer_lock:already_held") from exc
    return descriptor


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[4]
    local_root = Path(
        os.environ.get("AI_BOT_LOCAL_DATA_ROOT", str(Path.home() / "ai_bot_local_data"))
    )
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--state-root", type=Path, default=local_root / "adaptive_policy_v2/shadow")
    parser.add_argument(
        "--feature-archive-root",
        type=Path,
        default=repo_root / ".local_data/v2_native_trainer/durable_feature_snapshot_archive",
    )
    parser.add_argument(
        "--validator-seed-path",
        type=Path,
        default=Path.home() / ".config/ai-bot-v2/credentials/adaptive-hard-validator/seed.cred",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(f"/run/user/{os.getuid()}/ai-bot-v2-adaptive-policy-shadow/writer.lock"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.interval_seconds <= 0.0:
        raise SystemExit("--interval-seconds must be positive")
    lock_descriptor = _acquire_lock(args.lock_path)
    validator_seed = _load_validator_seed(args.validator_seed_path)
    args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = AdaptivePolicyShadowArchiveV2(args.state_root / "shadow_decisions_v2.sqlite3")
    archive.verify()
    client = redis.Redis.from_url(
        args.redis_url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=20.0,
    )
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    marker: str | None = None
    try:
        while not stopping:
            raw_values = client.mget((INTENTS_KEY, PAPER_STATUS_KEY, CALIBRATION_KEY, REGISTRY_KEY))
            current_marker = _sha256(raw_values)
            if current_marker != marker:
                try:
                    process_once(
                        client=client,
                        archive=archive,
                        state_root=args.state_root,
                        feature_archive_root=args.feature_archive_root,
                        validator_seed=validator_seed,
                        generated_at_ms=_now_ms(),
                    )
                except AdaptivePolicyShadowRuntimeError as exc:
                    # In --loop mode only: a not-yet-durable feature snapshot is
                    # a transient producer race, not a fail-closed condition.
                    # Leave ``marker`` unset so the same cycle is reattempted
                    # next tick once the archiver catches up; every other
                    # exception (including this one under --once) still
                    # propagates to the outer fail-closed handler unchanged.
                    if args.once or not _is_pending_feature_snapshot(exc):
                        raise
                    pending = _pending_feature_evidence_status(exc)
                    _write_json_atomic(args.state_root / "status.json", pending)
                    try:
                        client.set(
                            STATUS_KEY,
                            json.dumps(pending, sort_keys=True, allow_nan=False,
                                       default=_strict_json_default),
                        )
                    except Exception:
                        pass
                else:
                    marker = current_marker
            if args.once:
                break
            deadline = time.monotonic() + args.interval_seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    except Exception as exc:
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "status": "BLOCKED_FAIL_CLOSED",
            "exception_type": type(exc).__name__,
            "exact_blocker": str(exc),
            "adaptive_policy_authoritative": False,
            "execution_authority": False,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        }
        _write_json_atomic(args.state_root / "status.json", blocked)
        try:
            client.set(
                STATUS_KEY,
                json.dumps(
                    blocked,
                    sort_keys=True,
                    allow_nan=False,
                    default=_strict_json_default,
                ),
            )
        except Exception:
            pass
        print(f"adaptive policy shadow failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        os.close(lock_descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "AdaptivePolicyShadowArchiveV2",
    "AdaptivePolicyShadowRuntimeError",
    "process_once",
)
