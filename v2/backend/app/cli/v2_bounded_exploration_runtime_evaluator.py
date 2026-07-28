"""Read-only proof of the current bounded information-seeking allocation.

The escalation ladder may mark its exploration-increase rung complete only
when the authenticated adaptive calibration is already at its configured
paper-only bound.  This evaluator never edits calibration, policy, Redis, a
model registry, or an order path.  If controllable headroom remains it fails
closed instead of pretending that running a shadow cycle increased anything.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    MAX_BOUNDED_EXPLORATION_PROBABILITY,
    validate_candidate_outcome_calibration_v2,
)

SCHEMA_VERSION = "bounded_exploration_runtime_evaluation_v1"
CALIBRATION_KEY = "v2:adaptive_system:candidate_calibration:v2"
AUTHORITY_STATUS_KEY = "v2:adaptive_system:paper_policy_authority:status"
DEFAULT_MAX_AUTHORITY_AGE_SECONDS = 300.0


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"NONFINITE_JSON:{value}")


def _strict_object(raw: bytes, field: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise ValueError(f"{field}:RAW_BYTES_REQUIRED")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field}:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        raise ValueError(f"{field}:OBJECT_REQUIRED")
    return value


def _finite(value: Any, field: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise ValueError(f"{field}:FINITE_NUMBER_REQUIRED")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field}:FINITE_NUMBER_REQUIRED")
    return parsed


def _utc_epoch(value: Any, field: str) -> float:
    if type(value) is not str or not value:
        raise ValueError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}:UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{field}:UTC_TIMESTAMP_REQUIRED")
    return parsed.timestamp()


def _sha256(value: Any, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field}:SHA256_REQUIRED")
    return value


def _validate_no_live_authority(payload: dict[str, Any], field: str) -> None:
    if payload.get("paper_only") is not True:
        raise ValueError(f"{field}:PAPER_ONLY_REQUIRED")
    if payload.get("live_gate") != "blocked_human_only":
        raise ValueError(f"{field}:LIVE_GATE_BLOCK_REQUIRED")
    for name in ("routes_to_live", "places_real_order", "exchange_action_taken"):
        if payload.get(name) is not False:
            raise ValueError(f"{field}:UNSAFE_AUTHORITY:{name}")
    if "execution_authority" in payload and payload.get("execution_authority") is not False:
        raise ValueError(f"{field}:UNSAFE_AUTHORITY:execution_authority")


def evaluate_bounded_exploration(
    raw_calibration: bytes,
    raw_authority: bytes,
    *,
    now_utc: datetime | None = None,
    max_authority_age_seconds: float = DEFAULT_MAX_AUTHORITY_AGE_SECONDS,
) -> dict[str, Any]:
    """Authenticate the adaptive allocation and prove its bound is exhausted."""

    calibration = _strict_object(raw_calibration, "calibration")
    authority = _strict_object(raw_authority, "authority")
    validate_candidate_outcome_calibration_v2(calibration)
    if authority.get("schema_version") != "adaptive_paper_policy_runtime_status_v2":
        raise ValueError("authority:SCHEMA_VERSION_MISMATCH")
    if authority.get("status") != "PASS_AUTHORITATIVE_PAPER_POLICY":
        raise ValueError("authority:STATUS_NOT_PASS")
    _validate_no_live_authority(calibration, "calibration")
    _validate_no_live_authority(authority, "authority")
    generation = calibration.get("checkpoint_generation")
    checkpoint_id = calibration.get("checkpoint_id")
    if type(generation) is not int or isinstance(generation, bool) or generation < 1:
        raise ValueError("calibration:CHECKPOINT_GENERATION_INVALID")
    if type(checkpoint_id) is not str or not checkpoint_id:
        raise ValueError("calibration:CHECKPOINT_ID_INVALID")
    _sha256(calibration.get("checkpoint_sha256"), "calibration.checkpoint_sha256")
    _sha256(
        calibration.get("source_archive_chain_sha256"),
        "calibration.source_archive_chain_sha256",
    )

    evaluated_at = now_utc or datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(
        evaluated_at
    ):
        raise ValueError("now_utc:UTC_REQUIRED")
    maximum_age = _finite(max_authority_age_seconds, "max_authority_age_seconds")
    if maximum_age <= 0.0:
        raise ValueError("max_authority_age_seconds:POSITIVE_REQUIRED")
    age_seconds = evaluated_at.timestamp() - _utc_epoch(
        authority.get("generated_utc"), "authority.generated_utc"
    )
    if age_seconds < -5.0:
        raise ValueError("authority:FUTURE_GENERATED_AT")
    if age_seconds > maximum_age:
        raise ValueError("authority:STALE")

    if authority.get("adaptive_policy_authoritative") is not True:
        raise ValueError("authority:ADAPTIVE_POLICY_NOT_AUTHORITATIVE")
    parity_disagreements = authority.get("reference_parity_disagreement_count")
    if type(parity_disagreements) is not int or parity_disagreements != 0:
        raise ValueError("authority:REFERENCE_PARITY_DISAGREEMENT")
    if authority.get("static_category_e_authority_removed") is not True:
        raise ValueError("authority:STATIC_CATEGORY_E_AUTHORITY_PRESENT")
    if authority.get("physical_feasibility_is_policy") is not False:
        raise ValueError("authority:PHYSICAL_FEASIBILITY_POLICY_CONFUSION")
    if authority.get("performance_circuit_breaker_hard_trading_authority") is not False:
        raise ValueError("authority:PERFORMANCE_REGRESSION_HARD_VETO_PRESENT")
    if authority.get("performance_circuit_breaker_adaptive_policy_role") != (
        "CONTINUOUS_OBJECTIVE_RISK_INPUT"
    ):
        raise ValueError("authority:PERFORMANCE_REGRESSION_ROLE_INVALID")
    if authority.get("adaptive_policy_paper_cycle_receipts_complete") is not True:
        raise ValueError("authority:CYCLE_RECEIPTS_INCOMPLETE")

    calibration_sha256 = _sha256(
        calibration.get("calibration_sha256"), "calibration.calibration_sha256"
    )
    if authority.get("calibration_sha256") != calibration_sha256:
        raise ValueError("authority:CALIBRATION_IDENTITY_MISMATCH")
    for field in ("checkpoint_generation", "checkpoint_id"):
        if authority.get(field) != calibration.get(field):
            raise ValueError(f"authority:{field.upper()}_MISMATCH")

    allocation = calibration.get("mode_allocation")
    if type(allocation) is not dict:
        raise ValueError("calibration:MODE_ALLOCATION_REQUIRED")
    exploitation = _finite(
        allocation.get("champion_exploitation_probability"),
        "mode_allocation.champion_exploitation_probability",
    )
    exploration = _finite(
        allocation.get("bounded_exploration_probability"),
        "mode_allocation.bounded_exploration_probability",
    )
    if not (0.0 <= exploitation <= 1.0 and 0.0 <= exploration <= 1.0):
        raise ValueError("calibration:MODE_ALLOCATION_RANGE_INVALID")
    if exploitation + exploration != 1.0:
        raise ValueError("calibration:MODE_ALLOCATION_SUM_INVALID")
    if allocation.get("fit_method") != (
        "BETA_POSTERIOR_MISSED_PROFITABLE_REJECTION_RATE"
    ):
        raise ValueError("calibration:MODE_ALLOCATION_FIT_METHOD_INVALID")
    if allocation.get("permanent_percentage") is not False:
        raise ValueError("calibration:PERMANENT_EXPLORATION_TIER_FORBIDDEN")
    if exploration > MAX_BOUNDED_EXPLORATION_PROBABILITY:
        raise ValueError("calibration:EXPLORATION_ABOVE_CONFIGURED_BOUND")
    if exploration != MAX_BOUNDED_EXPLORATION_PROBABILITY:
        raise ValueError("CONTROLLABLE_BOUNDED_EXPLORATION_INCREASE_REMAINS")

    evaluated_utc = evaluated_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_BOUNDED_EXPLORATION_AT_CONFIGURED_LIMIT",
        "result": "NO_FURTHER_SAFE_INCREASE_WITHIN_CURRENT_BOUND",
        "calibration_source_key": CALIBRATION_KEY,
        "authority_source_key": AUTHORITY_STATUS_KEY,
        "calibration_sha256": calibration_sha256,
        "checkpoint_generation": calibration["checkpoint_generation"],
        "checkpoint_id": calibration["checkpoint_id"],
        "bounded_exploration_probability": exploration,
        "champion_exploitation_probability": exploitation,
        "configured_max_bounded_exploration_probability": (
            MAX_BOUNDED_EXPLORATION_PROBABILITY
        ),
        "controllable_increase_remaining": False,
        "increase_applied": False,
        "permanent_percentage": False,
        "fit_method": allocation["fit_method"],
        "authority_age_seconds": round(max(0.0, age_seconds), 6),
        "max_authority_age_seconds": maximum_age,
        "evaluated_utc": evaluated_utc,
        "adaptive_policy_authoritative": True,
        "reference_parity_disagreement_count": 0,
        "static_category_e_authority_removed": True,
        "physical_feasibility_is_policy": False,
        "evaluator_execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _redis_client(url: str):
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("V2_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0",
    )
    parser.add_argument(
        "--max-authority-age-seconds",
        type=float,
        default=DEFAULT_MAX_AUTHORITY_AGE_SECONDS,
    )
    args = parser.parse_args(argv)
    try:
        if os.environ.get("LIVE_GATE") != "blocked_human_only":
            raise ValueError("LIVE_GATE_BLOCK_REQUIRED")
        client = _redis_client(args.redis_url)
        receipt = evaluate_bounded_exploration(
            client.get(CALIBRATION_KEY),
            client.get(AUTHORITY_STATUS_KEY),
            max_authority_age_seconds=args.max_authority_age_seconds,
        )
    except (TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "evaluator_execution_authority": False,
                    "paper_only": True,
                    "live_gate": "blocked_human_only",
                    "routes_to_live": False,
                    "places_real_order": False,
                    "exchange_action_taken": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
