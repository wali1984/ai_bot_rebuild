"""Read-only evaluator for the canonical strategy-supply publisher.

The continuous-adaptation ladder must evaluate alternative strategy families
without starting a second writer against the canonical ``v2:strategy_supply``
keys.  This command authenticates the latest publisher status, emits a compact
learning receipt on stdout, and performs no Redis or filesystem writes.

Paper-only.  It never places, cancels, tests, or modifies an exchange order and
never changes a model registry, accounting record, hypothesis, or policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.strategy_supply.edge_hypothesis_generator import (
    LATEST_ERROR_SUMMARY_KEY,
    LATEST_POSITIVE_SUMMARY_KEY,
    STATUS_KEY,
    STRATEGY_FAMILIES,
)

SCHEMA_VERSION = "strategy_supply_runtime_evaluation_v1"
DEFAULT_MAX_AGE_SECONDS = 180.0
_ALLOWED_WRITTEN_KEY_PREFIXES = (
    "v2:strategy_supply:hypotheses:",
    "v2:strategy_supply:positive_hypotheses:",
    "v2:strategy_supply:gate_clean_positive_hypotheses:",
)
_ALLOWED_EXACT_WRITTEN_KEYS = frozenset(
    {STATUS_KEY, LATEST_POSITIVE_SUMMARY_KEY, LATEST_ERROR_SUMMARY_KEY}
)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"strategy_supply_status:DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"strategy_supply_status:NONFINITE_JSON:{value}")


def _strict_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}:STRICT_JSON_REQUIRED") from exc
    if type(value) is not dict:
        raise ValueError(f"{label}:OBJECT_REQUIRED")
    return value


def _utc_timestamp(value: Any, label: str) -> float:
    if type(value) is not str or not value:
        raise ValueError(f"{label}:UTC_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}:UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{label}:UTC_TIMESTAMP_REQUIRED")
    return parsed.timestamp()


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}:NONNEGATIVE_INT_REQUIRED")
    return value


def _finite_positive(value: Any, label: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise ValueError(f"{label}:FINITE_POSITIVE_REQUIRED")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{label}:FINITE_POSITIVE_REQUIRED")
    return parsed


def _validate_no_authority(status: dict[str, Any]) -> None:
    if status.get("paper_only") is not True:
        raise ValueError("strategy_supply_status:PAPER_ONLY_REQUIRED")
    if status.get("exchange_action_taken") is not False:
        raise ValueError("strategy_supply_status:EXCHANGE_ACTION_FORBIDDEN")
    if status.get("live_gate") != "blocked_human_only":
        raise ValueError("strategy_supply_status:LIVE_GATE_BLOCK_REQUIRED")
    required_false = (
        "approves_trade_alone",
        "routes_to_live",
        "places_real_order",
        "test_order_submitted",
        "cancel_or_modify_order",
        "leverage_mutation",
        "margin_mode_mutation",
        "transfer_or_withdrawal",
    )
    for field in required_false:
        if status.get(field) is not False:
            raise ValueError(f"strategy_supply_status:UNSAFE_AUTHORITY:{field}")
    if status.get("live_gate_required") != "blocked_human_only":
        raise ValueError("strategy_supply_status:LIVE_GATE_BLOCK_REQUIRED")


def evaluate_strategy_supply_status(
    raw_status: bytes,
    *,
    now_utc: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate one canonical publisher status and return a read-only receipt."""

    if type(raw_status) is not bytes or not raw_status:
        raise ValueError("strategy_supply_status:RAW_BYTES_REQUIRED")
    max_age = _finite_positive(max_age_seconds, "max_age_seconds")
    status = _strict_object(raw_status, "strategy_supply_status")
    if status.get("schema_version") != "strategy_supply_publish_status_v1":
        raise ValueError("strategy_supply_status:SCHEMA_VERSION_MISMATCH")
    _validate_no_authority(status)

    evaluated_at = now_utc or datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
        raise ValueError("now_utc:UTC_REQUIRED")
    source_epoch = _utc_timestamp(
        status.get("generated_utc"), "strategy_supply_status.generated_utc"
    )
    age_seconds = evaluated_at.timestamp() - source_epoch
    if age_seconds < -5.0:
        raise ValueError("strategy_supply_status:FUTURE_GENERATED_AT")
    if age_seconds > max_age:
        raise ValueError("strategy_supply_status:STALE")

    symbol_count = _nonnegative_int(status.get("symbol_count"), "symbol_count")
    timeframe_count = _nonnegative_int(
        status.get("timeframe_count"), "timeframe_count"
    )
    hypothesis_count = _nonnegative_int(
        status.get("hypothesis_count"), "hypothesis_count"
    )
    positive_count = _nonnegative_int(
        status.get("positive_hypothesis_count"), "positive_hypothesis_count"
    )
    gate_clean_count = _nonnegative_int(
        status.get("gate_clean_positive_hypothesis_count"),
        "gate_clean_positive_hypothesis_count",
    )
    rejected_positive_count = _nonnegative_int(
        status.get("stage_rejected_positive_hypothesis_count"),
        "stage_rejected_positive_hypothesis_count",
    )
    if not (gate_clean_count <= positive_count <= hypothesis_count):
        raise ValueError("strategy_supply_status:HYPOTHESIS_COUNT_ORDER_INVALID")
    if rejected_positive_count != positive_count - gate_clean_count:
        raise ValueError("strategy_supply_status:STAGE_REJECTION_COUNT_MISMATCH")
    if symbol_count == 0 or timeframe_count == 0 or hypothesis_count == 0:
        raise ValueError("strategy_supply_status:EMPTY_EVALUATION_UNIVERSE")

    families = status.get("strategy_families")
    expected_families = list(STRATEGY_FAMILIES)
    if families != expected_families or len(set(families or [])) != len(expected_families):
        raise ValueError("strategy_supply_status:STRATEGY_FAMILY_SET_MISMATCH")

    written_keys = status.get("redis_keys_written")
    if type(written_keys) is not list or any(type(key) is not str for key in written_keys):
        raise ValueError("strategy_supply_status:WRITTEN_KEY_LIST_INVALID")
    if len(written_keys) != len(set(written_keys)):
        raise ValueError("strategy_supply_status:DUPLICATE_WRITTEN_KEY")
    for key in written_keys:
        if key not in _ALLOWED_EXACT_WRITTEN_KEYS and not key.startswith(
            _ALLOWED_WRITTEN_KEY_PREFIXES
        ):
            raise ValueError(f"strategy_supply_status:UNAUTHORIZED_WRITTEN_KEY:{key}")
    expected_written_key_count = symbol_count * timeframe_count * 3 + 2
    if len(written_keys) != expected_written_key_count:
        raise ValueError("strategy_supply_status:WRITTEN_KEY_COUNT_MISMATCH")
    if {
        LATEST_POSITIVE_SUMMARY_KEY,
        LATEST_ERROR_SUMMARY_KEY,
    } - set(written_keys):
        raise ValueError("strategy_supply_status:SUMMARY_KEYS_MISSING")
    matrix_cell_count = symbol_count * timeframe_count
    for prefix in _ALLOWED_WRITTEN_KEY_PREFIXES:
        if sum(key.startswith(prefix) for key in written_keys) != matrix_cell_count:
            raise ValueError("strategy_supply_status:WRITTEN_KEY_MATRIX_INCOMPLETE")

    ttl_seconds = _finite_positive(status.get("ttl_seconds"), "ttl_seconds")
    cadence_seconds = _finite_positive(
        status.get("publish_cadence_seconds"), "publish_cadence_seconds"
    )
    if ttl_seconds <= cadence_seconds * 3.0:
        raise ValueError("strategy_supply_status:TTL_CADENCE_COVERAGE_INVALID")
    if status.get("ttl_longer_than_three_publish_cadences") is not True:
        raise ValueError("strategy_supply_status:TTL_CADENCE_ATTESTATION_MISSING")

    learning_signal = (
        "GATE_CLEAN_ALTERNATIVE_STRATEGY_HYPOTHESES_PRESENT"
        if gate_clean_count > 0
        else "ALTERNATIVE_STRATEGY_HYPOTHESES_PRESENT_BUT_STAGE_REJECTED"
    )
    evaluated_utc = evaluated_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_CANONICAL_STRATEGY_SUPPLY_EVALUATED",
        "learning_signal": learning_signal,
        "source_key": STATUS_KEY,
        "source_schema_version": status["schema_version"],
        "source_generated_utc": status["generated_utc"],
        "source_status_sha256": hashlib.sha256(raw_status).hexdigest(),
        "evaluated_utc": evaluated_utc,
        "source_age_seconds": round(max(0.0, age_seconds), 6),
        "max_age_seconds": max_age,
        "publisher_status": status.get("status"),
        "publisher_status_reason": status.get("status_reason"),
        "symbol_count": symbol_count,
        "timeframe_count": timeframe_count,
        "strategy_families": expected_families,
        "hypothesis_count": hypothesis_count,
        "positive_hypothesis_count": positive_count,
        "gate_clean_positive_hypothesis_count": gate_clean_count,
        "stage_rejected_positive_hypothesis_count": rejected_positive_count,
        "redis_keys_observed": len(written_keys),
        "approves_trade_alone": False,
        "execution_authority": False,
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
    parser = argparse.ArgumentParser(
        description="Read-only canonical strategy-supply runtime evaluator"
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("V2_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0",
    )
    parser.add_argument(
        "--max-age-seconds", type=float, default=DEFAULT_MAX_AGE_SECONDS
    )
    args = parser.parse_args(argv)
    if os.environ.get("LIVE_GATE") != "blocked_human_only":
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "BLOCKED",
                    "reason": "LIVE_GATE_BLOCK_REQUIRED",
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "exchange_action_taken": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    client = _redis_client(args.redis_url)
    raw_status = client.get(STATUS_KEY)
    try:
        receipt = evaluate_strategy_supply_status(
            raw_status,
            max_age_seconds=args.max_age_seconds,
        )
    except (TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "paper_only": True,
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
