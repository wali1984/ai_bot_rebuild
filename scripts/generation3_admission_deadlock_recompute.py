#!/usr/bin/env python3
"""Recompute the frozen generation-3 admission boundary independently.

The observer archive is the complete 2,757-row bounded projection. Redis
receipts are TTL-bound, so byte-replay coverage is reported separately and is
never inferred for receipts that have expired.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_generation_acceptance_observer import (  # noqa: E402
    ADAPTIVE_TUNING_KEY,
    COHORT_KEY,
)
from v2.backend.app.cli.v2_trade_management_paper_loop import (  # noqa: E402
    PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND,
    PAPER_RISK_CONTROLLER_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL,
    PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY,
    POSITIVE_EDGE_PROBATION_MAX_RISK_FRACTION_OF_NORMAL,
)
from v2.backend.app.services.preemptive_edge_control.decision import (  # noqa: E402
    POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND,
    POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY,
    replay_preemptive_decision,
)

DEFAULT_ARCHIVE = Path(
    ".local_data/permanent_system_recovery/generation_acceptance_cycles_v1.jsonl"
)
DEFAULT_MATRIX = Path(
    ".local_data/permanent_system_recovery/"
    "generation3_admission_deadlock_matrix_v1.jsonl"
)
DEFAULT_REPORT = Path(
    "goal_state/PERMANENT_SYSTEM_RECOVERY/" "generation3_admission_deadlock_report.json"
)
DEFAULT_BASELINE = Path(
    "goal_state/PERMANENT_SYSTEM_RECOVERY/"
    "generation3_admission_contract_baseline.json"
)
DEFAULT_CYCLES = 146
DEFAULT_EXPECTED_CANDIDATES = 2_757
ACTIVE_REGISTRY_KEY = "v2:model_registry:paper:active"
GLOBAL_BREAKER_KEY = "v2:paper:performance_circuit_breaker_status"
PREEMPTIVE_KEY_PATTERN = "v2:preemptive:decision:*"
ABI_PATH = Path("goal_state/PERMANENT_SYSTEM_RECOVERY/ServingFeatureABIV2.json")
ABI_SHA_PATH = Path("goal_state/PERMANENT_SYSTEM_RECOVERY/ServingFeatureABIV2.sha256")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _read_json(client: redis.Redis, key: str) -> dict[str, Any]:
    raw = client.get(key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return _mapping(parsed)


def _parse_archive(path: Path, *, cycles: int) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            row = json.loads(line)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"ARCHIVE_JSON_INVALID_LINE:{line_number}") from exc
        if isinstance(row, Mapping):
            parsed.append(dict(row))
        if len(parsed) == cycles:
            break
    if len(parsed) != cycles:
        raise RuntimeError(f"ARCHIVE_CYCLE_COUNT_MISMATCH:{len(parsed)}!={cycles}")
    return parsed


def _guardian_halted(guardian: Mapping[str, Any]) -> bool:
    if not guardian:
        return True
    state = str(guardian.get("status") or guardian.get("state") or "").upper()
    if any(token in state for token in ("HALTED", "BLOCKED", "SHADOW_ONLY")):
        return True
    for field in (
        "a_grade_new_entries_allowed",
        "new_entries_allowed",
        "guardian_new_entries_allowed",
    ):
        if field in guardian:
            return guardian.get(field) is not True
    return True


def _altdata_high_risk(material: Mapping[str, Any], *, side: str) -> bool:
    alt = _mapping(material.get("altdata_evidence"))
    features = _mapping(alt.get("features"))
    if not features or alt.get("actual_payload_present") is not True:
        return False
    block = _finite(features.get("altdata_trade_block_score"))
    distribution = _finite(features.get("altdata_wallet_distribution_score"))
    sweep = _finite(features.get("altdata_liquidation_sweep_risk_score"))
    euphoria = _finite(features.get("altdata_social_euphoria_risk_score"))
    return bool(
        (block is not None and block >= 0.70)
        or (side == "long" and distribution is not None and distribution >= 0.60)
        or (sweep is not None and sweep >= 0.70)
        or (euphoria is not None and euphoria >= 0.70)
    )


def independent_reference(
    values: Mapping[str, Any],
    *,
    material: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the binary admission result without calling production decision code."""

    material = _mapping(material)
    candidate = _mapping(material.get("candidate"))
    bucket = _mapping(material.get("bucket_assessment"))
    advanced = _mapping(material.get("advanced_indicator_evidence"))
    cost = _mapping(material.get("cost_evidence"))
    controls = _mapping(material.get("control_flags"))
    guardian = _mapping(material.get("continuous_edge_guardian_gate"))

    reasons = [str(reason) for reason in values.get("every_block_reason") or []]
    side = str(values.get("side") or candidate.get("side") or "").lower()
    loss = _finite(values.get("model_loss_probability"))
    exit_score = _finite(values.get("exit_feasibility"))
    confidence_risk = _finite(values.get("confidence_overstatement_risk"))
    trust = _finite(values.get("microstructure_score"))
    expected_edge = _finite(values.get("expected_edge_after_cost_bps"))
    adaptive_limit = _finite(values.get("adaptive_model_loss_probability_limit"))
    micro_action = str(values.get("microstructure_action") or "").upper()

    if material:
        expected_edge = _finite(cost.get("expected_edge_after_cost_bps"))
        bucket_negative = bucket.get("bucket_negative") is True
        bucket_missing = bucket.get("bucket_evidence_missing") is True
        matched_quarantine = bool(bucket.get("matched_quarantined_bucket_keys"))
        atr_stop = (_finite(bucket.get("recent_ATR_stop_risk")) or 0.0) >= 0.40
        advanced_block = advanced.get("advanced_indicator_block") is True
        advanced_shadow = advanced.get("advanced_indicator_shadow") is True
        allow_probation = controls.get("allow_positive_edge_probation") is True
        allow_exploration = (
            controls.get("allow_paper_risk_controller_exploration") is True
        )
        decision_time_valid = values.get("decision_time_valid") is True
        guardian_halted = _guardian_halted(guardian)
        altdata_high_risk = _altdata_high_risk(material, side=side)
        scoped = (
            candidate.get("paper_only") is True
            and candidate.get("routes_to_live") is False
            and candidate.get("places_real_order") is False
            and candidate.get("paper_cohort_preemptive_controls_scoped") is True
            and candidate.get("paper_cohort_breaker_new_entries_allowed") is True
        )
    else:
        bucket_negative = any(
            token in reason
            for reason in reasons
            for token in ("NEGATIVE_BUCKET", "BUCKET_PF_OR_EXPECTANCY_NEGATIVE")
        )
        bucket_missing = "BUCKET_EVIDENCE_INSUFFICIENT" in reasons
        matched_quarantine = bool(values.get("matched_quarantined_bucket_keys"))
        atr_stop = values.get("atr_stop_cluster_active") is True
        advanced_block = values.get("advanced_indicator_block") is True
        advanced_shadow = values.get("advanced_indicator_shadow") is True
        allow_probation = True
        allow_exploration = True
        decision_time_valid = values.get("decision_time_valid", True) is True
        guardian_halted = values.get("guardian_new_entries_allowed") is not True
        altdata_high_risk = values.get("altdata_high_risk") is True
        scoped = (
            values.get("cohort_preemptive_controls_scoped") is True
            and values.get("cohort_breaker_new_entries_allowed") is True
        )

    micro_tradeable = trust is not None and micro_action not in {
        "",
        "NO_TRADE",
        "SHADOW_ONLY",
        "CLOSE_OR_REDUCE_ONLY",
    }
    common = (
        scoped
        and guardian_halted
        and not bucket_negative
        and not matched_quarantine
        and expected_edge is not None
        and expected_edge > 0.0
        and loss is not None
        and confidence_risk is not None
        and confidence_risk < 0.75
        and exit_score is not None
        and micro_tradeable
        and not advanced_block
    )
    probation = bool(
        allow_probation
        and common
        and loss < POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND
        and exit_score >= POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY
        and not advanced_shadow
    )
    exploration = bool(
        allow_exploration
        and common
        and not atr_stop
        and loss < PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND
        and exit_score >= PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY
        and not altdata_high_risk
    )
    hard_safety_block = bool(
        bucket_negative
        or matched_quarantine
        or atr_stop
        or advanced_block
        or not decision_time_valid
    )

    if hard_safety_block:
        decision = "NO_TRADE"
    elif probation:
        decision = "POSITIVE_EDGE_PROBATION_PAPER"
    elif exploration:
        decision = "PAPER_RISK_CONTROLLER_EXPLORATION"
    elif loss is None or adaptive_limit is None or loss >= adaptive_limit:
        decision = "NO_TRADE"
    elif expected_edge is None or expected_edge <= 0.0:
        decision = "NO_TRADE"
    elif exit_score is None or exit_score < 0.35:
        decision = "NO_TRADE"
    elif guardian_halted:
        decision = "NO_TRADE"
    elif advanced_shadow:
        decision = "SHADOW_ONLY"
    elif (
        confidence_risk is None
        or confidence_risk >= 0.75
        or exit_score < 0.55
        or bucket_missing
    ):
        decision = "SHADOW_ONLY"
    elif micro_action == "REDUCE_SIZE" or (trust is not None and trust < 0.65):
        decision = "REDUCE_SIZE_PAPER_ONLY"
    else:
        decision = "ALLOW"

    predicates = {
        "model": loss is not None
        and loss < PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND,
        "microstructure": micro_tradeable,
        "guardian": scoped and guardian_halted,
        "fvg": not advanced_block,
        "exit_feasibility": exit_score is not None
        and exit_score >= PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY,
        "advanced_indicator": not advanced_block,
        "positive_after_cost_edge": expected_edge is not None and expected_edge > 0.0,
        "confidence": confidence_risk is not None and confidence_risk < 0.75,
        "bucket": not bucket_negative and not matched_quarantine and not atr_stop,
        "point_in_time": decision_time_valid,
        "altdata": not altdata_high_risk,
    }
    evaluable = all(
        value is not None
        for value in (
            loss,
            exit_score,
            confidence_risk,
            trust,
            expected_edge,
            adaptive_limit,
        )
    ) and bool(micro_action)
    return {
        "decision": decision,
        "allowed": decision
        in {
            "ALLOW",
            "REDUCE_SIZE_PAPER_ONLY",
            "POSITIVE_EDGE_PROBATION_PAPER",
            "PAPER_RISK_CONTROLLER_EXPLORATION",
        },
        "evaluable": evaluable,
        "predicates": predicates,
        "hard_safety_block": hard_safety_block,
        "positive_edge_probation_eligible": probation,
        "paper_risk_controller_exploration_eligible": exploration,
    }


_RECEIPT_INDEX_LUA = r"""
local raw=redis.call('GET',KEYS[1])
if not raw then return false end
local row=cjson.decode(raw)
return cjson.encode({
  prediction_id=row['prediction_id'],
  preemptive_decision_time=row['preemptive_decision_time']
})
"""


def _receipt_keys_by_prediction(
    client: redis.Redis,
    prediction_ids: set[str],
) -> dict[str, str]:
    keys = list(client.scan_iter(match=PREEMPTIVE_KEY_PATTERN, count=1_000))
    result: dict[str, str] = {}
    for offset in range(0, len(keys), 100):
        batch = keys[offset : offset + 100]
        pipe = client.pipeline(transaction=False)
        for key in batch:
            pipe.eval(_RECEIPT_INDEX_LUA, 1, key)
        for key, raw in zip(batch, pipe.execute()):
            if not raw:
                continue
            try:
                index = json.loads(raw)
            except (TypeError, ValueError):
                continue
            prediction_id = str(index.get("prediction_id") or "")
            if prediction_id in prediction_ids:
                result[prediction_id] = str(key)
    return result


def _microstructure_source(candidate: Mapping[str, Any]) -> dict[str, Any]:
    envelope = _mapping(candidate.get("microstructure_trust_evidence"))
    source = _mapping(envelope.get("source_payload"))
    source_key = candidate.get("microstructure_trust_source") or source.get(
        "source_key"
    )
    source_schema = source.get("schema_version") or envelope.get("schema_version")
    if source_schema in (None, "") and str(source_key or "").startswith(
        "v2:microstructure:trust_score:"
    ):
        source_schema = "microstructure_trust_score_v2"
    source_timeframe = source.get("timeframe")
    if source_timeframe in (None, "") and source_key:
        source_timeframe = str(source_key).rsplit(":", 1)[-1]
    return {
        "microstructure_source_key": source_key,
        "microstructure_source_schema": source_schema,
        "microstructure_source_time": source.get("source_available_at")
        or candidate.get("microstructure_available_at"),
        "microstructure_producer_generated_at": source.get("producer_generated_at")
        or candidate.get("microstructure_generated_at"),
        "microstructure_record_available_at": source.get("record_available_at")
        or candidate.get("microstructure_available_at"),
        "microstructure_source_timeframe": source_timeframe,
        "microstructure_consumer_source_key": candidate.get(
            "microstructure_trust_source"
        ),
        "microstructure_candidate_timeframe": candidate.get("timeframe"),
    }


def _archive_matrix_rows(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cycle_index, cycle in enumerate(cycles, 1):
        for candidate_index, source in enumerate(
            _rows(cycle.get("candidate_attribution")), 1
        ):
            every_reason = [str(reason) for reason in source.get("block_reasons") or []]
            row = {
                "schema_version": "generation3_admission_deadlock_matrix_v1",
                "cycle_index": cycle_index,
                "candidate_index": candidate_index,
                "cycle_generated_utc": cycle.get("cycle_generated_utc"),
                "cycle_observed_utc": cycle.get("observed_utc"),
                "candidate_id": source.get("candidate_id") or source.get("intent_id"),
                "symbol": source.get("symbol"),
                "timeframe": source.get("timeframe"),
                "prediction_id": source.get("prediction_id"),
                "selected_action": source.get("side"),
                "side": source.get("side"),
                "model_loss_probability": _finite(source.get("model_loss_probability")),
                "model_loss_probability_limit": (
                    PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND
                ),
                "adaptive_model_loss_probability_limit": _finite(
                    source.get("required_max_loss_probability")
                ),
                "microstructure_action": source.get("microstructure_action"),
                "microstructure_score": _finite(
                    source.get("microstructure_trust_score")
                ),
                "microstructure_required_score": None,
                "microstructure_source_time": None,
                "microstructure_record_available_at": None,
                "microstructure_age_seconds": _finite(
                    source.get("evidence_age_seconds")
                ),
                "liquidity_multiplier": None,
                "FVG_structure_valid": (
                    None
                    if source.get("advanced_indicator_block") is None
                    else source.get("advanced_indicator_block") is False
                ),
                "exit_feasibility": _finite(source.get("exit_feasibility_score")),
                "MFE_to_stop_ratio": None,
                "advanced_indicator_pass": (
                    None
                    if source.get("advanced_indicator_block") is None
                    else source.get("advanced_indicator_block") is False
                ),
                "advanced_indicator_block": source.get("advanced_indicator_block"),
                "advanced_indicator_shadow": source.get("advanced_indicator_shadow"),
                "expected_edge_after_cost_bps": _finite(
                    source.get("expected_edge_after_cost_bps")
                ),
                "confidence_overstatement_risk": _finite(
                    source.get("confidence_overstatement_risk")
                ),
                "guardian_state": source.get("guardian_state"),
                "guardian_new_entries_allowed": source.get(
                    "guardian_new_entries_allowed"
                ),
                "cohort_breaker_state": source.get("cohort_breaker_state"),
                "cohort_breaker_new_entries_allowed": source.get(
                    "cohort_breaker_new_entries_allowed"
                ),
                "cohort_preemptive_controls_scoped": source.get(
                    "cohort_preemptive_controls_scoped"
                ),
                "matched_quarantined_bucket_keys": list(
                    source.get("matched_quarantined_bucket_keys") or []
                ),
                "atr_stop_cluster_active": source.get("atr_stop_cluster_active"),
                "decision_time_valid": True,
                "every_block_reason": every_reason,
                "recorded_production_action": source.get("blocker"),
                "recorded_production_result": "BLOCK",
                "exact_receipt_available": False,
            }
            reference = independent_reference(row)
            row["reference_result"] = "ALLOW" if reference["allowed"] else "BLOCK"
            row["reference_decision"] = reference["decision"]
            row["reference_evaluable"] = reference["evaluable"]
            row["reference_predicates"] = reference["predicates"]
            row["recorded_production_reference_match"] = (
                row["recorded_production_result"] == row["reference_result"]
                if reference["evaluable"]
                else None
            )
            rows.append(row)
    return rows


def _enrich_exact_receipts(
    client: redis.Redis,
    rows: list[dict[str, Any]],
) -> None:
    by_prediction = {
        str(row.get("prediction_id")): row
        for row in rows
        if row.get("prediction_id") not in (None, "")
    }
    key_by_prediction = _receipt_keys_by_prediction(client, set(by_prediction))
    for prediction_id, key in key_by_prediction.items():
        raw = client.get(key)
        if not raw:
            continue
        try:
            receipt = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(receipt, Mapping):
            continue
        row = by_prediction[prediction_id]
        material = _mapping(receipt.get("preemptive_input_material"))
        candidate = _mapping(material.get("candidate"))
        advanced = _mapping(material.get("advanced_indicator_evidence"))
        source = _microstructure_source(candidate)
        mfe_required = _finite(receipt.get("MFE_required_to_profit"))
        stop_distance = _finite(candidate.get("stop_distance_bps"))
        row.update(source)
        row.update(
            {
                "exact_receipt_available": True,
                "preemptive_decision_id": receipt.get("preemptive_decision_id"),
                "preemptive_input_hash": receipt.get("preemptive_input_hash"),
                "candidate_id": receipt.get("candidate_id") or row.get("candidate_id"),
                "model_loss_probability": _finite(
                    receipt.get("pre_trade_loss_probability")
                ),
                "adaptive_model_loss_probability_limit": _finite(
                    receipt.get("adaptive_loss_probability_threshold_used")
                ),
                "microstructure_action": receipt.get("microstructure_action"),
                "microstructure_score": _finite(
                    receipt.get("microstructure_trust_score")
                ),
                "microstructure_required_score": _finite(
                    candidate.get("microstructure_adaptive_minimum")
                ),
                "liquidity_multiplier": _finite(
                    candidate.get("ordinary_paper_effective_sizing_weight")
                    or candidate.get("strategy_size_multiplier")
                    or candidate.get("allocator_liquidity_score_after_microstructure")
                    or candidate.get("liquidity_score")
                ),
                "liquidity_multiplier_source": next(
                    (
                        field
                        for field in (
                            "ordinary_paper_effective_sizing_weight",
                            "strategy_size_multiplier",
                            "allocator_liquidity_score_after_microstructure",
                            "liquidity_score",
                        )
                        if candidate.get(field) is not None
                    ),
                    None,
                ),
                "FVG_structure_valid": advanced.get("advanced_indicator_block")
                is False,
                "exit_feasibility": _finite(receipt.get("exit_feasibility_score")),
                "MFE_to_stop_ratio": (
                    None
                    if mfe_required is None or stop_distance in (None, 0.0)
                    else mfe_required / stop_distance
                ),
                "advanced_indicator_pass": advanced.get("advanced_indicator_block")
                is False,
                "advanced_indicator_block": advanced.get("advanced_indicator_block"),
                "advanced_indicator_shadow": advanced.get("advanced_indicator_shadow"),
                "expected_edge_after_cost_bps": _finite(
                    receipt.get("expected_edge_after_cost_bps")
                ),
                "confidence_overstatement_risk": _finite(
                    receipt.get("confidence_overstatement_risk")
                ),
                "decision_time_valid": (
                    receipt.get("preemptive_decision_time_input_valid") is True
                ),
                "recorded_production_decision": receipt.get("preemptive_decision"),
                "recorded_production_action": receipt.get("preemptive_action"),
                "every_block_reason": list(
                    receipt.get("preemptive_decision_reasons") or []
                ),
            }
        )
        decision_time = receipt.get("preemptive_decision_time")
        record_time = source.get("microstructure_record_available_at")
        try:
            decision_dt = datetime.fromisoformat(
                str(decision_time).replace("Z", "+00:00")
            )
            record_dt = datetime.fromisoformat(str(record_time).replace("Z", "+00:00"))
            row["microstructure_age_seconds"] = max(
                0.0, (decision_dt - record_dt).total_seconds()
            )
        except (TypeError, ValueError):
            pass

        reference = independent_reference(row, material=material)
        row["reference_result"] = "ALLOW" if reference["allowed"] else "BLOCK"
        row["reference_decision"] = reference["decision"]
        row["reference_evaluable"] = reference["evaluable"]
        row["reference_predicates"] = reference["predicates"]
        row["recorded_production_reference_match"] = (
            row["recorded_production_result"] == row["reference_result"]
        )
        try:
            replay = replay_preemptive_decision(
                material,
                expected_input_hash=str(receipt.get("preemptive_input_hash") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            row["current_production_replay_error"] = f"{type(exc).__name__}:{exc}"
            row["current_production_result"] = None
            row["current_production_reference_match"] = None
        else:
            current_allowed = replay.get("preemptive_allowed") is True
            row["current_production_decision"] = replay.get("preemptive_decision")
            row["current_production_result"] = "ALLOW" if current_allowed else "BLOCK"
            row["current_production_reference_match"] = (
                current_allowed is reference["allowed"]
            )


def _counterfactual(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = (
        "model",
        "microstructure",
        "guardian",
        "fvg",
        "exit_feasibility",
        "advanced_indicator",
        "positive_after_cost_edge",
        "confidence",
        "bucket",
        "point_in_time",
        "altdata",
    )
    evaluable = [row for row in rows if row.get("reference_evaluable") is True]
    single = {
        name: sum(
            row.get("reference_predicates", {}).get(name) is True for row in evaluable
        )
        for name in names
    }
    all_but = {
        name: sum(
            all(
                row.get("reference_predicates", {}).get(other) is True
                for other in names
                if other != name
            )
            for row in evaluable
        )
        for name in names
    }
    return {
        "evaluable_rows": len(evaluable),
        "single_predicate_pass_count": single,
        "all_but_predicate_pass_count": all_but,
        "all_but_microstructure_pass_count": all_but["microstructure"],
        "all_but_model_pass_count": all_but["model"],
        "all_but_guardian_pass_count": all_but["guardian"],
        "all_but_FVG_pass_count": all_but["fvg"],
        "fully_admissible_count": sum(
            row.get("reference_result") == "ALLOW" for row in evaluable
        ),
    }


def _baseline(client: redis.Redis, cycles: list[dict[str, Any]]) -> dict[str, Any]:
    cohort = _read_json(client, COHORT_KEY)
    cohort_id = str(cohort.get("cohort_id") or "")
    active = _read_json(client, ACTIVE_REGISTRY_KEY)
    tuning = _read_json(client, ADAPTIVE_TUNING_KEY)
    global_breaker = _read_json(client, GLOBAL_BREAKER_KEY)
    cohort_breaker_key = f"{GLOBAL_BREAKER_KEY}:{cohort_id}"
    cohort_breaker = _read_json(client, cohort_breaker_key)
    first = cycles[0]
    last = cycles[-1]
    return {
        "schema_version": "generation3_admission_contract_baseline_v1",
        "generated_utc": _utc_now(),
        "frozen_cycle_count": len(cycles),
        "earliest_cycle_generated_utc": first.get("cycle_generated_utc"),
        "latest_cycle_observed_utc": last.get("observed_utc"),
        "checkpoint_generation": cohort.get("checkpoint_generation"),
        "checkpoint_id": cohort.get("checkpoint_id"),
        "cohort_id": cohort_id,
        "active_registry": active,
        "ServingFeatureABIV2": {
            "path": str(ABI_PATH),
            "declared_canonical_sha256": (
                ABI_SHA_PATH.read_text(encoding="utf-8").strip()
                if ABI_SHA_PATH.is_file()
                else None
            ),
            "artifact_bytes_sha256": _sha256(ABI_PATH),
        },
        "admission_thresholds": {
            "adaptive_loss_probability_threshold": tuning.get(
                "adaptive_loss_probability_threshold"
            ),
            "positive_edge_probation_loss_probability_bound": (
                POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND
            ),
            "positive_edge_probation_min_exit_feasibility": (
                POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY
            ),
            "paper_risk_controller_exploration_loss_probability_bound": (
                PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND
            ),
            "paper_risk_controller_exploration_min_exit_feasibility": (
                PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY
            ),
            "confidence_overstatement_risk_max_exclusive": 0.75,
            "atr_stop_cluster_max_exclusive": 0.40,
            "standard_exit_feasibility_no_trade_below": 0.35,
            "standard_exit_feasibility_shadow_below": 0.55,
            "standard_microstructure_trust_reduce_below": 0.65,
        },
        "microstructure_thresholds": {
            "adaptive_microstructure_trust_threshold": tuning.get(
                "adaptive_microstructure_trust_threshold"
            ),
            "producer_adaptive_minimum_observed": 0.65,
            "tradeable_actions": ["ALLOW", "REDUCE_SIZE"],
            "unsafe_actions": ["NO_TRADE", "SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"],
        },
        "guardian_states": {
            "historical_global_breaker_key": GLOBAL_BREAKER_KEY,
            "historical_global_breaker": global_breaker,
            "generation_3_cohort_breaker_key": cohort_breaker_key,
            "generation_3_cohort_breaker": cohort_breaker,
        },
        "evidence_ttls": {
            "adaptive_tuning_key": ADAPTIVE_TUNING_KEY,
            "adaptive_tuning_redis_ttl_seconds": client.ttl(ADAPTIVE_TUNING_KEY),
            "adaptive_tuning_expires_at": tuning.get("expires_at"),
            "cohort_breaker_redis_ttl_seconds": client.ttl(cohort_breaker_key),
            "preemptive_receipts": "TTL_BOUND_RUNTIME_EVIDENCE",
        },
        "risk_limits": {
            "paper_risk_controller_exploration_max_risk_fraction_of_normal": (
                PAPER_RISK_CONTROLLER_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
            ),
            "positive_edge_probation_max_risk_fraction_of_normal": (
                POSITIVE_EDGE_PROBATION_MAX_RISK_FRACTION_OF_NORMAL
            ),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
            )
            handle.write("\n")


def _prior_exact_projection(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, Mapping):
            continue
        if not (
            row.get("exact_receipt_available") is True
            or row.get("exact_receipt_projection_preserved") is True
        ):
            continue
        prediction_id = str(row.get("prediction_id") or "")
        if prediction_id:
            result[prediction_id] = dict(row)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    prior_exact = _prior_exact_projection(args.matrix)
    cycles = _parse_archive(args.archive, cycles=args.cycles)
    rows = _archive_matrix_rows(cycles)
    if len(rows) != args.expected_candidates:
        raise RuntimeError(
            f"FROZEN_CANDIDATE_COUNT_MISMATCH:{len(rows)}!={args.expected_candidates}"
        )
    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    client.ping()
    baseline = _baseline(client, cycles)
    _enrich_exact_receipts(client, rows)
    current_exact_receipts = sum(
        row.get("exact_receipt_available") is True for row in rows
    )
    for row in rows:
        if row.get("exact_receipt_available") is True:
            row["exact_evidence_at_initial_freeze"] = True
            row["exact_receipt_projection_preserved"] = False
            continue
        prior = prior_exact.get(str(row.get("prediction_id") or ""))
        if prior is None:
            row["exact_evidence_at_initial_freeze"] = False
            row["exact_receipt_projection_preserved"] = False
            continue
        row.update(prior)
        row["exact_receipt_available"] = False
        row["exact_evidence_at_initial_freeze"] = True
        row["exact_receipt_projection_preserved"] = True
        # The initial projection retained MFE-required bps, not the stop distance
        # needed to label a ratio honestly.
        row["MFE_to_stop_ratio"] = None
        if str(row.get("microstructure_source_key") or "").startswith(
            "v2:microstructure:trust_score:"
        ):
            row["microstructure_source_schema"] = "microstructure_trust_score_v2"
            row["microstructure_source_timeframe"] = str(
                row["microstructure_source_key"]
            ).rsplit(":", 1)[-1]
    counterfactual = _counterfactual(rows)
    exact = [row for row in rows if row.get("exact_evidence_at_initial_freeze") is True]
    report = {
        "schema_version": "generation3_admission_deadlock_report_v1",
        "generated_utc": _utc_now(),
        "classification": "SYSTEMATIC_ADMISSION_DEADLOCK",
        "frozen_contract_baseline_path": str(args.baseline),
        "matrix_path": str(args.matrix),
        "frozen_cycles": len(cycles),
        "frozen_candidates": len(rows),
        "recorded_production_admissions": sum(
            row.get("recorded_production_result") == "ALLOW" for row in rows
        ),
        "projection_reference_evaluable_rows": sum(
            row.get("reference_evaluable") is True for row in rows
        ),
        "exact_receipts_available": len(exact),
        "exact_receipts_currently_available": current_exact_receipts,
        "exact_receipt_projections_preserved_after_ttl_expiry": sum(
            row.get("exact_receipt_projection_preserved") is True for row in rows
        ),
        "exact_receipts_expired_before_recompute": len(rows) - len(exact),
        "exact_receipt_coverage_complete": len(exact) == len(rows),
        "recorded_production_reference_disagreements": sum(
            row.get("recorded_production_reference_match") is False for row in rows
        ),
        "exact_recorded_production_reference_disagreements": sum(
            row.get("recorded_production_reference_match") is False for row in exact
        ),
        "exact_current_production_reference_disagreements": sum(
            row.get("current_production_reference_match") is False for row in exact
        ),
        "exact_current_production_replay_errors": sum(
            bool(row.get("current_production_replay_error")) for row in exact
        ),
        "counterfactual": counterfactual,
        "root_cause_graph": [
            {
                "raw_evidence_defect": (
                    "historical fail-closed adaptive threshold=0.0 was applied before "
                    "the generation-scoped paper probation/exploration predicates"
                ),
                "derived_predicate_failure": (
                    "every finite loss probability compared >=0.0 even when the "
                    "candidate satisfied the unchanged scoped 0.65/0.72 loss bound"
                ),
                "final_admission_block": "NO_TRADE",
                "repair": (
                    "hard safety blocks remain first; explicitly cohort-bound paper "
                    "lanes are evaluated next; the global adaptive ceiling remains "
                    "binding everywhere else"
                ),
            },
            {
                "raw_evidence_defect": (
                    "1h candidate trust lookup discarded the requested 1h key and "
                    "silently selected 1m"
                ),
                "derived_predicate_failure": "candidate/evidence timeframe lineage mismatch",
                "final_admission_block": "not causal where current producer values matched",
                "repair": "prefer exact 1h/4h trust keys before lower-timeframe fallback",
            },
        ],
        "safety": {
            "thresholds_changed": False,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
    }
    _write_json(args.baseline, baseline)
    _write_jsonl(args.matrix, rows)
    report["matrix_sha256"] = _sha256(args.matrix)
    report["baseline_sha256"] = _sha256(args.baseline)
    _write_json(args.report, report)
    return report


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument(
        "--expected-candidates", type=int, default=DEFAULT_EXPECTED_CANDIDATES
    )
    parser.add_argument(
        "--redis-url",
        default=os.getenv("V2_REDIS_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(_args()), indent=2, sort_keys=True))
